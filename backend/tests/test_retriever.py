from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from langchain_core.documents import Document

from app.ml.ingest_policies import (
    CHUNKING_STRATEGY,
    INGESTION_MANIFEST_SCHEMA_VERSION,
    STABLE_ID_STRATEGY,
    IngestionManifest,
    build_stable_chunk_id,
)
from app.ml.policy_loader import (
    compute_content_hash,
    compute_source_hash,
)
from app.ml.rag_config import settings
from app.ml.retriever import (
    PolicyRetrievalError,
    PolicyRetriever,
    cosine_distance_to_relevance,
)


MODEL_DIGEST = "a" * 64


class FakeVectorStore:
    def __init__(
        self,
        results: list[tuple[Document, float]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.results = results or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def similarity_search_with_score(
        self,
        query: str,
        k: int,
        filter: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[tuple[Document, float]]:
        self.calls.append(
            {
                "query": query,
                "k": k,
                "filter": filter,
                "kwargs": kwargs,
            }
        )

        if self.error is not None:
            raise self.error

        return self.results


def make_manifest() -> IngestionManifest:
    return IngestionManifest(
        schema_version=INGESTION_MANIFEST_SCHEMA_VERSION,
        collection_name=settings.collection_name,
        distance_metric=settings.chroma_distance_metric,
        embedding_model=settings.embedding_model,
        embedding_model_digest=MODEL_DIGEST,
        embedding_dimensions=768,
        embedding_document_prefix=settings.embedding_document_prefix,
        embedding_query_prefix=settings.embedding_query_prefix,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        chunking_strategy=CHUNKING_STRATEGY,
        stable_id_strategy=STABLE_ID_STRATEGY,
        source_document_count=4,
        chunk_count=10,
        created_at="2026-07-28T00:00:00Z",
        source_hashes={"fraud_policy.md": "b" * 64},
        policy_versions={"fraud_policy": "1.0"},
        package_versions={
            "chromadb": "1.5.9",
            "langchain-chroma": "1.1.0",
            "langchain-ollama": "1.1.0",
            "langchain-text-splitters": "1.1.2",
        },
    )


def make_document(
    *,
    document_id: str = "fraud_policy",
    content: str = (
        "# Fraud and Unauthorized Activity Policy\n\n"
        "Report an unrecognized cash withdrawal promptly."
    ),
    status: str = "approved",
) -> Document:
    content_hash = compute_content_hash(content)
    section_path = (
        "Fraud and Unauthorized Activity Policy "
        "> Unrecognized Cash Withdrawal"
    )
    chunk_id = build_stable_chunk_id(
        document_id=document_id,
        section_path=section_path,
        content_hash=content_hash,
    )
    metadata = {
        "document_id": document_id,
        "source_file": f"{document_id}.md",
        "title": "Fraud and Unauthorized Activity Policy",
        "version": "1.0",
        "effective_date": "2026-07-01",
        "review_date": "2026-10-01",
        "owner": "Prototype Risk and Support Team",
        "status": status,
        "policy_type": "customer_support",
        "product": "consumer_banking",
        "jurisdiction": "fictional_prototype",
        "source_hash": compute_source_hash("approved source\n"),
        "header_1": "Fraud and Unauthorized Activity Policy",
        "header_2": "Unrecognized Cash Withdrawal",
        "header_3": "",
        "section_path": section_path,
        "content_hash": content_hash,
        "chunk_index": 3,
    }
    return Document(
        id=chunk_id,
        page_content=content,
        metadata=metadata,
    )


def make_retriever(store: FakeVectorStore) -> PolicyRetriever:
    return PolicyRetriever(
        vector_store=store,
        manifest=make_manifest(),
        embedding_model_digest=MODEL_DIGEST,
    )


def test_customer_message_is_stripped_and_search_is_mandatorily_filtered() -> None:
    store = FakeVectorStore([(make_document(), 0.2)])
    retriever = make_retriever(store)

    policies = retriever.retrieve(
        query="  I do not recognize this cash withdrawal.  ",
        allowed_policy_ids=("fraud_policy",),
    )

    assert store.calls == [
        {
            "query": "I do not recognize this cash withdrawal.",
            "k": settings.candidate_k,
            "filter": {
                "document_id": {
                    "$in": ["fraud_policy"],
                }
            },
            "kwargs": {},
        }
    ]
    assert len(policies) == 1
    assert policies[0].document_id == "fraud_policy"
    assert policies[0].chunk_id == make_document().id
    assert policies[0].relevance_score == pytest.approx(0.8)


def test_calibration_threshold_override_is_local_to_one_call() -> None:
    store = FakeVectorStore([(make_document(), 0.45)])
    retriever = make_retriever(store)

    calibrated = retriever.retrieve(
        query="I do not recognize this cash withdrawal.",
        allowed_policy_ids=("fraud_policy",),
        min_relevance_score=0.60,
    )
    configured = retriever.retrieve(
        query="I do not recognize this cash withdrawal.",
        allowed_policy_ids=("fraud_policy",),
    )

    assert calibrated == ()
    assert len(configured) == 1


@pytest.mark.parametrize("query", ("", " ", "\n\t"))
def test_blank_queries_are_rejected_before_search(query: str) -> None:
    store = FakeVectorStore()

    with pytest.raises(PolicyRetrievalError, match="blank"):
        make_retriever(store).retrieve(
            query=query,
            allowed_policy_ids=("fraud_policy",),
        )

    assert store.calls == []


@pytest.mark.parametrize(
    "allowed_policy_ids",
    (
        (),
        ("unknown_policy",),
        ("fraud_policy", "fraud_policy"),
    ),
)
def test_invalid_policy_scopes_are_rejected_before_search(
    allowed_policy_ids: tuple[str, ...],
) -> None:
    store = FakeVectorStore()

    with pytest.raises(PolicyRetrievalError):
        make_retriever(store).retrieve(
            query="Report fraud",
            allowed_policy_ids=allowed_policy_ids,
        )

    assert store.calls == []


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("schema_version", 1),
        ("collection_name", "other_collection"),
        ("embedding_model", "other-model"),
        ("embedding_model_digest", "b" * 64),
        ("distance_metric", "l2"),
        ("embedding_document_prefix", "passage:"),
        ("embedding_query_prefix", "query:"),
        ("chunk_size", settings.chunk_size + 1),
        ("chunk_overlap", settings.chunk_overlap + 1),
    ),
)
def test_required_manifest_mismatches_fail_before_search(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(
        PolicyRetrievalError,
        match=field_name,
    ):
        PolicyRetriever(
            vector_store=FakeVectorStore(),
            manifest=replace(
                make_manifest(),
                **{field_name: value},
            ),
            embedding_model_digest=MODEL_DIGEST,
        )


@pytest.mark.parametrize(
    ("distance", "expected"),
    (
        (0.0, 1.0),
        (0.25, 0.75),
        (1.0, 0.0),
        (-0.25, 1.0),
        (1.25, 0.0),
    ),
)
def test_cosine_distance_conversion_is_clamped(
    distance: float,
    expected: float,
) -> None:
    assert cosine_distance_to_relevance(distance) == pytest.approx(expected)


@pytest.mark.parametrize("distance", (float("nan"), float("inf"), True))
def test_invalid_cosine_distances_fail_closed(distance: float) -> None:
    with pytest.raises(PolicyRetrievalError, match="distance"):
        cosine_distance_to_relevance(distance)


def test_low_score_candidates_are_filtered_in_step_18() -> None:
    store = FakeVectorStore([(make_document(), 0.99)])

    policies = make_retriever(store).retrieve(
        query="Report fraud",
        allowed_policy_ids=("fraud_policy",),
    )

    assert policies == ()


def test_disallowed_result_fails_closed_without_unfiltered_retry() -> None:
    store = FakeVectorStore([
        (make_document(document_id="card_delivery"), 0.1),
    ])

    with pytest.raises(
        PolicyRetrievalError,
        match="escaped",
    ):
        make_retriever(store).retrieve(
            query="Report fraud",
            allowed_policy_ids=("fraud_policy",),
        )

    assert len(store.calls) == 1
    assert store.calls[0]["filter"] is not None


def test_unapproved_or_corrupt_stored_candidate_fails_closed() -> None:
    store = FakeVectorStore([
        (make_document(status="draft"), 0.1),
    ])

    with pytest.raises(
        PolicyRetrievalError,
        match="not approved",
    ):
        make_retriever(store).retrieve(
            query="Report fraud",
            allowed_policy_ids=("fraud_policy",),
        )

    assert len(store.calls) == 1


def test_filtered_search_failure_never_triggers_unfiltered_fallback() -> None:
    store = FakeVectorStore(error=ConnectionError("Chroma unavailable"))

    with pytest.raises(
        PolicyRetrievalError,
        match="Filtered policy retrieval failed",
    ):
        make_retriever(store).retrieve(
            query="Report fraud",
            allowed_policy_ids=("fraud_policy",),
        )

    assert len(store.calls) == 1
    assert store.calls[0]["filter"] == {
        "document_id": {
            "$in": ["fraud_policy"],
        }
    }
