from __future__ import annotations

from pathlib import Path

import pytest
from langchain_chroma import Chroma

from app.ml.embeddings import get_embeddings
from app.ml.ingest_policies import (
    VectorStorePaths,
    activate_staged_vector_store,
    build_vector_store,
    load_ingestion_manifest,
    verify_vector_store,
)
from app.ml.rag_config import settings
from app.ml.retriever import PolicyRetriever
from app.ml.triage_types import TriageDecision


@pytest.mark.integration
def test_live_nomic_temporary_chroma_build_and_reopen(
    tmp_path: Path,
) -> None:
    """Requires running local Ollama with the approved Nomic model."""

    embeddings = get_embeddings()
    paths = VectorStorePaths(
        active=tmp_path / "chromadb_store",
        temporary=tmp_path / "chromadb_store_tmp",
        backup=tmp_path / "chromadb_store_backup",
    )
    paths.active.mkdir()
    (paths.active / "previous.marker").write_text(
        "previous",
        encoding="utf-8",
    )

    result = activate_staged_vector_store(
        paths,
        clients_stopped=True,
        build_temporary=lambda temporary: build_vector_store(
            temporary,
            embeddings=embeddings,
        ),
        verify_active=lambda active, expected: verify_vector_store(
            active,
            embeddings=embeddings,
            expected_result=expected,
        ),
    )

    assert result.chunk_count > 0
    assert result.embedding_dimensions > 0
    assert len(result.record_ids) == result.chunk_count
    assert result.manifest is not None
    assert paths.active.exists()
    assert not paths.temporary.exists()
    assert not paths.backup.exists()
    assert not (paths.active / "previous.marker").exists()

    manifest = load_ingestion_manifest(
        paths.active / "ingestion_manifest.json"
    )
    assert manifest.schema_version == 2
    assert manifest.collection_name == settings.collection_name
    assert manifest.embedding_model == settings.embedding_model
    assert len(manifest.embedding_model_digest) == 64
    assert manifest.embedding_dimensions == result.embedding_dimensions
    assert manifest.source_document_count == 4
    assert manifest.chunk_count == result.chunk_count

    vector_store = Chroma(
        collection_name=settings.collection_name,
        embedding_function=embeddings,
        persist_directory=str(paths.active),
        create_collection_if_not_exists=False,
    )
    retriever = PolicyRetriever(
        vector_store=vector_store,
        manifest=manifest,
        embedding_model_digest=manifest.embedding_model_digest,
    )
    similar = retriever.retrieve(
        query="When should my newly ordered bank card arrive?",
        allowed_policy_ids=("card_delivery",),
        required_policy_ids=("card_delivery",),
    )
    unrelated = retriever.retrieve(
        query="How do I report an unrecognized cash withdrawal?",
        allowed_policy_ids=("card_delivery",),
    )

    assert similar
    assert unrelated
    assert len(similar) <= settings.max_context_chunks
    assert len(unrelated) <= settings.max_context_chunks
    assert max(
        policy.relevance_score
        for policy in similar
    ) > max(
        policy.relevance_score
        for policy in unrelated
    )

    decision = TriageDecision(
        risk_level="low",
        action="generate",
        candidate_intents=(
            "card_arrival",
            "card_delivery_estimate",
            "mortgage_info",
        ),
        routing_intents=(
            "card_arrival",
            "card_delivery_estimate",
        ),
        allowed_policy_ids=("card_delivery",),
        required_policy_ids=("card_delivery",),
        security_signals=(),
        requires_human=False,
        reason_code="supported_policy_generation",
    )
    assert retriever.retrieval_is_sufficient(
        similar,
        decision,
    )
