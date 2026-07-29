from __future__ import annotations

from dataclasses import replace

import pytest

from app.ml import retriever as retriever_module
from app.ml.ingest_policies import (
    CHUNKING_STRATEGY,
    INGESTION_MANIFEST_SCHEMA_VERSION,
    STABLE_ID_STRATEGY,
    IngestionManifest,
    VectorStoreRebuildError,
)
from app.ml.rag_config import settings
from app.ml.retriever import (
    PolicyRetrievalError,
    filter_retrieval_candidates,
    normalized_token_overlap_ratio,
    retrieval_is_sufficient,
)
from app.ml.triage_types import RetrievedPolicy, TriageDecision


def policy(
    chunk_id: str,
    *,
    document_id: str = "fraud_policy",
    content: str | None = None,
    content_hash: str | None = None,
    section_path: str = "Fraud Policy > Reporting",
    chunk_index: int = 0,
    relevance_score: float = 0.8,
) -> RetrievedPolicy:
    resolved_content = content or f"Approved policy content for {chunk_id}."
    return RetrievedPolicy(
        chunk_id=chunk_id,
        document_id=document_id,
        content=resolved_content,
        source_file=f"{document_id}.md",
        title=f"{document_id} title",
        section_path=section_path,
        version="1.0",
        effective_date="2026-07-01",
        review_date="2026-10-01",
        status="approved",
        chunk_index=chunk_index,
        content_hash=content_hash or f"hash-{chunk_id}",
        relevance_score=relevance_score,
    )


def filter_candidates(
    candidates: tuple[RetrievedPolicy, ...],
    *,
    allowed_policy_ids: tuple[str, ...] = ("fraud_policy",),
    required_policy_ids: tuple[str, ...] = (),
    min_relevance_score: float = 0.35,
    max_context_chunks: int = 4,
) -> tuple[RetrievedPolicy, ...]:
    runtime_settings = replace(
        settings,
        min_relevance_score=min_relevance_score,
        max_context_chunks=max_context_chunks,
    )
    return filter_retrieval_candidates(
        candidates,
        allowed_policy_ids=allowed_policy_ids,
        required_policy_ids=required_policy_ids,
        runtime_settings=runtime_settings,
    )


def invalid_policy(
    valid: RetrievedPolicy,
    **changes: object,
) -> RetrievedPolicy:
    values = valid.model_dump()
    values.update(changes)
    return RetrievedPolicy.model_construct(**values)


def manifest() -> IngestionManifest:
    return IngestionManifest(
        schema_version=INGESTION_MANIFEST_SCHEMA_VERSION,
        collection_name=settings.collection_name,
        distance_metric=settings.chroma_distance_metric,
        embedding_model=settings.embedding_model,
        embedding_model_digest="a" * 64,
        embedding_dimensions=768,
        embedding_document_prefix=settings.embedding_document_prefix,
        embedding_query_prefix=settings.embedding_query_prefix,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        chunking_strategy=CHUNKING_STRATEGY,
        stable_id_strategy=STABLE_ID_STRATEGY,
        source_document_count=2,
        chunk_count=10,
        created_at="2026-07-28T00:00:00Z",
        source_hashes={
            "fraud_policy.md": "b" * 64,
            "card_replacement.md": "c" * 64,
        },
        policy_versions={
            "fraud_policy": "1.0",
            "card_replacement": "1.0",
        },
        package_versions={
            "chromadb": "1.5.9",
            "langchain-chroma": "1.1.0",
            "langchain-ollama": "1.1.0",
            "langchain-text-splitters": "1.1.2",
        },
    )


