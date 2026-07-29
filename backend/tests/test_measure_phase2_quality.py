from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.ml.output_validator import (
    INTERNAL_INFORMATION_LEAK,
    SENSITIVE_DATA_REQUEST,
    UNVERIFIED_COMPLETED_ACTION,
)
from app.ml.rag_config import settings
from app.ml.triage_types import (
    ClassificationResult,
    OutputValidationResult,
    PipelineAnswer,
)
from scripts.calibrate_retrieval import (
    CalibrationCase,
    RetrieverMetrics,
    load_calibration_cases,
)
from scripts import measure_phase2_quality as quality


class _FakeValidator:
    def validate(
        self,
        generated: object,
        *,
        decision: object,
        policies: object = (),
    ) -> OutputValidationResult:
        del decision, policies
        answer = getattr(generated, "answer", "")
        codes: list[str] = []

        if "unsafe-secret-request" in answer:
            codes.append(SENSITIVE_DATA_REQUEST)

        if "unsafe-completed-action" in answer:
            codes.append(UNVERIFIED_COMPLETED_ACTION)

        if "unsafe-hidden-leak" in answer:
            codes.append(INTERNAL_INFORMATION_LEAK)

        return OutputValidationResult(
            safe=not codes,
            failure_codes=tuple(codes),
        )


class _IncrementingClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


def _locked_cases() -> tuple[CalibrationCase, ...]:
    return quality.locked_evaluation_cases(
        load_calibration_cases()
    )


def _answer_for(
    case: CalibrationCase,
    *,
    answer: str | None = None,
    reason_code: str = "test_quality_outcome",
) -> quality.SafetyOutcome:
    decision = quality.risk_router.route_message(
        case.query,
        case.classification,
    )
    text = answer or ". ".join(case.required_concepts)
    return quality.SafetyOutcome(
        decision=decision,
        answer=PipelineAnswer(
            answer=text,
            response_mode=case.expected_response_mode,
            risk_level=decision.risk_level,
            requires_human=case.requires_human,
            retrieval_sufficient=case.retrieval.attempt,
            retrieved_policy_ids=(
                case.retrieval.expected_policy_ids
            ),
            retrieved_chunk_ids=(),
            reason_code=reason_code,
        ),
    )


def _retrieval_metrics(
    *,
    expected_policy_hit_rate: float = 1.0,
) -> RetrieverMetrics:
    return RetrieverMetrics(
        threshold=settings.min_relevance_score,
        attempted_case_count=10,
        expected_policy_hit_rate=expected_policy_hit_rate,
        recall_at_4=1.0,
        false_positive_policy_rate=0.0,
        unsupported_query_retrieval_acceptance_rate=0.0,
        false_fallback_rate=0.0,
        average_accepted_chunk_count=2.0,
        required_policy_family_coverage=1.0,
    )


def _performance_metrics() -> quality.PerformanceMetrics:
    return quality.PerformanceMetrics(
        classifier_cold_start_seconds=1.0,
        classifier_warm_latency_seconds=0.1,
        embedding_cold_start_seconds=0.2,
        retrieval_latency_seconds=0.3,
        generation_duration_seconds=0.4,
        total_cold_start_seconds=2.0,
        total_warm_response_seconds=0.5,
        buffered_streaming_duration_seconds=0.6,
    )


def test_locked_dataset_has_distinct_critical_takeover_denominator() -> None:
    locked = _locked_cases()
    takeover = tuple(
        case
        for case in locked
        if "security_account_takeover"
        in case.evaluation_categories
    )

    assert len(locked) == 36
    assert len(takeover) == 1
    assert takeover[0].case_id == "RAG-EVAL-036"
    assert takeover[0].query != (
        "Someone changed my email and I cannot log in."
    )


def test_routing_quality_records_all_locked_metrics() -> None:
    metrics = quality.evaluate_routing_quality(_locked_cases())

    assert metrics.case_count == 36
    assert metrics.direct_security_signal_recall == 1.0
    assert metrics.critical_takeover_recall == 1.0
    assert metrics.unsupported_request_rejection == 1.0
    assert metrics.clarification_accuracy == 1.0
    assert metrics.initial_versus_replacement_accuracy == 1.0
    assert metrics.security_false_positive_rate == 0.0
    assert metrics.security_false_negative_rate == 0.0


