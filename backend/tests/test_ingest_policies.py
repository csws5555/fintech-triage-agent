from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from types import SimpleNamespace

import pytest
from langchain_core.embeddings import Embeddings

from app.ml.ingest_policies import (
    EXPECTED_CHUNK_METADATA_FIELDS,
    INGESTION_MANIFEST_FIELDS,
    IngestionManifest,
    PolicyChunkingError,
    VectorStoreBuildResult,
    VectorStorePaths,
    VectorStoreRebuildError,
    activate_staged_vector_store,
    build_stable_chunk_id,
    build_vector_store,
    create_ingestion_manifest,
    get_local_embedding_model_digest,
    load_ingestion_manifest,
    slugify_identity_component,
    split_policy_document,
    split_policy_documents,
    validate_policy_chunks,
    validate_ingestion_manifest,
    write_ingestion_manifest,
)
from app.ml.policy_loader import (
    DuplicatePolicyDocumentError,
    PolicyDocument,
    load_policy_directory,
    load_policy_file,
)
from app.ml.rag_config import settings


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


TEST_MODEL_DIGEST = "a" * 64
TEST_PACKAGE_VERSIONS = {
    "chromadb": "1.5.9",
    "langchain-chroma": "1.1.0",
    "langchain-ollama": "1.1.0",
    "langchain-text-splitters": "1.1.2",
}


def manifest_fixture() -> tuple[
    IngestionManifest,
    tuple[PolicyDocument, ...],
    VectorStoreBuildResult,
]:
    documents = load_policy_directory(settings.policies_dir)
    chunks = split_policy_documents(documents)
    result = VectorStoreBuildResult(
        chunk_count=len(chunks),
        embedding_dimensions=768,
        record_ids=tuple(chunk.chunk_id for chunk in chunks),
    )
    manifest = create_ingestion_manifest(
        documents,
        build_result=result,
        embedding_model_digest=TEST_MODEL_DIGEST,
        package_versions=TEST_PACKAGE_VERSIONS,
        created_at=datetime(
            2026,
            7,
            27,
            12,
            30,
            tzinfo=timezone.utc,
        ),
    )
    return manifest, documents, result


def policy_text(
    body: str,
    *,
    document_id: str = "test_policy",
    title: str = "Test Policy",
) -> str:
    return (
        "---\n"
        f"document_id: {document_id}\n"
        f"title: {title}\n"
        'version: "1.0"\n'
        'effective_date: "2026-07-01"\n'
        'review_date: "2026-10-01"\n'
        "owner: Test Operations\n"
        "status: approved\n"
        "product: cards\n"
        "policy_type: operations\n"
        "jurisdiction: fictional_prototype\n"
        "---\n\n"
        f"{body.strip()}\n"
    )


def write_policy(
    directory: Path,
    body: str,
    *,
    filename: str = "test_policy.md",
    document_id: str = "test_policy",
    title: str = "Test Policy",
) -> Path:
    path = directory / filename
    path.write_text(
        policy_text(
            body,
            document_id=document_id,
            title=title,
        ),
        encoding="utf-8",
    )
    return path


def test_h1_h2_h3_metadata_and_headers_are_retained(
    tmp_path: Path,
) -> None:
    path = write_policy(
        tmp_path,
        """
# Test Policy

Introductory guidance.

## Card Security

Security guidance.

### Immediate Action

Freeze the affected card.
""",
    )
    chunks = split_policy_document(
        load_policy_file(path),
        chunk_size=700,
        chunk_overlap=100,
    )
    immediate = next(
        chunk
        for chunk in chunks
        if chunk.metadata["header_3"] == "Immediate Action"
    )

    assert immediate.metadata["header_1"] == "Test Policy"
    assert immediate.metadata["header_2"] == "Card Security"
    assert immediate.metadata["header_3"] == "Immediate Action"
    assert immediate.section_path == (
        "Test Policy > Card Security > Immediate Action"
    )
    assert "### Immediate Action" in immediate.content
    assert "Freeze the affected card." in immediate.content


def test_oversized_sections_are_split_and_normalized(
    tmp_path: Path,
) -> None:
    paragraphs = "\n\n".join(
        f"Guidance item {index} contains reviewed operational wording."
        for index in range(30)
    )
    path = write_policy(
        tmp_path,
        f"# Test Policy\n\n## Long Section\n\n{paragraphs}",
    )

    chunks = split_policy_document(
        load_policy_file(path),
        chunk_size=200,
        chunk_overlap=40,
    )

    assert len(chunks) > 1
    assert all(chunk.content for chunk in chunks)
    assert all(chunk.content == chunk.content.strip() for chunk in chunks)
    assert all(len(chunk.content) <= 200 for chunk in chunks)
    assert all(
        chunk.section_path == "Test Policy > Long Section"
        for chunk in chunks
    )


