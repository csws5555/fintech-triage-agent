from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.ml.ingest_policies import (
    VectorStoreBuildResult,
    create_ingestion_manifest,
    split_policy_documents,
    write_ingestion_manifest,
)
from app.ml.policy_loader import PolicyDocument, load_approved_policies
from app.ml.rag_config import settings
from scripts.inspect_vector_store import (
    VectorStoreInspectionError,
    inspect_vector_store,
    print_inspection_report,
)


MODEL_DIGEST = "a" * 64
PACKAGE_VERSIONS = {
    "chromadb": "1.5.9",
    "langchain-chroma": "1.1.0",
    "langchain-ollama": "1.0.1",
    "langchain-text-splitters": "1.0.0",
}


class FakeCollection:
    def __init__(
        self,
        *,
        ids: list[str],
        metadatas: list[object],
        name: str = settings.collection_name,
        metric: str | None = settings.chroma_distance_metric,
        dimensions: int = 3,
    ) -> None:
        self.name = name
        self.ids = ids
        self.metadatas = metadatas
        self.dimensions = dimensions
        self.configuration = (
            {"hnsw": {"space": metric}}
            if metric is not None
            else {}
        )
        self.get_calls: list[dict[str, Any]] = []

    def count(self) -> int:
        return len(self.ids)

    def get(self, **kwargs: Any) -> dict[str, object]:
        self.get_calls.append(kwargs)

        if kwargs.get("include") == ["embeddings"]:
            return {"embeddings": [[0.0] * self.dimensions]}

        return {
            "ids": list(self.ids),
            "metadatas": list(self.metadatas),
        }


class FakeClient:
    def __init__(self, collection: FakeCollection) -> None:
        self.collection = collection
        self.get_collection_calls: list[dict[str, Any]] = []
        self.closed = False
        self.cache_cleared = False

    def get_collection(self, **kwargs: Any) -> FakeCollection:
        self.get_collection_calls.append(kwargs)
        return self.collection

    def close(self) -> None:
        self.closed = True

    def clear_system_cache(self) -> None:
        self.cache_cleared = True


class FakeClientFactory:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeClient:
        self.calls.append(kwargs)
        return self.client


