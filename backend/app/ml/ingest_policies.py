"""Deterministic policy chunking and staged Chroma ingestion."""

from __future__ import annotations

import gc
import json
import re
import shutil
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Protocol

import chromadb
import ollama
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.ml.embeddings import get_embeddings
from app.ml.policy_loader import (
    PolicyDocument,
    PolicyValidationError,
    SHA256_PATTERN,
    compute_content_hash,
    load_approved_policies,
    normalize_chunk_content,
    validate_unique_document_ids,
)
from app.ml.rag_config import RagSettings, settings


MetadataValue = str | int

HEADERS_TO_SPLIT_ON: tuple[tuple[str, str], ...] = (
    ("#", "header_1"),
    ("##", "header_2"),
    ("###", "header_3"),
)

BASE_METADATA_FIELDS: tuple[str, ...] = (
    "document_id",
    "source_file",
    "title",
    "version",
    "effective_date",
    "review_date",
    "owner",
    "status",
    "policy_type",
    "product",
    "jurisdiction",
    "source_hash",
)

DERIVED_CHUNK_METADATA_FIELDS: tuple[str, ...] = (
    "header_1",
    "header_2",
    "header_3",
    "section_path",
    "content_hash",
    "chunk_index",
)

EXPECTED_CHUNK_METADATA_FIELDS: frozenset[str] = frozenset(
    (
        *BASE_METADATA_FIELDS,
        *DERIVED_CHUNK_METADATA_FIELDS,
    )
)

SAFE_RECORD_ID_PATTERN = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
)
MARKDOWN_HEADING_PATTERN = re.compile(r"^#{1,3}\s+\S")
UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)

INGESTION_MANIFEST_SCHEMA_VERSION = 2
INGESTION_MANIFEST_FILENAME = settings.ingestion_manifest_path.name
CHUNKING_STRATEGY = "markdown_headers_then_recursive_v1"
STABLE_ID_STRATEGY = "document_section_chunkhash_v1"
REQUIRED_PACKAGE_NAMES: tuple[str, ...] = (
    "chromadb",
    "langchain-chroma",
    "langchain-ollama",
    "langchain-text-splitters",
)
INGESTION_MANIFEST_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",
        "collection_name",
        "distance_metric",
        "embedding_model",
        "embedding_model_digest",
        "embedding_dimensions",
        "embedding_document_prefix",
        "embedding_query_prefix",
        "chunk_size",
        "chunk_overlap",
        "chunking_strategy",
        "stable_id_strategy",
        "source_document_count",
        "chunk_count",
        "created_at",
        "source_hashes",
        "policy_versions",
        "package_versions",
    }
)


class PolicyChunkingError(PolicyValidationError):
    """Raised when validated policies cannot be chunked safely."""


class VectorStoreRebuildError(RuntimeError):
    """Raised when a staged vector-store rebuild cannot complete safely."""


@dataclass(frozen=True, slots=True)
class PolicyChunk:
    """
    One immutable, validated policy chunk prepared for later ingestion.

    ``chunk_id`` is passed to Chroma as the record ID in Step 15.  It is kept
    separate from metadata so identity has one authoritative representation.
    """

    chunk_id: str
    content: str = field(repr=False)
    metadata: Mapping[str, MetadataValue]

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise TypeError("PolicyChunk metadata must be a mapping.")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    @property
    def document_id(self) -> str:
        return str(self.metadata["document_id"])

    @property
    def section_path(self) -> str:
        return str(self.metadata["section_path"])

    @property
    def content_hash(self) -> str:
        return str(self.metadata["content_hash"])

    @property
    def chunk_index(self) -> int:
        return int(self.metadata["chunk_index"])

    def storage_metadata(self) -> dict[str, MetadataValue]:
        """Return a mutable metadata copy safe for later storage."""

        return dict(self.metadata)


@dataclass(frozen=True, slots=True)
class _ChunkDraft:
    """Internal chunk representation before stable IDs are assigned."""

    content: str
    metadata: Mapping[str, MetadataValue]


@dataclass(frozen=True, slots=True)
class IngestionManifest:
    """Immutable schema-version-2 facts for one vector-store build."""

    schema_version: int
    collection_name: str
    distance_metric: str
    embedding_model: str
    embedding_model_digest: str
    embedding_dimensions: int
    embedding_document_prefix: str
    embedding_query_prefix: str
    chunk_size: int
    chunk_overlap: int
    chunking_strategy: str
    stable_id_strategy: str
    source_document_count: int
    chunk_count: int
    created_at: str
    source_hashes: Mapping[str, str]
    policy_versions: Mapping[str, str]
    package_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        for field_name in (
            "source_hashes",
            "policy_versions",
            "package_versions",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, Mapping):
                raise TypeError(f"{field_name} must be a mapping.")

            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(value)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "collection_name": self.collection_name,
            "distance_metric": self.distance_metric,
            "embedding_model": self.embedding_model,
            "embedding_model_digest": self.embedding_model_digest,
            "embedding_dimensions": self.embedding_dimensions,
            "embedding_document_prefix": self.embedding_document_prefix,
            "embedding_query_prefix": self.embedding_query_prefix,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunking_strategy": self.chunking_strategy,
            "stable_id_strategy": self.stable_id_strategy,
            "source_document_count": self.source_document_count,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at,
            "source_hashes": dict(self.source_hashes),
            "policy_versions": dict(self.policy_versions),
            "package_versions": dict(self.package_versions),
        }


@dataclass(frozen=True, slots=True)
class VectorStoreBuildResult:
    """Validated facts needed across the activation boundary."""

    chunk_count: int
    embedding_dimensions: int
    record_ids: tuple[str, ...]
    manifest: IngestionManifest | None = None


@dataclass(frozen=True, slots=True)
class VectorStorePaths:
    """Distinct sibling paths used by the staged rebuild."""

    active: Path
    temporary: Path
    backup: Path

    @classmethod
    def from_settings(
        cls,
        runtime_settings: RagSettings = settings,
    ) -> "VectorStorePaths":
        return cls(
            active=runtime_settings.chroma_store_dir,
            temporary=runtime_settings.chroma_temp_dir,
            backup=runtime_settings.chroma_backup_dir,
        )

    def validated(self) -> "VectorStorePaths":
        resolved = VectorStorePaths(
            active=self.active.expanduser().resolve(),
            temporary=self.temporary.expanduser().resolve(),
            backup=self.backup.expanduser().resolve(),
        )
        paths = (
            resolved.active,
            resolved.temporary,
            resolved.backup,
        )

        if len(set(paths)) != 3:
            raise VectorStoreRebuildError(
                "Active, temporary, and backup store paths must be distinct."
            )

        if len({path.parent for path in paths}) != 1:
            raise VectorStoreRebuildError(
                "Staged store paths must be sibling directories."
            )

        if any(path == path.parent for path in paths):
            raise VectorStoreRebuildError(
                "A staged store path cannot be a filesystem root."
            )

        if any(path.exists() and path.is_symlink() for path in paths):
            raise VectorStoreRebuildError(
                "Staged store paths cannot be symbolic links."
            )

        return resolved


