"""Bounded structured generation through the approved local chat model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage

from app.ml.chat_model import get_chat_model
from app.ml.grounding_prompt import SYSTEM_GROUNDING_RULES
from app.ml.response_templates import insufficient_policy_response
from app.ml.triage_types import GeneratedSupportResponse


STRUCTURED_GENERATION_INPUT_INVALID = (
    "structured_generation_input_invalid"
)
STRUCTURED_GENERATION_UNAVAILABLE = (
    "structured_generation_unavailable"
)
STRUCTURED_GENERATION_FAILED = "structured_generation_failed"

STRICT_STRUCTURED_OUTPUT_RETRY_RULES = """STRUCTURED OUTPUT RETRY

The previous response did not satisfy the required schema.

Return exactly one structured object with these fields and types:
- answer: string
- needs_human: boolean
- insufficient_policy: boolean
- claimed_completed_action: boolean

Do not add fields, prose, Markdown fences, or hidden reasoning.
Continue to follow the original system rules. Use exactly the same approved
policy context and customer message supplied below."""

_HUMAN_PROMPT_MARKERS = (
    "BEGIN APPROVED POLICY CONTEXT JSON",
    "END APPROVED POLICY CONTEXT JSON",
    "BEGIN CUSTOMER MESSAGE JSON",
    "END CUSTOMER MESSAGE JSON",
)


@dataclass(frozen=True, slots=True)
class StructuredGenerationResult:
    """Internal result of schema-bound local generation."""

    response: GeneratedSupportResponse
    used_fallback: bool
    failure_codes: tuple[str, ...] = ()


def generate_structured_response(
    messages: object,
    *,
    chat_model: object | None = None,
) -> StructuredGenerationResult:
    """Generate once, retry once, then return an approved fallback."""

    validated_messages = _validate_grounding_messages(messages)

    if validated_messages is None:
        return _fallback_result(
            STRUCTURED_GENERATION_INPUT_INVALID
        )

    try:
        model = (
            get_chat_model()
            if chat_model is None
            else chat_model
        )
        binder = getattr(model, "with_structured_output", None)

        if not callable(binder):
            return _fallback_result(
                STRUCTURED_GENERATION_UNAVAILABLE
            )

        structured_model = binder(GeneratedSupportResponse)
        invoke = getattr(structured_model, "invoke", None)

        if not callable(invoke):
            return _fallback_result(
                STRUCTURED_GENERATION_UNAVAILABLE
            )
    except Exception:
        return _fallback_result(
            STRUCTURED_GENERATION_UNAVAILABLE
        )

    attempts = (
        validated_messages,
        _build_retry_messages(validated_messages),
    )

    for attempt_messages in attempts:
        try:
            result = invoke(attempt_messages)
        except Exception:
            continue

        if isinstance(result, GeneratedSupportResponse):
            return StructuredGenerationResult(
                response=result,
                used_fallback=False,
            )

    return _fallback_result(STRUCTURED_GENERATION_FAILED)


def _validate_grounding_messages(
    messages: object,
) -> tuple[SystemMessage, HumanMessage] | None:
    if (
        not isinstance(messages, tuple)
        or len(messages) != 2
        or not isinstance(messages[0], SystemMessage)
        or not isinstance(messages[1], HumanMessage)
    ):
        return None

    system, human = messages

    if (
        not isinstance(system.content, str)
        or system.content != SYSTEM_GROUNDING_RULES
        or not isinstance(human.content, str)
        or not human.content.strip()
        or any(
            marker not in human.content
            for marker in _HUMAN_PROMPT_MARKERS
        )
    ):
        return None

    marker_positions = tuple(
        human.content.index(marker)
        for marker in _HUMAN_PROMPT_MARKERS
    )

    if marker_positions != tuple(sorted(marker_positions)):
        return None

    return cast(
        tuple[SystemMessage, HumanMessage],
        messages,
    )


def _build_retry_messages(
    messages: tuple[SystemMessage, HumanMessage],
) -> tuple[SystemMessage, SystemMessage, HumanMessage]:
    return (
        messages[0],
        SystemMessage(
            content=STRICT_STRUCTURED_OUTPUT_RETRY_RULES
        ),
        messages[1],
    )


def _fallback_result(
    failure_code: str,
) -> StructuredGenerationResult:
    return StructuredGenerationResult(
        response=GeneratedSupportResponse(
            answer=insufficient_policy_response(),
            needs_human=True,
            insufficient_policy=True,
            claimed_completed_action=False,
        ),
        used_fallback=True,
        failure_codes=(failure_code,),
    )


__all__ = [
    "STRICT_STRUCTURED_OUTPUT_RETRY_RULES",
    "STRUCTURED_GENERATION_FAILED",
    "STRUCTURED_GENERATION_INPUT_INVALID",
    "STRUCTURED_GENERATION_UNAVAILABLE",
    "StructuredGenerationResult",
    "generate_structured_response",
]
