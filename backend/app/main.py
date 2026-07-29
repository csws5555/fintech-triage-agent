"""FastAPI application factory and process-lifespan service initialization."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from app.api.config import (
    ApiSettings,
    api_settings,
    validate_api_settings,
)
from app.api.services import (
    ApiChatService,
    AppServices,
    ClassifierCallable,
    ServiceReadiness,
)
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

    def __post_init__(self) -> None:
        callables = (
            self.warm_classifier,
            self.classifier,
            self.inspect_vector_store,
            self.build_retriever,
            self.build_embeddings,
            self.build_chat_model,
            self.build_pipeline,
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
    try:
        return AppServices(
            classifier=builder.classifier,
            pipeline=pipeline,
            chat_service=chat_service,
            readiness=ServiceReadiness(
                configuration=True,
                classifier=True,
                pipeline=True,
                vector_store=manifest_ready and retriever is not None,
                ollama_chat_model=chat_model is not None,
                ollama_embedding_model=embeddings is not None,
                failure_codes=tuple(failure_codes),
            ),
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

    return FastAPI(
        title="Fintech Triage API",
        lifespan=lifespan,
    )


app = create_app()


__all__ = [
    "ApplicationStartupError",
    "ServiceBuilder",
    "app",
    "create_app",
]
