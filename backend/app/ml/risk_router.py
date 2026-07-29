"""
Deterministic risk and policy router for Phase 2.

The router combines:

- all three Banking77 classifier predictions;
- a smaller confidence-filtered set of routing intents;
- deterministic security and operational message signals;
- policy coverage rules;
- negation and hypothetical detection;
- clarification requirements;
- unsupported-request handling;
- internal-information refusals;
- unverified account-action requests.

The router does not:

- retrieve policy chunks;
- call Ollama;
- generate customer-facing responses;
- perform account actions;
- modify the saved Phase 1 classifier.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.ml.policy_registry import (
    AMBIGUOUS_FEE_INTENTS,
    INTENT_POLICY_MAP,
    KNOWN_POLICY_IDS,
    any_intent_is_supported,
    policies_for_intents,
)
from app.ml.rag_config import settings
from app.ml.triage_types import (
    ClassificationResult,
    TriageDecision,
)


# ============================================================
# Policy ordering
# ============================================================

# Sets and frozensets do not preserve a reliable presentation order.
# This tuple makes returned policy IDs deterministic.
POLICY_ORDER: tuple[str, ...] = (
    "fraud_policy",
    "card_replacement",
    "card_delivery",
    "international_fees",
)


# ============================================================
# Direct signal-to-policy mappings
# ============================================================

SECURITY_SIGNAL_POLICY_MAP: dict[str, frozenset[str]] = {
    "stolen_card": frozenset(
        {
            "card_replacement",
            "fraud_policy",
        }
    ),
    "lost_card": frozenset(
        {
            "card_replacement",
            "fraud_policy",
        }
    ),
    "compromised_card": frozenset(
        {
            "fraud_policy",
        }
    ),
    "unknown_transaction": frozenset(
        {
            "fraud_policy",
        }
    ),
    "unknown_withdrawal": frozenset(
        {
            "fraud_policy",
        }
    ),
    "account_takeover": frozenset(
        {
            "fraud_policy",
        }
    ),
}


OPERATIONAL_SIGNAL_POLICY_MAP: dict[str, frozenset[str]] = {
    "initial_card_delivery": frozenset(
        {
            "card_delivery",
        }
    ),
    "replacement_card_delivery": frozenset(
        {
            "card_replacement",
        }
    ),
    "damaged_card": frozenset(
        {
            "card_replacement",
        }
    ),
    "atm_retained_card": frozenset(
        {
            "card_replacement",
            "fraud_policy",
        }
    ),
    "international_charge": frozenset(
        {
            "international_fees",
        }
    ),
    "duplicate_transaction": frozenset(
        {
            "fraud_policy",
        }
    ),
}


# ============================================================
# Pattern helpers
# ============================================================


def _compile_patterns(
    patterns: Iterable[str],
) -> tuple[re.Pattern[str], ...]:
    """
    Compile a sequence of case-insensitive regular expressions.
    """

    return tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in patterns
    )


# ============================================================
# Security patterns
# ============================================================

SECURITY_PATTERNS: dict[
    str,
    tuple[re.Pattern[str], ...],
] = {
    "stolen_card": _compile_patterns(
        (
            r"\bcard\b(?:\W+\w+){0,5}\W+\bstolen\b",
            r"\bstolen\b(?:\W+\w+){0,5}\W+\bcard\b",
            r"\bsomeone stole\b(?:\W+\w+){0,5}\W+\bcard\b",
            r"\bcard theft\b",
        )
    ),

    "lost_card": _compile_patterns(
        (
            r"\blost\b(?:\W+\w+){0,5}\W+\bcard\b",
            r"\bcard\b(?:\W+\w+){0,5}\W+\blost\b",
            r"\bmissing\b(?:\W+\w+){0,5}\W+\bcard\b",
            r"\bcannot find\b(?:\W+\w+){0,5}\W+\bcard\b",
            r"\bcan['’]?t find\b(?:\W+\w+){0,5}\W+\bcard\b",
        )
    ),

    "compromised_card": _compile_patterns(
        (
            r"\bcard\b(?:\W+\w+){0,6}\W+\bcompromised\b",
            r"\bcard details\b(?:\W+\w+){0,6}\W+\bexposed\b",
            r"\bcard details\b(?:\W+\w+){0,6}\W+\bleaked\b",
            r"\bsomeone\b(?:\W+\w+){0,6}\W+\bcard details\b",
            r"\bcard information\b(?:\W+\w+){0,6}\W+\bstolen\b",
        )
    ),

    "unknown_transaction": _compile_patterns(
        (
            r"\bdo not recogni[sz]e\b",
            r"\bdon['’]?t recogni[sz]e\b",
            r"\bdont recogni[sz]e\b",
            r"\bnot mine\b",
            r"\bunauthori[sz]ed\b",
            r"\bi did not make\b(?:\W+\w+){0,6}\W+\bpayment\b",
            r"\bi didn['’]?t make\b(?:\W+\w+){0,6}\W+\bpayment\b",
            r"\bunknown transaction\b",
            r"\bunfamiliar transaction\b",
        )
    ),

    "unknown_withdrawal": _compile_patterns(
        (
            r"\bwithdrawal\b(?:\W+\w+){0,8}\W+\bnot mine\b",
            r"\bcash withdrawal\b(?:\W+\w+){0,8}\W+\bdo not recogni[sz]e\b",
            r"\bcash withdrawal\b(?:\W+\w+){0,8}\W+\bdon['’]?t recogni[sz]e\b",
            r"\bunauthori[sz]ed\b(?:\W+\w+){0,6}\W+\bwithdrawal\b",
            r"\bunknown\b(?:\W+\w+){0,5}\W+\bwithdrawal\b",
            r"\bi did not make\b(?:\W+\w+){0,6}\W+\bwithdrawal\b",
            r"\bi didn['’]?t make\b(?:\W+\w+){0,6}\W+\bwithdrawal\b",
        )
    ),

    "account_takeover": _compile_patterns(
        (
            r"\bchanged my email\b(?:\W+\w+){0,8}\W+\bnot me\b",
            r"\bchanged my phone\b(?:\W+\w+){0,8}\W+\bnot me\b",
            r"\bchanged my number\b(?:\W+\w+){0,8}\W+\bnot me\b",
            r"\bpassword reset\b(?:\W+\w+){0,8}\W+\bnot me\b",
            r"\baccount details\b(?:\W+\w+){0,8}\W+\bchanged\b",
            r"\bcontact details\b(?:\W+\w+){0,8}\W+\bchanged\b",
            r"\bemail address\b(?:\W+\w+){0,8}\W+\bchanged\b",
            r"\bphone number\b(?:\W+\w+){0,8}\W+\bchanged\b",
            r"\bsomeone\b(?:\W+\w+){0,8}\W+\bchanged\b"
            r"(?:\W+\w+){0,5}\W+\baccount\b",
        )
    ),
}


# ============================================================
# Operational patterns
# ============================================================

OPERATIONAL_PATTERNS: dict[
    str,
    tuple[re.Pattern[str], ...],
] = {
    "initial_card_delivery": _compile_patterns(
        (
            r"\bfirst card\b",
            r"\binitial card\b",
            r"\bfirst physical card\b",
            r"\bnewly ordered card\b",
            r"\bcard for my new account\b",
            r"\bnew account\b(?:\W+\w+){0,5}\W+\bcard\b",
        )
    ),

    "replacement_card_delivery": _compile_patterns(
        (
            r"\breplacement card\b",
            r"\breissued card\b",
            r"\bre-issued card\b",
            r"\brenewed card\b",
            r"\bnew card after losing\b",
            r"\bnew card after theft\b",
            r"\bnew card after my card was stolen\b",
            r"\bnew card after my card was lost\b",
        )
    ),

    "damaged_card": _compile_patterns(
        (
            r"\bdamaged card\b",
            r"\bcard is damaged\b",
            r"\bcracked card\b",
            r"\bcard is cracked\b",
            r"\bbroken chip\b",
            r"\bchip is broken\b",
            r"\bchip does not work\b",
            r"\bchip doesn['’]?t work\b",
            r"\bmagnetic stripe damaged\b",
            r"\bcard snapped\b",
            r"\bbent card\b",
        )
    ),

    "atm_retained_card": _compile_patterns(
        (
            r"\batm\b(?:\W+\w+){0,8}\W+\bkept\b"
            r"(?:\W+\w+){0,4}\W+\bcard\b",
            r"\batm\b(?:\W+\w+){0,8}\W+\bretained\b"
            r"(?:\W+\w+){0,4}\W+\bcard\b",
            r"\batm\b(?:\W+\w+){0,8}\W+\bswallowed\b"
            r"(?:\W+\w+){0,4}\W+\bcard\b",
            r"\bcard\b(?:\W+\w+){0,8}\W+\bstuck in\b"
            r"(?:\W+\w+){0,4}\W+\batm\b",
            r"\bcard swallowed\b",
        )
    ),

    "international_charge": _compile_patterns(
        (
            r"\bcharged\b(?:\W+\w+){0,8}\W+\babroad\b",
            r"\bfee\b(?:\W+\w+){0,8}\W+\babroad\b",
            r"\binternational\b(?:\W+\w+){0,5}\W+\bfee\b",
            r"\bforeign\b(?:\W+\w+){0,5}\W+\bfee\b",
            r"\bexchange rate\b",
            r"\bcurrency conversion\b",
            r"\bdynamic currency conversion\b",
            r"\bforeign atm\b",
            r"\binternational transfer\b",
        )
    ),

    "duplicate_transaction": _compile_patterns(
        (
            r"\bcharged twice\b",
            r"\bcharged two times\b",
            r"\bduplicate charge\b",
            r"\bduplicate transaction\b",
            r"\bsame transaction twice\b",
            r"\bdouble charged\b",
            r"\bdouble-charged\b",
        )
    ),
}


# ============================================================
# Negation and hypothetical patterns
# ============================================================

NEGATED_SECURITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    *_compile_patterns(
        (
            r"\bcard was not stolen\b",
            r"\bcard wasn['’]?t stolen\b",
            r"\bcard is not stolen\b",
            r"\bcard isn['’]?t stolen\b",
            r"\bcard was not lost\b",
            r"\bcard wasn['’]?t lost\b",
            r"\bcard is not lost\b",
            r"\bcard isn['’]?t lost\b",
            r"\bnot a stolen card\b",
            r"\bnot a lost card\b",
            r"\bno unauthori[sz]ed transaction\b",
            r"\bno unknown transaction\b",
            r"\bi recogni[sz]e the transaction\b",
        )
    ),
)


HYPOTHETICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    *_compile_patterns(
        (
            r"\bwhat should i do if\b",
            r"\bwhat do i do if\b",
            r"\bwhat happens if\b",
            r"\bif my card is stolen\b",
            r"\bif my card gets stolen\b",
            r"\bif i lose my card\b",
            r"\bin case my card is stolen\b",
            r"\bsuppose my card is stolen\b",
        )
    ),
)


# ============================================================
# Clarification patterns
# ============================================================

AMBIGUOUS_INTERNATIONAL_FEE_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bextra fee abroad\b",
        r"\bcharged a fee abroad\b",
        r"\bforeign fee\b",
        r"\binternational fee\b",
        r"\bfee while travelling\b",
        r"\bfee while traveling\b",
    )
)


SPECIFIC_TRANSACTION_TYPE_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\batm\b",
        r"\bwithdrawal\b",
        r"\bcard purchase\b",
        r"\bcard payment\b",
        r"\bmerchant\b",
        r"\bbank transfer\b",
        r"\binternational transfer\b",
        r"\bcurrency exchange\b",
        r"\bcurrency conversion\b",
        r"\bdynamic currency conversion\b",
    )
)


PIN_OR_PASSCODE_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bforgot\b(?:\W+\w+){0,4}\W+\bpin\b",
        r"\bforgotten\b(?:\W+\w+){0,4}\W+\bpin\b",
        r"\bi forgot my pin\b",
        r"\bcannot remember\b(?:\W+\w+){0,4}\W+\bpin\b",
        r"\bcan['’]?t remember\b(?:\W+\w+){0,4}\W+\bpin\b",
    )
)


AMBIGUOUS_CARD_DELIVERY_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bmy card has not arrived\b",
        r"\bmy card hasn['’]?t arrived\b",
        r"\bmy card is late\b",
        r"\bwhere is my card\b",
        r"\bcard delivery is late\b",
    )
)


# ============================================================
# Static-response patterns
# ============================================================

INTERNAL_INFORMATION_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bsystem prompt\b",
        r"\bhidden prompt\b",
        r"\binternal prompt\b",
        r"\bdeveloper message\b",
        r"\binternal instructions\b",
        r"\bhidden instructions\b",
        r"\brouting rules\b",
        r"\bclassifier labels\b",
        r"\bclassifier confidence\b",
        r"\bretrieval scores\b",
        r"\bfull retrieved documents\b",
        r"\bentire policy document\b",
        r"\bprint every policy\b",
        r"\breveal\b(?:\W+\w+){0,5}\W+\bprompt\b",
        r"\bshow\b(?:\W+\w+){0,5}\W+\bprompt\b",
    )
)


UNVERIFIED_ACTION_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bhas my card been frozen\b",
        r"\bis my card frozen\b",
        r"\bdid you freeze\b(?:\W+\w+){0,4}\W+\bcard\b",
        r"\bhave you frozen\b(?:\W+\w+){0,4}\W+\bcard\b",
        r"\bhas my card been cancelled\b",
        r"\bis my card cancelled\b",
        r"\bhas my replacement been ordered\b",
        r"\bis my replacement ordered\b",
        r"\bhas my dispute been filed\b",
        r"\bis my dispute filed\b",
        r"\bhas my refund been approved\b",
        r"\bis my refund approved\b",
        r"\bdid you change\b(?:\W+\w+){0,4}\W+\baddress\b",
    )
)


ACCOUNT_OPERATION_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\border me\b(?:\W+\w+){0,5}\W+\bcard\b",
        r"\bplace\b(?:\W+\w+){0,5}\W+\bcard order\b",
        r"\bsubmit\b(?:\W+\w+){0,5}\W+\bcard request\b",
    )
)


# ============================================================
# General account-access patterns
# ============================================================

LOGIN_PROBLEM_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bcannot log in\b",
        r"\bcan['’]?t log in\b",
        r"\bcannot login\b",
        r"\bcan['’]?t login\b",
        r"\bcannot access\b(?:\W+\w+){0,3}\W+\bapp\b",
        r"\bcan['’]?t access\b(?:\W+\w+){0,3}\W+\bapp\b",
        r"\blocked out\b(?:\W+\w+){0,5}\W+\baccount\b",
        r"\bunable to access\b(?:\W+\w+){0,5}\W+\baccount\b",
    )
)


STOLEN_DEVICE_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bphone was stolen\b",
        r"\bstolen phone\b",
        r"\bdevice was stolen\b",
        r"\bstolen device\b",
        r"\blost my phone\b",
        r"\blost my device\b",
    )
)


UNAUTHORIZED_PROFILE_CHANGE_PATTERNS: tuple[
    re.Pattern[str],
    ...,
] = _compile_patterns(
    (
        r"\bemail\b(?:\W+\w+){0,5}\W+\bchanged\b"
        r"(?:\W+\w+){0,5}\W+\bwithout\b"
        r"(?:\W+\w+){0,4}\W+\bpermission\b",

        r"\bphone\b(?:\W+\w+){0,5}\W+\bchanged\b"
        r"(?:\W+\w+){0,5}\W+\bwithout\b"
        r"(?:\W+\w+){0,4}\W+\bpermission\b",

        r"\bcontact details\b(?:\W+\w+){0,6}\W+\bchanged\b"
        r"(?:\W+\w+){0,5}\W+\bwithout\b"
        r"(?:\W+\w+){0,4}\W+\bpermission\b",

        r"\bsomeone changed my email\b",
        r"\bsomeone changed my phone\b",
        r"\bsomeone changed my details\b",
    )
)


# ============================================================
# Internal signal result
# ============================================================


@dataclass(frozen=True, slots=True)
class MessageSignals:
    """
    Deterministic signals found in one normalized message.
    """

    security_signals: tuple[str, ...]
    operational_signals: tuple[str, ...]

    negated_security: bool
    hypothetical_security: bool

    requests_internal_information: bool
    requests_unverified_action_status: bool
    requests_account_operation: bool

    ambiguous_international_fee: bool
    ambiguous_pin_or_passcode: bool
    ambiguous_card_delivery: bool

    login_problem: bool
    stolen_device: bool
    unauthorized_profile_change: bool


# ============================================================
# Generic helpers
# ============================================================


def _matches_any(
    text: str,
    patterns: Iterable[re.Pattern[str]],
) -> bool:
    """
    Return True when any pattern matches the supplied text.
    """

    return any(
        pattern.search(text) is not None
        for pattern in patterns
    )


def _matching_signal_names(
    text: str,
    pattern_map: dict[
        str,
        tuple[re.Pattern[str], ...],
    ],
) -> tuple[str, ...]:
    """
    Return signal names whose pattern sets match the text.
    """

    matched: list[str] = []

    for signal_name, patterns in pattern_map.items():
        if _matches_any(text, patterns):
            matched.append(signal_name)

    return tuple(matched)


def _ordered_policy_tuple(
    policy_ids: Iterable[str],
) -> tuple[str, ...]:
    """
    Return known policy IDs in deterministic project order.
    """

    unique = set(policy_ids)

    unknown = unique - set(KNOWN_POLICY_IDS)

    if unknown:
        raise ValueError(
            "Risk router produced unknown policy IDs: "
            f"{sorted(unknown)}"
        )

    return tuple(
        policy_id
        for policy_id in POLICY_ORDER
        if policy_id in unique
    )


def _policies_for_signal_names(
    signal_names: Iterable[str],
    mapping: dict[str, frozenset[str]],
) -> set[str]:
    """
    Return the union of policies associated with message signals.
    """

    policies: set[str] = set()

    for signal_name in signal_names:
        policies.update(
            mapping.get(signal_name, frozenset())
        )

    return policies


# ============================================================
# Routing-intent selection
# ============================================================


def select_routing_intents(
    classification: ClassificationResult,
) -> tuple[str, ...]:
    """
    Select classifier labels allowed to influence policy scope.

    All three predictions remain in candidate_intents.

    The highest-ranked prediction is always included. Lower-ranked
    predictions are included only when they meet the configured
    secondary confidence threshold.
    """

    predictions = classification.predictions

    selected: list[str] = [
        predictions[0].label,
    ]

    for prediction in predictions[1:]:
        if (
            prediction.confidence
            >= settings.routing_secondary_min_confidence
        ):
            selected.append(prediction.label)

    # dict.fromkeys preserves order while removing duplicates.
    return tuple(
        dict.fromkeys(selected)
    )


# ============================================================
# Signal detection
# ============================================================


def detect_message_signals(
    message: str,
) -> MessageSignals:
    """
    Detect deterministic security and operational message signals.
    """

    normalized = message.strip().lower()

    negated_security = _matches_any(
        normalized,
        NEGATED_SECURITY_PATTERNS,
    )

    hypothetical_security = _matches_any(
        normalized,
        HYPOTHETICAL_PATTERNS,
    )

    security_signals = _matching_signal_names(
        normalized,
        SECURITY_PATTERNS,
    )

    # Obvious negation suppresses incident-style card-loss and
    # transaction signals. It does not suppress a separately
    # detected account-takeover statement.
    if negated_security:
        security_signals = tuple(
            signal
            for signal in security_signals
            if signal == "account_takeover"
        )

    # Hypothetical statements are not treated as confirmed
    # incidents. They are handled as static general guidance.
    if hypothetical_security:
        security_signals = tuple(
            signal
            for signal in security_signals
            if signal == "account_takeover"
        )

    operational_signals = _matching_signal_names(
        normalized,
        OPERATIONAL_PATTERNS,
    )

    ambiguous_fee_wording = _matches_any(
        normalized,
        AMBIGUOUS_INTERNATIONAL_FEE_PATTERNS,
    )

    has_specific_transaction_type = _matches_any(
        normalized,
        SPECIFIC_TRANSACTION_TYPE_PATTERNS,
    )

    ambiguous_international_fee = (
        ambiguous_fee_wording
        and not has_specific_transaction_type
    )

    initial_delivery_detected = (
        "initial_card_delivery"
        in operational_signals
    )

    replacement_delivery_detected = (
        "replacement_card_delivery"
        in operational_signals
    )

    ambiguous_card_delivery = (
        _matches_any(
            normalized,
            AMBIGUOUS_CARD_DELIVERY_PATTERNS,
        )
        and not initial_delivery_detected
        and not replacement_delivery_detected
    )

    login_problem = _matches_any(
        normalized,
        LOGIN_PROBLEM_PATTERNS,
    )

    stolen_device = _matches_any(
        normalized,
        STOLEN_DEVICE_PATTERNS,
    )

    unauthorized_profile_change = _matches_any(
        normalized,
        UNAUTHORIZED_PROFILE_CHANGE_PATTERNS,
    )

    return MessageSignals(
        security_signals=security_signals,
        operational_signals=operational_signals,
        negated_security=negated_security,
        hypothetical_security=hypothetical_security,
        requests_internal_information=_matches_any(
            normalized,
            INTERNAL_INFORMATION_PATTERNS,
        ),
        requests_unverified_action_status=_matches_any(
            normalized,
            UNVERIFIED_ACTION_PATTERNS,
        ),
        requests_account_operation=_matches_any(
            normalized,
            ACCOUNT_OPERATION_PATTERNS,
        ),
        ambiguous_international_fee=(
            ambiguous_international_fee
        ),
        ambiguous_pin_or_passcode=_matches_any(
            normalized,
            PIN_OR_PASSCODE_PATTERNS,
        ),
        ambiguous_card_delivery=ambiguous_card_delivery,
        login_problem=login_problem,
        stolen_device=stolen_device,
        unauthorized_profile_change=(
            unauthorized_profile_change
        ),
    )


# ============================================================
# Risk-router implementation
# ============================================================


class RiskRouter:
    """
    Deterministic Phase 2 risk and policy router.
    """

    def route_message(
        self,
        message: str,
        classification: ClassificationResult,
    ) -> TriageDecision:
        """
        Produce the deterministic routing decision for one message.

        Priority:

        1. Critical account-takeover signal.
        2. Direct security incident.
        3. Internal-information request.
        4. Unverified completed-action request.
        5. Explicit account-operation request.
        6. Mandatory clarification.
        7. Unsupported request.
        8. Classifier uncertainty.
        9. Supported policy-grounded generation.
        """

        normalized_message = self._validate_message(message)

        candidate_intents = tuple(
            prediction.label
            for prediction in classification.predictions
        )

        routing_intents = select_routing_intents(
            classification
        )

        signals = detect_message_signals(
            normalized_message
        )

        classifier_policy_ids = set(
            policies_for_intents(routing_intents)
        )

        direct_security_policy_ids = (
            _policies_for_signal_names(
                signals.security_signals,
                SECURITY_SIGNAL_POLICY_MAP,
            )
        )

        direct_operational_policy_ids = (
            _policies_for_signal_names(
                signals.operational_signals,
                OPERATIONAL_SIGNAL_POLICY_MAP,
            )
        )

        # Direct replacement wording overrides a generic card-arrival
        # classifier prediction. This prevents replacement queries
        # from retrieving initial-card delivery policy.
        if (
            "replacement_card_delivery"
            in signals.operational_signals
        ):
            classifier_policy_ids.discard(
                "card_delivery"
            )

        # Direct initial-delivery wording similarly prevents
        # accidental replacement-policy access unless another
        # independent security or replacement signal requires it.
        if (
            "initial_card_delivery"
            in signals.operational_signals
            and "replacement_card_delivery"
            not in signals.operational_signals
        ):
            if not direct_security_policy_ids:
                classifier_policy_ids.discard(
                    "card_replacement"
                )

        allowed_policy_ids = (
            classifier_policy_ids
            | direct_security_policy_ids
            | direct_operational_policy_ids
        )

        # Direct message signals represent explicit user wording and
        # therefore determine required policy coverage when present.
        direct_required_policy_ids = (
            direct_security_policy_ids
            | direct_operational_policy_ids
        )

        # --------------------------------------------------------
        # 1. Critical account takeover
        # --------------------------------------------------------

        critical_takeover = self._is_critical_takeover(
            signals
        )

        if critical_takeover:
            policies = set(
                SECURITY_SIGNAL_POLICY_MAP[
                    "account_takeover"
                ]
            )

            return self._decision(
                risk_level="critical",
                action="human_escalation",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=policies,
                required_policy_ids=policies,
                security_signals=self._append_signal(
                    signals.security_signals,
                    "account_takeover",
                ),
                requires_human=True,
                reason_code=(
                    "critical_account_takeover_signal"
                ),
            )

        # --------------------------------------------------------
        # Hypothetical security guidance
        # --------------------------------------------------------

        if signals.hypothetical_security:
            policies = {
                "card_replacement",
                "fraud_policy",
            }

            return self._decision(
                risk_level="low",
                action="static_response",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=policies,
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code=(
                    "hypothetical_card_security_guidance"
                ),
            )

        # --------------------------------------------------------
        # Explicit negation
        # --------------------------------------------------------

        if (
            signals.negated_security
            and not signals.security_signals
            and not signals.operational_signals
        ):
            return self._decision(
                risk_level="low",
                action="static_response",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="negated_security_incident",
            )

        # --------------------------------------------------------
        # 2. Direct security incident
        # --------------------------------------------------------

        if signals.security_signals:
            security_policies = set(
                direct_security_policy_ids
            )

            # Operational signals can add required policy families.
            # Example: stolen card plus duplicate transaction.
            security_policies.update(
                direct_operational_policy_ids
            )

            requires_human = (
                signals.login_problem
                or signals.stolen_device
                or "account_takeover"
                in signals.security_signals
            )

            reason_code = self._security_reason_code(
                signals.security_signals
            )

            return self._decision(
                risk_level="high",
                action="urgent_guidance",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=security_policies,
                required_policy_ids=security_policies,
                security_signals=(
                    signals.security_signals
                ),
                requires_human=requires_human,
                reason_code=reason_code,
            )

        # ATM-retained cards require deterministic urgent guidance
        # even when no fraud wording is present.
        if (
            "atm_retained_card"
            in signals.operational_signals
        ):
            policies = set(
                OPERATIONAL_SIGNAL_POLICY_MAP[
                    "atm_retained_card"
                ]
            )

            return self._decision(
                risk_level="high",
                action="urgent_guidance",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=policies,
                required_policy_ids=policies,
                security_signals=("atm_retained_card",),
                requires_human=False,
                reason_code="atm_retained_card",
            )

        # --------------------------------------------------------
        # 3. Internal-information request
        # --------------------------------------------------------

        if signals.requests_internal_information:
            return self._decision(
                risk_level="low",
                action="static_response",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code=(
                    "internal_information_request"
                ),
            )

        # --------------------------------------------------------
        # 4. Unverified account-action status
        # --------------------------------------------------------

        if signals.requests_unverified_action_status:
            return self._decision(
                risk_level="low",
                action="static_response",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code=(
                    "unverified_action_status_request"
                ),
            )

        # --------------------------------------------------------
        # 5. Explicit account-operation request
        # --------------------------------------------------------

        if signals.requests_account_operation:
            return self._decision(
                risk_level="low",
                action="static_response",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="account_operation_request",
            )

        # --------------------------------------------------------
        # 6. Mandatory clarification
        # --------------------------------------------------------

        if signals.ambiguous_pin_or_passcode:
            return self._decision(
                risk_level="low",
                action="clarify",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="pin_or_passcode_ambiguous",
            )

        if signals.ambiguous_card_delivery:
            return self._decision(
                risk_level="low",
                action="clarify",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(
                    {
                        "card_delivery",
                        "card_replacement",
                    }
                ),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="card_delivery_type_ambiguous",
            )

        if signals.ambiguous_international_fee:
            return self._decision(
                risk_level="low",
                action="clarify",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(
                    {
                        "international_fees",
                    }
                ),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code=(
                    "international_fee_type_ambiguous"
                ),
            )

        if self._classifier_fee_intent_is_ambiguous(
            routing_intents,
            normalized_message,
        ):
            return self._decision(
                risk_level="low",
                action="clarify",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(
                    {
                        "international_fees",
                    }
                ),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code=(
                    "international_fee_type_ambiguous"
                ),
            )

        # A generic login problem is not proof of takeover.
        if (
            signals.login_problem
            and not signals.unauthorized_profile_change
            and not signals.stolen_device
        ):
            return self._decision(
                risk_level="low",
                action="clarify",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="account_access_issue_ambiguous",
            )

        # --------------------------------------------------------
        # 7. Unsupported request
        # --------------------------------------------------------

        supported_by_classifier = any_intent_is_supported(
            routing_intents
        )

        supported_by_direct_signal = bool(
            direct_security_policy_ids
            or direct_operational_policy_ids
        )

        if not (
            supported_by_classifier
            or supported_by_direct_signal
        ):
            return self._decision(
                risk_level="low",
                action="unsupported",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="unsupported_policy_scope",
            )

        # --------------------------------------------------------
        # 8. Classifier uncertainty
        # --------------------------------------------------------

        if (
            classification.uncertain
            and not supported_by_direct_signal
        ):
            return self._decision(
                risk_level="low",
                action="clarify",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=allowed_policy_ids,
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="classifier_uncertain",
            )

        # --------------------------------------------------------
        # 9. Normal supported generation
        # --------------------------------------------------------

        if not allowed_policy_ids:
            return self._decision(
                risk_level="low",
                action="unsupported",
                candidate_intents=candidate_intents,
                routing_intents=routing_intents,
                allowed_policy_ids=(),
                required_policy_ids=(),
                security_signals=(),
                requires_human=False,
                reason_code="no_allowed_policy_scope",
            )

        if direct_required_policy_ids:
            required_policy_ids = (
                direct_required_policy_ids
            )
        else:
            required_policy_ids = set(
                INTENT_POLICY_MAP.get(
                    classification.top_intent,
                    frozenset(),
                )
            )

        # If the top prediction is unsupported but a secondary
        # prediction is supported, require at least the first
        # supported routing intent's policy family.
        if not required_policy_ids:
            for intent in routing_intents:
                intent_policies = INTENT_POLICY_MAP.get(
                    intent,
                    frozenset(),
                )

                if intent_policies:
                    required_policy_ids.update(
                        intent_policies
                    )
                    break

        risk_level = self._normal_risk_level(
            operational_signals=(
                signals.operational_signals
            ),
            routing_intents=routing_intents,
        )

        return self._decision(
            risk_level=risk_level,
            action="generate",
            candidate_intents=candidate_intents,
            routing_intents=routing_intents,
            allowed_policy_ids=allowed_policy_ids,
            required_policy_ids=required_policy_ids,
            security_signals=(),
            requires_human=False,
            reason_code="supported_policy_generation",
        )

    @staticmethod
    def _validate_message(message: str) -> str:
        """
        Validate and normalize router input.
        """

        if not isinstance(message, str):
            raise TypeError(
                "Risk-router message must be a string."
            )

        normalized = message.strip()

        if not normalized:
            raise ValueError(
                "Risk-router message cannot be empty."
            )

        if (
            len(normalized)
            > settings.max_customer_message_length
        ):
            raise ValueError(
                "Risk-router message exceeds the configured "
                "maximum customer-message length."
            )

        return normalized

    @staticmethod
    def _is_critical_takeover(
        signals: MessageSignals,
    ) -> bool:
        """
        Return True only for strong account-takeover evidence.

        A login problem by itself is intentionally insufficient.
        """

        direct_takeover_signal = (
            "account_takeover"
            in signals.security_signals
        )

        login_plus_profile_change = (
            signals.login_problem
            and signals.unauthorized_profile_change
        )

        stolen_device_plus_access_problem = (
            signals.stolen_device
            and signals.login_problem
        )

        return (
            direct_takeover_signal
            or login_plus_profile_change
            or stolen_device_plus_access_problem
        )

    @staticmethod
    def _classifier_fee_intent_is_ambiguous(
        routing_intents: tuple[str, ...],
        message: str,
    ) -> bool:
        """
        Return True when a fee intent exists but transaction type
        is not clear from the message.
        """

        has_fee_intent = any(
            intent in AMBIGUOUS_FEE_INTENTS
            for intent in routing_intents
        )

        if not has_fee_intent:
            return False

        has_specific_type = _matches_any(
            message.lower(),
            SPECIFIC_TRANSACTION_TYPE_PATTERNS,
        )

        return not has_specific_type

    @staticmethod
    def _security_reason_code(
        security_signals: tuple[str, ...],
    ) -> str:
        """
        Return a stable reason code for direct security routing.
        """

        priority = (
            "account_takeover",
            "stolen_card",
            "lost_card",
            "unknown_withdrawal",
            "unknown_transaction",
            "compromised_card",
        )

        for signal in priority:
            if signal in security_signals:
                return f"direct_{signal}_signal"

        return "direct_security_signal"

    @staticmethod
    def _normal_risk_level(
        *,
        operational_signals: tuple[str, ...],
        routing_intents: tuple[str, ...],
    ) -> str:
        """
        Determine risk for non-security supported requests.
        """

        medium_signals = {
            "replacement_card_delivery",
            "damaged_card",
            "duplicate_transaction",
        }

        if any(
            signal in medium_signals
            for signal in operational_signals
        ):
            return "medium"

        medium_intents = {
            "transaction_charged_twice",
            "card_swallowed",
        }

        if any(
            intent in medium_intents
            for intent in routing_intents
        ):
            return "medium"

        return "low"

    @staticmethod
    def _append_signal(
        signals: tuple[str, ...],
        signal: str,
    ) -> tuple[str, ...]:
        """
        Add one signal while preserving order and uniqueness.
        """

        return tuple(
            dict.fromkeys(
                (
                    *signals,
                    signal,
                )
            )
        )

    @staticmethod
    def _decision(
        *,
        risk_level: str,
        action: str,
        candidate_intents: tuple[str, ...],
        routing_intents: tuple[str, ...],
        allowed_policy_ids: Iterable[str],
        required_policy_ids: Iterable[str],
        security_signals: tuple[str, ...],
        requires_human: bool,
        reason_code: str,
    ) -> TriageDecision:
        """
        Build and validate one deterministic TriageDecision.
        """

        allowed = _ordered_policy_tuple(
            allowed_policy_ids
        )

        required = _ordered_policy_tuple(
            required_policy_ids
        )

        missing_required = (
            set(required) - set(allowed)
        )

        if missing_required:
            raise ValueError(
                "Required policies must also be allowed. "
                f"Missing from allowed set: "
                f"{sorted(missing_required)}"
            )

        return TriageDecision(
            risk_level=risk_level,
            action=action,
            candidate_intents=candidate_intents,
            routing_intents=routing_intents,
            allowed_policy_ids=allowed,
            required_policy_ids=required,
            security_signals=security_signals,
            requires_human=requires_human,
            reason_code=reason_code,
        )


# Shared router instance for simple application imports.
risk_router = RiskRouter()
