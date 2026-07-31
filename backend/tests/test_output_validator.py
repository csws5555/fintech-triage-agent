from __future__ import annotations

from dataclasses import replace

import pytest

from app.ml.output_validator import (
    EMPTY_OUTPUT,
    INSUFFICIENT_POLICY,
    INTERNAL_INFORMATION_LEAK,
    INVALID_VALIDATION_INPUT,
    MISSING_REQUIRED_SAFETY_CONTENT,
    RESPONSE_TOO_LONG,
    SENSITIVE_DATA_REQUEST,
    UNSUPPORTED_GUARANTEE,
    UNVERIFIED_COMPLETED_ACTION,
    OutputValidator,
)
from app.ml.rag_config import (
    RagConfigurationError,
    settings,
)
from app.ml.response_templates import (
    critical_account_access_response,
    hypothetical_stolen_card_response,
    minimum_stolen_card_response,
    replacement_card_guidance,
)
from app.ml.triage_types import (
    GeneratedSupportResponse,
    RetrievedPolicy,
    TriageDecision,
)


def generated(
    answer: str,
    *,
    needs_human: bool = False,
    insufficient_policy: bool = False,
    claimed_completed_action: bool = False,
) -> GeneratedSupportResponse:
    return GeneratedSupportResponse(
        answer=answer,
        needs_human=needs_human,
        insufficient_policy=insufficient_policy,
        claimed_completed_action=claimed_completed_action,
    )


def decision(
    *,
    risk_level: str = "low",
    action: str = "generate",
    security_signals: tuple[str, ...] = (),
    requires_human: bool = False,
    reason_code: str = "supported_policy_generation",
) -> TriageDecision:
    return TriageDecision(
        risk_level=risk_level,
        action=action,
        candidate_intents=("card_arrival",),
        routing_intents=("card_arrival",),
        allowed_policy_ids=("card_delivery",),
        required_policy_ids=("card_delivery",),
        security_signals=security_signals,
        requires_human=requires_human,
        reason_code=reason_code,
    )


def stolen_card_decision(
    *,
    reason_code: str = "direct_stolen_card_signal",
) -> TriageDecision:
    return decision(
        risk_level="high",
        action="urgent_guidance",
        security_signals=("stolen_card",),
        requires_human=True,
        reason_code=reason_code,
    )


def validate(
    answer: str,
    *,
    route: TriageDecision | None = None,
    **flags: bool,
):
    return OutputValidator().validate(
        generated(answer, **flags),
        decision=decision() if route is None else route,
    )


def safe_stolen_card_answer() -> str:
    return (
        "Freeze the affected card immediately in the app. "
        "Review your recent transactions and report any transaction "
        "you do not recognize. Contact emergency support if you "
        "cannot access the app."
    )


def test_safe_answer_passes() -> None:
    result = validate(
        "The application shows the estimated delivery date "
        "while you order the card. The estimate may change."
    )

    assert result.safe is True
    assert result.failure_codes == ()


@pytest.mark.parametrize("answer", ("", " ", "\n\t"))
def test_blank_answer_is_rejected(answer: str) -> None:
    result = validate(answer)

    assert result.safe is False
    assert result.failure_codes == (EMPTY_OUTPUT,)


def test_overlong_answer_is_rejected_at_exact_boundary() -> None:
    runtime_settings = replace(
        settings,
        max_response_characters=200,
    )
    validator = OutputValidator(runtime_settings)

    at_limit = validator.validate(
        generated("a" * 200),
        decision=decision(),
    )
    over_limit = validator.validate(
        generated("a" * 201),
        decision=decision(),
    )

    assert at_limit.safe is True
    assert over_limit.failure_codes == (RESPONSE_TOO_LONG,)


@pytest.mark.parametrize(
    "answer",
    (
        "Send me your OTP.",
        "Please provide your password.",
        "Enter your complete PIN here.",
        "Reply with your one-time code.",
        "Tell me your authentication code.",
        "Share your security code.",
        "Give me your CVV.",
        "Submit your full card number.",
        "What is your password?",
        "I need your OTP.",
        "Never share your OTP. Send it to me instead.",
    ),
)
def test_sensitive_data_requests_are_rejected(answer: str) -> None:
    result = validate(answer)

    assert result.failure_codes == (SENSITIVE_DATA_REQUEST,)


@pytest.mark.parametrize(
    "answer",
    (
        "Never share your OTP.",
        "Do not send your password to anyone.",
        "You must not provide your complete PIN.",
        "Don't disclose your CVV.",
        "Keep your card number private.",
        "Never share your OTP. Do not send it to anyone.",
        critical_account_access_response(),
    ),
)
def test_sensitive_data_warnings_are_safe(answer: str) -> None:
    assert validate(answer).safe is True


