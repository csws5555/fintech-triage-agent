"""Calibrate policy retrieval without mutating the active Chroma store."""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import ValidationError

SCRIPT_FILE = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ml.policy_registry import KNOWN_POLICY_IDS  # noqa: E402
from app.ml.rag_config import settings  # noqa: E402
from app.ml.retriever import PolicyRetriever, get_retriever  # noqa: E402
from app.ml.risk_router import RiskRouter, risk_router  # noqa: E402
from app.ml.triage_types import (  # noqa: E402
    ClassificationResult,
    IntentPrediction,
    ResponseMode,
    RetrievedPolicy,
    TriageDecision,
)


CALIBRATION_SCHEMA_VERSION = 2
MIN_EVALUATION_CASES = 40
MAX_EVALUATION_CASES = 50
CALIBRATION_THRESHOLDS = (
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
    0.45,
    0.50,
)
EVALUATION_CATEGORIES = frozenset(
    {
        "security_stolen_card",
        "security_lost_card",
        "security_compromised_card",
        "security_unauthorized_payment",
        "security_unauthorized_withdrawal",
        "security_account_takeover",
        "security_stolen_card_with_unauthorized_withdrawals",
        "security_stolen_card_without_app_access",
        "security_hypothetical_stolen_card",
        "security_negated_stolen_card",
        "fees_foreign_atm",
        "fees_card_purchase",
        "fees_ambiguous_abroad",
        "fees_international_transfer",
        "fees_dynamic_currency_conversion",
        "fees_unknown_transaction_type",
        "fees_duplicate_international_charge",
        "card_first_delivery_missing",
        "card_replacement_delivery_missing",
        "card_damaged",
        "card_atm_retained",
        "card_replacement_abroad",
        "card_order_request",
        "card_freeze_status_request",
        "unsupported_mortgage_rate",
        "unsupported_investment_advice",
        "unsupported_cryptocurrency_account",
        "unsupported_loan_approval",
        "unsupported_virtual_card",
        "clarification_forgotten_pin",
        "unsupported_unrelated_non_banking",
        "adversarial_reveal_system_prompt",
        "adversarial_ignore_policy",
        "adversarial_guarantee_refund",
        "adversarial_print_all_policies",
        "adversarial_claim_card_frozen",
        "adversarial_request_otp",
        "adversarial_fake_policy_instructions",
        "adversarial_output_schema_override",
        "regression_duplicate_domestic_charge",
        "unsupported_savings_interest",
    }
)
ROUTER_CATEGORIES = frozenset(
    {
        "supported_intent",
        "unsupported_intent",
        "security_override",
        "delivery_distinction",
        "fee_clarification",
    }
)
RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
ACTIONS = frozenset(
    {
        "generate",
        "clarify",
        "urgent_guidance",
        "human_escalation",
        "static_response",
        "unsupported",
    }
)
Split = Literal["calibration", "evaluation"]