def test_routing_quality_rejects_calibration_cases() -> None:
    calibration = tuple(
        case
        for case in load_calibration_cases()
        if case.split == "calibration"
    )

    with pytest.raises(
        quality.QualityMeasurementError,
        match="locked evaluation",
    ):
        quality.evaluate_routing_quality(calibration)


def test_safety_quality_records_zero_failure_safe_matrix() -> None:
    locked = _locked_cases()

    metrics = quality.evaluate_safety_quality(
        locked,
        run_outcome=_answer_for,
        validator=_FakeValidator(),
    )

    assert metrics.case_count == 36
    assert metrics.required_safety_action_coverage == 1.0
    assert metrics.prohibited_claim_rate == 0.0
    assert metrics.prompt_injection_failure_rate == 0.0
    assert metrics.sensitive_data_request_rate == 0.0
    assert metrics.completed_action_claim_rate == 0.0
    assert metrics.hidden_information_leakage == 0.0
    assert metrics.validation_failure_rate == 0.0


def test_safety_quality_counts_validator_and_content_failures() -> None:
    locked = _locked_cases()
    injection_id = "RAG-EVAL-033"
    generation_id = "RAG-EVAL-003"

    def unsafe_outcome(
        case: CalibrationCase,
    ) -> quality.SafetyOutcome:
        if case.case_id == injection_id:
            return _answer_for(
                case,
                answer=(
                    "unsafe-secret-request unsafe-completed-action "
                    "unsafe-hidden-leak system prompt contents"
                ),
            )

        if case.case_id == generation_id:
            return _answer_for(
                case,
                reason_code=quality.OUTPUT_VALIDATION_FAILED,
            )

        return _answer_for(case)

    metrics = quality.evaluate_safety_quality(
        locked,
        run_outcome=unsafe_outcome,
        validator=_FakeValidator(),
    )

    assert metrics.prohibited_claim_rate > 0.0
    assert metrics.prompt_injection_failure_rate > 0.0
    assert metrics.sensitive_data_request_rate > 0.0
    assert metrics.completed_action_claim_rate > 0.0
    assert metrics.hidden_information_leakage > 0.0
    assert metrics.validation_failure_rate > 0.0


def test_safety_quality_fails_closed_on_invalid_outcome() -> None:
    with pytest.raises(
        quality.QualityMeasurementError,
        match="invalid outcome",
    ):
        quality.evaluate_safety_quality(
            _locked_cases(),
            run_outcome=lambda _case: object(),  # type: ignore[arg-type]
            validator=_FakeValidator(),
        )


def test_performance_metrics_use_injected_probes_and_monotonic_clock() -> None:
    locked = _locked_cases()
    calls = {
        "classifier": 0,
        "embedding": 0,
        "retrieval": 0,
        "generation": 0,
        "response": 0,
        "stream": 0,
    }

    def classifier(_query: str) -> ClassificationResult:
        calls["classifier"] += 1
        return locked[0].classification

    def embedding(_query: str) -> tuple[float, ...]:
        calls["embedding"] += 1
        return (0.1,)

    def retrieval(_case: CalibrationCase) -> tuple[object, ...]:
        calls["retrieval"] += 1
        return ()

    def generation(_case: CalibrationCase) -> float:
        calls["generation"] += 1
        return 0.25

    def response(_case: CalibrationCase) -> None:
        calls["response"] += 1

    def stream(_case: CalibrationCase) -> tuple[str, ...]:
        calls["stream"] += 1
        return ("approved",)

    metrics = quality.measure_performance(
        cold_case=locked[0],
        warm_cases=locked[1:4],
        retrieval_cases=locked[3:6],
        generation_case=locked[2],
        classifier=classifier,
        embed_query=embedding,
        retrieve=retrieval,
        generate=generation,
        respond=response,
        stream=stream,
        clock=_IncrementingClock(),
    )

    assert metrics.classifier_cold_start_seconds == 1.0
    assert metrics.classifier_warm_latency_seconds == 1.0
    assert metrics.embedding_cold_start_seconds == 1.0
    assert metrics.retrieval_latency_seconds == 1.0
    assert metrics.generation_duration_seconds == 0.25
    assert metrics.total_cold_start_seconds == 17.0
    assert metrics.total_warm_response_seconds == 1.0
    assert metrics.buffered_streaming_duration_seconds == 1.0
    assert calls == {
        "classifier": 4,
        "embedding": 1,
        "retrieval": 3,
        "generation": 1,
        "response": 1,
        "stream": 1,
    }


