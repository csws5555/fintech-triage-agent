"""Strict public transport contracts for the Phase 3 API."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.ml.rag_config import settings
from app.ml.triage_types import PipelineAnswer, ResponseMode, RiskLevel


PublicStatus = Literal[
    "answered",
    "clarification_required",
    "safety_guidance",
    "request_refused",
    "action_not_confirmed",
    "unsupported",
    "service_fallback",
]
ReadinessStatus = Literal["ready", "degraded"]
ComponentStatus = Literal["ready", "unavailable"]

_INTERNAL_INFORMATION_REQUEST = "internal_information_request"
_ACTION_NOT_CONFIRMED_REASONS = frozenset(
    {
        "unverified_action_status_request",
        "account_operation_request",
    }
)
_UNSUPPORTED_REASONS = frozenset(
    {
        "unsupported_policy_scope",
        "no_allowed_policy_scope",
    }
)


class _StrictPublicModel(BaseModel):
    """Shared fail-closed validation for public payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ChatRequest(_StrictPublicModel):
    """The only customer-controlled chat input accepted by the API."""

    message: str

    @field_validator("message", mode="before")
    @classmethod
    def validate_message(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("message must be a string.")

        normalized = value.strip()
        if not normalized:
            raise ValueError("message cannot be blank.")
        if len(normalized) > settings.max_customer_message_length:
            raise ValueError(
                "message exceeds the maximum customer message length."
            )
        return normalized


class ChatResponse(_StrictPublicModel):
    """Safe customer-facing result derived from a pipeline answer."""

    request_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    status: PublicStatus
    response_mode: ResponseMode
    risk_level: RiskLevel
    requires_human: bool


class ErrorDetail(_StrictPublicModel):
    """Stable public error information without internal exception data."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool


class ErrorResponse(_StrictPublicModel):
    """Standard HTTP error envelope."""

    request_id: str = Field(min_length=1)
    error: ErrorDetail


class LivenessResponse(_StrictPublicModel):
    """Cheap process-liveness payload."""

    status: Literal["alive"]
    service: Literal["fintech-triage-api"]


class ReadinessComponents(_StrictPublicModel):
    """Safe availability snapshot for every required local component."""

    configuration: ComponentStatus
    classifier: ComponentStatus
    pipeline: ComponentStatus
    vector_store: ComponentStatus
    ollama_chat_model: ComponentStatus
    ollama_embedding_model: ComponentStatus


class ReadinessResponse(_StrictPublicModel):
    """Readiness payload with no local model or storage diagnostics."""

    status: ReadinessStatus
    components: ReadinessComponents

    @model_validator(mode="after")
    def validate_status_matches_components(self) -> ReadinessResponse:
        component_values = self.components.model_dump().values()
        all_ready = all(value == "ready" for value in component_values)
        expected_status = "ready" if all_ready else "degraded"
        if self.status != expected_status:
            raise ValueError(
                "readiness status must match component availability."
            )
        return self


class StreamMetadataEvent(_StrictPublicModel):
    """Safe answer metadata emitted before any SSE chunks."""

    request_id: str = Field(min_length=1)
    status: PublicStatus
    response_mode: ResponseMode
    risk_level: RiskLevel
    requires_human: bool


class StreamChunkEvent(_StrictPublicModel):
    """One ordered chunk of fully validated answer text."""

    request_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1)


class StreamDoneEvent(_StrictPublicModel):
    """Successful SSE completion marker."""

    request_id: str = Field(min_length=1)
    chunks: int = Field(ge=0)


class StreamErrorEvent(_StrictPublicModel):
    """Terminal safe error emitted after SSE headers were sent."""

    request_id: str = Field(min_length=1)
    error: ErrorDetail


def public_status_for_pipeline_answer(
    pipeline_answer: PipelineAnswer,
) -> PublicStatus:
    """Map internal pipeline state to the stable public status vocabulary."""

    if not isinstance(pipeline_answer, PipelineAnswer):
        raise TypeError("pipeline_answer must be a PipelineAnswer.")

    if pipeline_answer.response_mode == "grounded_generation":
        return "answered"
    if pipeline_answer.response_mode == "deterministic_clarification":
        return "clarification_required"
    if pipeline_answer.reason_code == _INTERNAL_INFORMATION_REQUEST:
        return "request_refused"
    if pipeline_answer.reason_code in _ACTION_NOT_CONFIRMED_REASONS:
        return "action_not_confirmed"
    if pipeline_answer.reason_code in _UNSUPPORTED_REASONS:
        return "unsupported"
    if pipeline_answer.response_mode == "deterministic_safety":
        return "safety_guidance"
    return "service_fallback"


def chat_response_from_pipeline_answer(
    *,
    request_id: str,
    pipeline_answer: PipelineAnswer,
) -> ChatResponse:
    """Build the public chat payload without copying internal-only fields."""

    return ChatResponse(
        request_id=request_id,
        answer=pipeline_answer.answer,
        status=public_status_for_pipeline_answer(pipeline_answer),
        response_mode=pipeline_answer.response_mode,
        risk_level=pipeline_answer.risk_level,
        requires_human=pipeline_answer.requires_human,
    )


def stream_metadata_from_chat_response(
    response: ChatResponse,
) -> StreamMetadataEvent:
    """Build SSE metadata without exposing the complete answer text."""

    if not isinstance(response, ChatResponse):
        raise TypeError("response must be a ChatResponse.")

    return StreamMetadataEvent(
        request_id=response.request_id,
        status=response.status,
        response_mode=response.response_mode,
        risk_level=response.risk_level,
        requires_human=response.requires_human,
    )


__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ComponentStatus",
    "ErrorDetail",
    "ErrorResponse",
    "LivenessResponse",
    "PublicStatus",
    "ReadinessComponents",
    "ReadinessResponse",
    "ReadinessStatus",
    "StreamChunkEvent",
    "StreamDoneEvent",
    "StreamErrorEvent",
    "StreamMetadataEvent",
    "chat_response_from_pipeline_answer",
    "public_status_for_pipeline_answer",
    "stream_metadata_from_chat_response",
]