class CalibrationError(RuntimeError):
    """Raised when calibration cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ExpectedRoute:
    risk_level: str
    action: str
    allowed_policy_ids: tuple[str, ...]
    required_policy_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievalExpectation:
    attempt: bool
    allowed_policy_ids: tuple[str, ...]
    required_policy_ids: tuple[str, ...]
    expected_policy_ids: tuple[str, ...]
    unsupported_probe: bool


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    case_id: str
    split: Split
    query: str
    classification: ClassificationResult
    router_categories: tuple[str, ...]
    evaluation_categories: tuple[str, ...]
    expected_route: ExpectedRoute
    expected_response_mode: ResponseMode
    required_concepts: tuple[str, ...]
    prohibited_concepts: tuple[str, ...]
    requires_human: bool
    should_call_llm: bool
    retrieval: RetrievalExpectation


@dataclass(frozen=True, slots=True)
class RouterMetrics:
    case_count: int
    overall_accuracy: float
    supported_intent_routing_accuracy: float
    unsupported_intent_rejection_rate: float
    security_override_accuracy: float
    delivery_distinction_accuracy: float
    fee_clarification_accuracy: float


@dataclass(frozen=True, slots=True)
class RetrieverMetrics:
    threshold: float
    attempted_case_count: int
    expected_policy_hit_rate: float
    recall_at_4: float
    false_positive_policy_rate: float
    unsupported_query_retrieval_acceptance_rate: float
    false_fallback_rate: float
    average_accepted_chunk_count: float
    required_policy_family_coverage: float


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    selected_threshold: float
    calibration_router: RouterMetrics
    evaluation_router: RouterMetrics
    calibration_thresholds: tuple[RetrieverMetrics, ...]
    locked_evaluation: RetrieverMetrics


class Router(Protocol):
    def route_message(
        self,
        message: str,
        classification: ClassificationResult,
    ) -> TriageDecision: ...


RetrievalRunner = Callable[
    [CalibrationCase, float],
    Sequence[RetrievedPolicy],
]


def load_calibration_cases(
    path: Path = settings.evaluation_cases_path,
) -> tuple[CalibrationCase, ...]:
    """Load and strictly validate the split Step 20 dataset."""

    if (
        not isinstance(path, Path)
        or not path.exists()
        or not path.is_file()
        or path.is_symlink()
    ):
        raise CalibrationError(
            "Calibration dataset is unavailable or unsafe."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationError(
            "Calibration dataset could not be decoded."
        ) from exc

    root = _require_mapping(payload, "dataset")
    _require_exact_keys(
        root,
        {"schema_version", "thresholds", "cases"},
        "dataset",
    )

    if root["schema_version"] != CALIBRATION_SCHEMA_VERSION:
        raise CalibrationError(
            "Calibration dataset schema version is unsupported."
        )

    thresholds = _float_tuple(root["thresholds"], "thresholds")

    if thresholds != CALIBRATION_THRESHOLDS:
        raise CalibrationError(
            "Calibration dataset must use the approved thresholds."
        )

    raw_cases = root["cases"]

    if not isinstance(raw_cases, list) or not raw_cases:
        raise CalibrationError(
            "Calibration dataset must contain cases."
        )

    cases = tuple(
        _parse_case(item)
        for item in raw_cases
    )
    case_ids = tuple(case.case_id for case in cases)

    if len(set(case_ids)) != len(case_ids):
        raise CalibrationError(
            "Calibration case IDs must be unique."
        )

    for split in ("calibration", "evaluation"):
        split_cases = tuple(
            case for case in cases if case.split == split
        )

        if not split_cases:
            raise CalibrationError(
                "Both calibration and evaluation splits are required."
            )

        covered = frozenset(
            category
            for case in split_cases
            for category in case.router_categories
        )

        if covered != ROUTER_CATEGORIES:
            raise CalibrationError(
                "Each split must cover every router metric category."
            )

        retrieval_cases = tuple(
            case
            for case in split_cases
            if case.retrieval.attempt
        )

        if not any(
            case.retrieval.unsupported_probe
            for case in retrieval_cases
        ) or not any(
            case.retrieval.expected_policy_ids
            for case in retrieval_cases
        ):
            raise CalibrationError(
                "Each split needs supported and unsupported retrieval cases."
            )

    covered_evaluation_categories = frozenset(
        category
        for case in cases
        for category in case.evaluation_categories
    )

    if covered_evaluation_categories != EVALUATION_CATEGORIES:
        raise CalibrationError(
            "Dataset must cover every Step 29 evaluation category."
        )

    if not MIN_EVALUATION_CASES <= len(cases) <= MAX_EVALUATION_CASES:
        raise CalibrationError(
            "Step 29 dataset must contain 40 to 50 cases."
        )

    return cases


def evaluate_router(
    cases: Sequence[CalibrationCase],
    *,
    router: Router = risk_router,
) -> RouterMetrics:
    """Measure deterministic routing independently from retrieval."""

    if not cases:
        raise CalibrationError("Router evaluation requires cases.")

    passes: dict[str, list[bool]] = {
        category: []
        for category in ROUTER_CATEGORIES
    }
    overall: list[bool] = []

    for case in cases:
        try:
            decision = router.route_message(
                case.query,
                case.classification,
            )
        except Exception as exc:
            raise CalibrationError(
                "Router evaluation failed safely."
            ) from exc

        matched = _route_matches(decision, case.expected_route)
        overall.append(matched)

        for category in case.router_categories:
            passes[category].append(matched)

    return RouterMetrics(
        case_count=len(cases),
        overall_accuracy=_rate(overall),
        supported_intent_routing_accuracy=_rate(
            passes["supported_intent"]
        ),
        unsupported_intent_rejection_rate=_rate(
            passes["unsupported_intent"]
        ),
        security_override_accuracy=_rate(
            passes["security_override"]
        ),
        delivery_distinction_accuracy=_rate(
            passes["delivery_distinction"]
        ),
        fee_clarification_accuracy=_rate(
            passes["fee_clarification"]
        ),
    )


def evaluate_retriever(
    cases: Sequence[CalibrationCase],
    *,
    threshold: float,
    retrieve: RetrievalRunner,
) -> RetrieverMetrics:
    """Measure Step 20 retrieval metrics at one threshold."""

    _validate_threshold(threshold)
    attempted = tuple(
        case
        for case in cases
        if case.retrieval.attempt
    )

    if not attempted:
        raise CalibrationError(
            "Retriever evaluation requires attempted cases."
        )

    expected_case_hits = 0
    expected_policy_hits = 0
    expected_policy_total = 0
    supported_chunk_count = 0
    false_positive_chunk_count = 0
    unsupported_case_count = 0
    unsupported_accepted_count = 0
    supported_case_count = 0
    false_fallback_count = 0
    required_hits = 0
    required_total = 0
    accepted_chunk_total = 0

    for case in attempted:
        try:
            policies = tuple(retrieve(case, threshold))
        except Exception as exc:
            raise CalibrationError(
                "Retriever evaluation failed safely."
            ) from exc

        if (
            len(policies) > settings.max_context_chunks
            or any(
                not isinstance(policy, RetrievedPolicy)
                for policy in policies
            )
        ):
            raise CalibrationError(
                "Retriever evaluation returned invalid context."
            )

        allowed = frozenset(
            case.retrieval.allowed_policy_ids
        )

        if any(
            policy.document_id not in allowed
            or policy.status != "approved"
            or policy.relevance_score < threshold
            for policy in policies
        ):
            raise CalibrationError(
                "Retriever evaluation violated filtering invariants."
            )

        accepted_chunk_total += len(policies)
        retrieved_ids = frozenset(
            policy.document_id
            for policy in policies
        )
        expected = frozenset(
            case.retrieval.expected_policy_ids
        )
        required = frozenset(
            case.retrieval.required_policy_ids
        )

        if case.retrieval.unsupported_probe:
            unsupported_case_count += 1
            unsupported_accepted_count += bool(policies)
            continue

        supported_case_count += 1
        hits = expected & retrieved_ids
        expected_policy_hits += len(hits)
        expected_policy_total += len(expected)
        expected_case_hits += bool(expected) and expected <= retrieved_ids
        false_fallback_count += bool(expected) and not expected <= retrieved_ids
        required_hits += len(required & retrieved_ids)
        required_total += len(required)

        for policy in policies:
            supported_chunk_count += 1
            false_positive_chunk_count += (
                policy.document_id not in expected
            )

    return RetrieverMetrics(
        threshold=float(threshold),
        attempted_case_count=len(attempted),
        expected_policy_hit_rate=_ratio(
            expected_case_hits,
            supported_case_count,
        ),
        recall_at_4=_ratio(
            expected_policy_hits,
            expected_policy_total,
        ),
        false_positive_policy_rate=_ratio(
            false_positive_chunk_count,
            supported_chunk_count,
        ),
        unsupported_query_retrieval_acceptance_rate=_ratio(
            unsupported_accepted_count,
            unsupported_case_count,
        ),
        false_fallback_rate=_ratio(
            false_fallback_count,
            supported_case_count,
        ),
        average_accepted_chunk_count=_ratio(
            accepted_chunk_total,
            len(attempted),
        ),
        required_policy_family_coverage=_ratio(
            required_hits,
            required_total,
        ),
    )


def select_threshold(
    metrics: Sequence[RetrieverMetrics],
) -> RetrieverMetrics:
    """Choose one threshold using calibration metrics only."""

    if (
        tuple(item.threshold for item in metrics)
        != CALIBRATION_THRESHOLDS
    ):
        raise CalibrationError(
            "Threshold selection requires all approved thresholds in order."
        )

    return max(metrics, key=_selection_key)


def build_calibration_report(
    cases: Sequence[CalibrationCase],
    *,
    retrieve: RetrievalRunner,
    router: Router = risk_router,
) -> CalibrationReport:
    """Select on calibration data, then evaluate the locked split once."""

    calibration_cases = tuple(
        case for case in cases if case.split == "calibration"
    )
    evaluation_cases = tuple(
        case for case in cases if case.split == "evaluation"
    )

    if not calibration_cases or not evaluation_cases:
        raise CalibrationError(
            "Calibration and evaluation splits are both required."
        )

    calibration_metrics = tuple(
        evaluate_retriever(
            calibration_cases,
            threshold=threshold,
            retrieve=retrieve,
        )
        for threshold in CALIBRATION_THRESHOLDS
    )
    selected = select_threshold(calibration_metrics)

    return CalibrationReport(
        selected_threshold=selected.threshold,
        calibration_router=evaluate_router(
            calibration_cases,
            router=router,
        ),
        evaluation_router=evaluate_router(
            evaluation_cases,
            router=router,
        ),
        calibration_thresholds=calibration_metrics,
        locked_evaluation=evaluate_retriever(
            evaluation_cases,
            threshold=selected.threshold,
            retrieve=retrieve,
        ),
    )


def make_live_retrieval_runner(
    retriever: PolicyRetriever,
) -> RetrievalRunner:
    """Bind calibration cases to the validated active retriever."""

    if not isinstance(retriever, PolicyRetriever):
        raise TypeError("retriever must be a PolicyRetriever.")

    def retrieve(
        case: CalibrationCase,
        threshold: float,
    ) -> Sequence[RetrievedPolicy]:
        return retriever.retrieve(
            query=case.query,
            allowed_policy_ids=(
                case.retrieval.allowed_policy_ids
            ),
            required_policy_ids=(
                case.retrieval.required_policy_ids
            ),
            min_relevance_score=threshold,
        )

    return retrieve


def report_as_json(report: CalibrationReport) -> str:
    """Serialize aggregate calibration results without query content."""

    return json.dumps(
        asdict(report),
        indent=2,
        sort_keys=True,
    )


def main() -> int:
    """Run read-only calibration against the active local retriever."""

    try:
        cases = load_calibration_cases()
        report = build_calibration_report(
            cases,
            retrieve=make_live_retrieval_runner(
                get_retriever()
            ),
        )
    except Exception:
        print("FAIL: retrieval calibration failed safely.")
        return 1

    print(report_as_json(report))
    print(
        "PASS: selected retrieval threshold "
        f"{report.selected_threshold:.2f} using calibration cases "
        "and evaluated it once on the locked split."
    )
    return 0


def _parse_case(value: object) -> CalibrationCase:
    item = _require_mapping(value, "case")
    _require_exact_keys(
        item,
        {
            "id",
            "split",
            "query",
            "predictions",
            "uncertain",
            "top_two_margin",
            "router_categories",
            "evaluation_categories",
            "expected_route",
            "expected_response_mode",
            "required_concepts",
            "prohibited_concepts",
            "requires_human",
            "should_call_llm",
            "retrieval",
        },
        "case",
    )
    case_id = _nonblank_string(item["id"], "case.id")

    if re.fullmatch(r"RAG-(?:CAL|EVAL)-\d{3}", case_id) is None:
        raise CalibrationError(
            "Calibration case ID is invalid."
        )

    split = item["split"]

    if split not in {"calibration", "evaluation"}:
        raise CalibrationError(
            "Calibration case split is invalid."
        )

    expected_id_prefix = (
        "RAG-CAL-"
        if split == "calibration"
        else "RAG-EVAL-"
    )

    if not case_id.startswith(expected_id_prefix):
        raise CalibrationError(
            "Calibration case ID does not match its split."
        )

    query = _nonblank_string(item["query"], "case.query")
    raw_predictions = item["predictions"]

    if (
        not isinstance(raw_predictions, list)
        or len(raw_predictions) != 3
    ):
        raise CalibrationError(
            "Calibration cases require exactly three predictions."
        )

    predictions: list[IntentPrediction] = []

    for raw_prediction in raw_predictions:
        prediction = _require_mapping(
            raw_prediction,
            "prediction",
        )
        _require_exact_keys(
            prediction,
            {"label", "confidence"},
            "prediction",
        )
        try:
            predictions.append(
                IntentPrediction(
                    label=_nonblank_string(
                        prediction["label"],
                        "prediction.label",
                    ),
                    confidence=_finite_float(
                        prediction["confidence"],
                        "prediction.confidence",
                    ),
                )
            )
        except ValidationError as exc:
            raise CalibrationError(
                "Calibration prediction is invalid."
            ) from exc

    confidences = tuple(
        prediction.confidence
        for prediction in predictions
    )

    if (
        len({prediction.label for prediction in predictions}) != 3
        or tuple(sorted(confidences, reverse=True)) != confidences
    ):
        raise CalibrationError(
            "Calibration predictions must be unique and ranked."
        )

    uncertain = item["uncertain"]

    if not isinstance(uncertain, bool):
        raise CalibrationError(
            "Calibration uncertainty must be boolean."
        )

    margin = _finite_float(
        item["top_two_margin"],
        "case.top_two_margin",
    )
    expected_margin = confidences[0] - confidences[1]

    if (
        not 0.0 <= margin <= 1.0
        or not math.isclose(
            margin,
            expected_margin,
            abs_tol=1e-6,
        )
    ):
        raise CalibrationError(
            "Calibration top-two margin is inconsistent."
        )

    try:
        classification = ClassificationResult(
            predictions=tuple(predictions),
            uncertain=uncertain,
            top_two_margin=margin,
        )
    except ValidationError as exc:
        raise CalibrationError(
            "Calibration classification is invalid."
        ) from exc

    categories = _string_tuple(
        item["router_categories"],
        "case.router_categories",
    )

    if (
        not categories
        or len(set(categories)) != len(categories)
        or not set(categories) <= ROUTER_CATEGORIES
    ):
        raise CalibrationError(
            "Calibration router categories are invalid."
        )

    evaluation_categories = _string_tuple(
        item["evaluation_categories"],
        "case.evaluation_categories",
    )

    if (
        not evaluation_categories
        or len(set(evaluation_categories))
        != len(evaluation_categories)
        or not set(evaluation_categories)
        <= EVALUATION_CATEGORIES
    ):
        raise CalibrationError(
            "Case evaluation categories are invalid."
        )

    expected_route = _parse_expected_route(
        item["expected_route"]
    )
    expected_response_mode = _nonblank_string(
        item["expected_response_mode"],
        "case.expected_response_mode",
    )

    if expected_response_mode not in {
        "static_fallback",
        "deterministic_clarification",
        "deterministic_safety",
        "grounded_generation",
    }:
        raise CalibrationError(
            "Expected response mode is invalid."
        )

    required_concepts = _concepts(
        item["required_concepts"],
        "case.required_concepts",
    )
    prohibited_concepts = _concepts(
        item["prohibited_concepts"],
        "case.prohibited_concepts",
    )

    if {
        concept.casefold()
        for concept in required_concepts
    } & {
        concept.casefold()
        for concept in prohibited_concepts
    }:
        raise CalibrationError(
            "Required and prohibited concepts must not overlap."
        )

    requires_human = item["requires_human"]
    should_call_llm = item["should_call_llm"]

    if not isinstance(requires_human, bool) or not isinstance(
        should_call_llm,
        bool,
    ):
        raise CalibrationError(
            "Expected pipeline flags must be boolean."
        )

    _validate_pipeline_expectations(
        expected_route=expected_route,
        expected_response_mode=expected_response_mode,
        requires_human=requires_human,
        should_call_llm=should_call_llm,
    )
    retrieval = _parse_retrieval(item["retrieval"])

    return CalibrationCase(
        case_id=case_id,
        split=split,
        query=query,
        classification=classification,
        router_categories=categories,
        evaluation_categories=evaluation_categories,
        expected_route=expected_route,
        expected_response_mode=expected_response_mode,
        required_concepts=required_concepts,
        prohibited_concepts=prohibited_concepts,
        requires_human=requires_human,
        should_call_llm=should_call_llm,
        retrieval=retrieval,
    )


def _validate_pipeline_expectations(
    *,
    expected_route: ExpectedRoute,
    expected_response_mode: str,
    requires_human: bool,
    should_call_llm: bool,
) -> None:
    expected_mode_by_action = {
        "generate": "grounded_generation",
        "clarify": "deterministic_clarification",
        "urgent_guidance": "deterministic_safety",
        "human_escalation": "deterministic_safety",
        "static_response": "deterministic_safety",
        "unsupported": "static_fallback",
    }

    if (
        expected_response_mode
        != expected_mode_by_action[expected_route.action]
    ):
        raise CalibrationError(
            "Expected response mode is inconsistent with routing."
        )

    if should_call_llm != (expected_route.action == "generate"):
        raise CalibrationError(
            "Expected LLM usage is inconsistent with routing."
        )

    if expected_route.action in {
        "human_escalation",
        "unsupported",
    } and not requires_human:
        raise CalibrationError(
            "Expected human support is inconsistent with routing."
        )


def _parse_expected_route(value: object) -> ExpectedRoute:
    item = _require_mapping(value, "expected_route")
    _require_exact_keys(
        item,
        {
            "risk_level",
            "action",
            "allowed_policy_ids",
            "required_policy_ids",
        },
        "expected_route",
    )
    risk_level = _nonblank_string(
        item["risk_level"],
        "expected_route.risk_level",
    )
    action = _nonblank_string(
        item["action"],
        "expected_route.action",
    )

    if risk_level not in RISK_LEVELS or action not in ACTIONS:
        raise CalibrationError(
            "Expected routing outcome is invalid."
        )

    allowed = _policy_ids(
        item["allowed_policy_ids"],
        "expected_route.allowed_policy_ids",
        allow_empty=True,
    )
    required = _policy_ids(
        item["required_policy_ids"],
        "expected_route.required_policy_ids",
        allow_empty=True,
    )

    if not set(required) <= set(allowed):
        raise CalibrationError(
            "Expected required policies must be allowed."
        )

    return ExpectedRoute(
        risk_level=risk_level,
        action=action,
        allowed_policy_ids=allowed,
        required_policy_ids=required,
    )


def _parse_retrieval(value: object) -> RetrievalExpectation:
    item = _require_mapping(value, "retrieval")
    _require_exact_keys(
        item,
        {
            "attempt",
            "allowed_policy_ids",
            "required_policy_ids",
            "expected_policy_ids",
            "unsupported_probe",
        },
        "retrieval",
    )
    attempt = item["attempt"]
    unsupported_probe = item["unsupported_probe"]

    if not isinstance(attempt, bool) or not isinstance(
        unsupported_probe,
        bool,
    ):
        raise CalibrationError(
            "Retrieval flags must be boolean."
        )

    allowed = _policy_ids(
        item["allowed_policy_ids"],
        "retrieval.allowed_policy_ids",
        allow_empty=not attempt,
    )
    required = _policy_ids(
        item["required_policy_ids"],
        "retrieval.required_policy_ids",
        allow_empty=True,
    )
    expected = _policy_ids(
        item["expected_policy_ids"],
        "retrieval.expected_policy_ids",
        allow_empty=True,
    )

    if not attempt and (
        allowed or required or expected or unsupported_probe
    ):
        raise CalibrationError(
            "Non-attempted retrieval cases must have empty scope."
        )

    if (
        not set(required) <= set(allowed)
        or not set(expected) <= set(allowed)
    ):
        raise CalibrationError(
            "Retrieval expectations must remain in allowed scope."
        )

    if unsupported_probe:
        if required or expected:
            raise CalibrationError(
                "Unsupported probes cannot expect policy context."
            )
    elif attempt and not expected:
        raise CalibrationError(
            "Supported retrieval cases need expected policies."
        )

    return RetrievalExpectation(
        attempt=attempt,
        allowed_policy_ids=allowed,
        required_policy_ids=required,
        expected_policy_ids=expected,
        unsupported_probe=unsupported_probe,
    )


def _route_matches(
    decision: TriageDecision,
    expected: ExpectedRoute,
) -> bool:
    return (
        decision.risk_level == expected.risk_level
        and decision.action == expected.action
        and frozenset(decision.allowed_policy_ids)
        == frozenset(expected.allowed_policy_ids)
        and frozenset(decision.required_policy_ids)
        == frozenset(expected.required_policy_ids)
    )


def _selection_key(
    item: RetrieverMetrics,
) -> tuple[float, float, float, float, float, float, float]:
    balanced_acceptance = (
        item.expected_policy_hit_rate
        + 1.0
        - item.unsupported_query_retrieval_acceptance_rate
    ) / 2.0
    return (
        balanced_acceptance,
        item.required_policy_family_coverage,
        item.recall_at_4,
        1.0 - item.false_fallback_rate,
        1.0 - item.false_positive_policy_rate,
        -item.average_accepted_chunk_count,
        item.threshold,
    )


def _validate_threshold(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) not in CALIBRATION_THRESHOLDS
    ):
        raise CalibrationError(
            "Retriever threshold is not approved for calibration."
        )


def _rate(values: Sequence[bool]) -> float:
    if not values:
        raise CalibrationError(
            "A required metric category has no cases."
        )
    return _ratio(sum(values), len(values))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _require_mapping(
    value: object,
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CalibrationError(f"{name} must be an object.")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    name: str,
) -> None:
    if set(value) != expected:
        raise CalibrationError(
            f"{name} contains missing or unknown fields."
        )


def _nonblank_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CalibrationError(f"{name} must be a nonblank string.")
    return value.strip()


def _finite_float(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise CalibrationError(f"{name} must be a finite number.")
    return float(value)


def _float_tuple(value: object, name: str) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise CalibrationError(f"{name} must be a list.")
    return tuple(_finite_float(item, name) for item in value)


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CalibrationError(f"{name} must be a list.")
    return tuple(_nonblank_string(item, name) for item in value)


def _concepts(value: object, name: str) -> tuple[str, ...]:
    concepts = _string_tuple(value, name)
    normalized = tuple(concept.casefold() for concept in concepts)

    if not concepts or len(set(normalized)) != len(normalized):
        raise CalibrationError(
            f"{name} must contain unique concepts."
        )

    return concepts


def _policy_ids(
    value: object,
    name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    policy_ids = _string_tuple(value, name)

    if (
        (not allow_empty and not policy_ids)
        or len(set(policy_ids)) != len(policy_ids)
        or not set(policy_ids) <= set(KNOWN_POLICY_IDS)
    ):
        raise CalibrationError(f"{name} contains invalid policy IDs.")

    return policy_ids


if __name__ == "__main__":
    raise SystemExit(main())
