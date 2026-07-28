from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.ml.rag_config import settings
from app.ml.triage_types import RetrievedPolicy
from scripts.calibrate_retrieval import (
    CALIBRATION_THRESHOLDS,
    CalibrationError,
    RetrieverMetrics,
    build_calibration_report,
    evaluate_retriever,
    evaluate_router,
    load_calibration_cases,
    report_as_json,
    select_threshold,
)


def policy(
    document_id: str,
    *,
    score: float,
    suffix: str = "one",
) -> RetrievedPolicy:
    return RetrievedPolicy(
        chunk_id=f"{document_id}-{suffix}",
        document_id=document_id,
        content=f"Approved {document_id} content {suffix}.",
        source_file=f"{document_id}.md",
        title="Approved Policy",
        section_path=f"Approved Policy > {suffix}",
        version="1.0",
        effective_date="2026-07-01",
        review_date="2026-10-01",
        status="approved",
        chunk_index=0,
        content_hash=f"hash-{document_id}-{suffix}",
        relevance_score=score,
    )


def test_project_dataset_is_strictly_valid_and_split() -> None:
    cases = load_calibration_cases()

    assert len(cases) == 20
    assert sum(
        case.split == "calibration"
        for case in cases
    ) == 10
    assert sum(
        case.split == "evaluation"
        for case in cases
    ) == 10


def test_project_dataset_router_expectations_match_router() -> None:
    cases = load_calibration_cases()
    calibration = tuple(
        case for case in cases if case.split == "calibration"
    )
    evaluation = tuple(
        case for case in cases if case.split == "evaluation"
    )

    assert evaluate_router(calibration).overall_accuracy == 1.0
    assert evaluate_router(evaluation).overall_accuracy == 1.0


def test_dataset_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    payload = json.loads(
        settings.evaluation_cases_path.read_text(
            encoding="utf-8"
        )
    )
    payload["unexpected"] = True
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(CalibrationError, match="unknown"):
        load_calibration_cases(path)


def test_dataset_rejects_missing_locked_split(
    tmp_path: Path,
) -> None:
    payload = json.loads(
        settings.evaluation_cases_path.read_text(
            encoding="utf-8"
        )
    )
    payload["cases"] = [
        case
        for case in payload["cases"]
        if case["split"] == "calibration"
    ]
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(
        CalibrationError,
        match="Both calibration and evaluation",
    ):
        load_calibration_cases(path)


def test_retriever_metrics_cover_supported_and_unsupported() -> None:
    cases = load_calibration_cases()
    calibration = tuple(
        case for case in cases if case.split == "calibration"
    )

    def retrieve(case, threshold):
        if case.retrieval.unsupported_probe:
            return (
                (policy("fraud_policy", score=threshold),)
                if threshold <= 0.30
                else ()
            )
        return tuple(
            policy(
                document_id,
                score=threshold,
                suffix=str(index),
            )
            for index, document_id in enumerate(
                case.retrieval.expected_policy_ids
            )
        )

    metrics = evaluate_retriever(
        calibration,
        threshold=0.35,
        retrieve=retrieve,
    )

    assert metrics.expected_policy_hit_rate == 1.0
    assert metrics.recall_at_4 == 1.0
    assert metrics.false_positive_policy_rate == 0.0
    assert (
        metrics.unsupported_query_retrieval_acceptance_rate
        == 0.0
    )
    assert metrics.false_fallback_rate == 0.0
    assert metrics.required_policy_family_coverage == 1.0
    assert metrics.average_accepted_chunk_count > 0.0


def test_retriever_metrics_fail_closed_on_scope_violation() -> None:
    case = next(
        case
        for case in load_calibration_cases()
        if (
            case.split == "calibration"
            and case.retrieval.attempt
            and not case.retrieval.unsupported_probe
            and "fraud_policy"
            not in case.retrieval.allowed_policy_ids
        )
    )

    with pytest.raises(
        CalibrationError,
        match="filtering invariants",
    ):
        evaluate_retriever(
            (case,),
            threshold=0.35,
            retrieve=lambda _case, threshold: (
                policy("fraud_policy", score=threshold),
            ),
        )


def test_selection_uses_all_thresholds_and_is_deterministic() -> None:
    baseline = RetrieverMetrics(
        threshold=0.20,
        attempted_case_count=4,
        expected_policy_hit_rate=1.0,
        recall_at_4=1.0,
        false_positive_policy_rate=0.0,
        unsupported_query_retrieval_acceptance_rate=0.5,
        false_fallback_rate=0.0,
        average_accepted_chunk_count=2.0,
        required_policy_family_coverage=1.0,
    )
    metrics = tuple(
        replace(
            baseline,
            threshold=threshold,
            unsupported_query_retrieval_acceptance_rate=(
                0.0 if threshold >= 0.40 else 0.5
            ),
            average_accepted_chunk_count=(
                1.0 if threshold >= 0.45 else 2.0
            ),
        )
        for threshold in CALIBRATION_THRESHOLDS
    )

    assert select_threshold(metrics).threshold == 0.50


def test_locked_evaluation_is_run_only_at_selected_threshold() -> None:
    cases = load_calibration_cases()
    calls: list[tuple[str, float]] = []

    def retrieve(case, threshold):
        calls.append((case.split, threshold))

        if case.retrieval.unsupported_probe:
            return ()

        return tuple(
            policy(
                document_id,
                score=threshold,
                suffix=str(index),
            )
            for index, document_id in enumerate(
                case.retrieval.expected_policy_ids
            )
        )

    report = build_calibration_report(
        cases,
        retrieve=retrieve,
    )
    evaluation_thresholds = {
        threshold
        for split, threshold in calls
        if split == "evaluation"
    }

    assert evaluation_thresholds == {
        report.selected_threshold
    }
    assert len(report.calibration_thresholds) == 7
    assert (
        report.locked_evaluation.threshold
        == report.selected_threshold
    )
    serialized = report_as_json(report)
    assert cases[0].case_id not in serialized
    assert cases[0].query not in serialized
