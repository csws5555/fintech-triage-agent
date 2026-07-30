"""FastAPI application factory and process-lifespan service initialization."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

import ollama
from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from app.api.config import (
    ApiSettings,
    api_settings,
    validate_api_settings,
)
from app.api.errors import ApiErrorMiddleware, register_api_error_handlers
from app.api.middleware import (
    ChatRequestControlMiddleware,
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    configure_api_logger,
    structured_completion_logger,
)
from app.api.services import (
    ApiChatService,
    AppServices,
    ClassifierCallable,
    OllamaModelAvailability,
    ReadinessCoordinator,
    ServiceReadiness,
)
from app.api.routes import chat_router, health_router
from app.ml.chat_model import get_chat_model
from app.ml.classifier import classify_intent, get_classifier
from app.ml.embeddings import get_embeddings
from app.ml.ingest_policies import (
    IngestionManifest,
    load_ingestion_manifest,
)
from app.ml.rag_config import settings, validate_rag_settings
from app.ml.rag_pipeline import FintechRagPipeline
from app.ml.retriever import get_retriever, validate_retrieval_manifest


class ApplicationStartupError(RuntimeError):
    """Stable mandatory-startup failure without private component details."""


def _record_value(record: object, field_name: str) -> object:
    if isinstance(record, Mapping):
        return record.get(field_name)
    return getattr(record, field_name, None)


def _model_names_match(configured_name: str, installed_name: object) -> bool:
    return isinstance(installed_name, str) and (
        installed_name == configured_name
        or (
            ":" not in configured_name
            and installed_name == f"{configured_name}:latest"
        )
    )


def _probe_ollama_models(
    timeout_seconds: int,
) -> OllamaModelAvailability:
    """List installed local models without generating or embedding."""

    client = ollama.Client(
        host=settings.ollama_base_url,
        timeout=timeout_seconds,
    )
    list_models = getattr(client, "list", None)
    if not callable(list_models):
        raise RuntimeError("Ollama model inventory is unavailable.")
    response = list_models()
    models = _record_value(response, "models")
    if not isinstance(models, list):
        raise RuntimeError("Ollama model inventory is invalid.")

    def installed_exactly_once(configured_name: str) -> bool:
        return (
            sum(
                _model_names_match(
                    configured_name,
                    _record_value(model, "model"),
                )
                for model in models
            )
            == 1
        )

    return OllamaModelAvailability(
        chat_model=installed_exactly_once(settings.chat_model),
        embedding_model=installed_exactly_once(
            settings.embedding_model
        ),
    )


def _inspect_active_manifest_and_store() -> IngestionManifest:
    manifest = load_ingestion_manifest(settings.ingestion_manifest_path)
    if not isinstance(manifest, IngestionManifest):
        raise TypeError("Manifest loader returned an invalid contract.")

    validate_retrieval_manifest(
        manifest,
        embedding_model_digest=manifest.embedding_model_digest,
    )
    store_dir = settings.chroma_store_dir
    if (
        not store_dir.exists()
        or not store_dir.is_dir()
        or store_dir.is_symlink()
        or settings.ingestion_manifest_path.parent != store_dir
    ):
        raise RuntimeError("Configured vector store is unavailable.")
    return manifest


@dataclass(frozen=True, slots=True)
class ServiceBuilder:
    """Injectable constructors used by the application lifespan."""

    warm_classifier: Callable[[], object] = get_classifier
    classifier: ClassifierCallable = classify_intent
    inspect_vector_store: Callable[[], object] = (
        _inspect_active_manifest_and_store
    )
    build_retriever: Callable[[], object] = get_retriever
    build_embeddings: Callable[[], object] = get_embeddings
    build_chat_model: Callable[[], object] = get_chat_model
    build_pipeline: Callable[..., object] = FintechRagPipeline
    probe_ollama_models: Callable[
        [int], OllamaModelAvailability
    ] = _probe_ollama_models

    def __post_init__(self) -> None:
        callables = (
            self.warm_classifier,
            self.classifier,
            self.inspect_vector_store,
            self.build_retriever,
            self.build_embeddings,
            self.build_chat_model,
            self.build_pipeline,
            self.probe_ollama_models,
        )
        if any(not callable(candidate) for candidate in callables):
            raise TypeError("ServiceBuilder values must be callable.")


async def _bounded_optional_call(
    operation: Callable[..., object],
    *args: object,
    timeout_seconds: int,
) -> object | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(operation, *args),
            timeout=timeout_seconds,
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return None


async def _build_app_services(
    *,
    runtime_settings: ApiSettings,
    builder: ServiceBuilder,
) -> AppServices:
    # Mandatory startup boundary: configuration, classifier, and the pipeline.
    try:
        validate_rag_settings(settings)
        validate_api_settings(runtime_settings)
    except Exception:
        raise ApplicationStartupError(
            "Application configuration is invalid."
        ) from None

    try:
        await asyncio.to_thread(builder.warm_classifier)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        raise ApplicationStartupError(
            "Classifier startup failed."
        ) from None

    failure_codes: list[str] = []
    manifest = await _bounded_optional_call(
        builder.inspect_vector_store,
        timeout_seconds=runtime_settings.health_timeout_seconds,
    )
    manifest_ready = isinstance(manifest, IngestionManifest)
    if not manifest_ready:
        failure_codes.append("active_manifest_unavailable")

    retriever = await _bounded_optional_call(
        builder.build_retriever,
        timeout_seconds=runtime_settings.health_timeout_seconds,
    )
    if retriever is None:
        failure_codes.append("retriever_unavailable")

    embeddings = await _bounded_optional_call(
        builder.build_embeddings,
        timeout_seconds=runtime_settings.health_timeout_seconds,
    )
    if embeddings is None:
        failure_codes.append("embedding_model_unavailable")

    chat_model = await _bounded_optional_call(
        builder.build_chat_model,
        timeout_seconds=runtime_settings.health_timeout_seconds,
    )
    if chat_model is None:
        failure_codes.append("chat_model_unavailable")

    try:
        pipeline = builder.build_pipeline(
            retriever=retriever,
            llm=chat_model,
        )
        if not callable(getattr(pipeline, "answer", None)):
            raise TypeError("Pipeline builder returned an invalid contract.")
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        raise ApplicationStartupError(
            "Support pipeline startup failed."
        ) from None

    try:
        chat_service = ApiChatService(
            classifier=builder.classifier,
            pipeline=pipeline,
            runtime_settings=runtime_settings,
        )
    except Exception:
        raise ApplicationStartupError(
            "API service startup failed."
        ) from None
    initial_readiness = ServiceReadiness(
        configuration=True,
        classifier=True,
        pipeline=True,
        vector_store=manifest_ready and retriever is not None,
        ollama_chat_model=chat_model is not None,
        ollama_embedding_model=embeddings is not None,
        failure_codes=tuple(failure_codes),
    )

    async def recover_optional(
        snapshot: ServiceReadiness,
    ) -> ServiceReadiness:
        vector_store_ready = snapshot.vector_store
        chat_ready = snapshot.ollama_chat_model
        embedding_ready = snapshot.ollama_embedding_model
        recovered_codes: list[str] = []

        if not vector_store_ready:
            recovered_manifest, recovered_retriever = await asyncio.gather(
                _bounded_optional_call(
                    builder.inspect_vector_store,
                    timeout_seconds=runtime_settings.health_timeout_seconds,
                ),
                _bounded_optional_call(
                    builder.build_retriever,
                    timeout_seconds=runtime_settings.health_timeout_seconds,
                ),
            )
            vector_store_ready = (
                isinstance(recovered_manifest, IngestionManifest)
                and recovered_retriever is not None
            )
            if not isinstance(recovered_manifest, IngestionManifest):
                recovered_codes.append("active_manifest_unavailable")
            if recovered_retriever is None:
                recovered_codes.append("retriever_unavailable")

        if not embedding_ready:
            recovered_embeddings = await _bounded_optional_call(
                builder.build_embeddings,
                timeout_seconds=runtime_settings.health_timeout_seconds,
            )
            embedding_ready = recovered_embeddings is not None
            if not embedding_ready:
                recovered_codes.append("embedding_model_unavailable")

        if not chat_ready:
            recovered_chat_model = await _bounded_optional_call(
                builder.build_chat_model,
                timeout_seconds=runtime_settings.health_timeout_seconds,
            )
            chat_ready = recovered_chat_model is not None
            if not chat_ready:
                recovered_codes.append("chat_model_unavailable")

        return ServiceReadiness(
            configuration=snapshot.configuration,
            classifier=snapshot.classifier,
            pipeline=snapshot.pipeline,
            vector_store=vector_store_ready,
            ollama_chat_model=chat_ready,
            ollama_embedding_model=embedding_ready,
            failure_codes=tuple(recovered_codes),
        )

    readiness_coordinator = ReadinessCoordinator(
        initial=initial_readiness,
        model_probe=builder.probe_ollama_models,
        recover_optional=recover_optional,
        runtime_settings=runtime_settings,
    )

    try:
        return AppServices(
            classifier=builder.classifier,
            pipeline=pipeline,
            chat_service=chat_service,
            readiness=initial_readiness,
            readiness_coordinator=readiness_coordinator,
        )
    except BaseException:
        await chat_service.shutdown()
        raise


def create_app(
    api_runtime_settings: ApiSettings | None = None,
    service_builder: ServiceBuilder | None = None,
) -> FastAPI:
    """Create an API whose heavyweight services are owned by its lifespan."""

    runtime_settings = (
        api_settings
        if api_runtime_settings is None
        else api_runtime_settings
    )
    builder = ServiceBuilder() if service_builder is None else service_builder
    if not isinstance(runtime_settings, ApiSettings):
        raise TypeError(
            "api_runtime_settings must be an ApiSettings instance."
        )
    if not isinstance(builder, ServiceBuilder):
        raise TypeError("service_builder must be a ServiceBuilder instance.")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        services = await _build_app_services(
            runtime_settings=runtime_settings,
            builder=builder,
        )
        application.state.services = services
        try:
            yield
        finally:
            try:
                await services.shutdown()
            finally:
                if getattr(application.state, "services", None) is services:
                    del application.state.services

    logger = configure_api_logger(runtime_settings.log_level)
    middleware = [
        Middleware(
            RequestContextMiddleware,
            log_completion=structured_completion_logger(logger),
        ),
        Middleware(
            CORSMiddleware,
            allow_origins=runtime_settings.cors_origins,
            allow_methods=("GET", "POST", "OPTIONS"),
            allow_headers=("Accept", "Content-Type"),
            expose_headers=(REQUEST_ID_HEADER,),
            allow_credentials=False,
        ),
        Middleware(ApiErrorMiddleware),
        Middleware(
            ChatRequestControlMiddleware,
            api_prefix=runtime_settings.api_prefix,
            max_request_body_bytes=(
                runtime_settings.max_request_body_bytes
            ),
        ),
    ]
    application = FastAPI(
        title="Fintech Triage API",
        lifespan=lifespan,
        middleware=middleware,
    )
    register_api_error_handlers(application)
    application.include_router(health_router)
    application.include_router(
        chat_router,
        prefix=runtime_settings.api_prefix,
    )
    return application


app = create_app()


__all__ = [
    "ApplicationStartupError",
    "ServiceBuilder",
    "app",
    "create_app",
]