def test_blank_lines_do_not_create_blank_chunks(
    tmp_path: Path,
) -> None:
    path = write_policy(
        tmp_path,
        """

# Test Policy


## Guidance


Approved text.


""",
    )

    chunks = split_policy_document(load_policy_file(path))

    assert chunks
    assert all(chunk.content.strip() for chunk in chunks)


def test_chunk_metadata_is_complete_and_path_safe(
    tmp_path: Path,
) -> None:
    path = write_policy(
        tmp_path,
        "# Test Policy\n\n## Guidance\n\nApproved text.",
    )
    document = load_policy_file(path)
    chunks = split_policy_document(document)

    for chunk in chunks:
        metadata = chunk.storage_metadata()
        assert set(metadata) == EXPECTED_CHUNK_METADATA_FIELDS
        assert metadata["status"] == "approved"
        assert metadata["jurisdiction"] == "fictional_prototype"
        assert metadata["source_file"] == "test_policy.md"
        assert "source_path" not in metadata
        assert str(document.source_path) not in repr(metadata)
        assert len(str(metadata["source_hash"])) == 64
        assert len(str(metadata["content_hash"])) == 64
        assert metadata["source_hash"] != metadata["content_hash"]

    with pytest.raises(TypeError):
        chunks[0].metadata["title"] = "Changed"  # type: ignore[index]

    assert isinstance(chunks[0].metadata, MappingProxyType)


def test_chunking_is_deterministic(tmp_path: Path) -> None:
    path = write_policy(
        tmp_path,
        """
# Test Policy

## First

First guidance.

## Second

Second guidance.
""",
    )
    document = load_policy_file(path)

    first_run = split_policy_document(document)
    second_run = split_policy_document(document)

    assert [
        (
            chunk.chunk_id,
            chunk.content,
            chunk.storage_metadata(),
        )
        for chunk in first_run
    ] == [
        (
            chunk.chunk_id,
            chunk.content,
            chunk.storage_metadata(),
        )
        for chunk in second_run
    ]


def test_repeated_identical_content_gets_occurrence_suffix(
    tmp_path: Path,
) -> None:
    repeated_content = "a" * 190
    path = write_policy(
        tmp_path,
        f"""
# Test Policy

## Repeated

{repeated_content}

{repeated_content}

{repeated_content}
""",
    )

    chunks = split_policy_document(
        load_policy_file(path),
        chunk_size=200,
        chunk_overlap=0,
    )
    repeated = [
        chunk
        for chunk in chunks
        if chunk.content == repeated_content
    ]

    assert len(repeated) == 3
    assert repeated[1].chunk_id == f"{repeated[0].chunk_id}-02"
    assert repeated[2].chunk_id == f"{repeated[0].chunk_id}-03"


def test_inserting_earlier_section_preserves_later_stable_id(
    tmp_path: Path,
) -> None:
    original_path = write_policy(
        tmp_path,
        """
# Test Policy

## Existing

Unchanged reviewed guidance.
""",
        filename="original.md",
    )
    updated_path = write_policy(
        tmp_path,
        """
# Test Policy

## New Earlier Section

New guidance.

## Existing

Unchanged reviewed guidance.
""",
        filename="updated.md",
    )
    original = split_policy_document(
        load_policy_file(original_path)
    )
    updated = split_policy_document(
        load_policy_file(updated_path)
    )
    original_existing = next(
        chunk
        for chunk in original
        if chunk.section_path == "Test Policy > Existing"
    )
    updated_existing = next(
        chunk
        for chunk in updated
        if chunk.section_path == "Test Policy > Existing"
    )

    assert original_existing.chunk_id == updated_existing.chunk_id
    assert original_existing.chunk_index != updated_existing.chunk_index


def test_stable_id_format_and_slug_normalization() -> None:
    content_hash = "a" * 64

    assert slugify_identity_component(
        "  Fraud_Policy  "
    ) == "fraud-policy"
    assert build_stable_chunk_id(
        document_id="fraud_policy",
        section_path=(
            "Fraud and Unauthorized Activity Policy "
            "> Unrecognized Cash Withdrawal"
        ),
        content_hash=content_hash,
    ) == (
        "fraud-policy-fraud-and-unauthorized-activity-policy-"
        "unrecognized-cash-withdrawal-aaaaaaaaaaaa"
    )
    assert build_stable_chunk_id(
        document_id="fraud_policy",
        section_path="Repeated",
        content_hash=content_hash,
        occurrence=2,
    ).endswith("-02")


