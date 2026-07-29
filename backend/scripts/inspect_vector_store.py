"""Read-only integrity inspection for the active policy vector store.

Run from the backend directory:

    python scripts/inspect_vector_store.py

The command uses Chroma public read operations only. It never requests or
prints stored policy documents, embedding values, environment contents, or
absolute local paths.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import chromadb

# Direct script execution initially places backend/scripts on sys.path. Add the
# backend package root so the documented command works from backend/.
SCRIPT_FILE = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ml.ingest_policies import (  # noqa: E402
    CHUNKING_STRATEGY,
    EXPECTED_CHUNK_METADATA_FIELDS,
    INGESTION_MANIFEST_FILENAME,
    INGESTION_MANIFEST_SCHEMA_VERSION,
    STABLE_ID_STRATEGY,
    IngestionManifest,
    VectorStoreBuildResult,
    VectorStoreRebuildError,
    get_required_package_versions,
    load_ingestion_manifest,
    validate_ingestion_manifest,
)
from app.ml.policy_loader import (  # noqa: E402
    PolicyDocument,
    load_approved_policies,
)
from app.ml.policy_registry import KNOWN_POLICY_IDS  # noqa: E402
from app.ml.rag_config import (  # noqa: E402
    RagSettings,
    settings,
    validate_rag_settings,
)


class VectorStoreInspectionError(RuntimeError):
    """Raised when the active store cannot be inspected safely."""


@dataclass(frozen=True, slots=True)
class VectorStoreInspectionReport:
    """Safe, immutable summary of active vector-store integrity."""

    collection_name: str
    active_store_path: str
    manifest_schema_version: int
    configured_distance_metric: str
    actual_distance_metric: str | None
    stored_chunk_count: int
    manifest_chunk_count: int
    source_document_count: int
    embedding_model: str
    embedding_model_digest: str
    embedding_dimensions: int
    query_prefix: str
    document_prefix: str
    policy_files: tuple[str, ...]
    policy_versions: Mapping[str, str]
    chunks_per_policy: Mapping[str, int]
    distinct_section_paths: Mapping[str, int]
    duplicate_ids: int
    duplicate_content_hashes: int
    records_with_unapproved_status: int
    records_outside_known_policy_ids: int
    records_with_missing_metadata: int
    records_with_unsafe_source_paths: int
    manifest_mismatches: tuple[str, ...]
    integrity_failures: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "policy_versions",
            "chunks_per_policy",
            "distinct_section_paths",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(value)),
            )

    @property
    def passed(self) -> bool:
        """Return whether every required inspection invariant passed."""

        return not self.integrity_failures


ClientFactory = Callable[..., object]
PolicyLoader = Callable[[str | Path], Iterable[PolicyDocument]]
PackageVersionsProvider = Callable[[], Mapping[str, str]]

NONBLANK_CHUNK_METADATA_FIELDS = (
    EXPECTED_CHUNK_METADATA_FIELDS
    - {"header_1", "header_2", "header_3"}
)


@dataclass(frozen=True, slots=True)
class _RecordAnalysis:
    chunks_per_policy: Mapping[str, int]
    distinct_section_paths: Mapping[str, int]
    duplicate_ids: int
    duplicate_content_hashes: int
    unapproved_records: int
    unknown_policy_records: int
    missing_metadata_records: int
    unsafe_source_path_records: int
    stored_metadata_mismatches: tuple[str, ...]


def inspect_vector_store(
    runtime_settings: RagSettings = settings,
    *,
    client_factory: ClientFactory = chromadb.PersistentClient,
    policy_loader: PolicyLoader = load_approved_policies,
    package_versions_provider: PackageVersionsProvider = (
        get_required_package_versions
    ),
    store_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> VectorStoreInspectionReport:
    """Inspect the active store without changing it or contacting Ollama."""

    if not isinstance(runtime_settings, RagSettings):
        raise TypeError("runtime_settings must be a RagSettings instance.")

    for name, dependency in (
        ("client_factory", client_factory),
        ("policy_loader", policy_loader),
        ("package_versions_provider", package_versions_provider),
    ):
        if not callable(dependency):
            raise TypeError(f"{name} must be callable.")

    try:
        validate_rag_settings(runtime_settings)
    except Exception as exc:
        raise VectorStoreInspectionError(
            "Runtime RAG configuration is invalid."
        ) from exc

    active_store = Path(
        runtime_settings.chroma_store_dir
        if store_dir is None
        else store_dir
    ).expanduser().resolve()

    if (
        not active_store.exists()
        or not active_store.is_dir()
        or active_store.is_symlink()
    ):
        raise VectorStoreInspectionError(
            "The active Chroma store is unavailable or unsafe."
        )

    selected_manifest_path = Path(
        active_store / INGESTION_MANIFEST_FILENAME
        if manifest_path is None
        else manifest_path
    ).expanduser().resolve()

    if selected_manifest_path.parent != active_store:
        raise VectorStoreInspectionError(
            "The ingestion manifest must be inside the active store."
        )

    try:
        manifest = load_ingestion_manifest(selected_manifest_path)
        documents = tuple(policy_loader(runtime_settings.policies_dir))
        package_versions = dict(package_versions_provider())
    except Exception as exc:
        raise VectorStoreInspectionError(
            "The ingestion manifest or approved policy sources are invalid."
        ) from exc

    client: object | None = None

    try:
        client = client_factory(path=str(active_store))
        get_collection = getattr(client, "get_collection")
        collection = get_collection(
            name=runtime_settings.collection_name,
            embedding_function=None,
        )
        report = _inspect_collection(
            collection,
            manifest=manifest,
            documents=documents,
            package_versions=package_versions,
            runtime_settings=runtime_settings,
            active_store=active_store,
        )
    except VectorStoreInspectionError:
        raise
    except Exception as exc:
        raise VectorStoreInspectionError(
            "The configured Chroma collection could not be inspected."
        ) from exc
    finally:
        _release_client(client)

    return report


def print_inspection_report(
    report: VectorStoreInspectionReport,
) -> None:
    """Print a deterministic report containing no policy bodies or paths."""

    print(f"Collection name: {report.collection_name}")
    print(f"Active store path: {report.active_store_path}")
    print(
        "Manifest schema version: "
        f"{report.manifest_schema_version}"
    )
    print(
        "Configured distance metric: "
        f"{report.configured_distance_metric}"
    )
    print(
        "Actual collection distance metric: "
        f"{report.actual_distance_metric or 'unavailable'}"
    )
    print(f"Stored chunk count: {report.stored_chunk_count}")
    print(f"Manifest chunk count: {report.manifest_chunk_count}")
    print(
        "Source document count: "
        f"{report.source_document_count}"
    )
    print(f"Embedding model: {report.embedding_model}")
    print("Embedding-model digest: recorded")
    print(
        "Embedding dimensions: "
        f"{report.embedding_dimensions}"
    )
    print(f"Query prefix: {report.query_prefix}")
    print(f"Document prefix: {report.document_prefix}")
    _print_sequence("Policy files", report.policy_files)
    _print_mapping("Policy versions", report.policy_versions)
    _print_mapping("Chunks per policy", report.chunks_per_policy)
    _print_mapping(
        "Distinct section paths",
        report.distinct_section_paths,
    )
    print(f"Duplicate IDs: {report.duplicate_ids}")
    print(
        "Duplicate content hashes: "
        f"{report.duplicate_content_hashes}"
    )
    print(
        "Records with unapproved status: "
        f"{report.records_with_unapproved_status}"
    )
    print(
        "Records outside known policy IDs: "
        f"{report.records_outside_known_policy_ids}"
    )
    print(
        "Missing metadata: "
        f"{report.records_with_missing_metadata}"
    )
    print(
        "Absolute or unsafe source paths: "
        f"{report.records_with_unsafe_source_paths}"
    )
    _print_sequence(
        "Manifest mismatches",
        report.manifest_mismatches,
    )
    _print_sequence(
        "Integrity failures",
        report.integrity_failures,
    )
    print(
        "Inspection result: "
        f"{'PASS' if report.passed else 'FAIL'}"
    )


def main() -> int:
    """Run the active-store inspection and return a process exit status."""

    try:
        report = inspect_vector_store()
    except VectorStoreInspectionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "FAIL Unexpected vector-store inspection error.",
            file=sys.stderr,
        )
        return 1

    print_inspection_report(report)
    return 0 if report.passed else 1


def _inspect_collection(
    collection: object,
    *,
    manifest: IngestionManifest,
    documents: Sequence[PolicyDocument],
    package_versions: Mapping[str, str],
    runtime_settings: RagSettings,
    active_store: Path,
) -> VectorStoreInspectionReport:
    collection_name = getattr(collection, "name", None)

    if not isinstance(collection_name, str) or not collection_name.strip():
        raise VectorStoreInspectionError(
            "Chroma returned an invalid collection name."
        )

    count_method = getattr(collection, "count", None)
    get_method = getattr(collection, "get", None)

    if not callable(count_method) or not callable(get_method):
        raise VectorStoreInspectionError(
            "Chroma collection does not expose required read operations."
        )

    stored_count = count_method()

    if (
        isinstance(stored_count, bool)
        or not isinstance(stored_count, int)
        or stored_count < 0
    ):
        raise VectorStoreInspectionError(
            "Chroma returned an invalid stored chunk count."
        )

    stored = get_method(
        limit=max(1, stored_count),
        include=["metadatas"],
    )

    if not isinstance(stored, Mapping):
        raise VectorStoreInspectionError(
            "Chroma returned malformed stored metadata."
        )

    ids = stored.get("ids")
    metadatas = stored.get("metadatas")

    if (
        not isinstance(ids, list)
        or not isinstance(metadatas, list)
        or len(ids) != stored_count
        or len(metadatas) != stored_count
        or any(not isinstance(record_id, str) for record_id in ids)
    ):
        raise VectorStoreInspectionError(
            "Chroma returned malformed stored IDs or metadata."
        )

    actual_dimensions = _read_embedding_dimensions(
        get_method,
        stored_count=stored_count,
    )
    actual_metric = _read_distance_metric(collection)
    record_analysis = _analyze_records(
        ids,
        metadatas,
        manifest=manifest,
    )

    build_result = VectorStoreBuildResult(
        chunk_count=stored_count,
        embedding_dimensions=actual_dimensions,
        record_ids=tuple(ids),
        manifest=manifest,
    )
    manifest_mismatches = list(
        record_analysis.stored_metadata_mismatches
    )

    try:
        validate_ingestion_manifest(
            manifest,
            documents=documents,
            expected_result=build_result,
            expected_model_digest=manifest.embedding_model_digest,
            runtime_settings=runtime_settings,
            expected_package_versions=package_versions,
        )
    except (VectorStoreRebuildError, TypeError) as exc:
        manifest_mismatches.append(_safe_mismatch_message(exc))

    for field_name, actual, expected in (
        (
            "collection name",
            collection_name,
            manifest.collection_name,
        ),
        (
            "configured collection name",
            runtime_settings.collection_name,
            manifest.collection_name,
        ),
        (
            "collection distance metric",
            actual_metric,
            manifest.distance_metric,
        ),
        (
            "configured distance metric",
            runtime_settings.chroma_distance_metric,
            manifest.distance_metric,
        ),
        (
            "stored embedding dimensions",
            actual_dimensions,
            manifest.embedding_dimensions,
        ),
    ):
        if actual != expected:
            manifest_mismatches.append(
                f"{field_name} differs from the manifest"
            )

    manifest_mismatches = sorted(set(manifest_mismatches))
    failures: list[str] = []

    if stored_count != manifest.chunk_count:
        failures.append(
            "manifest and collection chunk counts differ"
        )
    if record_analysis.duplicate_ids:
        failures.append("duplicate record IDs exist")
    if record_analysis.unapproved_records:
        failures.append("unapproved records exist")
    if record_analysis.unknown_policy_records:
        failures.append("records outside known policy IDs exist")
    if record_analysis.missing_metadata_records:
        failures.append("records have missing or malformed metadata")
    if record_analysis.unsafe_source_path_records:
        failures.append("records contain unsafe source paths")
    if manifest_mismatches:
        failures.append(
            "collection or runtime ingestion facts differ from the manifest"
        )

    return VectorStoreInspectionReport(
        collection_name=collection_name,
        active_store_path=_safe_store_path(active_store),
        manifest_schema_version=manifest.schema_version,
        configured_distance_metric=(
            runtime_settings.chroma_distance_metric
        ),
        actual_distance_metric=actual_metric,
        stored_chunk_count=stored_count,
        manifest_chunk_count=manifest.chunk_count,
        source_document_count=manifest.source_document_count,
        embedding_model=manifest.embedding_model,
        embedding_model_digest=manifest.embedding_model_digest,
        embedding_dimensions=manifest.embedding_dimensions,
        query_prefix=manifest.embedding_query_prefix,
        document_prefix=manifest.embedding_document_prefix,
        policy_files=tuple(sorted(manifest.source_hashes)),
        policy_versions=dict(sorted(manifest.policy_versions.items())),
        chunks_per_policy=record_analysis.chunks_per_policy,
        distinct_section_paths=(
            record_analysis.distinct_section_paths
        ),
        duplicate_ids=record_analysis.duplicate_ids,
        duplicate_content_hashes=(
            record_analysis.duplicate_content_hashes
        ),
        records_with_unapproved_status=(
            record_analysis.unapproved_records
        ),
        records_outside_known_policy_ids=(
            record_analysis.unknown_policy_records
        ),
        records_with_missing_metadata=(
            record_analysis.missing_metadata_records
        ),
        records_with_unsafe_source_paths=(
            record_analysis.unsafe_source_path_records
        ),
        manifest_mismatches=tuple(manifest_mismatches),
        integrity_failures=tuple(failures),
    )


def _analyze_records(
    ids: Sequence[str],
    metadatas: Sequence[object],
    *,
    manifest: IngestionManifest,
) -> _RecordAnalysis:
    id_counts = Counter(ids)
    content_hash_counts: Counter[str] = Counter()
    chunks_per_policy: Counter[str] = Counter()
    section_paths: dict[str, set[str]] = defaultdict(set)
    unapproved = 0
    unknown = 0
    missing = 0
    unsafe_paths = 0
    stored_mismatches: set[str] = set()

    for metadata in metadatas:
        if not isinstance(metadata, Mapping):
            missing += 1
            continue

        missing_fields = EXPECTED_CHUNK_METADATA_FIELDS - set(metadata)
        malformed_fields = any(
            metadata.get(field_name) is None
            or (
                isinstance(metadata.get(field_name), str)
                and not str(metadata.get(field_name)).strip()
            )
            for field_name in NONBLANK_CHUNK_METADATA_FIELDS
        )

        if missing_fields or malformed_fields:
            missing += 1

        status = metadata.get("status")
        if status is not None and status != "approved":
            unapproved += 1

        document_id = metadata.get("document_id")
        if isinstance(document_id, str) and document_id.strip():
            chunks_per_policy[document_id] += 1

            if document_id not in KNOWN_POLICY_IDS:
                unknown += 1

            section_path = metadata.get("section_path")
            if isinstance(section_path, str) and section_path.strip():
                section_paths[document_id].add(section_path)

            stored_version = metadata.get("version")
            expected_version = manifest.policy_versions.get(document_id)
            if (
                expected_version is not None
                and stored_version != expected_version
            ):
                stored_mismatches.add(
                    "stored policy versions differ from the manifest"
                )

        content_hash = metadata.get("content_hash")
        if isinstance(content_hash, str) and content_hash.strip():
            content_hash_counts[content_hash] += 1

        source_file = metadata.get("source_file")
        if isinstance(source_file, str) and source_file.strip():
            if not _is_safe_source_file(source_file):
                unsafe_paths += 1
            elif source_file not in manifest.source_hashes:
                stored_mismatches.add(
                    "stored policy files differ from the manifest"
                )

            expected_source_hash = manifest.source_hashes.get(source_file)
            if (
                expected_source_hash is not None
                and metadata.get("source_hash")
                != expected_source_hash
            ):
                stored_mismatches.add(
                    "stored source hashes differ from the manifest"
                )

    duplicate_ids = sum(
        count - 1
        for count in id_counts.values()
        if count > 1
    )
    duplicate_content_hashes = sum(
        count - 1
        for count in content_hash_counts.values()
        if count > 1
    )
    ordered_policy_ids = sorted(
        set(manifest.policy_versions) | set(chunks_per_policy)
    )

    return _RecordAnalysis(
        chunks_per_policy={
            policy_id: chunks_per_policy.get(policy_id, 0)
            for policy_id in ordered_policy_ids
        },
        distinct_section_paths={
            policy_id: len(section_paths.get(policy_id, set()))
            for policy_id in ordered_policy_ids
        },
        duplicate_ids=duplicate_ids,
        duplicate_content_hashes=duplicate_content_hashes,
        unapproved_records=unapproved,
        unknown_policy_records=unknown,
        missing_metadata_records=missing,
        unsafe_source_path_records=unsafe_paths,
        stored_metadata_mismatches=tuple(sorted(stored_mismatches)),
    )


def _read_embedding_dimensions(
    get_method: Callable[..., object],
    *,
    stored_count: int,
) -> int:
    if stored_count < 1:
        return 0

    result = get_method(limit=1, include=["embeddings"])

    if not isinstance(result, Mapping):
        raise VectorStoreInspectionError(
            "Chroma returned malformed stored embeddings."
        )

    embeddings = result.get("embeddings")

    try:
        sample = embeddings[0]  # type: ignore[index]
        dimensions = len(sample)
    except (IndexError, KeyError, TypeError) as exc:
        raise VectorStoreInspectionError(
            "Chroma returned malformed stored embeddings."
        ) from exc

    if dimensions < 1:
        raise VectorStoreInspectionError(
            "Chroma returned an empty stored embedding."
        )

    return dimensions


def _read_distance_metric(collection: object) -> str | None:
    configuration = getattr(collection, "configuration", None)

    if not isinstance(configuration, Mapping):
        return None

    hnsw = configuration.get("hnsw")

    if not isinstance(hnsw, Mapping):
        return None

    metric = hnsw.get("space")
    return metric if isinstance(metric, str) and metric.strip() else None


def _is_safe_source_file(value: str) -> bool:
    return (
        Path(value).name == value
        and "/" not in value
        and "\\" not in value
        and not Path(value).is_absolute()
    )


def _safe_store_path(active_store: Path) -> str:
    try:
        relative = active_store.relative_to(BACKEND_DIR)
    except ValueError:
        return "<external-store>"

    return relative.as_posix()


def _safe_mismatch_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())

    if not message:
        return "manifest validation failed"

    if "stale or mismatched:" in message:
        field_name = message.rsplit(":", maxsplit=1)[-1].rstrip(". ")
        return f"runtime {field_name} differs from the manifest"

    if "build result is inconsistent" in message:
        return "stored record identities differ from the manifest"

    return "manifest validation failed"


def _print_mapping(
    label: str,
    values: Mapping[str, object],
) -> None:
    print(f"{label}:")

    if not values:
        print("  None")
        return

    for key, value in sorted(values.items()):
        print(f"  {key}: {value}")


def _print_sequence(
    label: str,
    values: Sequence[str],
) -> None:
    print(f"{label}:")

    if not values:
        print("  None")
        return

    for value in values:
        print(f"  {value}")


def _release_client(client: object | None) -> None:
    if client is None:
        return

    for method_name in ("close", "clear_system_cache"):
        method = getattr(client, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
