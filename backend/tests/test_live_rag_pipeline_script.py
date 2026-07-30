from __future__ import annotations

from typing import Any

import pytest

from app.ml.risk_router import risk_router
from app.ml.triage_types import (
    ClassificationResult,
    GeneratedSupportResponse,
    IntentPrediction,
    RetrievedPolicy,
)
from scripts import test_rag_pipeline


def classification_for(query: str) -> ClassificationResult:
    top_label = (
        "mortgage_info"
        if "mortgage" in query.lower()
        else "card_arrival"
    )
    return ClassificationResult(
        predictions=(
            IntentPrediction(label=top_label, confidence=0.90),
            IntentPrediction(
                label="card_delivery_estimate",
                confidence=0.05,
            ),
            IntentPrediction(label="cash_withdrawal_charge", confidence=0.02),
        ),
        uncertain=False,
        top_two_margin=0.85,
    )


def policy(document_id: str) -> RetrievedPolicy:
    return RetrievedPolicy(
        chunk_id=f"{document_id}-live-test",
        document_id=document_id,
        content=(
            f"Private complete {document_id} policy body. "
            "Delivery dates are estimates and cannot be guaranteed."
        ),
        source_file=f"{document_id}.md",
        title=f"{document_id} policy",
        section_path=f"{document_id} > guidance",
        version="1.0",
        effective_date="2026-07-01",
        review_date="2026-10-01",
        status="approved",
        chunk_index=0,
        content_hash=f"{document_id}-hash",
        relevance_score=0.90,
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.retrieve_calls: list[dict[str, Any]] = []

    def retrieve(self, **kwargs: Any) -> tuple[RetrievedPolicy, ...]:
        self.retrieve_calls.append(kwargs)
        return tuple(
            policy(document_id)
            for document_id in kwargs["required_policy_ids"]
        )

    def retrieval_is_sufficient(
        self,
        policies: object,
        decision: object,
    ) -> bool:
        return bool(policies)


class FakeStructuredModel:
    def invoke(self, messages: object) -> GeneratedSupportResponse:
        return GeneratedSupportResponse(
            answer=(
                "Delivery dates are estimates and cannot be guaranteed. "
                "Check the application for the current delivery details."
            ),
            needs_human=False,
            insufficient_policy=False,
            claimed_completed_action=False,
        )


class FakeChatModel:
    def with_structured_output(self, schema: object) -> FakeStructuredModel:
        return FakeStructuredModel()


class GuaranteeStructuredModel:
    def invoke(self, messages: object) -> GeneratedSupportResponse:
        return GeneratedSupportResponse(
            answer="Your card will definitely arrive tomorrow.",
            needs_human=False,
            insufficient_policy=False,
            claimed_completed_action=False,
        )


class GuaranteeChatModel:
    def with_structured_output(
        self,
        schema: object,
    ) -> GuaranteeStructuredModel:
        return GuaranteeStructuredModel()


def test_live_pipeline_checks_report_real_component_boundaries() -> None:
    retriever = FakeRetriever()

    report = test_rag_pipeline.run_live_pipeline_checks(
        classifier=classification_for,
        router=risk_router,
        retriever=retriever,
        chat_model=FakeChatModel(),
    )

    assert len(report.probes) == 7
    assert sum(probe.llm_called for probe in report.probes) == 2
    assert {
        probe.validator_result
        for probe in report.probes
        if probe.llm_called
    } == {"PASS"}
    assert {
        probe.validator_result
        for probe in report.probes
        if not probe.llm_called
    } == {"NOT_CALLED"}
    assert len(retriever.retrieve_calls) == 3
    assert report.probes[0].retrieved_policy_ids == (
        "card_delivery",
    )
    assert report.probes[1].retrieved_policy_ids == (
        "card_replacement",
    )


def test_pipeline_expectation_mismatch_fails_closed() -> None:
    def always_delivery(_: str) -> ClassificationResult:
        return classification_for("delivery")

    with pytest.raises(
        test_rag_pipeline.LivePipelineTestError,
        match="unsupported_request",
    ) as captured:
        test_rag_pipeline.run_live_pipeline_checks(
            classifier=always_delivery,
            router=risk_router,
            retriever=FakeRetriever(),
            chat_model=FakeChatModel(),
        )

    diagnostic = str(captured.value)
    assert "pipeline outcome did not match expectations" in diagnostic
    assert "route action expected=unsupported actual=generate" in diagnostic
    assert (
        "response mode expected=static_fallback "
        "actual=grounded_generation"
    ) in diagnostic
    assert (
        "retrieved policy IDs expected=None actual=card_delivery"
        in diagnostic
    )
    assert "LLM called expected=no actual=yes" in diagnostic
    assert "validator=PASS" in diagnostic
    assert "requires_human=no" in diagnostic
    assert "retrieval_sufficient=yes" in diagnostic
    assert "final_answer=Delivery dates are estimates" in diagnostic
    assert "Private complete" not in diagnostic
    assert "BEGIN APPROVED POLICY CONTEXT JSON" not in diagnostic


def test_validator_rejection_is_typed_as_pipeline_safe() -> None:
    with pytest.raises(
        test_rag_pipeline.SafeGenerationRejectedError,
        match="initial_delivery_generation",
    ) as captured:
        test_rag_pipeline.run_live_pipeline_checks(
            classifier=classification_for,
            router=risk_router,
            retriever=FakeRetriever(),
            chat_model=GuaranteeChatModel(),
            probes=(test_rag_pipeline.PIPELINE_PROBES[0],),
        )

    diagnostic = str(captured.value)
    assert (
        "response mode expected=grounded_generation "
        "actual=static_fallback"
    ) in diagnostic
    assert "validator=REJECTED:unsupported_guarantee" in diagnostic
    assert "FAIL:" not in diagnostic
    assert "requires_human=yes" in diagnostic
    assert "retrieval_sufficient=yes" in diagnostic
    assert "Your card will definitely arrive tomorrow." not in diagnostic
    assert "final_answer=I could not verify enough approved" in diagnostic


def test_report_contains_required_fields_without_prompts_or_policies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = test_rag_pipeline.run_live_pipeline_checks(
        classifier=classification_for,
        router=risk_router,
        retriever=FakeRetriever(),
        chat_model=FakeChatModel(),
    )

    test_rag_pipeline.print_pipeline_report(report)

    captured = capsys.readouterr()
    assert "Query:" in captured.out
    assert "Top-three labels:" in captured.out
    assert "Risk:" in captured.out
    assert "Action:" in captured.out
    assert "Response mode:" in captured.out
    assert "Retrieved policy IDs:" in captured.out
    assert "LLM called:" in captured.out
    assert "Validator result:" in captured.out
    assert "Final answer:" in captured.out
    assert "BEGIN APPROVED POLICY CONTEXT JSON" not in captured.out
    assert "Private complete" not in captured.out


def test_main_returns_success_for_completed_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = test_rag_pipeline.run_live_pipeline_checks(
        classifier=classification_for,
        router=risk_router,
        retriever=FakeRetriever(),
        chat_model=FakeChatModel(),
    )
    monkeypatch.setattr(
        test_rag_pipeline,
        "run_live_pipeline_checks",
        lambda: report,
    )

    assert test_rag_pipeline.main() == 0
    assert "PASS live classifier-to-answer" in capsys.readouterr().out


def test_main_contains_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> object:
        raise RuntimeError("private prompt details")

    monkeypatch.setattr(
        test_rag_pipeline,
        "run_live_pipeline_checks",
        fail,
    )

    assert test_rag_pipeline.main() == 1

    captured = capsys.readouterr()
    assert "failed safely" in captured.err
    assert "private prompt details" not in captured.err


def test_main_prints_safe_expected_versus_actual_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> object:
        raise test_rag_pipeline.LivePipelineTestError(
            "initial_delivery_generation: pipeline outcome did not match "
            "expectations. Mismatches: response mode "
            "expected=grounded_generation actual=static_fallback. "
            "Safe execution snapshot: validator=FAIL:response_too_long; "
            "requires_human=yes; retrieval_sufficient=yes; "
            "final_answer=Use an official support channel."
        )

    monkeypatch.setattr(
        test_rag_pipeline,
        "run_live_pipeline_checks",
        fail,
    )

    assert test_rag_pipeline.main() == 1

    captured = capsys.readouterr()
    assert "FAIL: initial_delivery_generation" in captured.err
    assert (
        "response mode expected=grounded_generation "
        "actual=static_fallback"
    ) in captured.err
    assert "validator=FAIL:response_too_long" in captured.err
    assert "final_answer=Use an official support channel." in captured.err


def test_main_labels_validator_fallback_as_pipeline_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject_generation() -> object:
        raise test_rag_pipeline.SafeGenerationRejectedError(
            "initial_delivery_generation: pipeline outcome did not match "
            "expectations. Mismatches: response mode "
            "expected=grounded_generation actual=static_fallback. "
            "Safe execution snapshot: "
            "validator=REJECTED:unsupported_guarantee; "
            "requires_human=yes; retrieval_sufficient=yes; "
            "final_answer=Use an official support channel."
        )

    monkeypatch.setattr(
        test_rag_pipeline,
        "run_live_pipeline_checks",
        reject_generation,
    )

    assert test_rag_pipeline.main() == 1

    captured = capsys.readouterr()
    assert (
        "PIPELINE_SAFE / GENERATION_REJECTED: "
        "initial_delivery_generation"
    ) in captured.err
    assert "Strict live generation-quality check did not pass" in captured.err
    assert "process exit code is 1" in captured.err
    assert "FAIL:" not in captured.err