@pytest.mark.parametrize(
    "content_hash",
    (
        "",
        "abc",
        "g" * 64,
        "A" * 64,
    ),
)
def test_invalid_content_hash_is_rejected(
    content_hash: str,
) -> None:
    with pytest.raises(PolicyChunkingError):
        build_stable_chunk_id(
            document_id="test_policy",
            section_path="Test Policy",
            content_hash=content_hash,
        )


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    (
        (199, 0),
        (700, -1),
        (700, 700),
    ),
)
def test_invalid_chunk_settings_are_rejected(
    tmp_path: Path,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    path = write_policy(
        tmp_path,
        "# Test Policy\n\nApproved guidance.",
    )

    with pytest.raises(PolicyChunkingError):
        split_policy_document(
            load_policy_file(path),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def test_duplicate_policy_ids_are_rejected_before_chunking(
    tmp_path: Path,
) -> None:
    first = write_policy(
        tmp_path,
        "# First\n\nGuidance.",
        filename="first.md",
        document_id="duplicate",
        title="First",
    )
    second = write_policy(
        tmp_path,
        "# Second\n\nGuidance.",
        filename="second.md",
        document_id="duplicate",
        title="Second",
    )

    with pytest.raises(DuplicatePolicyDocumentError):
        split_policy_documents(
            (
                load_policy_file(first),
                load_policy_file(second),
            )
        )


def test_empty_policy_collection_is_rejected() -> None:
    with pytest.raises(
        PolicyChunkingError,
        match="At least one",
    ):
        split_policy_documents(())


def test_duplicate_final_ids_are_rejected(
    tmp_path: Path,
) -> None:
    path = write_policy(
        tmp_path,
        "# Test Policy\n\nApproved guidance.",
    )
    chunk = split_policy_document(
        load_policy_file(path)
    )[0]

    with pytest.raises(
        PolicyChunkingError,
        match="Duplicate stable chunk ID",
    ):
        validate_policy_chunks((chunk, chunk))


def test_all_approved_policies_chunk_successfully() -> None:
    documents = load_policy_directory(settings.policies_dir)
    chunks = split_policy_documents(documents)
    document_ids = {chunk.document_id for chunk in chunks}

    assert document_ids == {
        "fraud_policy",
        "card_replacement",
        "card_delivery",
        "international_fees",
    }
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all(
        "/" not in chunk.chunk_id
        and "\\" not in chunk.chunk_id
        and ":" not in chunk.chunk_id
        for chunk in chunks
    )

    for document in documents:
        document_chunks = [
            chunk
            for chunk in chunks
            if chunk.document_id == document.document_id
        ]
        assert document_chunks
        assert [
            chunk.chunk_index for chunk in document_chunks
        ] == list(range(len(document_chunks)))
        assert all("---" not in chunk.content for chunk in document_chunks)


def staged_paths(tmp_path: Path) -> VectorStorePaths:
    return VectorStorePaths(
        active=tmp_path / "active",
        temporary=tmp_path / "temporary",
        backup=tmp_path / "backup",
    )


def build_marker_store(path: Path) -> VectorStoreBuildResult:
    (path / "new.marker").write_text("new", encoding="utf-8")
    return VectorStoreBuildResult(
        chunk_count=1,
        embedding_dimensions=3,
        record_ids=("record-id",),
    )


def test_activation_requires_stopped_client_confirmation(
    tmp_path: Path,
) -> None:
    paths = staged_paths(tmp_path)

    with pytest.raises(
        VectorStoreRebuildError,
        match="Confirm",
    ):
        activate_staged_vector_store(
            paths,
            build_temporary=build_marker_store,
            verify_active=lambda _path, _result: None,
            clients_stopped=False,
        )

    assert not paths.temporary.exists()
    assert not paths.active.exists()


def test_pre_swap_failure_leaves_active_store_untouched(
    tmp_path: Path,
) -> None:
    paths = staged_paths(tmp_path)
    paths.active.mkdir()
    (paths.active / "old.marker").write_text("old", encoding="utf-8")

    def fail_build(_path: Path) -> VectorStoreBuildResult:
        raise RuntimeError("simulated build failure")

    with pytest.raises(
        VectorStoreRebuildError,
        match="active store was not changed",
    ):
        activate_staged_vector_store(
            paths,
            build_temporary=fail_build,
            verify_active=lambda _path, _result: None,
            clients_stopped=True,
        )

    assert (paths.active / "old.marker").read_text(
        encoding="utf-8"
    ) == "old"
    assert not paths.backup.exists()


def test_post_swap_failure_restores_previous_active_store(
    tmp_path: Path,
) -> None:
    paths = staged_paths(tmp_path)
    paths.active.mkdir()
    (paths.active / "old.marker").write_text("old", encoding="utf-8")

    def fail_verify(
        _path: Path,
        _result: VectorStoreBuildResult,
    ) -> None:
        raise RuntimeError("simulated reopen failure")

    with pytest.raises(
        VectorStoreRebuildError,
        match="previous active store was restored",
    ):
        activate_staged_vector_store(
            paths,
            build_temporary=build_marker_store,
            verify_active=fail_verify,
            clients_stopped=True,
        )

    assert (paths.active / "old.marker").read_text(
        encoding="utf-8"
    ) == "old"
    assert (paths.temporary / "new.marker").read_text(
        encoding="utf-8"
    ) == "new"
    assert not paths.backup.exists()


def test_successful_activation_removes_backup_after_reopen(
    tmp_path: Path,
) -> None:
    paths = staged_paths(tmp_path)
    paths.active.mkdir()
    (paths.active / "old.marker").write_text("old", encoding="utf-8")
    verified: list[Path] = []

    result = activate_staged_vector_store(
        paths,
        build_temporary=build_marker_store,
        verify_active=lambda path, _result: verified.append(path),
        clients_stopped=True,
    )

    assert result.chunk_count == 1
    assert verified == [paths.active.resolve()]
    assert (paths.active / "new.marker").exists()
    assert not paths.temporary.exists()
    assert not paths.backup.exists()


def test_existing_backup_fails_closed(
    tmp_path: Path,
) -> None:
    paths = staged_paths(tmp_path)
    paths.backup.mkdir()
    (paths.backup / "old.marker").write_text("old", encoding="utf-8")

    with pytest.raises(
        VectorStoreRebuildError,
        match="backup Chroma directory already exists",
    ):
        activate_staged_vector_store(
            paths,
            build_temporary=build_marker_store,
            verify_active=lambda _path, _result: None,
            clients_stopped=True,
        )

    assert (paths.backup / "old.marker").exists()


def test_non_cosine_chroma_configuration_fails_closed(
    tmp_path: Path,
) -> None:
    class WrongMetricCollection:
        configuration = {"hnsw": {"space": "l2"}}

    class FakeClient:
        closed = False
        cache_cleared = False

        def get_or_create_collection(
            self,
            **_kwargs: object,
        ) -> WrongMetricCollection:
            return WrongMetricCollection()

        def close(self) -> None:
            self.closed = True

        def clear_system_cache(self) -> None:
            self.cache_cleared = True

    created: list[FakeClient] = []

    def client_factory(_path: str) -> FakeClient:
        client = FakeClient()
        created.append(client)
        return client

    with pytest.raises(
        VectorStoreRebuildError,
        match="cosine",
    ):
        build_vector_store(
            tmp_path,
            embeddings=FixedEmbeddings(),
            client_factory=client_factory,
        )

    assert created[0].closed is True
    assert created[0].cache_cleared is True


def test_manifest_has_exact_schema_and_count_semantics() -> None:
    manifest, documents, result = manifest_fixture()
    raw = manifest.to_dict()

    assert set(raw) == INGESTION_MANIFEST_FIELDS
    assert "document_count" not in raw
    assert raw["source_document_count"] == len(documents) == 4
    assert raw["chunk_count"] == result.chunk_count
    assert raw["chunk_count"] > raw["source_document_count"]
    assert raw["embedding_dimensions"] == 768
    assert raw["embedding_model_digest"] == TEST_MODEL_DIGEST
    assert raw["source_document_count"] != raw["chunk_count"]


def test_manifest_serialization_is_deterministic(
    tmp_path: Path,
) -> None:
    manifest, documents, result = manifest_fixture()
    first_store = tmp_path / "first"
    second_store = tmp_path / "second"
    first_store.mkdir()
    second_store.mkdir()

    first_path = write_ingestion_manifest(first_store, manifest)
    second_manifest = create_ingestion_manifest(
        tuple(reversed(documents)),
        build_result=result,
        embedding_model_digest=TEST_MODEL_DIGEST,
        package_versions=dict(reversed(
            list(TEST_PACKAGE_VERSIONS.items())
        )),
        created_at=datetime(
            2026,
            7,
            27,
            12,
            30,
            tzinfo=timezone.utc,
        ),
    )
    second_path = write_ingestion_manifest(
        second_store,
        second_manifest,
    )

    assert first_path.read_bytes() == second_path.read_bytes()
    assert load_ingestion_manifest(first_path).to_dict() == (
        manifest.to_dict()
    )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("collection_name", "other_collection"),
        ("distance_metric", "l2"),
        ("embedding_model", "other-model"),
        ("embedding_model_digest", "b" * 64),
        ("embedding_dimensions", 384),
        ("embedding_document_prefix", "document:"),
        ("embedding_query_prefix", "query:"),
        ("chunk_size", 701),
        ("chunk_overlap", 99),
        ("chunking_strategy", "other_chunking_v1"),
        ("stable_id_strategy", "other_ids_v1"),
        ("source_document_count", 5),
        ("chunk_count", 66),
        (
            "source_hashes",
            {"unexpected.md": "b" * 64},
        ),
        (
            "policy_versions",
            {"unexpected_policy": "1.0"},
        ),
        (
            "package_versions",
            {
                **TEST_PACKAGE_VERSIONS,
                "chromadb": "0.0.0",
            },
        ),
    ),
)
def test_manifest_mismatches_fail_closed(
    field_name: str,
    replacement: object,
) -> None:
    manifest, documents, result = manifest_fixture()
    changed = replace(
        manifest,
        **{field_name: replacement},
    )

    with pytest.raises(
        VectorStoreRebuildError,
        match="stale or mismatched",
    ):
        validate_ingestion_manifest(
            changed,
            documents=documents,
            expected_result=result,
            expected_model_digest=TEST_MODEL_DIGEST,
            expected_package_versions=TEST_PACKAGE_VERSIONS,
        )