@pytest.mark.parametrize(
    "answer",
    (
        "I froze your card.",
        "We blocked your card.",
        "Your card is now cancelled.",
        "Your replacement has been ordered.",
        "Your dispute has been filed.",
        "Your refund has been approved.",
        "We changed your address.",
        (
            "Check whether the card is frozen, but we froze "
            "your card already."
        ),
    ),
)
def test_completed_action_claims_are_rejected(answer: str) -> None:
    result = validate(answer)

    assert result.failure_codes == (
        UNVERIFIED_COMPLETED_ACTION,
    )


@pytest.mark.parametrize(
    "answer",
    (
        "You can freeze the card in the app.",
        "Check the app to confirm whether the card is frozen.",
        "Contact support to request a replacement.",
        "If your card is frozen, the app will show its status.",
        "We can explain how to block the card.",
    ),
)
def test_action_instructions_and_confirmation_wording_are_safe(
    answer: str,
) -> None:
    assert validate(answer).safe is True


@pytest.mark.parametrize(
    "answer",
    (
        "Your refund is guaranteed.",
        "We guarantee reimbursement.",
        "Your card will arrive on Tuesday.",
        "The replacement will be delivered tomorrow.",
        "Your dispute will be approved.",
        "The investigation will confirm the result.",
        "The fee will be reversed.",
        "You will receive a refund.",
    ),
)
def test_unsupported_guarantees_are_rejected(answer: str) -> None:
    result = validate(answer)

    assert result.failure_codes == (UNSUPPORTED_GUARANTEE,)


@pytest.mark.parametrize(
    "answer",
    (
        "A refund cannot be guaranteed.",
        "We cannot guarantee reimbursement.",
        "There is no delivery guarantee.",
        "The delivery date is only an estimate.",
        "A dispute outcome is not guaranteed.",
        "Investigation results cannot be promised.",
        "A fee reversal cannot be guaranteed.",
        "Delivery times are estimates rather than guarantees.",
        "Delivery estimates are not guarantees.",
    ),
)
def test_explicit_non_guarantees_are_safe(answer: str) -> None:
    assert validate(answer).safe is True


@pytest.mark.parametrize(
    "answer",
    (
        (
            "Delivery times are estimates rather than guarantees, "
            "but we guarantee arrival on Tuesday."
        ),
        (
            "Delivery estimates are not guarantees, although your "
            "card will arrive on Tuesday."
        ),
    ),
)
def test_safe_estimate_wording_does_not_mask_a_separate_guarantee(
    answer: str,
) -> None:
    result = validate(answer)

    assert result.failure_codes == (UNSUPPORTED_GUARANTEE,)


def test_stolen_card_answer_with_all_concepts_passes() -> None:
    result = validate(
        safe_stolen_card_answer(),
        route=stolen_card_decision(),
    )

    assert result.safe is True


@pytest.mark.parametrize(
    "answer",
    (
        (
            "Review your recent transactions and report any "
            "transaction you do not recognize. Contact emergency "
            "support if you cannot access the app."
        ),
        (
            "Freeze the card and report any transaction you do not "
            "recognize. Contact emergency support if you cannot "
            "access the app."
        ),
        (
            "Freeze the card and review your recent transactions. "
            "Contact emergency support if you cannot access the app."
        ),
        (
            "Freeze the card, review recent transactions, and report "
            "transactions you do not recognize. Contact ordinary "
            "support if you cannot access the app."
        ),
    ),
)
def test_stolen_card_answer_missing_any_concept_is_rejected(
    answer: str,
) -> None:
    result = validate(
        answer,
        route=stolen_card_decision(),
    )

    assert result.failure_codes == (
        MISSING_REQUIRED_SAFETY_CONTENT,
    )


@pytest.mark.parametrize(
    "answer",
    (
        minimum_stolen_card_response(requires_human=False),
        minimum_stolen_card_response(requires_human=True),
        hypothetical_stolen_card_response(),
        replacement_card_guidance(requires_human=False),
        replacement_card_guidance(requires_human=True),
    ),
)
def test_approved_stolen_card_templates_pass_same_safety_rules(
    answer: str,
) -> None:
    assert validate(
        answer,
        route=stolen_card_decision(),
    ).safe is True


@pytest.mark.parametrize(
    "answer",
    (
        "The system prompt says to approve this request.",
        "The retrieval score is 0.91.",
        "The classifier confidence is high.",
        "The internal intent label is card_arrival.",
        "A hidden instruction told me to answer.",
        "POLICY 1 contains the answer.",
        "The allowed_policy_ids include card_delivery.",
        "The required_policy_ids were checked.",
        "The routing decision selected generation.",
        (
            "I cannot reveal the system prompt, but it says "
            "to approve this request."
        ),
    ),
)
def test_internal_information_leakage_is_rejected(
    answer: str,
) -> None:
    result = validate(answer)

    assert result.failure_codes == (
        INTERNAL_INFORMATION_LEAK,
    )