@pytest.fixture
def store_fixture(
    tmp_path: Path,
) -> tuple[
    Path,
    tuple[PolicyDocument, ...],
    list[str],
    list[dict[str, object]],
]:
    documents = load_approved_policies(settings.policies_dir)
    chunks = split_policy_documents(
        documents,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    ids = [chunk.chunk_id for chunk in chunks]
    metadatas = [
        dict(chunk.storage_metadata())
        for chunk in chunks
    ]
    result = VectorStoreBuildResult(
        chunk_count=len(ids),
        embedding_dimensions=3,
        record_ids=tuple(ids),
    )
    manifest = create_ingestion_manifest(
        documents,
        build_result=result,
        embedding_model_digest=MODEL_DIGEST,
        package_versions=PACKAGE_VERSIONS,
        created_at=datetime(
            2026,
            7,
            28,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )
    store_dir = tmp_path / "chromadb_store"
    store_dir.mkdir()
    write_ingestion_manifest(store_dir, manifest)
    return store_dir, documents, ids, metadatas


def run_inspection(
    store_fixture: tuple[
        Path,
        tuple[PolicyDocument, ...],
        list[str],
        list[dict[str, object]],
    ],
    *,
    ids: list[str] | None = None,
    metadatas: list[object] | None = None,
    metric: str | None = settings.chroma_distance_metric,
    dimensions: int = 3,
    runtime_settings=settings,
):
    store_dir, documents, fixture_ids, fixture_metadatas = store_fixture
    collection = FakeCollection(
        ids=list(fixture_ids if ids is None else ids),
        metadatas=list(
            fixture_metadatas
            if metadatas is None
            else metadatas
        ),
        metric=metric,
        dimensions=dimensions,
    )
    client = FakeClient(collection)
    factory = FakeClientFactory(client)
    report = inspect_vector_store(
        runtime_settings,
        client_factory=factory,
        policy_loader=lambda _: documents,
        package_versions_provider=lambda: PACKAGE_VERSIONS,
        store_dir=store_dir,
    )
    return report, collection, client, factory


def test_inspection_reads_only_safe_collection_facts(
    store_fixture,
) -> None:
    report, collection, client, factory = run_inspection(
        store_fixture
    )

    store_dir, documents, ids, _ = store_fixture
    assert report.passed is True
    assert report.collection_name == settings.collection_name
    assert report.active_store_path == "<external-store>"
    assert report.manifest_schema_version == 2
    assert report.actual_distance_metric == "cosine"
    assert report.stored_chunk_count == len(ids)
    assert report.manifest_chunk_count == len(ids)
    assert report.source_document_count == len(documents) == 4
    assert report.embedding_model == settings.embedding_model
    assert report.embedding_model_digest == MODEL_DIGEST
    assert report.embedding_dimensions == 3
    assert report.query_prefix == settings.embedding_query_prefix
    assert report.document_prefix == settings.embedding_document_prefix
    assert set(report.policy_versions) == {
        document.document_id for document in documents
    }
    assert sum(report.chunks_per_policy.values()) == len(ids)
    assert report.duplicate_ids == 0
    assert report.records_with_unapproved_status == 0
    assert report.records_outside_known_policy_ids == 0
    assert report.records_with_missing_metadata == 0
    assert report.records_with_unsafe_source_paths == 0
    assert report.manifest_mismatches == ()
    assert collection.get_calls == [
        {
            "limit": len(ids),
            "include": ["metadatas"],
        },
        {
            "limit": 1,
            "include": ["embeddings"],
        },
    ]
    assert all(
        "documents" not in call.get("include", [])
        for call in collection.get_calls
    )
    assert factory.calls == [{"path": str(store_dir.resolve())}]
    assert client.get_collection_calls == [{
        "name": settings.collection_name,
        "embedding_function": None,
    }]
    assert client.closed is True
    assert client.cache_cleared is True


def test_printed_report_has_every_required_field_without_private_data(
    store_fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report, _, _, _ = run_inspection(store_fixture)
    _, documents, _, _ = store_fixture

    print_inspection_report(report)
    output = capsys.readouterr().out

    for label in (
        "Collection name:",
        "Active store path:",
        "Manifest schema version:",
        "Configured distance metric:",
        "Actual collection distance metric:",
        "Stored chunk count:",
        "Manifest chunk count:",
        "Source document count:",
        "Embedding model:",
        "Embedding-model digest:",
        "Embedding dimensions:",
        "Query prefix:",
        "Document prefix:",
        "Policy files:",
        "Policy versions:",
        "Chunks per policy:",
        "Distinct section paths:",
        "Duplicate IDs:",
        "Duplicate content hashes:",
        "Records with unapproved status:",
        "Records outside known policy IDs:",
        "Missing metadata:",
        "Absolute or unsafe source paths:",
        "Manifest mismatches:",
    ):
        assert label in output

    assert str(settings.chroma_store_dir) not in output
    assert str(store_fixture[0].resolve()) not in output
    assert all(document.body not in output for document in documents)
    assert "embeddings" not in output
    assert report.embedding_model_digest not in output
    assert "Embedding-model digest: recorded" in output


def test_manifest_and_collection_count_mismatch_fails(
    store_fixture,
) -> None:
    store_dir, _, ids, _ = store_fixture
    manifest_path = store_dir / "ingestion_manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    raw = raw.replace(
        f'"chunk_count": {len(ids)}',
        f'"chunk_count": {len(ids) + 1}',
    )
    manifest_path.write_text(raw, encoding="utf-8")

    report, _, _, _ = run_inspection(store_fixture)

    assert report.passed is False
    assert any(
        "chunk counts differ" in failure
        for failure in report.integrity_failures
    )


def test_duplicate_ids_fail(
    store_fixture,
) -> None:
    _, _, ids, metadatas = store_fixture
    changed_ids = list(ids)
    changed_ids[-1] = changed_ids[0]

    report, _, _, _ = run_inspection(
        store_fixture,
        ids=changed_ids,
        metadatas=metadatas,
    )

    assert report.duplicate_ids == 1
    assert report.passed is False
    assert "duplicate record IDs exist" in report.integrity_failures


def test_duplicate_content_hashes_are_reported_without_printing_hashes(
    store_fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, _, metadatas = store_fixture
    changed = [dict(metadata) for metadata in metadatas]
    duplicate_hash = str(changed[0]["content_hash"])
    changed[-1]["content_hash"] = duplicate_hash

    report, _, _, _ = run_inspection(
        store_fixture,
        metadatas=changed,
    )
    print_inspection_report(report)
    output = capsys.readouterr().out

    assert report.duplicate_content_hashes >= 1
    assert duplicate_hash not in output


@pytest.mark.parametrize(
    ("field_name", "value", "expected_failure"),
    (
        (
            "status",
            "draft",
            "unapproved records exist",
        ),
        (
            "document_id",
            "unknown_policy",
            "records outside known policy IDs exist",
        ),
    ),
)
def test_unsafe_policy_records_fail(
    store_fixture,
    field_name: str,
    value: str,
    expected_failure: str,
) -> None:
    _, _, _, metadatas = store_fixture
    changed = [dict(metadata) for metadata in metadatas]
    changed[0][field_name] = value

    report, _, _, _ = run_inspection(
        store_fixture,
        metadatas=changed,
    )

    assert report.passed is False
    assert expected_failure in report.integrity_failures


def test_missing_metadata_and_unsafe_source_paths_fail(
    store_fixture,
) -> None:
    _, _, _, metadatas = store_fixture
    changed = [dict(metadata) for metadata in metadatas]
    changed[0].pop("section_path")
    changed[1]["source_file"] = "C:\\private\\policy.md"

    report, _, _, _ = run_inspection(
        store_fixture,
        metadatas=changed,
    )

    assert report.records_with_missing_metadata == 1
    assert report.records_with_unsafe_source_paths == 1
    assert report.passed is False
    assert (
        "records have missing or malformed metadata"
        in report.integrity_failures
    )
    assert (
        "records contain unsafe source paths"
        in report.integrity_failures
    )


@pytest.mark.parametrize(
    ("metric", "dimensions"),
    (
        ("l2", 3),
        (None, 3),
        ("cosine", 4),
    ),
)
def test_collection_settings_differing_from_manifest_fail(
    store_fixture,
    metric: str | None,
    dimensions: int,
) -> None:
    report, _, _, _ = run_inspection(
        store_fixture,
        metric=metric,
        dimensions=dimensions,
    )

    assert report.passed is False
    assert report.manifest_mismatches
    assert any(
        "collection or runtime ingestion facts differ"
        in failure
        for failure in report.integrity_failures
    )


def test_runtime_ingestion_setting_mismatch_fails(
    store_fixture,
) -> None:
    changed_settings = replace(
        settings,
        chunk_size=settings.chunk_size + 1,
    )

    report, _, _, _ = run_inspection(
        store_fixture,
        runtime_settings=changed_settings,
    )

    assert report.passed is False
    assert any(
        "chunk_size" in mismatch
        for mismatch in report.manifest_mismatches
    )


def test_package_version_mismatch_fails(
    store_fixture,
) -> None:
    store_dir, documents, ids, metadatas = store_fixture
    collection = FakeCollection(ids=ids, metadatas=metadatas)
    client = FakeClient(collection)

    report = inspect_vector_store(
        client_factory=FakeClientFactory(client),
        policy_loader=lambda _: documents,
        package_versions_provider=lambda: {
            **PACKAGE_VERSIONS,
            "chromadb": "0.0.0",
        },
        store_dir=store_dir,
    )

    assert report.passed is False
    assert any(
        "package_versions" in mismatch
        for mismatch in report.manifest_mismatches
    )


def test_manifest_outside_active_store_is_refused(
    store_fixture,
    tmp_path: Path,
) -> None:
    store_dir, documents, ids, metadatas = store_fixture
    external = tmp_path / "external-manifest.json"
    external.write_text("{}", encoding="utf-8")
    client = FakeClient(
        FakeCollection(ids=ids, metadatas=metadatas)
    )

    with pytest.raises(
        VectorStoreInspectionError,
        match="inside the active store",
    ):
        inspect_vector_store(
            client_factory=FakeClientFactory(client),
            policy_loader=lambda _: documents,
            package_versions_provider=lambda: PACKAGE_VERSIONS,
            store_dir=store_dir,
            manifest_path=external,
        )

    assert client.closed is False


def test_malformed_collection_response_fails_and_releases_client(
    store_fixture,
) -> None:
    store_dir, documents, ids, _ = store_fixture
    collection = FakeCollection(ids=ids, metadatas=[])
    client = FakeClient(collection)

    with pytest.raises(
        VectorStoreInspectionError,
        match="malformed stored IDs or metadata",
    ):
        inspect_vector_store(
            client_factory=FakeClientFactory(client),
            policy_loader=lambda _: documents,
            package_versions_provider=lambda: PACKAGE_VERSIONS,
            store_dir=store_dir,
        )

    assert client.closed is True
    assert client.cache_cleared is True