class _Collection(Protocol):
    configuration: Mapping[str, Any]

    def add(self, **kwargs: Any) -> None: ...
    def count(self) -> int: ...
    def get(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def query(self, **kwargs: Any) -> Mapping[str, Any]: ...


class _ChromaClient(Protocol):
    def get_max_batch_size(self) -> int: ...
    def get_or_create_collection(self, **kwargs: Any) -> _Collection: ...
    def get_collection(self, **kwargs: Any) -> _Collection: ...
    def close(self) -> None: ...
    def clear_system_cache(self) -> None: ...


ClientFactory = Callable[[str], _ChromaClient]


def normalize_identity_text(value: str) -> str:
    """Normalize identity text without changing stored display metadata."""

    if not isinstance(value, str):
        raise TypeError("Stable-ID identity text must be a string.")

    return " ".join(value.split())


def slugify_identity_component(value: str) -> str:
    """Return a deterministic lowercase ASCII slug for one ID component."""

    normalized = normalize_identity_text(value)

    if not normalized:
        raise PolicyChunkingError(
            "Stable-ID identity components cannot be blank."
        )

    ascii_text = (
        unicodedata.normalize("NFKD", normalized)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")

    if not slug:
        raise PolicyChunkingError(
            "Stable-ID identity component has no safe ASCII characters."
        )

    return slug


def build_stable_chunk_id(
    *,
    document_id: str,
    section_path: str,
    content_hash: str,
    occurrence: int = 1,
) -> str:
    """
    Build a stable vector-record ID independent of ``chunk_index``.

    Repeated identical content in the same section receives ``-02``, ``-03``,
    and so on.  The first occurrence has no suffix.
    """

    if not isinstance(content_hash, str):
        raise TypeError("content_hash must be a string.")

    normalized_hash = content_hash.strip()

    if SHA256_PATTERN.fullmatch(normalized_hash) is None:
        raise PolicyChunkingError(
            "Stable IDs require a complete lowercase SHA-256 content hash."
        )

    if isinstance(occurrence, bool) or not isinstance(occurrence, int):
        raise TypeError("occurrence must be an integer.")

    if occurrence < 1:
        raise PolicyChunkingError(
            "Stable-ID occurrence must be at least 1."
        )

    document_slug = slugify_identity_component(document_id)
    section_slug = slugify_identity_component(section_path)
    record_id = (
        f"{document_slug}-{section_slug}-{normalized_hash[:12]}"
    )

    if occurrence > 1:
        record_id = f"{record_id}-{occurrence:02d}"

    _validate_record_id(record_id)
    return record_id


def split_policy_document(
    document: PolicyDocument,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> tuple[PolicyChunk, ...]:
    """
    Split one validated policy using Markdown headings, then size limits.

    Production callers should omit the size arguments so the validated central
    settings are used.  Explicit values support deterministic unit testing.
    """

    base_metadata = _validated_base_metadata(document)
    resolved_size, resolved_overlap = _resolve_chunk_settings(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=list(HEADERS_TO_SPLIT_ON),
        strip_headers=False,
    )
    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=resolved_size,
        chunk_overlap=resolved_overlap,
    )

    try:
        sections = header_splitter.split_text(document.body)
        canonical_sections = [
            Document(
                page_content=_canonicalize_section_content(
                    section.page_content,
                    headers=_headers_from_metadata(
                        section.metadata
                    ),
                ),
                metadata=dict(section.metadata),
            )
            for section in sections
        ]
        split_sections = recursive_splitter.split_documents(
            canonical_sections
        )
    except (TypeError, ValueError) as exc:
        raise PolicyChunkingError(
            f"{document.source_file}: policy splitting failed: {exc}"
        ) from exc

    drafts: list[_ChunkDraft] = []

    for split_section in split_sections:
        try:
            content = normalize_chunk_content(
                split_section.page_content
            )
        except PolicyValidationError:
            # Splitters may produce whitespace-only fragments around headings.
            # Such fragments carry no retrievable policy meaning.
            continue

        headers = _headers_from_metadata(
            split_section.metadata
        )
        section_path = _build_section_path(
            headers=headers,
            fallback_title=base_metadata["title"],
        )
        content_hash = compute_content_hash(content)
        chunk_index = len(drafts)

        chunk_metadata: dict[str, MetadataValue] = {
            **base_metadata,
            "header_1": headers[0],
            "header_2": headers[1],
            "header_3": headers[2],
            "section_path": section_path,
            "content_hash": content_hash,
            "chunk_index": chunk_index,
        }

        drafts.append(
            _ChunkDraft(
                content=content,
                metadata=MappingProxyType(chunk_metadata),
            )
        )

    if not drafts:
        raise PolicyChunkingError(
            f"{document.source_file}: policy produced no nonblank chunks."
        )

    chunks = _assign_stable_ids(drafts)
    validate_policy_chunks(chunks)
    return chunks


def split_policy_documents(
    documents: Iterable[PolicyDocument],
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> tuple[PolicyChunk, ...]:
    """Split a validated policy collection in deterministic input order."""

    document_tuple = tuple(documents)

    if not document_tuple:
        raise PolicyChunkingError(
            "At least one validated policy document is required."
        )

    for document in document_tuple:
        if not isinstance(document, PolicyDocument):
            raise TypeError(
                "Policy collections may contain only PolicyDocument objects."
            )

    validate_unique_document_ids(document_tuple)

    chunks = tuple(
        chunk
        for document in document_tuple
        for chunk in split_policy_document(
            document,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    )

    validate_policy_chunks(chunks)
    return chunks


def validate_policy_chunks(
    chunks: Iterable[PolicyChunk],
) -> None:
    """Fail closed when final chunks or stable IDs are malformed."""

    chunk_tuple = tuple(chunks)

    if not chunk_tuple:
        raise PolicyChunkingError(
            "At least one policy chunk is required."
        )

    seen_ids: set[str] = set()
    indices_by_document: dict[str, list[int]] = {}
    occurrence_by_base_id: dict[str, int] = {}

    for chunk in chunk_tuple:
        if not isinstance(chunk, PolicyChunk):
            raise TypeError(
                "Chunk collections may contain only PolicyChunk objects."
            )

        _validate_record_id(chunk.chunk_id)

        if chunk.chunk_id in seen_ids:
            raise PolicyChunkingError(
                f"Duplicate stable chunk ID: {chunk.chunk_id!r}."
            )

        seen_ids.add(chunk.chunk_id)
        normalized_content = normalize_chunk_content(chunk.content)

        if normalized_content != chunk.content:
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: chunk content is not normalized."
            )

        metadata = dict(chunk.metadata)

        if set(metadata) != EXPECTED_CHUNK_METADATA_FIELDS:
            missing = sorted(
                EXPECTED_CHUNK_METADATA_FIELDS - set(metadata)
            )
            unexpected = sorted(
                set(metadata) - EXPECTED_CHUNK_METADATA_FIELDS
            )
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: invalid metadata fields; "
                f"missing={missing}, unexpected={unexpected}."
            )

        if metadata["status"] != "approved":
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: chunk policy is not approved."
            )

        if metadata["jurisdiction"] != "fictional_prototype":
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: chunk jurisdiction is invalid."
            )

        source_file = str(metadata["source_file"])

        if (
            not source_file
            or "/" in source_file
            or "\\" in source_file
        ):
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: source_file is not a safe basename."
            )

        if (
            SHA256_PATTERN.fullmatch(str(metadata["source_hash"]))
            is None
        ):
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: source_hash is invalid."
            )

        expected_content_hash = compute_content_hash(chunk.content)

        if metadata["content_hash"] != expected_content_hash:
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: content_hash does not match content."
            )

        section_path = str(metadata["section_path"]).strip()

        if not section_path:
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: section_path cannot be blank."
            )

        expected_base_id = build_stable_chunk_id(
            document_id=str(metadata["document_id"]),
            section_path=section_path,
            content_hash=expected_content_hash,
        )

        if not (
            chunk.chunk_id == expected_base_id
            or _has_valid_occurrence_suffix(
                chunk.chunk_id,
                expected_base_id,
            )
        ):
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: ID does not match chunk identity."
            )

        occurrence = (
            1
            if chunk.chunk_id == expected_base_id
            else int(
                chunk.chunk_id[
                    len(expected_base_id) + 1:
                ]
            )
        )
        expected_occurrence = (
            occurrence_by_base_id.get(expected_base_id, 0) + 1
        )

        if occurrence != expected_occurrence:
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: expected stable-ID occurrence "
                f"{expected_occurrence:02d}."
            )

        occurrence_by_base_id[expected_base_id] = occurrence
        chunk_index = metadata["chunk_index"]

        if (
            isinstance(chunk_index, bool)
            or not isinstance(chunk_index, int)
            or chunk_index < 0
        ):
            raise PolicyChunkingError(
                f"{chunk.chunk_id}: chunk_index must be a "
                "non-negative integer."
            )

        indices_by_document.setdefault(
            str(metadata["document_id"]),
            [],
        ).append(chunk_index)

    for document_id, indices in indices_by_document.items():
        if indices != list(range(len(indices))):
            raise PolicyChunkingError(
                f"{document_id}: chunk indices must be contiguous "
                "and start at zero."
            )