def test_manifest_rejects_unknown_fields_and_absolute_paths(
    tmp_path: Path,
) -> None:
    manifest, documents, result = manifest_fixture()
    raw = manifest.to_dict()
    raw["unexpected"] = "value"
    path = tmp_path / "ingestion_manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(
        VectorStoreRebuildError,
        match="missing or unexpected",
    ):
        load_ingestion_manifest(path)

    raw = manifest.to_dict()
    raw["chunk_count"] = "67"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(
        VectorStoreRebuildError,
        match="positive integer",
    ):
        load_ingestion_manifest(path)

    unsafe_versions = dict(manifest.policy_versions)
    first_policy = next(iter(unsafe_versions))
    unsafe_versions[first_policy] = (
        "C:\\private\\runtime\\policy-version"
    )
    unsafe = replace(
        manifest,
        policy_versions=unsafe_versions,
    )

    with pytest.raises(
        VectorStoreRebuildError,
        match="policy versions",
    ):
        validate_ingestion_manifest(
            unsafe,
            documents=documents,
            expected_result=result,
            expected_model_digest=TEST_MODEL_DIGEST,
            expected_package_versions=TEST_PACKAGE_VERSIONS,
        )

    serialized = json.dumps(manifest.to_dict())
    assert str(settings.policies_dir) not in serialized
    assert ".env" not in serialized
    assert "policy body" not in serialized


