from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.api.config import api_settings
from app.api.dependencies import get_app_services, get_chat_service
from app.api.services import AppServices
from app.main import ApplicationStartupError, ServiceBuilder, create_app
from app.ml.ingest_policies import IngestionManifest
from app.ml.triage_types import (
    ClassificationResult,
    IntentPrediction,
    PipelineAnswer,
)


def classification() -> ClassificationResult:
    return ClassificationResult(
        predictions=(
            IntentPrediction(label="card_arrival", confidence=0.8),
            IntentPrediction(
                label="card_delivery_tracking",
                confidence=0.1,
            ),
            IntentPrediction(label="cash_withdrawal", confidence=0.05),
        ),
        uncertain=False,
        top_two_margin=0.7,
    )


def pipeline_answer() -> PipelineAnswer:
    return PipelineAnswer(
        answer="Approved complete answer.",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
        retrieval_sufficient=True,
        retrieved_policy_ids=("card_delivery",),
        retrieved_chunk_ids=("card-delivery-chunk",),
        reason_code="supported_policy_scope",
    )


class FakePipeline:
    def __init__(
        self,
        *,
        retriever: object | None,
        llm: object | None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.calls = 0

    def answer(
        self,
        *,
        query: str,
        classification: ClassificationResult,
    ) -> PipelineAnswer:
        self.calls += 1
        return pipeline_answer()


def fake_manifest() -> IngestionManifest:
    return IngestionManifest(
        schema_version=2,
        collection_name="fake_collection",
        distance_metric="cosine",
        embedding_model="nomic-embed-text",
        embedding_model_digest="0" * 64,
        embedding_dimensions=768,
        embedding_document_prefix="search_document:",
        embedding_query_prefix="search_query:",
        chunk_size=800,
        chunk_overlap=120,
        chunking_strategy="fake",
        stable_id_strategy="fake",
        source_document_count=1,
        chunk_count=1,
        created_at="2026-01-01T00:00:00Z",
        source_hashes={"policy.md": "1" * 64},
        policy_versions={"policy": "1.0"},
        package_versions={"fake": "1.0"},
    )


def successful_builder(
    calls: list[str],
    *,
    optional_failures: frozenset[str] = frozenset(),
    warm_error: Exception | None = None,
    pipeline_error: Exception | None = None,
) -> tuple[ServiceBuilder, object, object, object]:
    retriever = object()
    embeddings = object()
    chat_model = object()

    def warm_classifier() -> object:
        calls.append("warm_classifier")
        if warm_error is not None:
            raise warm_error
        return object()

    def classifier(_message: str) -> ClassificationResult:
        return classification()

    def optional(name: str, result: object):
        def build() -> object:
            calls.append(name)
            if name in optional_failures:
                raise OSError(f"private {name} detail")
            return result

        return build

    def build_pipeline(**kwargs: Any) -> FakePipeline:
        calls.append("build_pipeline")
        if pipeline_error is not None:
            raise pipeline_error
        return FakePipeline(**kwargs)

    return (
        ServiceBuilder(
            warm_classifier=warm_classifier,
            classifier=classifier,
            inspect_vector_store=optional(
                "inspect_vector_store",
                fake_manifest(),
            ),
            build_retriever=optional("build_retriever", retriever),
            build_embeddings=optional("build_embeddings", embeddings),
            build_chat_model=optional("build_chat_model", chat_model),
            build_pipeline=build_pipeline,
        ),
        retriever,
        embeddings,
        chat_model,
    )


def request_for(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
            "app": app,
        }
    )


def test_application_factory_defers_service_construction_until_lifespan() -> None:
    calls: list[str] = []
    builder, _, _, _ = successful_builder(calls)

    created = create_app(service_builder=builder)

    assert isinstance(created, FastAPI)
    assert calls == []
    assert getattr(created.state, "services", None) is None


@pytest.mark.asyncio
async def test_successful_lifespan_populates_one_container_and_shuts_down() -> None:
    calls: list[str] = []
    builder, retriever, _, chat_model = successful_builder(calls)
    created = create_app(service_builder=builder)

    async with created.router.lifespan_context(created):
        services = created.state.services
        assert isinstance(services, AppServices)
        assert services.readiness.ready
        assert services.pipeline.retriever is retriever
        assert services.pipeline.llm is chat_model
        assert get_app_services(request_for(created)) is services
        assert get_chat_service(services) is services.chat_service
        assert get_app_services(request_for(created)) is services
        assert calls == [
            "warm_classifier",
            "inspect_vector_store",
            "build_retriever",
            "build_embeddings",
            "build_chat_model",
            "build_pipeline",
        ]

    assert services.chat_service.shutdown_started
    assert getattr(created.state, "services", None) is None


@pytest.mark.asyncio
async def test_optional_failures_start_with_safe_degraded_readiness() -> None:
    calls: list[str] = []
    builder, _, _, _ = successful_builder(
        calls,
        optional_failures=frozenset(
            {
                "inspect_vector_store",
                "build_retriever",
                "build_embeddings",
                "build_chat_model",
            }
        ),
    )
    created = create_app(service_builder=builder)

    async with created.router.lifespan_context(created):
        services = created.state.services
        assert not services.readiness.ready
        assert services.readiness.configuration
        assert services.readiness.classifier
        assert services.readiness.pipeline
        assert not services.readiness.vector_store
        assert not services.readiness.ollama_chat_model
        assert not services.readiness.ollama_embedding_model
        assert services.readiness.failure_codes == (
            "active_manifest_unavailable",
            "retriever_unavailable",
            "embedding_model_unavailable",
            "chat_model_unavailable",
        )
        assert services.pipeline.retriever is None
        assert services.pipeline.llm is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("classifier", "pipeline"))
async def test_mandatory_startup_failure_aborts_without_state(
    failure: str,
) -> None:
    calls: list[str] = []
    builder, _, _, _ = successful_builder(
        calls,
        warm_error=(
            OSError("private classifier path")
            if failure == "classifier"
            else None
        ),
        pipeline_error=(
            RuntimeError("private pipeline detail")
            if failure == "pipeline"
            else None
        ),
    )
    created = create_app(service_builder=builder)

    with pytest.raises(ApplicationStartupError) as captured:
        async with created.router.lifespan_context(created):
            pytest.fail("Mandatory startup failure entered lifespan.")

    assert "private" not in str(captured.value)
    assert getattr(created.state, "services", None) is None


@pytest.mark.asyncio
async def test_invalid_api_settings_abort_before_classifier_warmup() -> None:
    calls: list[str] = []
    builder, _, _, _ = successful_builder(calls)
    invalid_settings = replace(api_settings, max_concurrent_requests=0)
    created = create_app(
        api_runtime_settings=invalid_settings,
        service_builder=builder,
    )

    with pytest.raises(
        ApplicationStartupError,
        match="configuration is invalid",
    ):
        async with created.router.lifespan_context(created):
            pytest.fail("Invalid configuration entered lifespan.")

    assert calls == []


def test_dependencies_fail_closed_outside_active_lifespan() -> None:
    created = create_app(
        service_builder=successful_builder([])[0],
    )

    with pytest.raises(RuntimeError, match="services are unavailable"):
        get_app_services(request_for(created))


def test_factory_and_builder_reject_invalid_injection() -> None:
    with pytest.raises(TypeError, match="ApiSettings"):
        create_app(api_runtime_settings=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ServiceBuilder"):
        create_app(service_builder=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="callable"):
        ServiceBuilder(warm_classifier=None)  # type: ignore[arg-type]
