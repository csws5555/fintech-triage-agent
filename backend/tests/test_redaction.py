"""Focused service-free tests for safe logging and redaction."""

from __future__ import annotations

import math

import pytest

from app.ml.redaction import (
    REDACTED,
    SAFE_LOG_FIELDS,
    UnsafeLogRecordError,
    redact_sensitive_data,
    rounded_confidence_range,
    rounded_confidence_ranges,
    sanitize_log_record,
)


@pytest.mark.parametrize(
    ("value", "visible_fragment"),
    (
        ("4111111111111111", "4111"),
        ("4111 1111 1111 1111", "1111"),
        ("5555-5555-5555-4444", "4444"),
        ("378282246310005", "3782"),
    ),
)
def test_payment_card_like_sequences_are_redacted(
    value: str,
    visible_fragment: str,
) -> None:
    result = redact_sensitive_data(f"card={value}")

    assert result == f"card={REDACTED}"
    assert visible_fragment not in result


@pytest.mark.parametrize(
    "text",
    (
        "OTP: 123456",
        "one-time code is 876543",
        "authentication code=445566",
        "778899 is my verification code",
        "PIN 1234",
        "4321 is my passcode",
        "CVV: 123",
        "security code is 987",
        "456 is my CVC",
    ),
)
def test_contextual_authentication_codes_are_redacted(
    text: str,
) -> None:
    result = redact_sensitive_data(text)

    assert REDACTED in result
    assert remainders_are_not_numeric_secrets(result)


def remainders_are_not_numeric_secrets(text: str) -> bool:
    return not any(
        character.isdigit()
        for character in text
    )


def test_short_numbers_without_authentication_context_are_preserved() -> None:
    text = "Ticket 123456 was opened on 2026-07-29 at 14:30."

    assert redact_sensitive_data(text) == text


def test_unlabeled_non_card_numeric_identifier_is_preserved() -> None:
    text = "reference=1234567890123456"

    assert redact_sensitive_data(text) == text


def test_explicit_card_context_redacts_even_when_checksum_is_invalid() -> None:
    text = "card number=1234567890123456"

    assert redact_sensitive_data(text) == f"card number={REDACTED}"


@pytest.mark.parametrize(
    "text",
    (
        "password=hunter2!",
        "Password: 'correct-horse-battery-staple'",
        '"password":"s3cr3t"',
        "my password is summer2026",
    ),
)
def test_password_field_values_are_redacted(text: str) -> None:
    result = redact_sensitive_data(text)

    assert REDACTED in result
    assert not any(
        secret in result
        for secret in (
            "hunter2",
            "correct-horse",
            "s3cr3t",
            "summer2026",
        )
    )


def test_bearer_token_is_redacted_without_removing_scheme() -> None:
    token = "eyJhbGciOiJIUzI1NiJ9.payload.signature"

    result = redact_sensitive_data(f"Authorization: Bearer {token}")

    assert result == f"Authorization: Bearer {REDACTED}"
    assert token not in result


@pytest.mark.parametrize(
    "text",
    (
        "api_key=abcdefghijklmnopqrstuvwxyz012345",
        "API key: abcdefghijklmnopqrstuvwxyz012345",
        "secret-key is abcdefghijklmnopqrstuvwxyz012345",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        # Build this detector-shaped fake at runtime so secret scanners do not
        # mistake the source fixture for a committed Stripe credential.
        "".join(("sk", "_live_", "abcdefghijklmnopqrstuvwxyz012345")),
        "AIzaabcdefghijklmnopqrstuvwxyz012345",
    ),
)
def test_api_key_like_values_are_redacted(text: str) -> None:
    result = redact_sensitive_data(text)

    assert REDACTED in result
    assert "abcdefghijklmnopqrstuvwxyz012345" not in result


def test_multiple_secret_families_are_redacted_and_result_is_idempotent() -> None:
    text = (
        "card 4111 1111 1111 1111; OTP 123456; PIN=4321; "
        "CVV 987; password=hunter2; Bearer abcdefghijklmnop; "
        "api_key=abcdefghijklmnopqrstuvwxyz"
    )

    once = redact_sensitive_data(text)
    twice = redact_sensitive_data(once)

    assert once.count(REDACTED) == 7
    assert twice == once