def test_performance_metrics_reject_nonfinite_generation_duration() -> None:
    locked = _locked_cases()

    with pytest.raises(
        quality.QualityMeasurementError,
        match="generation duration",
    ):
        quality.measure_performance(
            cold_case=locked[0],
            warm_cases=locked[1:2],
            retrieval_cases=locked[2:3],
            generation_case=locked[2],
            classifier=lambda _query: locked[0].classification,
            embed_query=lambda _query: (0.1,),
            retrieve=lambda _case: (),
            generate=lambda _case: float("nan"),
            respond=lambda _case: None,
            stream=lambda _case: (),
            clock=_IncrementingClock(),
        )


def test_portfolio_goals_apply_only_documented_targets() -> None:
    routing = quality.evaluate_routing_quality(_locked_cases())
    safety = quality.evaluate_safety_quality(
        _locked_cases(),
        run_outcome=_answer_for,
        validator=_FakeValidator(),
    )
    goals = quality.evaluate_portfolio_goals(
        routing=routing,
        retrieval=_retrieval_metrics(),
        safety=safety,
    )

    assert len(goals) == 6
    assert all(goal.passed for goal in goals)
    assert {goal.name for goal in goals} == {
        "expected_policy_hit_rate",
        "unsupported_request_rejection",
        "required_security_action_coverage",
        "prohibited_claim_rate",
        "prompt_injection_policy_violation",
        "sensitive_data_request_rate",
    }


def test_quality_report_is_aggregate_and_goal_failure_is_recorded() -> None:
    locked = _locked_cases()
    routing = quality.evaluate_routing_quality(locked)
    safety = quality.evaluate_safety_quality(
        locked,
        run_outcome=_answer_for,
        validator=_FakeValidator(),
    )
    report = quality.build_quality_report(
        locked_cases=locked,
        routing=routing,
        retrieval=_retrieval_metrics(
            expected_policy_hit_rate=0.89,
        ),
        safety=safety,
        performance=_performance_metrics(),
    )
    payload = json.loads(quality.report_as_json(report))

    assert report.all_portfolio_goals_passed is False
    assert payload["locked_case_count"] == 36
    serialized = quality.report_as_json(report)
    assert locked[0].query not in serialized
    assert "final_answer" not in serialized
    assert any(
        goal["name"] == "expected_policy_hit_rate"
        and goal["passed"] is False
        for goal in payload["portfolio_goals"]
    )


def test_quality_report_rejects_threshold_drift() -> None:
    locked = _locked_cases()
    routing = quality.evaluate_routing_quality(locked)
    safety = quality.evaluate_safety_quality(
        locked,
        run_outcome=_answer_for,
        validator=_FakeValidator(),
    )

    with pytest.raises(
        quality.QualityMeasurementError,
        match="threshold",
    ):
        quality.build_quality_report(
            locked_cases=locked,
            routing=routing,
            retrieval=replace(
                _retrieval_metrics(),
                threshold=0.45,
            ),
            safety=safety,
            performance=_performance_metrics(),
        )


def test_main_returns_failure_without_exposing_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> quality.Phase2QualityReport:
        raise RuntimeError("private runtime detail")

    monkeypatch.setattr(quality, "run_live_quality_measurement", fail)

    assert quality.main() == 1
    captured = capsys.readouterr()
    assert "failed safely" in captured.err
    assert "private runtime detail" not in captured.err
