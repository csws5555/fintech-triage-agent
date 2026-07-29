from __future__ import annotations

from typing import Any

import pytest

from app.ml.triage_types import RetrievedPolicy
from scripts import test_retrieval


def policy(
    chunk_id: str,
    document_id: str,
    score: float,
) -> RetrievedPolicy:
    return RetrievedPolicy(
        chunk_id=chunk_id,
        document_id=document_id,
        content=f"Private policy body for {chunk_id}.",
        source_file=f"{document_id}.md",
        title=f"{document_id} policy",
        section_path=f"{document_id} > guidance",
        version="1.0",
        effective_date="2026-07-01",
        review_date="2026-10-01",
        status="approved",
        chunk_index=0,
        content_hash=f"{chunk_id}-hash",
        relevance_score=score,
    )


class FakeRetriever:
    def __init__(self, *, unsupported_result: bool = False) -> None:
        self.unsupported_result = unsupported_result
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, **kwargs: Any) -> tuple[RetrievedPolicy, ...]:
        self.calls.append(kwargs)
        query = str(kwargs["query"])

        if query == "When should my newly ordered bank card arrive?":
            return (policy("delivery-related", "card_delivery", 0.91),)

        if query == "My replacement card still has not arrived.":
            return (
                policy(
                    "replacement-related",
                    "card_replacement",
                    0.88,
                ),
            )

        if query == "My card was stolen in London.":
            return (
                policy("fraud", "fraud_policy", 0.93),
                policy("replacement", "card_replacement", 0.84),
            )

        if query == "The foreign ATM added a fee.":
            return (
                policy("fee", "international_fees", 0.86),
            )

        if query == "How do I cook pasta?":
            if self.unsupported_result:
                return (policy("unsafe-hit", "fraud_policy", 0.51),)
            return ()

        if query == "How do I report an unrecognized cash withdrawal?":
            return (policy("delivery-unrelated", "card_delivery", 0.55),)

        raise AssertionError(f"Unexpected query: {query}")


def test_live_retrieval_checks_cover_every_required_invariant() -> None:
    retriever = FakeRetriever()

    report = test_retrieval.run_live_retrieval_checks(retriever)

    assert len(report.probes) == 6
    assert report.score_direction_passed is True
    assert report.delivery_distinction_passed is True
    assert len(retriever.calls) == 6
    assert all(
        call["allowed_policy_ids"]
        for call in retriever.calls
    )
    stolen_call = retriever.calls[2]
    assert stolen_call["required_policy_ids"] == (
        "fraud_policy",
        "card_replacement",
    )


def test_unsupported_threshold_hit_fails_closed() -> None:
    with pytest.raises(
        test_retrieval.LiveRetrievalTestError,
        match="unsupported probe",
    ):
        test_retrieval.run_live_retrieval_checks(
            FakeRetriever(unsupported_result=True)
        )


def test_main_prints_safe_facts_without_policy_bodies(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        test_retrieval,
        "get_retriever",
        FakeRetriever,
    )

    assert test_retrieval.main() == 0

    captured = capsys.readouterr()
    assert "PASS expected policies appeared" in captured.out
    assert "Query: How do I cook pasta?" in captured.out
    assert "card_delivery" in captured.out
    assert "Private policy body" not in captured.out
    assert captured.err == ""


def test_main_contains_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> object:
        raise RuntimeError("private active-store path")

    monkeypatch.setattr(test_retrieval, "get_retriever", fail)

    assert test_retrieval.main() == 1

    captured = capsys.readouterr()
    assert "failed safely" in captured.err
    assert "private active-store path" not in captured.err