def decision(
    *,
    allowed_policy_ids: tuple[str, ...] = (
        "fraud_policy",
        "card_replacement",
    ),
    required_policy_ids: tuple[str, ...] = (
        "fraud_policy",
        "card_replacement",
    ),
) -> TriageDecision:
    return TriageDecision(
        risk_level="high",
        action="urgent_guidance",
        candidate_intents=(
            "lost_or_stolen_card",
            "compromised_card",
            "card_arrival",
        ),
        routing_intents=(
            "lost_or_stolen_card",
            "compromised_card",
        ),
        allowed_policy_ids=allowed_policy_ids,
        required_policy_ids=required_policy_ids,
        security_signals=("stolen_card",),
        requires_human=False,
        reason_code="stolen_card",
    )


def test_threshold_is_applied_to_each_candidate() -> None:
    candidates = (
        policy("below", relevance_score=0.349),
        policy("equal", relevance_score=0.35),
        policy("above", relevance_score=0.9),
    )

    selected = filter_candidates(candidates)

    assert tuple(item.chunk_id for item in selected) == (
        "above",
        "equal",
    )


@pytest.mark.parametrize(
    "candidate",
    (
        invalid_policy(policy("disallowed"), document_id="card_delivery"),
        invalid_policy(policy("draft"), status="draft"),
        invalid_policy(policy("unsafe-source"), source_file="../policy.md"),
        invalid_policy(policy("blank-content"), content="   "),
        invalid_policy(policy("blank-id"), chunk_id="   "),
        invalid_policy(policy("malformed-source"), source_file=None),
    ),
)
def test_invalid_policy_records_are_removed(
    candidate: RetrievedPolicy,
) -> None:
    assert filter_candidates((candidate,)) == ()


def test_duplicate_ids_keep_only_highest_ranked_candidate() -> None:
    selected = filter_candidates((
        policy(
            "same-id",
            content="Lower ranked text.",
            content_hash="lower-hash",
            relevance_score=0.6,
        ),
        policy(
            "same-id",
            content="Higher ranked text.",
            content_hash="higher-hash",
            relevance_score=0.9,
        ),
    ))

    assert len(selected) == 1
    assert selected[0].content == "Higher ranked text."


def test_identical_normalized_text_is_deduplicated() -> None:
    selected = filter_candidates((
        policy(
            "lower",
            content="SAME policy, text!",
            content_hash="lower-hash",
            relevance_score=0.6,
        ),
        policy(
            "higher",
            content=" same   POLICY text ",
            content_hash="higher-hash",
            relevance_score=0.9,
        ),
    ))

    assert tuple(item.chunk_id for item in selected) == ("higher",)


def test_duplicate_content_hash_is_deduplicated() -> None:
    selected = filter_candidates((
        policy(
            "lower",
            content="Different lower content.",
            content_hash="shared-hash",
            relevance_score=0.5,
        ),
        policy(
            "higher",
            content="Different higher content.",
            content_hash="shared-hash",
            relevance_score=0.8,
        ),
    ))

    assert tuple(item.chunk_id for item in selected) == ("higher",)


def test_overlap_ratio_uses_normalized_token_multisets() -> None:
    assert normalized_token_overlap_ratio(
        "Alpha alpha, BETA gamma.",
        " alpha beta gamma ALPHA delta ",
    ) == pytest.approx(1.0)
    assert normalized_token_overlap_ratio("", "content") == 0.0


