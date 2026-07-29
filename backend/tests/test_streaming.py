from __future__ import annotations

import pytest

from app.ml.output_validator import output_validator
from app.ml.rag_pipeline import STREAM_CHUNK_CHARACTERS
from app.ml.response_templates import (
    classifier_uncertainty_clarification,
    insufficient_policy_response,
    replacement_card_guidance,
    unsupported_policy_response,
)
from tests.test_rag_pipeline import (
    FakeLlm,
    FakeRetriever,
    build_pipeline,
    classification,
    decision,
    generated,
    policy,
    urgent_decision,
)


def test_stream_answer_reconstructs_approved_generated_text() -> None:
    approved = (
        "The estimated delivery date appears while ordering. "
        "Tracking may become available after dispatch, and support can "
        "help if the displayed estimate has passed."
    )
    pipeline, _, _, _, _ = build_pipeline(
        decision(),
        retriever=FakeRetriever((policy(),), sufficient=True),
        llm=FakeLlm((generated(approved),)),
    )

    chunks = list(
        pipeline.stream_answer(
            query="When will my card arrive?",
            classification=classification(),
        )
    )

    assert "".join(chunks) == approved
    assert len(chunks) > 1
    assert all(
        chunk and len(chunk) <= STREAM_CHUNK_CHARACTERS
        for chunk in chunks
    )


def test_static_response_uses_same_buffered_delivery_path() -> None:
    pipeline, _, retriever, llm, validator = build_pipeline(
        decision(
            action="unsupported",
            reason_code="unsupported_policy_scope",
            allowed_policy_ids=(),
            required_policy_ids=(),
        )
    )

    chunks = list(
        pipeline.stream_answer(
            query="What mortgage rate can I receive?",
            classification=classification(),
        )
    )

    assert "".join(chunks) == unsupported_policy_response()
    assert retriever.retrieve_calls == []
    assert getattr(llm, "schemas") == []
    assert getattr(validator, "calls") == []


def test_clarification_uses_same_buffered_delivery_path() -> None:
    pipeline, _, retriever, llm, validator = build_pipeline(
        decision(
            action="clarify",
            reason_code="classifier_uncertain",
            required_policy_ids=(),
        )
    )

    chunks = list(
        pipeline.stream_answer(
            query="I need help with something.",
            classification=classification(),
        )
    )

    assert "".join(chunks) == classifier_uncertainty_clarification()
    assert retriever.retrieve_calls == []
    assert getattr(llm, "schemas") == []
    assert getattr(validator, "calls") == []


def test_urgent_safety_uses_same_buffered_delivery_path() -> None:
    route = urgent_decision("stolen_card")
    policies = tuple(
        policy(str(index), document_id=document_id)
        for index, document_id in enumerate(
            route.required_policy_ids
        )
    )
    pipeline, _, _, llm, validator = build_pipeline(
        route,
        retriever=FakeRetriever(policies, sufficient=True),
    )

    chunks = list(
        pipeline.stream_answer(
            query="My card was stolen.",
            classification=classification(),
        )
    )

    assert "".join(chunks) == replacement_card_guidance(
        requires_human=False
    )
    assert getattr(llm, "schemas") == []
    assert getattr(validator, "calls") == []


def test_stream_answer_never_yields_rejected_generated_text() -> None:
    rejected = "I froze your card."
    pipeline, _, _, _, _ = build_pipeline(
        decision(),
        retriever=FakeRetriever((policy(),), sufficient=True),
        llm=FakeLlm((generated(rejected),)),
        validator=output_validator,
    )

    chunks = list(
        pipeline.stream_answer(
            query="When will my card arrive?",
            classification=classification(),
        )
    )
    delivered = "".join(chunks)

    assert delivered == insufficient_policy_response()
    assert rejected not in delivered


def test_stream_answer_yields_nothing_when_answer_fails() -> None:
    pipeline, _, _, _, _ = build_pipeline(
        decision(action="unsupported")
    )
    chunks = pipeline.stream_answer(
        query="   ",
        classification=classification(),
    )

    with pytest.raises(ValueError, match="blank"):
        next(chunks)

    assert list(chunks) == []
