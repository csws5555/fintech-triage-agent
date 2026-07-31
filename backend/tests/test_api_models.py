"""Tests for strict, non-leaking Phase 3 API contracts."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    ErrorResponse,
    LivenessResponse,
    ReadinessComponents,
    ReadinessResponse,
    StreamChunkEvent,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamMetadataEvent,
    chat_response_from_pipeline_answer,
    public_status_for_pipeline_answer,
    stream_metadata_from_chat_response,
)
from app.ml.rag_config import settings
from app.ml.triage_types import PipelineAnswer


INTERNAL_FIELD_NAMES = frozenset(
    {
        "reason_code",
        "predictions",
        "confidence",
        "top_two_margin",
        "retrieval_sufficient",
        "retrieved_policy_ids",
        "retrieved_chunk_ids",
        "allowed_policy_ids",
        "required_policy_ids",
        "prompt",
        "distance",
        "source_file",
    }
)


def _pipeline_answer(
    *,
    response_mode: str = "deterministic_safety",
    reason_code: str = "direct_stolen_card_signal",
) -> PipelineAnswer:
    return PipelineAnswer(
        answer="Use the official app and contact official support if needed.",
        response_mode=response_mode,
        risk_level="high",
        requires_human=False,
        retrieval_sufficient=True,
        retrieved_policy_ids=("fraud_policy",),
        retrieved_chunk_ids=("private-chunk-id",),
        reason_code=reason_code,
    )


def _assert_rejects_extra_field(
    model_type: type[Any],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model_type.model_validate({**payload, "diagnostic": "private"})


def test_chat_request_strips_only_surrounding_whitespace() -> None:
    request = ChatRequest(message=" \tKeep   internal\nspacing.\r\n ")

    assert request.message == "Keep   internal\nspacing."


@pytest.mark.parametrize("message", ["", " ", "\t\r\n"])
def test_chat_request_rejects_empty_or_whitespace_only(message: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message=message)


def test_chat_request_rejects_oversized_normalized_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            message="x" * (settings.max_customer_message_length + 1)
        )


def test_chat_request_accepts_message_at_authoritative_limit() -> None:
    message = "x" * settings.max_customer_message_length

    assert ChatRequest(message=message).message == message


@pytest.mark.parametrize("message", [None, 1, True, ["message"]])
def test_chat_request_rejects_non_string_values(message: object) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message=message)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "hello", "request_id": "client-id"},
        {"message": "hello", "conversation_id": "client-conversation"},
        {"message": "hello", "risk_level": "low"},
        {"message": "hello", "allowed_policy_ids": ["fraud_policy"]},
        {"message": "hello", "prompt": "hidden"},
    ],
)
def test_chat_request_rejects_every_unknown_or_trusted_field(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("response_mode", "reason_code", "expected"),
    [
        ("grounded_generation", "supported_policy_generation", "answered"),
        (
            "deterministic_clarification",
            "classifier_uncertain",
            "clarification_required",
        ),
        (
            "deterministic_safety",
            "internal_information_request",
            "request_refused",
        ),
        (
            "deterministic_safety",
            "unverified_action_status_request",
            "action_not_confirmed",
        ),
        (
            "deterministic_safety",
            "account_operation_request",
            "action_not_confirmed",
        ),
        (
            "static_fallback",
            "unsupported_policy_scope",
            "unsupported",
        ),
        (
            "static_fallback",
            "no_allowed_policy_scope",
            "unsupported",
        ),
        (
            "deterministic_safety",
            "direct_stolen_card_signal",
            "safety_guidance",
        ),
        ("static_fallback", "retrieval_failed", "service_fallback"),
    ],
)
def test_every_public_status_mapping(
    response_mode: str,
    reason_code: str,
    expected: str,
) -> None:
    answer = _pipeline_answer(
        response_mode=response_mode,
        reason_code=reason_code,
    )

    assert public_status_for_pipeline_answer(answer) == expected


def test_status_mapping_rejects_non_pipeline_value() -> None:
    with pytest.raises(TypeError):
        public_status_for_pipeline_answer(object())  # type: ignore[arg-type]


def test_chat_response_mapper_exposes_only_approved_fields() -> None:
    pipeline_answer = _pipeline_answer(
        response_mode="grounded_generation",
        reason_code="supported_policy_generation",
    )

    response = chat_response_from_pipeline_answer(
        request_id="server-request-id",
        pipeline_answer=pipeline_answer,
    )

    assert response.model_dump() == {
        "request_id": "server-request-id",
        "answer": pipeline_answer.answer,
        "status": "answered",
        "response_mode": "grounded_generation",
        "risk_level": "high",
        "requires_human": False,
    }
    assert INTERNAL_FIELD_NAMES.isdisjoint(response.model_dump())


def test_chat_response_mapper_validates_request_id() -> None:
    with pytest.raises(ValidationError):
        chat_response_from_pipeline_answer(
            request_id="",
            pipeline_answer=_pipeline_answer(),
        )


def test_chat_response_is_strict_and_forbids_extra_fields() -> None:
    payload = {
        "request_id": "request-id",
        "answer": "Safe answer.",
        "status": "answered",
        "response_mode": "grounded_generation",
        "risk_level": "low",
        "requires_human": False,
    }
    _assert_rejects_extra_field(ChatResponse, payload)

    with pytest.raises(ValidationError):
        ChatResponse.model_validate({**payload, "requires_human": 0})


def test_error_models_serialize_only_safe_contract_fields() -> None:
    response = ErrorResponse(
        request_id="request-id",
        error=ErrorDetail(
            code="invalid_request",
            message="The request body is invalid.",
            retryable=False,
        ),
    )

    assert response.model_dump() == {
        "request_id": "request-id",
        "error": {
            "code": "invalid_request",
            "message": "The request body is invalid.",
            "retryable": False,
        },
    }
    _assert_rejects_extra_field(
        ErrorResponse,
        {
            "request_id": "request-id",
            "error": response.error,
        },
    )
    _assert_rejects_extra_field(
        ErrorDetail,
        {
            "code": "invalid_request",
            "message": "The request body is invalid.",
            "retryable": False,
        },
    )


def test_liveness_contract_is_exact_and_strict() -> None:
    response = LivenessResponse(
        status="alive",
        service="fintech-triage-api",
    )

    assert response.model_dump() == {
        "status": "alive",
        "service": "fintech-triage-api",
    }
    with pytest.raises(ValidationError):
        LivenessResponse(status="ready", service="fintech-triage-api")


def test_readiness_contract_requires_every_safe_component() -> None:
    response = ReadinessResponse(
        status="degraded",
        components=ReadinessComponents(
            configuration="ready",
            classifier="ready",
            pipeline="ready",
            vector_store="unavailable",
            ollama_chat_model="unavailable",
            ollama_embedding_model="ready",
        ),
    )

    assert response.model_dump() == {
        "status": "degraded",
        "components": {
            "configuration": "ready",
            "classifier": "ready",
            "pipeline": "ready",
            "vector_store": "unavailable",
            "ollama_chat_model": "unavailable",
            "ollama_embedding_model": "ready",
        },
    }

    with pytest.raises(ValidationError):
        ReadinessComponents(
            configuration="ready",
            classifier="ready",
            pipeline="ready",
            vector_store="ready",
            ollama_chat_model="ready",
        )


def test_readiness_rejects_unknown_status_and_component() -> None:
    with pytest.raises(ValidationError):
        ReadinessResponse.model_validate(
            {
                "status": "starting",
                "components": {
                    "configuration": "ready",
                    "classifier": "ready",
                    "pipeline": "ready",
                    "vector_store": "ready",
                    "ollama_chat_model": "ready",
                    "ollama_embedding_model": "ready",
                    "model_path": "private",
                },
            }
        )


@pytest.mark.parametrize(
    ("status", "unavailable_component"),
    [
        ("ready", True),
        ("degraded", False),
    ],
)
def test_readiness_status_must_match_component_availability(
    status: str,
    unavailable_component: bool,
) -> None:
    vector_store = "unavailable" if unavailable_component else "ready"

    with pytest.raises(ValidationError):
        ReadinessResponse(
            status=status,
            components=ReadinessComponents(
                configuration="ready",
                classifier="ready",
                pipeline="ready",
                vector_store=vector_store,
                ollama_chat_model="ready",
                ollama_embedding_model="ready",
            ),
        )


def test_stream_metadata_excludes_complete_answer() -> None:
    chat_response = chat_response_from_pipeline_answer(
        request_id="request-id",
        pipeline_answer=_pipeline_answer(),
    )

    metadata = stream_metadata_from_chat_response(chat_response)

    assert metadata.model_dump() == {
        "request_id": "request-id",
        "status": "safety_guidance",
        "response_mode": "deterministic_safety",
        "risk_level": "high",
        "requires_human": False,
    }
    assert "answer" not in metadata.model_dump()


def test_stream_metadata_mapper_requires_chat_response() -> None:
    with pytest.raises(TypeError):
        stream_metadata_from_chat_response(object())  # type: ignore[arg-type]


def test_stream_event_contracts_are_strict_and_serializable() -> None:
    metadata = StreamMetadataEvent(
        request_id="request-id",
        status="answered",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
    )
    chunk = StreamChunkEvent(
        request_id="request-id",
        sequence=0,
        text="Validated text.",
    )
    done = StreamDoneEvent(request_id="request-id", chunks=1)
    error = StreamErrorEvent(
        request_id="request-id",
        error=ErrorDetail(
            code="stream_interrupted",
            message="The response stream was interrupted.",
            retryable=True,
        ),
    )

    assert metadata.model_dump()["status"] == "answered"
    assert chunk.model_dump()["sequence"] == 0
    assert done.model_dump()["chunks"] == 1
    assert error.model_dump()["error"]["code"] == "stream_interrupted"

    with pytest.raises(ValidationError):
        StreamChunkEvent(
            request_id="request-id",
            sequence=-1,
            text="Validated text.",
        )
    with pytest.raises(ValidationError):
        StreamDoneEvent(request_id="request-id", chunks=True)
    _assert_rejects_extra_field(
        StreamErrorEvent,
        {
            "request_id": "request-id",
            "error": error.error,
        },
    )


def test_public_model_serialization_never_contains_internal_field_names() -> None:
    payloads = (
        chat_response_from_pipeline_answer(
            request_id="request-id",
            pipeline_answer=_pipeline_answer(),
        ).model_dump(),
        ErrorResponse(
            request_id="request-id",
            error=ErrorDetail(
                code="internal_error",
                message="The request could not be completed.",
                retryable=False,
            ),
        ).model_dump(),
        LivenessResponse(
            status="alive",
            service="fintech-triage-api",
        ).model_dump(),
        ReadinessResponse(
            status="ready",
            components=ReadinessComponents(
                configuration="ready",
                classifier="ready",
                pipeline="ready",
                vector_store="ready",
                ollama_chat_model="ready",
                ollama_embedding_model="ready",
            ),
        ).model_dump(),
    )

    serialized = repr(payloads)
    for field_name in INTERNAL_FIELD_NAMES:
        assert field_name not in serialized