def test_highly_overlapping_adjacent_chunk_keeps_higher_ranked() -> None:
    higher = policy(
        "higher",
        content=(
            "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        ),
        chunk_index=4,
        relevance_score=0.9,
    )
    lower = policy(
        "lower",
        content=(
            "alpha beta gamma delta epsilon zeta eta theta iota lambda"
        ),
        chunk_index=5,
        relevance_score=0.8,
    )

    selected = filter_candidates((lower, higher))

    assert tuple(item.chunk_id for item in selected) == ("higher",)


def test_overlap_at_exact_threshold_is_retained() -> None:
    shared = " ".join(f"token{index}" for index in range(17))
    first = policy(
        "first",
        content=f"{shared} a b c",
        chunk_index=1,
        relevance_score=0.9,
    )
    second = policy(
        "second",
        content=f"{shared} d e f",
        chunk_index=2,
        relevance_score=0.8,
    )

    assert normalized_token_overlap_ratio(
        first.content,
        second.content,
    ) == pytest.approx(0.85)
    assert len(filter_candidates((first, second))) == 2


def test_overlap_rule_applies_only_to_adjacent_same_section_chunks() -> None:
    content_a = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    content_b = "alpha beta gamma delta epsilon zeta eta theta iota lambda"
    non_adjacent = (
        policy(
            "one",
            content=content_a,
            chunk_index=1,
            relevance_score=0.9,
        ),
        policy(
            "three",
            content=content_b,
            chunk_index=3,
            relevance_score=0.8,
        ),
    )
    different_section = (
        policy(
            "section-one",
            content=content_a,
            section_path="Fraud Policy > One",
            chunk_index=1,
            relevance_score=0.9,
        ),
        policy(
            "section-two",
            content=content_b,
            section_path="Fraud Policy > Two",
            chunk_index=2,
            relevance_score=0.8,
        ),
    )

    assert len(filter_candidates(non_adjacent)) == 2
    assert len(filter_candidates(different_section)) == 2


def test_required_policy_diversity_is_reserved_before_filling_limit() -> None:
    candidates = (
        policy("fraud-best", relevance_score=0.99),
        policy(
            "fraud-second",
            content="Second distinct fraud procedure.",
            relevance_score=0.95,
            chunk_index=2,
        ),
        policy(
            "replacement",
            document_id="card_replacement",
            content="Replacement card procedure.",
            section_path="Replacement Policy > Stolen Cards",
            relevance_score=0.4,
        ),
    )

    selected = filter_candidates(
        candidates,
        allowed_policy_ids=("fraud_policy", "card_replacement"),
        required_policy_ids=("fraud_policy", "card_replacement"),
        max_context_chunks=2,
    )

    assert tuple(item.chunk_id for item in selected) == (
        "fraud-best",
        "replacement",
    )


def test_missing_required_candidate_returns_available_context_for_step_19() -> None:
    selected = filter_candidates(
        (policy("fraud"),),
        allowed_policy_ids=("fraud_policy", "card_replacement"),
        required_policy_ids=("fraud_policy", "card_replacement"),
    )

    assert tuple(item.chunk_id for item in selected) == ("fraud",)


def test_context_limit_keeps_highest_ranked_candidates() -> None:
    candidates = tuple(
        policy(
            f"chunk-{index}",
            content=f"Distinct content number {index}.",
            chunk_index=index,
            relevance_score=score,
        )
        for index, score in enumerate((0.6, 0.9, 0.7, 0.8))
    )

    selected = filter_candidates(
        candidates,
        max_context_chunks=3,
    )

    assert tuple(item.chunk_id for item in selected) == (
        "chunk-1",
        "chunk-3",
        "chunk-2",
    )


@pytest.mark.parametrize(
    "required_policy_ids",
    (
        ("unknown_policy",),
        ("card_replacement",),
        ("fraud_policy", "fraud_policy"),
    ),
)
def test_invalid_required_policy_scopes_fail_closed(
    required_policy_ids: tuple[str, ...],
) -> None:
    with pytest.raises(PolicyRetrievalError):
        filter_candidates(
            (policy("fraud"),),
            required_policy_ids=required_policy_ids,
        )


def test_required_scope_must_fit_context_limit() -> None:
    with pytest.raises(
        PolicyRetrievalError,
        match="context limit",
    ):
        filter_candidates(
            (policy("fraud"),),
            allowed_policy_ids=("fraud_policy", "card_replacement"),
            required_policy_ids=("fraud_policy", "card_replacement"),
            max_context_chunks=1,
        )


def test_valid_retrieval_context_is_sufficient() -> None:
    policies = (
        policy("fraud"),
        policy(
            "replacement",
            document_id="card_replacement",
            content="Replacement card procedure.",
            section_path="Replacement Policy > Stolen Cards",
        ),
    )

    assert retrieval_is_sufficient(
        policies,
        decision(),
        manifest=manifest(),
    )


def test_empty_retrieval_context_is_insufficient() -> None:
    assert not retrieval_is_sufficient(
        (),
        decision(),
        manifest=manifest(),
    )


def test_disallowed_or_unapproved_context_is_insufficient() -> None:
    disallowed = policy(
        "delivery",
        document_id="card_delivery",
    )
    unapproved = invalid_policy(
        policy("draft"),
        status="draft",
    )
    scoped_decision = decision(
        allowed_policy_ids=("fraud_policy",),
        required_policy_ids=("fraud_policy",),
    )

    assert not retrieval_is_sufficient(
        (disallowed,),
        scoped_decision,
        manifest=manifest(),
    )
    assert not retrieval_is_sufficient(
        (unapproved,),
        scoped_decision,
        manifest=manifest(),
    )


def test_missing_required_policy_is_insufficient() -> None:
    assert not retrieval_is_sufficient(
        (policy("fraud"),),
        decision(),
        manifest=manifest(),
    )


def test_conflicting_policy_versions_are_insufficient() -> None:
    policies = (
        policy("version-one"),
        invalid_policy(
            policy(
                "version-two",
                content="Different version content.",
                chunk_index=2,
            ),
            version="2.0",
        ),
    )
    scoped_decision = decision(
        allowed_policy_ids=("fraud_policy",),
        required_policy_ids=("fraud_policy",),
    )

    assert not retrieval_is_sufficient(
        policies,
        scoped_decision,
        manifest=manifest(),
    )


@pytest.mark.parametrize(
    "stale_manifest",
    (
        replace(
            manifest(),
            collection_name="other_collection",
        ),
        replace(
            manifest(),
            policy_versions={
                "fraud_policy": "2.0",
                "card_replacement": "1.0",
            },
        ),
        replace(
            manifest(),
            source_hashes={
                "other.md": "b" * 64,
                "card_replacement.md": "c" * 64,
            },
        ),
        replace(
            manifest(),
            chunk_count=1,
        ),
    ),
)
def test_manifest_conflicts_are_insufficient(
    stale_manifest: IngestionManifest,
) -> None:
    policies = (
        policy("fraud"),
        policy(
            "replacement",
            document_id="card_replacement",
            content="Replacement card procedure.",
            section_path="Replacement Policy > Stolen Cards",
        ),
    )

    assert not retrieval_is_sufficient(
        policies,
        decision(),
        manifest=stale_manifest,
    )


def test_context_above_configured_maximum_is_insufficient() -> None:
    policies = (
        policy("one"),
        policy(
            "two",
            content="Second accepted policy.",
            chunk_index=2,
        ),
    )
    runtime_settings = replace(
        settings,
        max_context_chunks=1,
    )
    scoped_decision = decision(
        allowed_policy_ids=("fraud_policy",),
        required_policy_ids=("fraud_policy",),
    )

    assert not retrieval_is_sufficient(
        policies,
        scoped_decision,
        manifest=manifest(),
        runtime_settings=runtime_settings,
    )


def test_missing_active_manifest_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_load(_: object) -> IngestionManifest:
        raise VectorStoreRebuildError("manifest unavailable")

    monkeypatch.setattr(
        retriever_module,
        "load_ingestion_manifest",
        fail_to_load,
    )

    assert not retrieval_is_sufficient(
        (policy("fraud"),),
        decision(
            allowed_policy_ids=("fraud_policy",),
            required_policy_ids=("fraud_policy",),
        ),
    )


def test_malformed_decision_scope_fails_closed() -> None:
    malformed = TriageDecision.model_construct(
        **{
            **decision().model_dump(),
            "required_policy_ids": ("card_delivery",),
        }
    )

    assert not retrieval_is_sufficient(
        (policy("fraud"),),
        malformed,
        manifest=manifest(),
    )