def get_local_embedding_model_digest(
    *,
    model_name: str,
    base_url: str,
    client_factory: Callable[..., Any] = ollama.Client,
) -> str:
    """Return the real digest for the exact configured local Ollama model."""

    try:
        response = client_factory(host=base_url).list()
    except Exception as exc:
        raise VectorStoreRebuildError(
            "Unable to read installed models from local Ollama."
        ) from exc

    models = _record_value(response, "models")

    if not isinstance(models, list):
        raise VectorStoreRebuildError(
            "Ollama installed-model response is malformed."
        )

    matches: list[str] = []

    for model in models:
        installed_name = _record_value(model, "model")
        digest = _record_value(model, "digest")

        if not isinstance(installed_name, str):
            continue

        if not _model_names_match(model_name, installed_name):
            continue

        if (
            not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise VectorStoreRebuildError(
                "The installed embedding model has an invalid digest."
            )

        matches.append(digest)

    if len(matches) != 1:
        raise VectorStoreRebuildError(
            "The exact configured embedding model must appear once in the "
            "local Ollama installed-model response."
        )

    return matches[0]


def get_required_package_versions() -> dict[str, str]:
    """Read the installed versions that affect ingestion compatibility."""

    versions: dict[str, str] = {}

    for name in REQUIRED_PACKAGE_NAMES:
        try:
            installed = package_version(name)
        except PackageNotFoundError as exc:
            raise VectorStoreRebuildError(
                f"Required package version is unavailable: {name}."
            ) from exc

        if not installed.strip():
            raise VectorStoreRebuildError(
                f"Required package version is blank: {name}."
            )

        versions[name] = installed

    return versions


def create_ingestion_manifest(
    documents: Iterable[PolicyDocument],
    *,
    build_result: VectorStoreBuildResult,
    embedding_model_digest: str,
    runtime_settings: RagSettings = settings,
    package_versions: Mapping[str, str] | None = None,
    created_at: datetime | None = None,
) -> IngestionManifest:
    """Create and validate a manifest from actual runtime build facts."""

    document_tuple = tuple(documents)
    validate_unique_document_ids(document_tuple)

    if not document_tuple:
        raise VectorStoreRebuildError(
            "At least one policy document is required for the manifest."
        )

    timestamp = created_at or datetime.now(timezone.utc)

    if timestamp.tzinfo is None:
        raise VectorStoreRebuildError(
            "Manifest creation time must be timezone-aware."
        )

    timestamp = timestamp.astimezone(timezone.utc).replace(microsecond=0)
    installed_versions = dict(
        package_versions
        if package_versions is not None
        else get_required_package_versions()
    )
    manifest = IngestionManifest(
        schema_version=INGESTION_MANIFEST_SCHEMA_VERSION,
        collection_name=runtime_settings.collection_name,
        distance_metric=runtime_settings.chroma_distance_metric,
        embedding_model=runtime_settings.embedding_model,
        embedding_model_digest=embedding_model_digest,
        embedding_dimensions=build_result.embedding_dimensions,
        embedding_document_prefix=(
            runtime_settings.embedding_document_prefix
        ),
        embedding_query_prefix=runtime_settings.embedding_query_prefix,
        chunk_size=runtime_settings.chunk_size,
        chunk_overlap=runtime_settings.chunk_overlap,
        chunking_strategy=CHUNKING_STRATEGY,
        stable_id_strategy=STABLE_ID_STRATEGY,
        source_document_count=len(document_tuple),
        chunk_count=build_result.chunk_count,
        created_at=timestamp.isoformat().replace("+00:00", "Z"),
        source_hashes={
            document.source_file: document.source_hash
            for document in sorted(
                document_tuple,
                key=lambda item: item.source_file.casefold(),
            )
        },
        policy_versions={
            document.document_id: str(document.metadata["version"])
            for document in sorted(
                document_tuple,
                key=lambda item: item.document_id,
            )
        },
        package_versions=installed_versions,
    )
    validate_ingestion_manifest(
        manifest,
        documents=document_tuple,
        expected_result=build_result,
        expected_model_digest=embedding_model_digest,
        runtime_settings=runtime_settings,
        expected_package_versions=installed_versions,
    )
    return manifest


def validate_ingestion_manifest(
    manifest: IngestionManifest,
    *,
    documents: Iterable[PolicyDocument],
    expected_result: VectorStoreBuildResult,
    expected_model_digest: str,
    runtime_settings: RagSettings = settings,
    expected_package_versions: Mapping[str, str] | None = None,
) -> None:
    """Fail closed when a manifest is malformed, unsafe, or stale."""

    if not isinstance(manifest, IngestionManifest):
        raise TypeError(
            "Manifest validation requires an IngestionManifest."
        )

    _validate_manifest_shape(manifest)
    document_tuple = tuple(documents)
    validate_unique_document_ids(document_tuple)
    expected_versions = dict(
        expected_package_versions
        if expected_package_versions is not None
        else get_required_package_versions()
    )
    expected_source_hashes = {
        document.source_file: document.source_hash
        for document in document_tuple
    }
    expected_policy_versions = {
        document.document_id: str(document.metadata["version"])
        for document in document_tuple
    }
    expected_values: dict[str, Any] = {
        "schema_version": INGESTION_MANIFEST_SCHEMA_VERSION,
        "collection_name": runtime_settings.collection_name,
        "distance_metric": runtime_settings.chroma_distance_metric,
        "embedding_model": runtime_settings.embedding_model,
        "embedding_model_digest": expected_model_digest,
        "embedding_dimensions": expected_result.embedding_dimensions,
        "embedding_document_prefix": (
            runtime_settings.embedding_document_prefix
        ),
        "embedding_query_prefix": runtime_settings.embedding_query_prefix,
        "chunk_size": runtime_settings.chunk_size,
        "chunk_overlap": runtime_settings.chunk_overlap,
        "chunking_strategy": CHUNKING_STRATEGY,
        "stable_id_strategy": STABLE_ID_STRATEGY,
        "source_document_count": len(document_tuple),
        "chunk_count": expected_result.chunk_count,
        "source_hashes": expected_source_hashes,
        "policy_versions": expected_policy_versions,
        "package_versions": expected_versions,
    }

    for field_name, expected in expected_values.items():
        actual = getattr(manifest, field_name)

        if isinstance(actual, Mapping):
            actual = dict(actual)

        if actual != expected:
            raise VectorStoreRebuildError(
                f"Ingestion manifest is stale or mismatched: {field_name}."
            )

    if (
        expected_result.chunk_count < 1
        or expected_result.embedding_dimensions < 1
        or len(expected_result.record_ids)
        != expected_result.chunk_count
        or len(set(expected_result.record_ids))
        != expected_result.chunk_count
    ):
        raise VectorStoreRebuildError(
            "Vector-store build result is inconsistent."
        )


def write_ingestion_manifest(
    store_dir: str | Path,
    manifest: IngestionManifest,
) -> Path:
    """Write a validated manifest deterministically inside a staged store."""

    _validate_manifest_shape(manifest)
    directory = Path(store_dir).expanduser().resolve()

    if not directory.exists() or not directory.is_dir():
        raise VectorStoreRebuildError(
            "Manifest store directory does not exist."
        )

    target = directory / INGESTION_MANIFEST_FILENAME
    temporary = directory / f"{INGESTION_MANIFEST_FILENAME}.tmp"
    serialized = json.dumps(
        manifest.to_dict(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"

    try:
        temporary.write_text(serialized, encoding="utf-8", newline="\n")
        temporary.replace(target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise VectorStoreRebuildError(
            "Unable to write the ingestion manifest."
        ) from exc

    return target


def load_ingestion_manifest(
    manifest_path: str | Path,
) -> IngestionManifest:
    """Load a strict schema-version-2 ingestion manifest."""

    path = Path(manifest_path).expanduser()

    if not path.exists() or not path.is_file():
        raise VectorStoreRebuildError(
            "Ingestion manifest does not exist."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VectorStoreRebuildError(
            "Ingestion manifest is not valid UTF-8 JSON."
        ) from exc

    if not isinstance(raw, dict) or set(raw) != INGESTION_MANIFEST_FIELDS:
        raise VectorStoreRebuildError(
            "Ingestion manifest fields are missing or unexpected."
        )

    try:
        manifest = IngestionManifest(**raw)
    except (TypeError, ValueError) as exc:
        raise VectorStoreRebuildError(
            "Ingestion manifest has invalid field values."
        ) from exc

    _validate_manifest_shape(manifest)
    return manifest


def _validate_manifest_shape(
    manifest: IngestionManifest,
) -> None:
    raw = manifest.to_dict()

    if set(raw) != INGESTION_MANIFEST_FIELDS:
        raise VectorStoreRebuildError(
            "Ingestion manifest fields are missing or unexpected."
        )

    positive_integer_fields = (
        "schema_version",
        "embedding_dimensions",
        "chunk_size",
        "source_document_count",
        "chunk_count",
    )

    for field_name in positive_integer_fields:
        value = raw[field_name]

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise VectorStoreRebuildError(
                f"Ingestion manifest field must be a positive integer: "
                f"{field_name}."
            )

    overlap = raw["chunk_overlap"]

    if (
        isinstance(overlap, bool)
        or not isinstance(overlap, int)
        or overlap < 0
        or overlap >= raw["chunk_size"]
    ):
        raise VectorStoreRebuildError(
            "Ingestion manifest chunk_overlap is invalid."
        )

    string_fields = (
        "collection_name",
        "distance_metric",
        "embedding_model",
        "embedding_model_digest",
        "embedding_document_prefix",
        "embedding_query_prefix",
        "chunking_strategy",
        "stable_id_strategy",
        "created_at",
    )

    for field_name in string_fields:
        value = raw[field_name]

        if not isinstance(value, str) or not value.strip():
            raise VectorStoreRebuildError(
                f"Ingestion manifest field must be nonblank text: "
                f"{field_name}."
            )

        if _looks_like_absolute_path(value):
            raise VectorStoreRebuildError(
                "Ingestion manifest cannot contain absolute paths."
            )

    if (
        SHA256_PATTERN.fullmatch(
            str(raw["embedding_model_digest"])
        )
        is None
    ):
        raise VectorStoreRebuildError(
            "Ingestion manifest embedding model digest is invalid."
        )

    timestamp = str(raw["created_at"])

    if UTC_TIMESTAMP_PATTERN.fullmatch(timestamp) is None:
        raise VectorStoreRebuildError(
            "Ingestion manifest created_at must be canonical UTC."
        )

    try:
        parsed_timestamp = datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise VectorStoreRebuildError(
            "Ingestion manifest created_at is invalid."
        ) from exc

    if parsed_timestamp.utcoffset() != timezone.utc.utcoffset(None):
        raise VectorStoreRebuildError(
            "Ingestion manifest created_at must use UTC."
        )

    source_hashes = raw["source_hashes"]
    policy_versions = raw["policy_versions"]
    package_versions = raw["package_versions"]

    if not all(
        isinstance(mapping, dict) and mapping
        for mapping in (
            source_hashes,
            policy_versions,
            package_versions,
        )
    ):
        raise VectorStoreRebuildError(
            "Ingestion manifest mappings must be nonempty objects."
        )

    for source_file, source_hash in source_hashes.items():
        if (
            not isinstance(source_file, str)
            or not source_file
            or Path(source_file).name != source_file
            or "/" in source_file
            or "\\" in source_file
            or not isinstance(source_hash, str)
            or SHA256_PATTERN.fullmatch(source_hash) is None
        ):
            raise VectorStoreRebuildError(
                "Ingestion manifest source hashes are invalid."
            )

    for document_id, policy_version_value in policy_versions.items():
        if (
            not isinstance(document_id, str)
            or not document_id.strip()
            or "/" in document_id
            or "\\" in document_id
            or _looks_like_absolute_path(document_id)
            or not isinstance(policy_version_value, str)
            or not policy_version_value.strip()
            or _looks_like_absolute_path(policy_version_value)
        ):
            raise VectorStoreRebuildError(
                "Ingestion manifest policy versions are invalid."
            )

    if set(package_versions) != set(REQUIRED_PACKAGE_NAMES):
        raise VectorStoreRebuildError(
            "Ingestion manifest package versions are incomplete."
        )

    for name, installed_version in package_versions.items():
        if (
            not isinstance(name, str)
            or not isinstance(installed_version, str)
            or not installed_version.strip()
            or _looks_like_absolute_path(installed_version)
        ):
            raise VectorStoreRebuildError(
                "Ingestion manifest package versions are invalid."
            )


def _record_value(record: object, field_name: str) -> object:
    if isinstance(record, Mapping):
        return record.get(field_name)

    return getattr(record, field_name, None)


def _model_names_match(
    configured_name: str,
    installed_name: str,
) -> bool:
    if installed_name == configured_name:
        return True

    return (
        ":" not in configured_name
        and installed_name == f"{configured_name}:latest"
    )


def _looks_like_absolute_path(value: str) -> bool:
    return (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
    )


def build_vector_store(
    store_dir: str | Path,
    *,
    embeddings: Embeddings,
    runtime_settings: RagSettings = settings,
    client_factory: ClientFactory = chromadb.PersistentClient,
    model_digest_provider: Callable[..., str] = (
        get_local_embedding_model_digest
    ),
    package_versions_provider: Callable[
        [], Mapping[str, str]
    ] = get_required_package_versions,
    smoke_query: str = "How should a customer report card fraud?",
) -> VectorStoreBuildResult:
    """Build and fully verify one new Chroma store at an empty path."""

    target = Path(store_dir).expanduser().resolve()

    if not target.exists() or not target.is_dir():
        raise VectorStoreRebuildError(
            "The temporary Chroma directory must already exist."
        )

    if any(target.iterdir()):
        raise VectorStoreRebuildError(
            "The temporary Chroma directory must be empty."
        )

    documents = load_approved_policies(runtime_settings.policies_dir)
    chunks = split_policy_documents(
        documents,
        chunk_size=runtime_settings.chunk_size,
        chunk_overlap=runtime_settings.chunk_overlap,
    )
    validate_policy_chunks(chunks)

    query_vector = embeddings.embed_query(smoke_query)
    vectors = embeddings.embed_documents(
        [chunk.content for chunk in chunks]
    )
    dimensions = _validate_embedding_batch(
        vectors,
        expected_count=len(chunks),
        query_vector=query_vector,
    )
    build_facts = VectorStoreBuildResult(
        chunk_count=len(chunks),
        embedding_dimensions=dimensions,
        record_ids=tuple(chunk.chunk_id for chunk in chunks),
    )
    client: _ChromaClient | None = None

    try:
        client = client_factory(str(target))
        collection = client.get_or_create_collection(
            name=runtime_settings.collection_name,
            configuration={
                "hnsw": {
                    "space": runtime_settings.chroma_distance_metric,
                }
            },
            embedding_function=None,
        )
        _require_cosine_collection(
            collection,
            expected_metric=runtime_settings.chroma_distance_metric,
        )
        batch_size = client.get_max_batch_size()

        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise VectorStoreRebuildError(
                "Chroma returned an invalid maximum batch size."
            )

        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset:offset + batch_size]
            collection.add(
                ids=[chunk.chunk_id for chunk in batch],
                documents=[chunk.content for chunk in batch],
                metadatas=[
                    chunk.storage_metadata()
                    for chunk in batch
                ],
                embeddings=vectors[offset:offset + batch_size],
            )

        _verify_collection(
            collection,
            embeddings=embeddings,
            expected_result=build_facts,
            expected_metric=runtime_settings.chroma_distance_metric,
            smoke_query=smoke_query,
        )
        model_digest = model_digest_provider(
            model_name=runtime_settings.embedding_model,
            base_url=runtime_settings.ollama_base_url,
        )
        installed_versions = dict(package_versions_provider())
        manifest = create_ingestion_manifest(
            documents,
            build_result=build_facts,
            embedding_model_digest=model_digest,
            runtime_settings=runtime_settings,
            package_versions=installed_versions,
        )
        manifest_path = write_ingestion_manifest(target, manifest)
        loaded_manifest = load_ingestion_manifest(manifest_path)
        validate_ingestion_manifest(
            loaded_manifest,
            documents=documents,
            expected_result=build_facts,
            expected_model_digest=model_digest,
            runtime_settings=runtime_settings,
            expected_package_versions=installed_versions,
        )
        return VectorStoreBuildResult(
            chunk_count=build_facts.chunk_count,
            embedding_dimensions=build_facts.embedding_dimensions,
            record_ids=build_facts.record_ids,
            manifest=loaded_manifest,
        )
    except VectorStoreRebuildError:
        raise
    except Exception as exc:
        raise VectorStoreRebuildError(
            "Temporary Chroma build or verification failed."
        ) from exc
    finally:
        _release_chroma_client(client)


def verify_vector_store(
    store_dir: str | Path,
    *,
    embeddings: Embeddings,
    expected_result: VectorStoreBuildResult,
    runtime_settings: RagSettings = settings,
    client_factory: ClientFactory = chromadb.PersistentClient,
    model_digest_provider: Callable[..., str] = (
        get_local_embedding_model_digest
    ),
    package_versions_provider: Callable[
        [], Mapping[str, str]
    ] = get_required_package_versions,
    smoke_query: str = "How should a customer report card fraud?",
) -> None:
    """Reopen and verify an activated Chroma store through public APIs."""

    target = Path(store_dir).expanduser().resolve()

    if not target.exists() or not target.is_dir():
        raise VectorStoreRebuildError(
            "The activated Chroma store directory does not exist."
        )

    if expected_result.manifest is None:
        raise VectorStoreRebuildError(
            "Reopened verification requires the expected ingestion manifest."
        )

    client: _ChromaClient | None = None

    try:
        client = client_factory(str(target))
        collection = client.get_collection(
            name=runtime_settings.collection_name,
            embedding_function=None,
        )
        _verify_collection(
            collection,
            embeddings=embeddings,
            expected_result=expected_result,
            expected_metric=runtime_settings.chroma_distance_metric,
            smoke_query=smoke_query,
        )
        documents = load_approved_policies(runtime_settings.policies_dir)
        model_digest = model_digest_provider(
            model_name=runtime_settings.embedding_model,
            base_url=runtime_settings.ollama_base_url,
        )
        installed_versions = dict(package_versions_provider())
        manifest = load_ingestion_manifest(
            target / INGESTION_MANIFEST_FILENAME
        )
        validate_ingestion_manifest(
            manifest,
            documents=documents,
            expected_result=expected_result,
            expected_model_digest=model_digest,
            runtime_settings=runtime_settings,
            expected_package_versions=installed_versions,
        )

        if manifest.to_dict() != expected_result.manifest.to_dict():
            raise VectorStoreRebuildError(
                "Reopened manifest differs from the verified staged manifest."
            )
    except VectorStoreRebuildError:
        raise
    except Exception as exc:
        raise VectorStoreRebuildError(
            "Reopened Chroma verification failed."
        ) from exc
    finally:
        _release_chroma_client(client)


def activate_staged_vector_store(
    paths: VectorStorePaths,
    *,
    build_temporary: Callable[[Path], VectorStoreBuildResult],
    verify_active: Callable[[Path, VectorStoreBuildResult], None],
    clients_stopped: bool,
) -> VectorStoreBuildResult:
    """Build, activate, reopen, and roll back a staged store.

    Directory moves are staged and rollback-capable, but are not claimed to be
    atomic across all Windows filesystems and failure modes.
    """

    if clients_stopped is not True:
        raise VectorStoreRebuildError(
            "Confirm that the backend and all Chroma clients are stopped "
            "before activating a store."
        )

    staged = paths.validated()

    if staged.backup.exists():
        raise VectorStoreRebuildError(
            "A backup Chroma directory already exists; inspect or recover it "
            "before another rebuild."
        )

    _remove_staged_directory(
        staged.temporary,
        allowed=(staged.temporary, staged.backup),
    )
    staged.temporary.mkdir(parents=False, exist_ok=False)

    try:
        result = build_temporary(staged.temporary)
    except Exception as exc:
        if isinstance(exc, VectorStoreRebuildError):
            raise
        raise VectorStoreRebuildError(
            "Temporary-store build failed; active store was not changed."
        ) from exc

    if not staged.temporary.exists():
        raise VectorStoreRebuildError(
            "Temporary-store builder removed its staging directory."
        )

    had_active = staged.active.exists()
    active_moved = False
    replacement_activated = False

    try:
        if had_active:
            staged.active.replace(staged.backup)
            active_moved = True

        staged.temporary.replace(staged.active)
        replacement_activated = True
        verify_active(staged.active, result)
    except Exception as exc:
        rollback_error = _restore_after_failed_activation(
            staged,
            active_moved=active_moved,
            replacement_activated=replacement_activated,
        )

        if rollback_error is not None:
            raise VectorStoreRebuildError(
                "Store activation failed and automatic rollback was "
                f"incomplete: {rollback_error}"
            ) from exc

        raise VectorStoreRebuildError(
            "Store activation or reopened verification failed; the previous "
            "active store was restored."
        ) from exc

    if staged.backup.exists():
        _remove_staged_directory(
            staged.backup,
            allowed=(staged.temporary, staged.backup),
        )

    return result


def rebuild_project_vector_store(
    *,
    clients_stopped: bool,
    runtime_settings: RagSettings = settings,
) -> VectorStoreBuildResult:
    """Run the complete protected rebuild against configured project paths."""

    embeddings = get_embeddings()
    paths = VectorStorePaths.from_settings(runtime_settings)

    return activate_staged_vector_store(
        paths,
        clients_stopped=clients_stopped,
        build_temporary=lambda temporary: build_vector_store(
            temporary,
            embeddings=embeddings,
            runtime_settings=runtime_settings,
        ),
        verify_active=lambda active, result: verify_vector_store(
            active,
            embeddings=embeddings,
            expected_result=result,
            runtime_settings=runtime_settings,
        ),
    )


def _verify_collection(
    collection: _Collection,
    *,
    embeddings: Embeddings,
    expected_result: VectorStoreBuildResult,
    expected_metric: str,
    smoke_query: str,
) -> None:
    _require_cosine_collection(
        collection,
        expected_metric=expected_metric,
    )

    if collection.count() != expected_result.chunk_count:
        raise VectorStoreRebuildError(
            "Chroma record count does not match inserted chunk count."
        )

    stored = collection.get(
        limit=expected_result.chunk_count,
        include=["documents", "metadatas"],
    )
    ids = stored.get("ids")
    documents = stored.get("documents")
    metadatas = stored.get("metadatas")

    if not (
        isinstance(ids, list)
        and isinstance(documents, list)
        and isinstance(metadatas, list)
        and len(ids) == expected_result.chunk_count
        and len(documents) == expected_result.chunk_count
        and len(metadatas) == expected_result.chunk_count
    ):
        raise VectorStoreRebuildError(
            "Chroma returned malformed stored records."
        )

    if set(ids) != set(expected_result.record_ids):
        raise VectorStoreRebuildError(
            "Stored Chroma IDs do not match stable chunk IDs."
        )

    embedding_sample = collection.get(
        limit=1,
        include=["embeddings"],
    ).get("embeddings")

    try:
        actual_dimensions = len(embedding_sample[0])
    except (IndexError, KeyError, TypeError) as exc:
        raise VectorStoreRebuildError(
            "Chroma returned malformed stored embeddings."
        ) from exc

    if actual_dimensions != expected_result.embedding_dimensions:
        raise VectorStoreRebuildError(
            "Stored embedding dimensions do not match the build result."
        )

    stored_chunks: list[PolicyChunk] = []

    for record_id, document, metadata in zip(
        ids,
        documents,
        metadatas,
        strict=True,
    ):
        if (
            not isinstance(record_id, str)
            or not isinstance(document, str)
            or not isinstance(metadata, Mapping)
        ):
            raise VectorStoreRebuildError(
                "Chroma returned a malformed record."
            )

        stored_chunks.append(
            PolicyChunk(
                chunk_id=record_id,
                content=document,
                metadata=dict(metadata),
            )
        )

    stored_chunks.sort(
        key=lambda chunk: (
            chunk.document_id,
            chunk.chunk_index,
        )
    )

    try:
        validate_policy_chunks(stored_chunks)
    except (PolicyValidationError, TypeError) as exc:
        raise VectorStoreRebuildError(
            "Stored Chroma policy metadata failed validation."
        ) from exc

    query_vector = embeddings.embed_query(smoke_query)

    if len(query_vector) != expected_result.embedding_dimensions:
        raise VectorStoreRebuildError(
            "Query embedding dimensions do not match stored vectors."
        )

    query_result = collection.query(
        query_embeddings=[query_vector],
        n_results=min(4, expected_result.chunk_count),
        include=["documents", "metadatas", "distances"],
    )
    result_ids = query_result.get("ids")
    result_metadatas = query_result.get("metadatas")

    if not (
        isinstance(result_ids, list)
        and result_ids
        and isinstance(result_ids[0], list)
        and result_ids[0]
        and set(result_ids[0]).issubset(
            set(expected_result.record_ids)
        )
        and isinstance(result_metadatas, list)
        and result_metadatas
        and isinstance(result_metadatas[0], list)
        and result_metadatas[0]
        and all(
            isinstance(metadata, Mapping)
            and metadata.get("status") == "approved"
            and metadata.get("jurisdiction")
            == "fictional_prototype"
            for metadata in result_metadatas[0]
        )
    ):
        raise VectorStoreRebuildError(
            "Chroma retrieval smoke test returned invalid records."
        )


def _require_cosine_collection(
    collection: _Collection,
    *,
    expected_metric: str,
) -> None:
    configuration = collection.configuration
    hnsw = (
        configuration.get("hnsw")
        if isinstance(configuration, Mapping)
        else None
    )
    actual_metric = (
        hnsw.get("space")
        if isinstance(hnsw, Mapping)
        else None
    )

    if expected_metric != "cosine" or actual_metric != "cosine":
        raise VectorStoreRebuildError(
            "Chroma collection does not explicitly report cosine distance."
        )


def _validate_embedding_batch(
    vectors: list[list[float]],
    *,
    expected_count: int,
    query_vector: list[float],
) -> int:
    if len(vectors) != expected_count or not vectors:
        raise VectorStoreRebuildError(
            "Document embedding count does not match chunk count."
        )

    dimensions = len(vectors[0])

    if dimensions < 1 or any(
        len(vector) != dimensions
        for vector in vectors
    ):
        raise VectorStoreRebuildError(
            "Document embeddings have invalid or inconsistent dimensions."
        )

    if len(query_vector) != dimensions:
        raise VectorStoreRebuildError(
            "Document and query embedding dimensions do not match."
        )

    return dimensions


def _release_chroma_client(
    client: _ChromaClient | None,
) -> None:
    if client is None:
        return

    try:
        client.close()
    finally:
        client.clear_system_cache()
        gc.collect()


def _remove_staged_directory(
    path: Path,
    *,
    allowed: tuple[Path, Path],
) -> None:
    resolved = path.resolve()
    allowed_resolved = {candidate.resolve() for candidate in allowed}

    if resolved not in allowed_resolved:
        raise VectorStoreRebuildError(
            "Refusing to remove a directory outside staged paths."
        )

    if resolved.exists():
        if resolved.is_symlink() or not resolved.is_dir():
            raise VectorStoreRebuildError(
                "Staged removal target is not a regular directory."
            )

        shutil.rmtree(resolved)


def _restore_after_failed_activation(
    paths: VectorStorePaths,
    *,
    active_moved: bool,
    replacement_activated: bool,
) -> str | None:
    try:
        if replacement_activated and paths.active.exists():
            if paths.temporary.exists():
                return (
                    "temporary path unexpectedly exists, so the failed "
                    "replacement could not be preserved"
                )

            paths.active.replace(paths.temporary)

        if active_moved and paths.backup.exists():
            paths.backup.replace(paths.active)

        return None
    except OSError:
        return "a filesystem rollback operation failed"


def _validated_base_metadata(
    document: PolicyDocument,
) -> dict[str, str]:
    if not isinstance(document, PolicyDocument):
        raise TypeError(
            "Policy chunking requires a validated PolicyDocument."
        )

    if not document.body.strip():
        raise PolicyChunkingError(
            f"{document.source_file}: policy body cannot be blank."
        )

    stored = document.storage_metadata()
    missing = [
        field_name
        for field_name in BASE_METADATA_FIELDS
        if field_name not in stored
    ]

    if missing:
        raise PolicyChunkingError(
            f"{document.source_file}: missing validated metadata "
            f"for chunking: {missing}."
        )

    metadata: dict[str, str] = {}

    for field_name in BASE_METADATA_FIELDS:
        value = stored[field_name]

        if not isinstance(value, str) or not value.strip():
            raise PolicyChunkingError(
                f"{document.source_file}: metadata field "
                f"{field_name!r} must be a nonblank string."
            )

        metadata[field_name] = value.strip()

    if metadata["status"] != "approved":
        raise PolicyChunkingError(
            f"{document.source_file}: policy is not approved."
        )

    if metadata["jurisdiction"] != "fictional_prototype":
        raise PolicyChunkingError(
            f"{document.source_file}: policy jurisdiction is invalid."
        )

    if (
        "/" in metadata["source_file"]
        or "\\" in metadata["source_file"]
    ):
        raise PolicyChunkingError(
            f"{document.source_file}: source_file is not a safe basename."
        )

    if (
        SHA256_PATTERN.fullmatch(metadata["source_hash"])
        is None
    ):
        raise PolicyChunkingError(
            f"{document.source_file}: source_hash is invalid."
        )

    return metadata


def _resolve_chunk_settings(
    *,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> tuple[int, int]:
    resolved_size = (
        settings.chunk_size
        if chunk_size is None
        else chunk_size
    )
    resolved_overlap = (
        settings.chunk_overlap
        if chunk_overlap is None
        else chunk_overlap
    )

    if (
        isinstance(resolved_size, bool)
        or not isinstance(resolved_size, int)
    ):
        raise TypeError("chunk_size must be an integer.")

    if (
        isinstance(resolved_overlap, bool)
        or not isinstance(resolved_overlap, int)
    ):
        raise TypeError("chunk_overlap must be an integer.")

    if resolved_size < 200:
        raise PolicyChunkingError(
            "chunk_size must be at least 200."
        )

    if resolved_overlap < 0:
        raise PolicyChunkingError(
            "chunk_overlap cannot be negative."
        )

    if resolved_overlap >= resolved_size:
        raise PolicyChunkingError(
            "chunk_overlap must be smaller than chunk_size."
        )

    return resolved_size, resolved_overlap


def _normalize_header_value(value: object) -> str:
    if value is None:
        return ""

    if not isinstance(value, str):
        raise PolicyChunkingError(
            "Markdown header metadata must be text."
        )

    return normalize_identity_text(value)


def _headers_from_metadata(
    metadata: Mapping[str, object],
) -> tuple[str, str, str]:
    return tuple(
        _normalize_header_value(
            metadata.get(field_name, "")
        )
        for field_name in (
            "header_1",
            "header_2",
            "header_3",
        )
    )


def _canonicalize_section_content(
    content: str,
    *,
    headers: tuple[str, str, str],
) -> str:
    """
    Make splitter output stable when parent headings are conditionally present.

    The installed Markdown splitter includes an ancestor heading in a child
    section only when no earlier sibling caused a split. Removing those leading
    headings and rebuilding the complete hierarchy makes unchanged sections
    content-stable when an earlier section is inserted.
    """

    if not isinstance(content, str):
        raise TypeError("Markdown section content must be text.")

    lines = (
        content.replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )

    while lines and not lines[0].strip():
        lines.pop(0)

    while (
        lines
        and MARKDOWN_HEADING_PATTERN.match(
            lines[0].strip()
        )
    ):
        lines.pop(0)

        while lines and not lines[0].strip():
            lines.pop(0)

    body = "\n".join(lines).strip()
    heading_lines = [
        f"{'#' * level} {header}"
        for level, header in enumerate(headers, start=1)
        if header
    ]
    heading_context = "\n\n".join(heading_lines)

    if heading_context and body:
        return f"{heading_context}\n\n{body}"

    if heading_context:
        return heading_context

    if body:
        return body

    raise PolicyChunkingError(
        "Markdown section produced no retrievable content."
    )


def _build_section_path(
    *,
    headers: tuple[str, str, str],
    fallback_title: str,
) -> str:
    components = tuple(
        header for header in headers if header
    )

    if not components:
        components = (normalize_identity_text(fallback_title),)

    section_path = " > ".join(components)

    if not section_path:
        raise PolicyChunkingError(
            "Policy chunks require a nonblank section path."
        )

    return section_path


def _assign_stable_ids(
    drafts: Iterable[_ChunkDraft],
) -> tuple[PolicyChunk, ...]:
    identity_by_base_id: dict[
        str,
        tuple[str, str, str],
    ] = {}
    occurrence_by_base_id: dict[str, int] = {}
    chunks: list[PolicyChunk] = []

    for draft in drafts:
        document_id = str(draft.metadata["document_id"])
        section_path = str(draft.metadata["section_path"])
        content_hash = str(draft.metadata["content_hash"])
        identity = (
            normalize_identity_text(document_id),
            normalize_identity_text(section_path),
            content_hash,
        )
        base_id = build_stable_chunk_id(
            document_id=document_id,
            section_path=section_path,
            content_hash=content_hash,
        )
        existing_identity = identity_by_base_id.get(base_id)

        if (
            existing_identity is not None
            and existing_identity != identity
        ):
            raise PolicyChunkingError(
                "Stable-ID slug collision between different "
                f"chunk identities: {base_id!r}."
            )

        identity_by_base_id[base_id] = identity
        occurrence = occurrence_by_base_id.get(base_id, 0) + 1
        occurrence_by_base_id[base_id] = occurrence
        chunk_id = build_stable_chunk_id(
            document_id=document_id,
            section_path=section_path,
            content_hash=content_hash,
            occurrence=occurrence,
        )
        chunks.append(
            PolicyChunk(
                chunk_id=chunk_id,
                content=draft.content,
                metadata=draft.metadata,
            )
        )

    return tuple(chunks)


def _validate_record_id(record_id: str) -> None:
    if not isinstance(record_id, str):
        raise TypeError("Stable chunk ID must be a string.")

    if (
        not record_id
        or SAFE_RECORD_ID_PATTERN.fullmatch(record_id) is None
        or "/" in record_id
        or "\\" in record_id
        or ":" in record_id
    ):
        raise PolicyChunkingError(
            f"Unsafe stable chunk ID: {record_id!r}."
        )


def _has_valid_occurrence_suffix(
    record_id: str,
    base_id: str,
) -> bool:
    prefix = f"{base_id}-"

    if not record_id.startswith(prefix):
        return False

    suffix = record_id[len(prefix):]
    return (
        suffix.isdigit()
        and len(suffix) >= 2
        and int(suffix) >= 2
    )


__all__ = [
    "BASE_METADATA_FIELDS",
    "DERIVED_CHUNK_METADATA_FIELDS",
    "EXPECTED_CHUNK_METADATA_FIELDS",
    "HEADERS_TO_SPLIT_ON",
    "INGESTION_MANIFEST_FIELDS",
    "INGESTION_MANIFEST_SCHEMA_VERSION",
    "IngestionManifest",
    "PolicyChunk",
    "PolicyChunkingError",
    "VectorStoreBuildResult",
    "VectorStorePaths",
    "VectorStoreRebuildError",
    "activate_staged_vector_store",
    "build_stable_chunk_id",
    "build_vector_store",
    "create_ingestion_manifest",
    "get_local_embedding_model_digest",
    "get_required_package_versions",
    "load_ingestion_manifest",
    "normalize_identity_text",
    "rebuild_project_vector_store",
    "slugify_identity_component",
    "split_policy_document",
    "split_policy_documents",
    "validate_policy_chunks",
    "validate_ingestion_manifest",
    "verify_vector_store",
    "write_ingestion_manifest",
]
