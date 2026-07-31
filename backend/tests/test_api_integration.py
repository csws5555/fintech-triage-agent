"""Local runner checks and read-only real-stack API integration coverage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.config import ApiConfigurationError, api_settings
from app.api.middleware import REQUEST_ID_HEADER
from app.main import create_app
from app.ml import rag_pipeline as rag_pipeline_module
from app.ml.output_validator import OutputValidator
from app.ml.rag_config import settings
from app.ml.triage_types import OutputValidationResult
from scripts.run_api import run_local_api


CHAT_PATH = f"{api_settings.api_prefix}/chat"
STREAM_PATH = f"{api_settings.api_prefix}/chat/stream"
SUPPORTED_QUERY = "My first physical card has not arrived."
STOLEN_CARD_QUERY = "My card was stolen in London."
UNSUPPORTED_QUERY = "What mortgage rate can I receive?"

_CHAT_FIELDS = {
    "request_id",
    "answer",
    "status",
    "response_mode",
    "risk_level",
    "requires_human",
}
_INTERNAL_FIELD_NAMES = (
    "reason_code",
    "retrieval_sufficient",
    "retrieved_policy_ids",
    "retrieved_chunk_ids",
    "predictions",
    "confidence",
    "top_two_margin",
    "allowed_policy_ids",
    "required_policy_ids",
    "security_signals",
    "failure_codes",
)


def test_local_runner_uses_validated_settings_and_exactly_one_worker() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def server_runner(application: str, **options: object) -> None:
        calls.append((application, options))

    run_local_api(server_runner=server_runner)

    assert calls == [
        (
            "app.main:app",
            {
                "host": api_settings.host,
                "port": api_settings.port,
                "log_level": api_settings.log_level.lower(),
                "workers": 1,
                "reload": False,
            },
        )
    ]

    with pytest.raises(ApiConfigurationError):
        run_local_api(
            replace(api_settings, port=0),
            server_runner=server_runner,
        )
    assert len(calls) == 1


def _active_manifest_hash() -> str:
    manifest_path = settings.ingestion_manifest_path
    assert manifest_path.is_file()
    assert not manifest_path.is_symlink()
    assert manifest_path.parent == settings.chroma_store_dir
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    assert body.endswith("\n\n")
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in body.removesuffix("\n\n").split("\n\n"):
        lines = frame.splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        payload = json.loads(lines[1].removeprefix("data: "))
        assert isinstance(payload, dict)
        events.append(
            (
                lines[0].removeprefix("event: "),
                payload,
            )
        )
    return events


def _assert_chat_contract(payload: object, request_id: str) -> dict[str, Any]:
    assert isinstance(payload, dict)
    assert set(payload) == _CHAT_FIELDS
    assert payload["request_id"] == request_id
    assert isinstance(payload["answer"], str)
    assert payload["answer"].strip()
    assert len(payload["answer"]) <= settings.max_response_characters
    assert isinstance(payload["requires_human"], bool)
    return payload


def _assert_no_internal_data(texts: Iterator[str]) -> None:
    combined = "\n".join(texts).casefold()
    forbidden_values = (
        *_INTERNAL_FIELD_NAMES,
        settings.chat_model,
        settings.embedding_model,
        settings.collection_name,
        "fraud_policy",
        "card_replacement",
        "card_delivery",
        "international_fees",
        str(settings.classifier_model_dir),
        str(settings.chroma_store_dir),
        ".env",
    )
    for forbidden in forbidden_values:
        assert forbidden.casefold() not in combined


@pytest.mark.integration
def test_real_api_lifespan_json_sse_and_safe_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the protected classifier and complete active local stack."""

    prompt_calls = 0
    generation_calls = 0
    validation_calls = 0
    original_prompt_builder = rag_pipeline_module.build_grounding_prompt
    original_generator = rag_pipeline_module.generate_structured_response
    original_validate = OutputValidator.validate

    def tracked_prompt_builder(*args: object, **kwargs: object) -> object:
        nonlocal prompt_calls
        prompt_calls += 1
        return original_prompt_builder(*args, **kwargs)

    def tracked_generator(*args: object, **kwargs: object) -> object:
        nonlocal generation_calls
        generation_calls += 1
        return original_generator(*args, **kwargs)

    def tracked_validate(
        validator: OutputValidator,
        generated: object,
        *,
        decision: object,
        policies: object = (),
    ) -> OutputValidationResult:
        nonlocal validation_calls
        validation_calls += 1
        return original_validate(
            validator,
            generated,
            decision=decision,
            policies=policies,
        )

    monkeypatch.setattr(
        rag_pipeline_module,
        "build_grounding_prompt",
        tracked_prompt_builder,
    )
    monkeypatch.setattr(
        rag_pipeline_module,
        "generate_structured_response",
        tracked_generator,
    )
    monkeypatch.setattr(OutputValidator, "validate", tracked_validate)

    manifest_before = _active_manifest_hash()
    application = create_app()
    public_texts: list[str] = []

    with TestClient(
        application,
        raise_server_exceptions=False,
    ) as client:
        liveness = client.get("/health/live")
        assert liveness.status_code == 200
        assert liveness.json() == {
            "status": "alive",
            "service": "fintech-triage-api",
        }
        public_texts.append(liveness.text)

        readiness = client.get("/health/ready")
        assert readiness.status_code == 200
        assert readiness.json() == {
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
        public_texts.append(readiness.text)

        supported = client.post(
            CHAT_PATH,
            json={"message": SUPPORTED_QUERY},
        )
        assert supported.status_code == 200
        supported_payload = _assert_chat_contract(
            supported.json(),
            supported.headers[REQUEST_ID_HEADER],
        )
        assert supported_payload["risk_level"] == "low"
        assert (
            supported_payload["status"],
            supported_payload["response_mode"],
        ) in {
            ("answered", "grounded_generation"),
            ("service_fallback", "static_fallback"),
        }
        assert prompt_calls == 1
        assert generation_calls == 1
        assert validation_calls == 1
        public_texts.append(supported.text)

        generation_count_after_supported = generation_calls
        stolen = client.post(
            STREAM_PATH,
            json={"message": STOLEN_CARD_QUERY},
            headers={"Accept": "text/event-stream"},
        )
        assert stolen.status_code == 200
        assert stolen.headers["content-type"].startswith(
            "text/event-stream"
        )
        assert stolen.headers["cache-control"] == "no-cache"
        events = _parse_sse(stolen.text)
        assert [event_name for event_name, _payload in events] == [
            "metadata",
            *("chunk" for _event in events[1:-1]),
            "done",
        ]
        metadata = events[0][1]
        request_id = stolen.headers[REQUEST_ID_HEADER]
        assert metadata == {
            "request_id": request_id,
            "status": "safety_guidance",
            "response_mode": "deterministic_safety",
            "risk_level": "high",
            "requires_human": False,
        }
        chunks = events[1:-1]
        assert chunks
        assert all(name == "chunk" for name, _payload in chunks)
        assert [
            payload["sequence"] for _name, payload in chunks
        ] == list(range(len(chunks)))
        assert all(
            payload["request_id"] == request_id
            for _name, payload in chunks
        )
        stolen_answer = "".join(
            payload["text"] for _name, payload in chunks
        )
        assert stolen_answer.strip()
        assert "freeze" in stolen_answer.casefold()
        assert events[-1] == (
            "done",
            {
                "request_id": request_id,
                "chunks": len(chunks),
            },
        )
        assert generation_calls == generation_count_after_supported
        public_texts.append(stolen.text)

        unsupported = client.post(
            CHAT_PATH,
            json={"message": UNSUPPORTED_QUERY},
        )
        assert unsupported.status_code == 200
        unsupported_payload = _assert_chat_contract(
            unsupported.json(),
            unsupported.headers[REQUEST_ID_HEADER],
        )
        assert unsupported_payload == {
            "request_id": unsupported.headers[REQUEST_ID_HEADER],
            "answer": unsupported_payload["answer"],
            "status": "unsupported",
            "response_mode": "static_fallback",
            "risk_level": "low",
            "requires_human": True,
        }
        assert generation_calls == generation_count_after_supported
        public_texts.append(unsupported.text)

    assert _active_manifest_hash() == manifest_before
    _assert_no_internal_data(iter(public_texts))
