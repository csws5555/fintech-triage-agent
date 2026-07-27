from __future__ import annotations

from pathlib import Path

import pytest

from app.ml.embeddings import get_embeddings
from app.ml.ingest_policies import (
    VectorStorePaths,
    activate_staged_vector_store,
    build_vector_store,
    load_ingestion_manifest,
    verify_vector_store,
)
from app.ml.rag_config import settings


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
