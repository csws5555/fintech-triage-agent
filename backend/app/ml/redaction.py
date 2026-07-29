"""Fail-closed redaction helpers for structured application logging."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import TypeAlias


REDACTED = "[REDACTED]"

SAFE_LOG_FIELDS = frozenset(
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

_PASSWORD_PATTERN = re.compile(
    r"(?P<prefix>\bpasswords?\b[\"']?\s*"
    r"(?:(?:is|=|:)\s*)[\"']?)"
    r"(?P<secret>[^\s,;}\[\]\"']+)",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(
    r"(?P<prefix>\bbearer\s+)"
    r"(?P<secret>[A-Za-z0-9._~+/=-]{8,})",
    re.IGNORECASE,
)
_LABELED_API_KEY_PATTERN = re.compile(
    r"(?P<prefix>\b(?:api[\s_-]?keys?|secret[\s_-]?keys?|"
    r"access[\s_-]?tokens?)\b\s*(?:(?:is|=|:)\s*)[\"']?)"
    r"(?P<secret>[A-Za-z0-9._~+/=-]{8,})",
    re.IGNORECASE,
)
_API_KEY_LIKE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-[A-Za-z0-9_-]{16,}|"
    r"AIza[A-Za-z0-9_-]{20,}|"
    r"(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"
    r")(?![A-Za-z0-9])"
)
_CARD_LIKE_PATTERN = re.compile(
    r"(?<!\d)(?:\d[ -]?){12,18}\d(?![ -]?\d)"
)
_PAYMENT_CARD_CONTEXT_PATTERN = re.compile(
    r"\b(?:card(?:\s+number)?|payment\s+card|pan)\b",
    re.IGNORECASE,
)

_OTP_TERM = (
    r"(?:otp|one[\s-]?time(?:\s+(?:password|passcode|code))?|"
    r"authentication\s+code|verification\s+code)"
)
_PIN_TERM = r"(?:pin|passcode)"
_CVV_TERM = (
    r"(?:cvv|cvc|security\s+code|card\s+verification\s+value)"
)


class UnsafeLogRecordError(ValueError):
    """Raised when a structured log record contains unsafe fields or values."""


LogScalar: TypeAlias = str | int | float | bool | None
SafeLogValue: TypeAlias = (
    LogScalar | tuple["SafeLogValue", ...] | list["SafeLogValue"]
)


def _contextual_code_patterns(
    term: str,
    *,
    minimum_digits: int,
    maximum_digits: int,
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    value = rf"\d{{{minimum_digits},{maximum_digits}}}"
    before = re.compile(
        rf"(?P<prefix>\b{term}\b"
        rf"(?:\s+(?:code|value|number|is|equals))*"
        rf"\s*(?:[:=#-]\s*)?)"
        rf"(?P<secret>{value})\b",
        re.IGNORECASE,
    )
    after = re.compile(
        rf"\b(?P<secret>{value})"
        rf"(?P<suffix>\s+(?:is\s+)?(?:my\s+)?{term}\b)",
        re.IGNORECASE,
    )
    return before, after


_CONTEXTUAL_CODE_PATTERNS = (
    *_contextual_code_patterns(
        _OTP_TERM,
        minimum_digits=4,
        maximum_digits=8,
    ),
    *_contextual_code_patterns(
        _PIN_TERM,
        minimum_digits=3,
        maximum_digits=6,
    ),
    *_contextual_code_patterns(
        _CVV_TERM,
        minimum_digits=3,
        maximum_digits=4,
    ),
)


def _replace_named_secret(match: re.Match[str]) -> str:
    prefix = match.groupdict().get("prefix") or ""
    suffix = match.groupdict().get("suffix") or ""
    return f"{prefix}{REDACTED}{suffix}"


def _passes_luhn_check(digits: str) -> bool:
    if (
        not 13 <= len(digits) <= 19
        or not digits.isdigit()
        or digits[0] == "0"
        or len(set(digits)) == 1
    ):
        return False

    total = 0
    parity = len(digits) % 2

    for index, character in enumerate(digits):
        value = int(character)

        if index % 2 == parity:
            value *= 2

            if value > 9:
                value -= 9

        total += value

    return total % 10 == 0


def _redact_card_candidate(match: re.Match[str]) -> str:
    candidate = match.group(0)
    digits = re.sub(r"[ -]", "", candidate)
    context_start = max(0, match.start() - 32)
    context_end = min(len(match.string), match.end() + 32)
    context = match.string[context_start:context_end]

    if (
        _passes_luhn_check(digits)
        or _PAYMENT_CARD_CONTEXT_PATTERN.search(context)
    ):
        return REDACTED

    return candidate


def redact_sensitive_data(text: str) -> str:
    """
    Replace obvious authentication and payment secrets in text.

    Short numeric values are redacted only when adjacent wording identifies
    them as an OTP, PIN, passcode, CVV, CVC, or security code. Payment-card-
    like sequences are conservatively redacted based on their digit length.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string.")

    redacted = text

    for pattern in (
        _PASSWORD_PATTERN,
        _BEARER_PATTERN,
        _LABELED_API_KEY_PATTERN,
    ):
        redacted = pattern.sub(_replace_named_secret, redacted)

    redacted = _API_KEY_LIKE_PATTERN.sub(REDACTED, redacted)
    redacted = _CARD_LIKE_PATTERN.sub(
        _redact_card_candidate,
        redacted,
    )

    for pattern in _CONTEXTUAL_CODE_PATTERNS:
        redacted = pattern.sub(_replace_named_secret, redacted)

    return redacted


