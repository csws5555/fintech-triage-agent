"""Read-only live retrieval checks for the active policy vector store.

Run from the backend directory:

    python scripts/test_retrieval.py

The command uses the active manifest, active Chroma collection, and approved
local Nomic model. It never rebuilds or modifies the store and never prints
policy bodies, embedding vectors, model digests, environment values, or local
paths.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SCRIPT_FILE = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ml.policy_registry import KNOWN_POLICY_IDS  # noqa: E402
from app.ml.rag_config import settings  # noqa: E402
from app.ml.retriever import get_retriever  # noqa: E402
from app.ml.triage_types import RetrievedPolicy  # noqa: E402


class LiveRetrievalTestError(RuntimeError):
    """Raised when a required live retrieval invariant fails."""


class Retriever(Protocol):
    """Minimal active-retriever interface used by the command."""

    def retrieve(
        self,
        *,
        query: str,
        allowed_policy_ids: tuple[str, ...],
        required_policy_ids: tuple[str, ...] = (),
    ) -> tuple[RetrievedPolicy, ...]: ...


@dataclass(frozen=True, slots=True)
class RetrievalProbe:
    """One safe live retrieval expectation."""

    probe_id: str
    query: str
    allowed_policy_ids: tuple[str, ...]
    required_policy_ids: tuple[str, ...]
    expected_policy_ids: tuple[str, ...]
    unsupported_probe: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalProbeResult:
    """Safe facts recorded for one completed probe."""

    probe_id: str
    query: str
    allowed_policy_ids: tuple[str, ...]
    required_policy_ids: tuple[str, ...]
    retrieved_policy_ids: tuple[str, ...]
    relevance_scores: tuple[float, ...]

    @property
    def best_score(self) -> float:
        """Return the highest accepted relevance score, or zero."""

        return max(self.relevance_scores, default=0.0)


@dataclass(frozen=True, slots=True)
class LiveRetrievalReport:
    """Complete safe result of the Step 31 retrieval checks."""

    probes: tuple[RetrievalProbeResult, ...]
    score_direction_passed: bool
    delivery_distinction_passed: bool


ALL_POLICY_IDS = tuple(sorted(KNOWN_POLICY_IDS))

RETRIEVAL_PROBES: tuple[RetrievalProbe, ...] = (
    RetrievalProbe(
        probe_id="initial_delivery",
        query="When should my newly ordered bank card arrive?",
        allowed_policy_ids=("card_delivery",),
        required_policy_ids=("card_delivery",),
        expected_policy_ids=("card_delivery",),
    ),
    RetrievalProbe(
        probe_id="replacement_delivery",
        query="My replacement card still has not arrived.",
        allowed_policy_ids=("card_replacement",),
        required_policy_ids=("card_replacement",),
        expected_policy_ids=("card_replacement",),
    ),
    RetrievalProbe(
        probe_id="stolen_card_required_families",
        query="My card was stolen in London.",
        allowed_policy_ids=("fraud_policy", "card_replacement"),
        required_policy_ids=("fraud_policy", "card_replacement"),
        expected_policy_ids=("fraud_policy", "card_replacement"),
    ),
    RetrievalProbe(
        probe_id="international_atm_fee",
        query="The foreign ATM added a fee.",
        allowed_policy_ids=("international_fees",),
        required_policy_ids=("international_fees",),
        expected_policy_ids=("international_fees",),
    ),
    RetrievalProbe(
        probe_id="unsupported_unrelated",
        query="How do I cook pasta?",
        allowed_policy_ids=ALL_POLICY_IDS,
        required_policy_ids=(),
        expected_policy_ids=(),
        unsupported_probe=True,
    ),
    RetrievalProbe(
        probe_id="delivery_scope_unrelated_query",
        query="How do I report an unrecognized cash withdrawal?",
        allowed_policy_ids=("card_delivery",),
        required_policy_ids=(),
        expected_policy_ids=("card_delivery",),
    ),
)


def run_live_retrieval_checks(
    retriever: Retriever | None = None,
) -> LiveRetrievalReport:
    """Run every Step 31 active-store retrieval invariant."""

    active_retriever = get_retriever() if retriever is None else retriever

    if not callable(getattr(active_retriever, "retrieve", None)):
        raise TypeError("retriever must provide retrieve().")

    results = tuple(
        _run_probe(active_retriever, probe)
        for probe in RETRIEVAL_PROBES
    )
    by_id = {result.probe_id: result for result in results}
    initial = by_id["initial_delivery"]
    replacement = by_id["replacement_delivery"]
    unrelated = by_id["delivery_scope_unrelated_query"]

    score_direction_passed = (
        initial.best_score > unrelated.best_score
    )

    if not score_direction_passed:
        raise LiveRetrievalTestError(
            "Relevant and unrelated retrieval score direction is invalid."
        )

    delivery_distinction_passed = (
        frozenset(initial.retrieved_policy_ids)
        == {"card_delivery"}
        and frozenset(replacement.retrieved_policy_ids)
        == {"card_replacement"}
        and frozenset(initial.retrieved_policy_ids)
        != frozenset(replacement.retrieved_policy_ids)
    )

    if not delivery_distinction_passed:
        raise LiveRetrievalTestError(
            "Initial and replacement delivery policy scope is not distinct."
        )

    return LiveRetrievalReport(
        probes=results,
        score_direction_passed=True,
        delivery_distinction_passed=True,
    )


def print_retrieval_report(report: LiveRetrievalReport) -> None:
    """Print safe retrieval facts without policy text or internal paths."""

    for result in report.probes:
        print(f"Probe: {result.probe_id}")
        print(f"Query: {result.query}")
        print(
            "Allowed policy IDs: "
            f"{_format_values(result.allowed_policy_ids)}"
        )
        print(
            "Required policy IDs: "
            f"{_format_values(result.required_policy_ids)}"
        )
        print(
            "Retrieved policy IDs: "
            f"{_format_values(result.retrieved_policy_ids)}"
        )
        print(
            "Accepted relevance scores: "
            f"{_format_scores(result.relevance_scores)}"
        )

    print("PASS expected policies appeared")
    print("PASS metadata filters contained every result")
    print("PASS required policy families were represented")
    print("PASS unsupported probe remained below threshold")
    print("PASS score direction was correct")
    print("PASS initial and replacement delivery were distinct")


def main() -> int:
    """Run the read-only live retrieval command."""

    try:
        report = run_live_retrieval_checks()
    except LiveRetrievalTestError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "FAIL: live retrieval checks failed safely.",
            file=sys.stderr,
        )
        return 1

    print_retrieval_report(report)
    return 0


def _run_probe(
    retriever: Retriever,
    probe: RetrievalProbe,
) -> RetrievalProbeResult:
    try:
        raw_policies = retriever.retrieve(
            query=probe.query,
            allowed_policy_ids=probe.allowed_policy_ids,
            required_policy_ids=probe.required_policy_ids,
        )
    except Exception as exc:
        raise LiveRetrievalTestError(
            f"{probe.probe_id}: retrieval failed safely."
        ) from exc

    if (
        not isinstance(raw_policies, Sequence)
        or isinstance(raw_policies, (str, bytes))
        or any(
            not isinstance(policy, RetrievedPolicy)
            for policy in raw_policies
        )
    ):
        raise LiveRetrievalTestError(
            f"{probe.probe_id}: retrieval returned malformed context."
        )

    policies = tuple(raw_policies)
    allowed = frozenset(probe.allowed_policy_ids)

    if (
        len(policies) > settings.max_context_chunks
        or len({policy.chunk_id for policy in policies})
        != len(policies)
        or any(
            policy.document_id not in allowed
            or policy.status != "approved"
            or policy.relevance_score
            < settings.min_relevance_score
            for policy in policies
        )
    ):
        raise LiveRetrievalTestError(
            f"{probe.probe_id}: retrieval filtering invariants failed."
        )

    retrieved_ids = tuple(
        dict.fromkeys(policy.document_id for policy in policies)
    )
    retrieved_set = frozenset(retrieved_ids)

    if probe.unsupported_probe:
        if policies:
            raise LiveRetrievalTestError(
                f"{probe.probe_id}: unsupported probe passed the threshold."
            )
    elif not frozenset(probe.expected_policy_ids) <= retrieved_set:
        raise LiveRetrievalTestError(
            f"{probe.probe_id}: an expected policy was not retrieved."
        )

    if not frozenset(probe.required_policy_ids) <= retrieved_set:
        raise LiveRetrievalTestError(
            f"{probe.probe_id}: a required policy family is missing."
        )

    return RetrievalProbeResult(
        probe_id=probe.probe_id,
        query=probe.query,
        allowed_policy_ids=probe.allowed_policy_ids,
        required_policy_ids=probe.required_policy_ids,
        retrieved_policy_ids=retrieved_ids,
        relevance_scores=tuple(
            policy.relevance_score for policy in policies
        ),
    )


def _format_values(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "None"


def _format_scores(values: tuple[float, ...]) -> str:
    if not values:
        return "None"
    return ", ".join(f"{value:.4f}" for value in values)


if __name__ == "__main__":
    raise SystemExit(main())
