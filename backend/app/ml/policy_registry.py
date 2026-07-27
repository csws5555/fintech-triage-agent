"""
Explicit policy coverage registry for Phase 2.

The classifier may predict any of 77 Banking77 intents, while the
prototype knowledge base supports only a reviewed subset.
"""

from __future__ import annotations


KNOWN_POLICY_IDS = frozenset(
    {
        "fraud_policy",
        "card_replacement",
        "card_delivery",
        "international_fees",
    }
)


INTENT_POLICY_MAP: dict[str, frozenset[str]] = {
    "lost_or_stolen_card": frozenset(
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

    "cash_withdrawal_not_recognised": frozenset(
        {
            "fraud_policy",
        }
    ),

    "card_payment_not_recognised": frozenset(
        {
            "fraud_policy",
        }
    ),

    "transaction_charged_twice": frozenset(
        {
            "fraud_policy",
        }
    ),

    "cash_withdrawal_charge": frozenset(
        {
            "international_fees",
        }
    ),

    "transfer_fee_charged": frozenset(
        {
            "international_fees",
        }
    ),

    "card_payment_fee_charged": frozenset(
        {
            "international_fees",
        }
    ),

    "extra_charge_on_statement": frozenset(
        {
            "international_fees",
            "fraud_policy",
        }
    ),

    "card_arrival": frozenset(
        {
            "card_delivery",
        }
    ),

    "card_delivery_estimate": frozenset(
        {
            "card_delivery",
        }
    ),

    "card_swallowed": frozenset(
        {
            "card_replacement",
            "fraud_policy",
        }
    ),
}


SECURITY_INTENTS = frozenset(
    {
        "lost_or_stolen_card",
        "compromised_card",
        "cash_withdrawal_not_recognised",
        "card_payment_not_recognised",
    }
)


AMBIGUOUS_FEE_INTENTS = frozenset(
    {
        "cash_withdrawal_charge",
        "transfer_fee_charged",
        "card_payment_fee_charged",
        "extra_charge_on_statement",
    }
)


def policies_for_intents(
    intents: tuple[str, ...],
) -> frozenset[str]:
    """
    Return the union of policies mapped to the supplied intents.
    """

    policies: set[str] = set()

    for intent in intents:
        policies.update(
            INTENT_POLICY_MAP.get(intent, frozenset())
        )

    return frozenset(policies)


def intent_is_supported(intent: str) -> bool:
    """
    Return True when an intent has explicit policy coverage.
    """

    return intent in INTENT_POLICY_MAP


def any_intent_is_supported(
    intents: tuple[str, ...],
) -> bool:
    """
    Return True when any supplied intent is explicitly supported.
    """

    return any(
        intent_is_supported(intent)
        for intent in intents
    )


def validate_policy_registry() -> None:
    """
    Fail if the registry references an unknown policy ID.
    """

    for intent, policy_ids in INTENT_POLICY_MAP.items():
        if not intent.strip():
            raise ValueError(
                "Policy registry contains an empty intent."
            )

        unknown = set(policy_ids) - set(KNOWN_POLICY_IDS)

        if unknown:
            raise ValueError(
                f"Intent {intent!r} references unknown "
                f"policies: {sorted(unknown)}"
            )


validate_policy_registry()
