from __future__ import annotations

import pytest

from app.ml.grounding_prompt import build_grounding_prompt
from app.ml.structured_generation import (
    generate_structured_response,
)
from app.ml.triage_types import RetrievedPolicy, TriageDecision


@pytest.mark.integration
def test_live_structured_generation_returns_typed_output() -> None:
    decision = TriageDecision(
        risk_level="low",
        action="generate",
        candidate_intents=(
            "card_arrival",
            "card_delivery_estimate",
            "mortgage_info",
        ),
        routing_intents=("card_arrival",),
        allowed_policy_ids=("card_delivery",),
        required_policy_ids=("card_delivery",),
        security_signals=(),
        requires_human=False,
        reason_code="supported_policy_generation",
    )
    policy = RetrievedPolicy(
        chunk_id="live-card-delivery",
        document_id="card_delivery",
        content=(
            "The application shows an estimated delivery date "
            "during the card-ordering process. Delivery dates are "
            "estimates and cannot be guaranteed."
        ),
        source_file="live-policy.md",
        title="Initial Card Delivery Policy",
        section_path=(
            "Initial Card Delivery Policy > Delivery Estimates"
        ),
        version="1.0",
        effective_date="2026-07-01",
        review_date="2026-10-01",
        status="approved",
        chunk_index=0,
        content_hash="live-card-delivery-hash",
        relevance_score=0.90,
    )
    messages = build_grounding_prompt(
        "When should my newly ordered bank card arrive?",
        decision,
        (policy,),
    )

    result = generate_structured_response(messages)

    assert result.used_fallback is False
    assert result.failure_codes == ()
    assert isinstance(result.response.answer, str)
    assert isinstance(result.response.needs_human, bool)
    assert isinstance(result.response.insufficient_policy, bool)
    assert isinstance(
        result.response.claimed_completed_action,
        bool,
    )