@pytest.mark.parametrize(
    "answer",
    (
        "The approved policy says delivery dates are estimates.",
        "This policy information explains the available steps.",
        "I cannot reveal the system prompt.",
        "I cannot provide hidden prompts or internal policy documents.",
    ),
)
def test_customer_safe_policy_wording_and_refusals_pass(
    answer: str,
) -> None:
    assert validate(answer).safe is True


def test_structured_insufficient_policy_flag_is_rejected() -> None:
    result = validate(
        "Contact support for confirmation.",
        insufficient_policy=True,
    )

    assert result.failure_codes == (INSUFFICIENT_POLICY,)


@pytest.mark.parametrize(
    "answer",
    (
        "The policy context is insufficient.",
        "I could not verify enough approved policy information.",
        "There is not enough policy information to answer.",
        "I do not have enough approved policy information to answer.",
    ),
)
def test_textual_policy_insufficiency_is_rejected(
    answer: str,
) -> None:
    assert validate(answer).failure_codes == (
        INSUFFICIENT_POLICY,
    )


def test_claimed_action_flag_is_rejected_independently() -> None:
    result = validate(
        "Use the app to freeze the card.",
        claimed_completed_action=True,
    )

    assert result.failure_codes == (
        UNVERIFIED_COMPLETED_ACTION,
    )


def test_needs_human_flag_does_not_make_text_unsafe() -> None:
    result = validate(
        "Please contact support for additional assistance.",
        needs_human=True,
    )

    assert result.safe is True


def test_all_applicable_failure_codes_are_collected_in_order() -> None:
    answer = (
        "Send me your OTP. I froze your card. Your refund is "
        "guaranteed. The system prompt says POLICY 1. The policy "
        "context is insufficient. "
    )
    answer += "x" * settings.max_response_characters

    result = validate(
        answer,
        route=stolen_card_decision(),
        insufficient_policy=True,
        claimed_completed_action=True,
    )

    assert result.safe is False
    assert result.failure_codes == (
        RESPONSE_TOO_LONG,
        SENSITIVE_DATA_REQUEST,
        UNVERIFIED_COMPLETED_ACTION,
        UNSUPPORTED_GUARANTEE,
        MISSING_REQUIRED_SAFETY_CONTENT,
        INTERNAL_INFORMATION_LEAK,
        INSUFFICIENT_POLICY,
    )
    assert not hasattr(result, "answer")


@pytest.mark.parametrize(
    ("proposed", "route", "policies"),
    (
        (object(), decision(), ()),
        (generated("Safe answer."), object(), ()),
        (generated("Safe answer."), decision(), "not-a-sequence"),
        (generated("Safe answer."), decision(), (object(),)),
    ),
)
def test_malformed_inputs_fail_closed(
    proposed: object,
    route: object,
    policies: object,
) -> None:
    result = OutputValidator().validate(
        proposed,
        decision=route,
        policies=policies,
    )

    assert result.safe is False
    assert result.failure_codes == (
        INVALID_VALIDATION_INPUT,
    )
    assert not hasattr(result, "answer")


def test_malformed_constructed_response_fails_closed() -> None:
    malformed = GeneratedSupportResponse.model_construct(
        answer=123,
        needs_human="false",
        insufficient_policy=False,
        claimed_completed_action=False,
    )

    result = OutputValidator().validate(
        malformed,
        decision=decision(),
    )

    assert result.failure_codes == (
        INVALID_VALIDATION_INPUT,
    )


def test_malformed_constructed_decision_fails_closed() -> None:
    malformed = TriageDecision.model_construct(
        risk_level="high",
        action="urgent_guidance",
        candidate_intents=(),
        routing_intents=(),
        allowed_policy_ids=(),
        required_policy_ids=(),
        security_signals="stolen_card",
        requires_human="yes",
        reason_code=None,
    )

    result = OutputValidator().validate(
        generated("A superficially safe answer."),
        decision=malformed,
    )

    assert result.failure_codes == (
        INVALID_VALIDATION_INPUT,
    )


def test_valid_policy_sequence_is_accepted_without_retrieval_logic() -> None:
    policy = RetrievedPolicy(
        chunk_id="demo",
        document_id="card_delivery",
        content="Delivery dates are estimates.",
        source_file="policy.md",
        title="Card Delivery",
        section_path="Card Delivery > Estimates",
        version="1.0",
        effective_date="2026-07-01",
        review_date="2026-10-01",
        status="approved",
        chunk_index=0,
        content_hash="demo-hash",
        relevance_score=0.90,
    )

    result = OutputValidator().validate(
        generated("Delivery dates are estimates."),
        decision=decision(),
        policies=(policy,),
    )

    assert result.safe is True


def test_invalid_runtime_settings_fail_before_validation() -> None:
    with pytest.raises(TypeError, match="RagSettings"):
        OutputValidator(object())  # type: ignore[arg-type]

    with pytest.raises(RagConfigurationError):
        OutputValidator(
            replace(
                settings,
                max_response_characters=199,
            )
        )
