"""Deterministic safety validation for generated support responses."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.ml.rag_config import (
    RagSettings,
    settings,
    validate_rag_settings,
)
from app.ml.triage_types import (
    GeneratedSupportResponse,
    OutputValidationResult,
    RetrievedPolicy,
    TriageDecision,
)


INVALID_VALIDATION_INPUT = "invalid_validation_input"
EMPTY_OUTPUT = "empty_output"
RESPONSE_TOO_LONG = "response_too_long"
SENSITIVE_DATA_REQUEST = "sensitive_data_request"
UNVERIFIED_COMPLETED_ACTION = "unverified_completed_action"
UNSUPPORTED_GUARANTEE = "unsupported_guarantee"
MISSING_REQUIRED_SAFETY_CONTENT = (
    "missing_required_safety_content"
)
INTERNAL_INFORMATION_LEAK = "internal_information_leak"
INSUFFICIENT_POLICY = "insufficient_policy"

_SECRET_TERM = (
    r"(?:passwords?|(?:complete|full)\s+pins?|pins?|otps?|"
    r"one[\s-]+time\s+codes?|authentication\s+codes?|"
    r"security\s+codes?|cvvs?|"
    r"(?:complete|full)\s+card\s+numbers?|"
    r"card\s+numbers?\s+in\s+full)"
)
_SECRET_REQUEST_VERB = (
    r"(?:send|provide|share|tell|give|enter|type|submit|"
    r"upload|disclose|reveal|reply\s+with|confirm)"
)
_SAFE_SECRET_WARNING_PATTERN = re.compile(
    rf"\b(?:never|do\s+not|don['’]?t|must\s+not|"
    rf"should\s+not|cannot|can['’]?t)\s+(?:ever\s+)?"
    rf"{_SECRET_REQUEST_VERB}\b(?:\W+\w+){{0,6}}?\W+"
    rf"(?:your\s+)?{_SECRET_TERM}",
    re.IGNORECASE,
)
_SECRET_REQUEST_PATTERNS = (
    re.compile(
        rf"\b{_SECRET_REQUEST_VERB}\b"
        rf"(?:\W+\w+){{0,6}}?\W+(?:your\s+)?{_SECRET_TERM}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:what\s+is|i\s+need|may\s+i\s+have|"
        rf"can\s+you\s+(?:send|provide|tell|give))\b"
        rf"(?:\W+\w+){{0,6}}?\W+(?:your\s+)?{_SECRET_TERM}",
        re.IGNORECASE,
    ),
)
_SAFE_SECRET_PRONOUN_WARNING_PATTERN = re.compile(
    rf"\b(?:never|do\s+not|don['’]?t|must\s+not|"
    rf"should\s+not|cannot|can['’]?t)\s+(?:ever\s+)?"
    rf"{_SECRET_REQUEST_VERB}\b"
    rf"(?:\W+\w+){{0,4}}?\W+"
    rf"(?:it|them|that\s+code|those\s+details)\b",
    re.IGNORECASE,
)
_SECRET_PRONOUN_REQUEST_PATTERN = re.compile(
    rf"\b{_SECRET_REQUEST_VERB}\b"
    rf"(?:\W+\w+){{0,4}}?\W+"
    rf"(?:it|them|that\s+code|those\s+details)\b",
    re.IGNORECASE,
)

_ACTIVE_COMPLETED_ACTION_PATTERN = re.compile(
    r"\b(?:i|we|support|our\s+team)\s+"
    r"(?:have\s+|already\s+|successfully\s+)*"
    r"(?:froze|frozen|blocked|cancelled|canceled|ordered|filed|"
    r"approved|changed|reversed|refunded|closed|submitted)\b",
    re.IGNORECASE,
)
_PASSIVE_COMPLETED_ACTION_PATTERN = re.compile(
    r"\b(?:your\s+)?(?:card|replacement|replacement\s+card|"
    r"dispute|refund|address|fee|request)\s+"
    r"(?:is|was|has\s+been|have\s+been)\s+(?:now\s+|already\s+)?"
    r"(?:frozen|blocked|cancelled|canceled|ordered|filed|approved|"
    r"changed|reversed|refunded|closed|submitted|completed)\b",
    re.IGNORECASE,
)
_SAFE_ACTION_QUALIFIER_PATTERN = re.compile(
    r"\b(?:if|whether|may|might|could|cannot\s+confirm|"
    r"can['’]?t\s+confirm|check\b.{0,50}\bconfirm|"
    r"contact\b.{0,30}\brequest|you\s+can|you\s+may)\b",
    re.IGNORECASE,
)

_OUTCOME_TERM_PATTERN = re.compile(
    r"\b(?:refunds?|reimbursements?|delivery(?:\s+dates?)?|"
    r"delivered|arriv(?:e|al)|disputes?|investigations?|"
    r"fee\s+reversals?|fees?\s+(?:will\s+be\s+)?reversed)\b",
    re.IGNORECASE,
)
_SAFE_GUARANTEE_PATTERN = re.compile(
    r"\b(?:cannot|can['’]?t|can\s+not|do\s+not|don['’]?t|"
    r"unable\s+to|not|never)\s+(?:be\s+)?"
    r"(?:guarantee(?:d)?|promise(?:d)?)\b|"
    r"\bno\s+(?:refund\s+|delivery\s+|outcome\s+)?guarantee\b|"
    r"\bestimates?\s+(?:(?:are\s+)?not|rather\s+than)\s+"
    r"guarantees?\b",
    re.IGNORECASE,
)
_EXPLICIT_GUARANTEE_PATTERN = re.compile(
    r"\b(?:guarantee(?:d|s)?|promise(?:d|s)?|definitely|"
    r"certainly)\b",
    re.IGNORECASE,
)
_FUTURE_OUTCOME_PATTERNS = (
    re.compile(
        r"\b(?:you\s+will\s+(?:receive|get)|we\s+will\s+(?:issue|"
        r"approve|pay))\b.{0,40}\b(?:refund|reimbursement)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:card|replacement|delivery)\b.{0,30}\bwill\s+"
        r"(?:arrive|be\s+delivered)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:dispute|refund|reimbursement)\b.{0,30}\bwill\s+"
        r"(?:be\s+)?(?:approved|successful|resolved|paid|issued)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\binvestigation\b.{0,30}\bwill\s+"
        r"(?:confirm|find|result|conclude)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfees?\b.{0,30}\bwill\s+be\s+"
        r"(?:reversed|refunded|waived)\b",
        re.IGNORECASE,
    ),
)

_INTERNAL_TERM_PATTERN = re.compile(
    r"\b(?:system\s+prompts?|retrieval\s+(?:scores?|distances?|"
    r"information)|classifier\s+(?:confidence|labels?)|"
    r"internal\s+intent\s+labels?|hidden\s+instructions?|"
    r"routing\s+(?:data|rules?|decisions?)|"
    r"internal\s+policy\s+documents?|retrieved\s+chunks?|"
    r"chunk\s+ids?|reason[_\s-]?code|security[_\s-]?signals)\b",
    re.IGNORECASE,
)
_INTERNAL_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:allowed_policy_ids|required_policy_ids)\b|"
    r"\bpolicy\s+\d+\b",
    re.IGNORECASE,
)
_SAFE_INTERNAL_REFUSAL_PATTERN = re.compile(
    r"\b(?:cannot|can['’]?t|will\s+not|won['’]?t|"
    r"do\s+not|don['’]?t)\b.{0,35}\b"
    r"(?:provide|reveal|share|disclose|show|expose)\b",
    re.IGNORECASE,
)
_CONTRADICTORY_INTERNAL_DISCLOSURE_PATTERN = re.compile(
    r"\b(?:system\s+prompts?|retrieval\s+scores?|"
    r"classifier\s+confidence|internal\s+intent\s+labels?|"
    r"hidden\s+instructions?)\b.{0,100}\b"
    r"(?:but|however|yet)\b.{0,60}\b"
    r"(?:says?|contains?|shows?|instructs?|is|are)\b",
    re.IGNORECASE,
)
_INSUFFICIENT_POLICY_PATTERNS = (
    re.compile(
        r"\b(?:insufficient|not\s+enough|lack(?:ing)?)\b"
        r".{0,45}\b(?:policy|context|information)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:could\s+not|couldn['’]?t|unable\s+to)\s+"
        r"(?:verify|find)\b.{0,45}\b"
        r"(?:policy|context|information)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:do\s+not|don['’]?t)\s+have\s+enough\b"
        r".{0,45}\b(?:policy|context|information)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:policy|context)\b.{0,35}\b"
        r"(?:is\s+)?(?:insufficient|does\s+not\s+(?:cover|address))\b",
        re.IGNORECASE,
    ),
)

_STOLEN_CARD_SIGNALS = frozenset(
    {
        "stolen_card",
        "lost_card",
        "compromised_card",
    }
)
_STOLEN_CARD_REASON_CODES = frozenset(
    {
        "direct_stolen_card_signal",
        "direct_lost_card_signal",
        "direct_compromised_card_signal",
        "hypothetical_card_security_guidance",
    }
)


class OutputValidator:
    """Validate generated text and flags without returning the answer."""

    def __init__(
        self,
        runtime_settings: RagSettings = settings,
    ) -> None:
        if not isinstance(runtime_settings, RagSettings):
            raise TypeError(
                "runtime_settings must be a RagSettings instance."
            )

        validate_rag_settings(runtime_settings)
        self._settings = runtime_settings

    def validate(
        self,
        generated: object,
        *,
        decision: object,
        policies: object = (),
    ) -> OutputValidationResult:
        """Return every deterministic failure code in stable order."""

        if not _validation_inputs_are_valid(
            generated,
            decision=decision,
            policies=policies,
        ):
            return OutputValidationResult(
                safe=False,
                failure_codes=(INVALID_VALIDATION_INPUT,),
            )

        response = generated
        route = decision
        answer = response.answer
        failure_codes: list[str] = []

        if not answer.strip():
            failure_codes.append(EMPTY_OUTPUT)

        if len(answer) > self._settings.max_response_characters:
            failure_codes.append(RESPONSE_TOO_LONG)

        if _contains_sensitive_data_request(answer):
            failure_codes.append(SENSITIVE_DATA_REQUEST)

        if (
            response.claimed_completed_action
            or _contains_unverified_completed_action(answer)
        ):
            failure_codes.append(UNVERIFIED_COMPLETED_ACTION)

        if _contains_unsupported_guarantee(answer):
            failure_codes.append(UNSUPPORTED_GUARANTEE)

        if (
            _requires_stolen_card_safety(route)
            and not _contains_all_stolen_card_safety_concepts(
                answer
            )
        ):
            failure_codes.append(
                MISSING_REQUIRED_SAFETY_CONTENT
            )

        if _contains_internal_information_leak(answer):
            failure_codes.append(INTERNAL_INFORMATION_LEAK)

        if (
            response.insufficient_policy
            or _states_policy_is_insufficient(answer)
        ):
            failure_codes.append(INSUFFICIENT_POLICY)

        return OutputValidationResult(
            safe=not failure_codes,
            failure_codes=tuple(failure_codes),
        )


def _validation_inputs_are_valid(
    generated: object,
    *,
    decision: object,
    policies: object,
) -> bool:
    if (
        not isinstance(generated, GeneratedSupportResponse)
        or not isinstance(decision, TriageDecision)
        or not isinstance(policies, Sequence)
        or isinstance(policies, (str, bytes))
        or any(
            not isinstance(policy, RetrievedPolicy)
            for policy in policies
        )
    ):
        return False

    return (
        isinstance(generated.answer, str)
        and isinstance(generated.needs_human, bool)
        and isinstance(generated.insufficient_policy, bool)
        and isinstance(
            generated.claimed_completed_action,
            bool,
        )
        and isinstance(decision.risk_level, str)
        and isinstance(decision.action, str)
        and isinstance(decision.security_signals, tuple)
        and all(
            isinstance(signal, str) and bool(signal.strip())
            for signal in decision.security_signals
        )
        and isinstance(decision.requires_human, bool)
        and isinstance(decision.reason_code, str)
        and bool(decision.reason_code.strip())
    )


def _contains_sensitive_data_request(answer: str) -> bool:
    masked = _SAFE_SECRET_WARNING_PATTERN.sub(" ", answer)
    masked = _SAFE_SECRET_PRONOUN_WARNING_PATTERN.sub(
        " ",
        masked,
    )
    direct_request = any(
        pattern.search(masked) is not None
        for pattern in _SECRET_REQUEST_PATTERNS
    )
    pronoun_request = (
        re.search(_SECRET_TERM, answer, re.IGNORECASE) is not None
        and _SECRET_PRONOUN_REQUEST_PATTERN.search(masked)
        is not None
    )
    return direct_request or pronoun_request


def _sentences(answer: str) -> tuple[str, ...]:
    return tuple(
        sentence.strip()
        for sentence in re.split(
            r"[.!?\n;]+|\b(?:but|however|yet)\b",
            answer,
            flags=re.IGNORECASE,
        )
        if sentence.strip()
    )


def _contains_unverified_completed_action(answer: str) -> bool:
    for sentence in _sentences(answer):
        matches = (
            *_ACTIVE_COMPLETED_ACTION_PATTERN.finditer(sentence),
            *_PASSIVE_COMPLETED_ACTION_PATTERN.finditer(sentence),
        )

        for match in matches:
            if _SAFE_ACTION_QUALIFIER_PATTERN.search(
                sentence[: match.start()]
            ):
                continue

            return True

    return False


def _contains_unsupported_guarantee(answer: str) -> bool:
    for sentence in _sentences(answer):
        masked = _SAFE_GUARANTEE_PATTERN.sub(" ", sentence)

        if (
            _OUTCOME_TERM_PATTERN.search(masked)
            and _EXPLICIT_GUARANTEE_PATTERN.search(masked)
        ):
            return True

        if any(
            pattern.search(masked)
            for pattern in _FUTURE_OUTCOME_PATTERNS
        ):
            return True

    return False


def _requires_stolen_card_safety(
    decision: TriageDecision,
) -> bool:
    return (
        bool(
            set(decision.security_signals)
            & _STOLEN_CARD_SIGNALS
        )
        or decision.reason_code in _STOLEN_CARD_REASON_CODES
    )


def _contains_all_stolen_card_safety_concepts(
    answer: str,
) -> bool:
    normalized = " ".join(answer.lower().split())
    has_freeze = bool(
        re.search(
            r"\bfreez(?:e|es|ing)\b.{0,35}\bcard\b|"
            r"\bcard\b.{0,35}\bfreez(?:e|es|ing)\b",
            normalized,
        )
    )
    has_review = bool(
        re.search(
            r"\b(?:review|check|look\s+(?:at|over))\b"
            r".{0,55}\b(?:recent|latest|other)\b"
            r".{0,35}\b(?:transactions?|activity|withdrawals?)\b",
            normalized,
        )
    )
    has_report = (
        re.search(r"\breport\b", normalized) is not None
        and re.search(
            r"\b(?:transactions?|withdrawals?)\b",
            normalized,
        )
        is not None
        and re.search(
            r"\b(?:unrecognized|unauthorized|unknown)\b|"
            r"\bdo\s+not\s+recognize\b|"
            r"\bdon['’]?t\s+recognize\b",
            normalized,
        )
        is not None
    )
    has_emergency_support = bool(
        re.search(
            r"\b(?:contact|call|reach)\b.{0,25}\b"
            r"emergency\s+support\b",
            normalized,
        )
        and (
            re.search(
                r"\b(?:cannot|can['’]?t|unable\s+to)\b"
                r".{0,20}\b(?:access|use|open)\b"
                r".{0,15}\b(?:the\s+)?app\b|"
                r"\bapp\b.{0,20}\b(?:unavailable|inaccessible)\b",
                normalized,
            )
            or re.search(
                r"\bemergency\s+support\b.{0,20}\b"
                r"(?:now|immediately)\b",
                normalized,
            )
        )
    )
    return (
        has_freeze
        and has_review
        and has_report
        and has_emergency_support
    )


def _contains_internal_information_leak(answer: str) -> bool:
    if _INTERNAL_IDENTIFIER_PATTERN.search(answer):
        return True

    if _CONTRADICTORY_INTERNAL_DISCLOSURE_PATTERN.search(
        answer
    ):
        return True

    for sentence in _sentences(answer):
        if not _INTERNAL_TERM_PATTERN.search(sentence):
            continue

        if _SAFE_INTERNAL_REFUSAL_PATTERN.search(sentence):
            continue

        return True

    return False


def _states_policy_is_insufficient(answer: str) -> bool:
    return any(
        pattern.search(answer) is not None
        for pattern in _INSUFFICIENT_POLICY_PATTERNS
    )


output_validator = OutputValidator()


__all__ = [
    "EMPTY_OUTPUT",
    "INSUFFICIENT_POLICY",
    "INTERNAL_INFORMATION_LEAK",
    "INVALID_VALIDATION_INPUT",
    "MISSING_REQUIRED_SAFETY_CONTENT",
    "OutputValidator",
    "RESPONSE_TOO_LONG",
    "SENSITIVE_DATA_REQUEST",
    "UNSUPPORTED_GUARANTEE",
    "UNVERIFIED_COMPLETED_ACTION",
    "output_validator",
]