def test_safe_identifiers_and_text_are_unchanged() -> None:
    text = (
        "request=req-20260729; intent=card_arrival; "
        "chunk=card-delivery--arrival--abc123def456"
    )

    assert redact_sensitive_data(text) == text


def test_redactor_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="text must be a string"):
        redact_sensitive_data(123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("confidence", "expected"),
    (
        (0.0, "0.0-0.1"),
        (0.09, "0.0-0.1"),
        (0.1, "0.1-0.2"),
        (0.5324, "0.5-0.6"),
        (0.9999, "0.9-1.0"),
        (1.0, "0.9-1.0"),
    ),
)
def test_confidence_is_bucketed_without_logging_exact_value(
    confidence: float,
    expected: str,
) -> None:
    assert rounded_confidence_range(confidence) == expected


def test_confidence_sequence_preserves_order() -> None:
    assert rounded_confidence_ranges((0.81, 0.15, 0.04)) == (
        "0.8-0.9",
        "0.1-0.2",
        "0.0-0.1",
    )


@pytest.mark.parametrize(
    "confidence",
    (-0.1, 1.1, math.inf, -math.inf, math.nan),
)
def test_invalid_confidence_fails_closed(confidence: float) -> None:
    with pytest.raises(ValueError):
        rounded_confidence_range(confidence)


def test_non_numeric_confidence_fails_closed() -> None:
    with pytest.raises(TypeError):
        rounded_confidence_range(True)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        rounded_confidence_ranges("0.5")  # type: ignore[arg-type]


def test_safe_log_field_allowlist_matches_roadmap_metadata() -> None:
    assert SAFE_LOG_FIELDS == frozenset(
        {
            "request_id",
            "timestamp",
            "top_intent_labels",
            "confidence_ranges",
            "uncertain",
            "risk_level",
            "action",
            "reason_code",
            "allowed_policy_ids",
            "required_policy_ids",
            "retrieved_policy_ids",
            "retrieved_chunk_ids",
            "retrieval_scores",
            "response_mode",
            "latency_ms",
            "validator_passed",
            "validator_failure_codes",
            "internal_error_code",
        }
    )


def test_safe_log_record_is_copied_and_sensitive_values_are_redacted() -> None:
    source = {
        "request_id": "req-123",
        "top_intent_labels": ["card_arrival", "OTP 123456"],
        "confidence_ranges": ("0.5-0.6", "0.1-0.2"),
        "uncertain": True,
        "retrieval_scores": [0.75, 0.61],
        "internal_error_code": None,
    }

    result = sanitize_log_record(source)

    assert result is not source
    assert result["top_intent_labels"] == [
        "card_arrival",
        f"OTP {REDACTED}",
    ]
    assert result["confidence_ranges"] == ("0.5-0.6", "0.1-0.2")
    assert source["top_intent_labels"][1] == "OTP 123456"


@pytest.mark.parametrize(
    "unsafe_field",
    (
        "customer_message",
        "raw_message",
        "conversation",
        "policy_content",
        "hidden_prompt",
        "reasoning",
        "model_output",
        "authorization",
        "authentication_headers",
    ),
)
def test_unapproved_log_fields_fail_closed(unsafe_field: str) -> None:
    with pytest.raises(
        UnsafeLogRecordError,
        match="unapproved field",
    ):
        sanitize_log_record(
            {
                "request_id": "req-123",
                unsafe_field: "must not be logged",
            }
        )


def test_non_finite_or_arbitrary_log_values_fail_closed() -> None:
    with pytest.raises(
        UnsafeLogRecordError,
        match="finite",
    ):
        sanitize_log_record({"latency_ms": math.inf})

    with pytest.raises(
        UnsafeLogRecordError,
        match="JSON-safe",
    ):
        sanitize_log_record({"timestamp": object()})


def test_log_record_requires_a_mapping() -> None:
    with pytest.raises(TypeError, match="record must be a mapping"):
        sanitize_log_record(())  # type: ignore[arg-type]
