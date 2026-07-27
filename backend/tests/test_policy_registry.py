from __future__ import annotations

import pytest

from app.ml import policy_registry


def test_known_policy_ids_match_the_approved_documents() -> None:
    assert policy_registry.KNOWN_POLICY_IDS == {
        "fraud_policy",
        "card_replacement",
        "card_delivery",
        "international_fees",
    }


def test_unsupported_intent_has_no_policy_scope() -> None:
    assert not policy_registry.intent_is_supported("mortgage_info")
    assert policy_registry.policies_for_intents(
        ("mortgage_info",)
    ) == frozenset()


def test_security_intents_map_to_reviewed_policies() -> None:
    assert policy_registry.policies_for_intents(
        ("lost_or_stolen_card",)
    ) == {"fraud_policy", "card_replacement"}
    assert policy_registry.policies_for_intents(
        ("cash_withdrawal_not_recognised",)
    ) == {"fraud_policy"}


def test_duplicate_transaction_has_policy_coverage() -> None:
    assert policy_registry.policies_for_intents(
        ("transaction_charged_twice",)
    ) == {"fraud_policy"}


def test_registry_rejects_unknown_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        policy_registry.INTENT_POLICY_MAP,
        "invalid_test_intent",
        frozenset({"unknown_policy"}),
    )

    with pytest.raises(ValueError, match="unknown"):
        policy_registry.validate_policy_registry()


def test_registry_rejects_empty_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        policy_registry.INTENT_POLICY_MAP,
        "",
        frozenset({"fraud_policy"}),
    )

    with pytest.raises(ValueError, match="empty intent"):
        policy_registry.validate_policy_registry()