def rounded_confidence_range(confidence: float) -> str:
    """Return a stable tenth-wide range instead of an exact confidence."""

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, Real)
    ):
        raise TypeError("confidence must be a real number.")

    value = float(confidence)

    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be finite and between 0 and 1.")

    bucket = min(int(value * 10), 9)
    lower = bucket / 10
    upper = (bucket + 1) / 10
    return f"{lower:.1f}-{upper:.1f}"


def rounded_confidence_ranges(
    confidences: Sequence[float],
) -> tuple[str, ...]:
    """Return stable rounded ranges for an ordered confidence sequence."""

    if isinstance(confidences, (str, bytes)) or not isinstance(
        confidences,
        Sequence,
    ):
        raise TypeError("confidences must be a sequence of real numbers.")

    return tuple(
        rounded_confidence_range(confidence)
        for confidence in confidences
    )


def _sanitize_log_value(value: object) -> SafeLogValue:
    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, str):
        return redact_sensitive_data(value)

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise UnsafeLogRecordError(
                "Structured log values must be finite."
            )
        return value

    if isinstance(value, tuple):
        return tuple(_sanitize_log_value(item) for item in value)

    if isinstance(value, list):
        return [_sanitize_log_value(item) for item in value]

    raise UnsafeLogRecordError(
        "Structured log values must use JSON-safe scalar or sequence types."
    )


def sanitize_log_record(
    record: Mapping[str, object],
) -> dict[str, SafeLogValue]:
    """
    Validate and redact one allowlisted structured log record.

    Unknown fields are rejected so raw messages, prompts, policy bodies,
    model output, authentication headers, and arbitrary object
    representations cannot be added accidentally.
    """

    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping.")

    unsafe_keys = tuple(
        key
        for key in record
        if not isinstance(key, str) or key not in SAFE_LOG_FIELDS
    )

    if unsafe_keys:
        raise UnsafeLogRecordError(
            "Structured log record contains an unapproved field."
        )

    return {
        key: _sanitize_log_value(value)
        for key, value in record.items()
    }


__all__ = [
    "REDACTED",
    "SAFE_LOG_FIELDS",
    "UnsafeLogRecordError",
    "redact_sensitive_data",
    "rounded_confidence_range",
    "rounded_confidence_ranges",
    "sanitize_log_record",
]
