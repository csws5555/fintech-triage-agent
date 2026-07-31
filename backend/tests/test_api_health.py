from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.config import api_settings
from app.api.services import (
    OllamaModelAvailability,
    ReadinessCoordinator,
    ServiceReadiness,
)
from app.main import ServiceBuilder, create_app
from app.ml.ingest_policies import IngestionManifest
from app.ml.triage_types import ClassificationResult, PipelineAnswer


class FakePipeline:
    def __init__(self, **kwargs: Any) -> None:
        self.dependencies = kwargs
        self.answer_calls = 0

    def answer(
        self,
        *,
        query: str,
        classification: ClassificationResult,
    ) -> PipelineAnswer:
        self.answer_calls += 1
        raise AssertionError("Health checks must not execute the pipeline.")


class ForbiddenEmbeddings:
    def embed_query(self, _text: str) -> list[float]:
        raise AssertionError("Health checks must not create embeddings.")

    def embed_documents(self, _texts: list[str]) -> list[list[float]]:
        raise AssertionError("Health checks must not create embeddings.")


class ForbiddenChatModel:
    def invoke(self, _input: object) -> object:
        raise AssertionError("Health checks must not generate text.")

    def stream(self, _input: object) -> object:
        raise AssertionError("Health checks must not generate text.")


def manifest() -> IngestionManifest:
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


def builder(
    *,
    availability: OllamaModelAvailability = OllamaModelAvailability(
        chat_model=True,
        embedding_model=True,
    ),
    optional_failure: str | None = None,
    recover: bool = False,
    calls: list[str] | None = None,
) -> ServiceBuilder:
    observed = [] if calls is None else calls
    counts: dict[str, int] = {}

    def optional(name: str, result: object):
        def operation() -> object:
            observed.append(name)
            counts[name] = counts.get(name, 0) + 1
            if optional_failure == name and (
                not recover or counts[name] == 1
            ):
                raise OSError("private path token=secret")
            return result

        return operation

    def classifier(_message: str) -> ClassificationResult:
        raise AssertionError("Health checks must not run classifier inference.")

    def probe(timeout_seconds: int) -> OllamaModelAvailability:
        observed.append(f"probe:{timeout_seconds}")
        return availability

    return ServiceBuilder(
        warm_classifier=lambda: observed.append("warm_classifier"),
        classifier=classifier,
        inspect_vector_store=optional("vector_store", manifest()),
        build_retriever=optional("retriever", object()),
        build_embeddings=optional("embeddings", ForbiddenEmbeddings()),
        build_chat_model=optional("chat_model", ForbiddenChatModel()),
        build_pipeline=FakePipeline,
        probe_ollama_models=probe,
    )


def test_liveness_returns_exact_public_payload() -> None:
    created = create_app(service_builder=builder())

    with TestClient(created) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": "fintech-triage-api",
    }


def test_fully_ready_response_is_typed_and_cheap() -> None:
    calls: list[str] = []
    created = create_app(service_builder=builder(calls=calls))

    with TestClient(created) as client:
        response = client.get("/health/ready")
        pipeline = created.state.services.pipeline

        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "components": {
                "configuration": "ready",
                "classifier": "ready",
                "pipeline": "ready",
                "vector_store": "ready",
                "ollama_chat_model": "ready",
                "ollama_embedding_model": "ready",
            },
        }
        assert pipeline.answer_calls == 0

    assert calls.count(f"probe:{api_settings.health_timeout_seconds}") == 1


@pytest.mark.parametrize(
    "component",
    (
        "configuration",
        "classifier",
        "pipeline",
        "vector_store",
        "ollama_chat_model",
        "ollama_embedding_model",
    ),
)
def test_each_individual_unavailable_component_returns_http_503(
    component: str,
) -> None:
    created = create_app(service_builder=builder())

    with TestClient(created) as client:
        services = created.state.services
        values = {
            "configuration": True,
            "classifier": True,
            "pipeline": True,
            "vector_store": True,
            "ollama_chat_model": True,
            "ollama_embedding_model": True,
        }
        values[component] = False
        object.__setattr__(
            services,
            "readiness",
            ServiceReadiness(**values),
        )
        object.__setattr__(services, "readiness_coordinator", None)

        response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["components"][component] == "unavailable"
    assert set(payload) == {"status", "components"}


def test_failed_startup_dependency_recovers_once_without_replacing_pipeline() -> None:
    calls: list[str] = []
    created = create_app(
        service_builder=builder(
            optional_failure="chat_model",
            recover=True,
            calls=calls,
        )
    )

    with TestClient(created) as client:
        original_pipeline = created.state.services.pipeline
        response = client.get("/health/ready")

        assert response.status_code == 200
        assert created.state.services.pipeline is original_pipeline
        assert created.state.services.readiness.ready

    assert calls.count("chat_model") == 2


@pytest.mark.asyncio
async def test_concurrent_checks_share_recovery_and_cooldown() -> None:
    recovery_calls = 0
    probe_calls = 0

    async def recover(
        _snapshot: ServiceReadiness,
    ) -> ServiceReadiness:
        nonlocal recovery_calls
        recovery_calls += 1
        await asyncio.sleep(0)
        return ServiceReadiness(
            configuration=True,
            classifier=True,
            pipeline=True,
            vector_store=True,
            ollama_chat_model=True,
            ollama_embedding_model=True,
        )

    def probe(_timeout: int) -> OllamaModelAvailability:
        nonlocal probe_calls
        probe_calls += 1
        return OllamaModelAvailability(True, True)

    coordinator = ReadinessCoordinator(
        initial=ServiceReadiness(
            configuration=True,
            classifier=True,
            pipeline=True,
            vector_store=False,
            ollama_chat_model=True,
            ollama_embedding_model=True,
        ),
        model_probe=probe,
        recover_optional=recover,
        runtime_settings=replace(
            api_settings,
            health_timeout_seconds=2,
            readiness_retry_cooldown_seconds=60,
        ),
    )

    results = await asyncio.gather(
        coordinator.check(),
        coordinator.check(),
        coordinator.check(),
    )

    assert all(result.ready for result in results)
    assert recovery_calls == 1
    assert probe_calls == 1


@pytest.mark.asyncio
async def test_health_timeout_fails_closed_without_private_details() -> None:
    async def slow_recovery(
        _snapshot: ServiceReadiness,
    ) -> ServiceReadiness:
        await asyncio.sleep(2)
        raise AssertionError("not reached")

    coordinator = ReadinessCoordinator(
        initial=ServiceReadiness(
            configuration=True,
            classifier=True,
            pipeline=True,
            vector_store=False,
            ollama_chat_model=True,
            ollama_embedding_model=True,
        ),
        model_probe=lambda _timeout: OllamaModelAvailability(True, True),
        recover_optional=slow_recovery,
        runtime_settings=replace(
            api_settings,
            health_timeout_seconds=1,
        ),
    )

    snapshot = await coordinator.check()

    assert not snapshot.ready
    assert not snapshot.ollama_chat_model
    assert not snapshot.ollama_embedding_model
    assert snapshot.failure_codes == ("health_check_unavailable",)