def test_local_model_digest_comes_from_exact_ollama_record() -> None:
    class FakeClient:
        def __init__(self, *, host: str) -> None:
            assert host == "http://127.0.0.1:11434"

        def list(self) -> SimpleNamespace:
            return SimpleNamespace(
                models=[
                    SimpleNamespace(
                        model="other-model:latest",
                        digest="b" * 64,
                    ),
                    SimpleNamespace(
                        model="nomic-embed-text:latest",
                        digest=TEST_MODEL_DIGEST,
                    ),
                ]
            )

    assert get_local_embedding_model_digest(
        model_name="nomic-embed-text",
        base_url="http://127.0.0.1:11434",
        client_factory=FakeClient,
    ) == TEST_MODEL_DIGEST


def test_missing_or_invalid_ollama_digest_fails_closed() -> None:
    class FakeClient:
        def __init__(self, *, host: str) -> None:
            pass

        def list(self) -> SimpleNamespace:
            return SimpleNamespace(
                models=[
                    SimpleNamespace(
                        model="nomic-embed-text:latest",
                        digest="not-a-digest",
                    )
                ]
            )

    with pytest.raises(
        VectorStoreRebuildError,
        match="invalid digest",
    ):
        get_local_embedding_model_digest(
            model_name="nomic-embed-text",
            base_url="http://127.0.0.1:11434",
            client_factory=FakeClient,
        )
