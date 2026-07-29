"""Policy-scoped retrieval from the validated local Chroma store."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.ml.embeddings import get_embeddings
from app.ml.ingest_policies import (
    EXPECTED_CHUNK_METADATA_FIELDS,
    INGESTION_MANIFEST_SCHEMA_VERSION,
    IngestionManifest,
    build_stable_chunk_id,
    get_local_embedding_model_digest,
    load_ingestion_manifest,
)
from app.ml.policy_loader import (
    SHA256_PATTERN,
    compute_content_hash,
    normalize_chunk_content,
)
from app.ml.policy_registry import KNOWN_POLICY_IDS
from app.ml.rag_config import RagSettings, settings
from app.ml.triage_types import RetrievedPolicy, TriageDecision


class PolicyRetrievalError(RuntimeError):
    """Raised when policy retrieval cannot proceed safely."""


class _VectorStore(Protocol):
    def similarity_search_with_score(
        self,
        query: str,
        k: int,
        filter: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[tuple[Document, float]]: ...


VectorStoreFactory = Callable[..., _VectorStore]
ModelDigestProvider = Callable[..., str]

ADJACENT_CHUNK_OVERLAP_THRESHOLD = 0.85
NORMALIZED_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


class PolicyRetriever:
    """Retrieve a safe, ranked context from an approved policy scope."""

    def __init__(
        self,
        *,
        vector_store: _VectorStore,
        manifest: IngestionManifest,
        embedding_model_digest: str,
        runtime_settings: RagSettings = settings,
    ) -> None:
        search = getattr(vector_store, "similarity_search_with_score", None)

        if not callable(search):
            raise TypeError(
                "vector_store must provide similarity_search_with_score()."
            )

        validate_retrieval_manifest(
            manifest,
            embedding_model_digest=embedding_model_digest,
            runtime_settings=runtime_settings,
        )
        self._vector_store = vector_store
        self._manifest = manifest
        self._settings = runtime_settings

    def retrieve(
        self,
        *,
        query: str,
        allowed_policy_ids: tuple[str, ...],
        required_policy_ids: tuple[str, ...] = (),
        min_relevance_score: float | None = None,
    ) -> tuple[RetrievedPolicy, ...]:
        """Search, filter, deduplicate, rank, and limit policy context."""

        retrieval_query = _validate_query(query)
        selection_settings = (
            self._settings
            if min_relevance_score is None
            else replace(
                self._settings,
                min_relevance_score=min_relevance_score,
            )
        )
        allowed = _validate_allowed_policy_ids(allowed_policy_ids)
        required = _validate_required_policy_ids(
            required_policy_ids,
            allowed_policy_ids=allowed,
            max_context_chunks=selection_settings.max_context_chunks,
        )
        metadata_filter = {
            "document_id": {
                "$in": list(allowed),
            }
        }

        try:
            results = self._vector_store.similarity_search_with_score(
                query=retrieval_query,
                k=self._settings.candidate_k,
                filter=metadata_filter,
            )
        except PolicyRetrievalError:
            raise
        except Exception as exc:
            raise PolicyRetrievalError(
                "Filtered policy retrieval failed."
            ) from exc

        if not isinstance(results, list):
            raise PolicyRetrievalError(
                "Vector store returned malformed retrieval results."
            )

        candidates = tuple(
            _to_retrieved_policy(
                document,
                distance=distance,
                allowed_policy_ids=frozenset(allowed),
            )
            for document, distance in results
        )
        return filter_retrieval_candidates(
            candidates,
            allowed_policy_ids=allowed,
            required_policy_ids=required,
            runtime_settings=selection_settings,
        )

    def retrieval_is_sufficient(
        self,
        policies: Sequence[RetrievedPolicy],
        decision: TriageDecision,
    ) -> bool:
        """Check sufficiency against this retriever's validated manifest."""

        return retrieval_is_sufficient(
            policies,
            decision,
            manifest=self._manifest,
            runtime_settings=self._settings,
        )


def validate_retrieval_manifest(
    manifest: IngestionManifest,
    *,
    embedding_model_digest: str,
    runtime_settings: RagSettings = settings,
) -> None:
    """Validate every active-manifest field required by Step 17."""

    if not isinstance(manifest, IngestionManifest):
        raise TypeError(
            "Retrieval manifest must be an IngestionManifest."
        )

    expected_values: dict[str, object] = {
        "schema_version": INGESTION_MANIFEST_SCHEMA_VERSION,
        "collection_name": runtime_settings.collection_name,
        "embedding_model": runtime_settings.embedding_model,
        "embedding_model_digest": embedding_model_digest,
        "distance_metric": runtime_settings.chroma_distance_metric,
        "embedding_document_prefix": (
            runtime_settings.embedding_document_prefix
        ),
        "embedding_query_prefix": runtime_settings.embedding_query_prefix,
        "chunk_size": runtime_settings.chunk_size,
        "chunk_overlap": runtime_settings.chunk_overlap,
    }

    for field_name, expected in expected_values.items():
        if getattr(manifest, field_name) != expected:
            raise PolicyRetrievalError(
                "Active ingestion manifest is stale or mismatched: "
                f"{field_name}."
            )


def cosine_distance_to_relevance(distance: float) -> float:
    """Convert one finite cosine distance to clamped relevance."""

    if (
        isinstance(distance, bool)
        or not isinstance(distance, (int, float))
        or not math.isfinite(float(distance))
    ):
        raise PolicyRetrievalError(
            "Vector store returned an invalid cosine distance."
        )

    return max(0.0, min(1.0, 1.0 - float(distance)))


def normalized_token_overlap_ratio(
    first: str,
    second: str,
) -> float:
    """Return deterministic multiset token overlap over the smaller input."""

    first_tokens = _normalized_tokens(first)
    second_tokens = _normalized_tokens(second)

    if not first_tokens or not second_tokens:
        return 0.0

    first_counts = Counter(first_tokens)
    second_counts = Counter(second_tokens)
    shared_count = sum(
        min(count, second_counts[token])
        for token, count in first_counts.items()
    )
    return shared_count / min(
        len(first_tokens),
        len(second_tokens),
    )


def filter_retrieval_candidates(
    candidates: Sequence[RetrievedPolicy],
    *,
    allowed_policy_ids: tuple[str, ...],
    required_policy_ids: tuple[str, ...] = (),
    runtime_settings: RagSettings = settings,
    overlap_threshold: float = ADJACENT_CHUNK_OVERLAP_THRESHOLD,
) -> tuple[RetrievedPolicy, ...]:
    """Apply the deterministic Step 18 retrieval-selection rules."""

    if not isinstance(candidates, Sequence) or isinstance(
        candidates,
        (str, bytes),
    ):
        raise TypeError(
            "Retrieval candidates must be supplied as a sequence."
        )

    if not isinstance(runtime_settings, RagSettings):
        raise TypeError("runtime_settings must be a RagSettings instance.")

    allowed = _validate_allowed_policy_ids(allowed_policy_ids)
    required = _validate_required_policy_ids(
        required_policy_ids,
        allowed_policy_ids=allowed,
        max_context_chunks=runtime_settings.max_context_chunks,
    )
    _validate_filter_configuration(
        min_relevance_score=runtime_settings.min_relevance_score,
        max_context_chunks=runtime_settings.max_context_chunks,
        overlap_threshold=overlap_threshold,
    )

    ranked = sorted(
        (
            candidate
            for candidate in candidates
            if _candidate_is_accepted(
                candidate,
                allowed_policy_ids=frozenset(allowed),
                min_relevance_score=(
                    runtime_settings.min_relevance_score
                ),
            )
        ),
        key=_candidate_rank_key,
    )
    deduplicated: list[RetrievedPolicy] = []
    seen_chunk_ids: set[str] = set()
    seen_normalized_text: set[str] = set()
    seen_content_hashes: set[str] = set()

    for candidate in ranked:
        normalized_text = " ".join(
            _normalized_tokens(candidate.content)
        )

        if (
            candidate.chunk_id in seen_chunk_ids
            or normalized_text in seen_normalized_text
            or candidate.content_hash in seen_content_hashes
            or any(
                _is_high_overlap_adjacent_candidate(
                    candidate,
                    retained,
                    overlap_threshold=overlap_threshold,
                )
                for retained in deduplicated
            )
        ):
            continue

        deduplicated.append(candidate)
        seen_chunk_ids.add(candidate.chunk_id)
        seen_normalized_text.add(normalized_text)
        seen_content_hashes.add(candidate.content_hash)

    selected: list[RetrievedPolicy] = []
    selected_chunk_ids: set[str] = set()

    for policy_id in required:
        representative = next(
            (
                candidate
                for candidate in deduplicated
                if candidate.document_id == policy_id
            ),
            None,
        )

        if representative is not None:
            selected.append(representative)
            selected_chunk_ids.add(representative.chunk_id)

    for candidate in deduplicated:
        if len(selected) >= runtime_settings.max_context_chunks:
            break

        if candidate.chunk_id in selected_chunk_ids:
            continue

        selected.append(candidate)
        selected_chunk_ids.add(candidate.chunk_id)

    return tuple(
        sorted(
            selected,
            key=_candidate_rank_key,
        )[:runtime_settings.max_context_chunks]
    )


def retrieval_is_sufficient(
    policies: Sequence[RetrievedPolicy],
    decision: TriageDecision,
    *,
    manifest: IngestionManifest | None = None,
    runtime_settings: RagSettings = settings,
) -> bool:
    """Return whether accepted retrieval context satisfies Step 19."""

    if (
        not isinstance(policies, Sequence)
        or isinstance(policies, (str, bytes))
        or not policies
        or not isinstance(decision, TriageDecision)
        or not isinstance(runtime_settings, RagSettings)
    ):
        return False

    try:
        _validate_filter_configuration(
            min_relevance_score=runtime_settings.min_relevance_score,
            max_context_chunks=runtime_settings.max_context_chunks,
            overlap_threshold=ADJACENT_CHUNK_OVERLAP_THRESHOLD,
        )
        allowed = _validate_allowed_policy_ids(
            decision.allowed_policy_ids
        )
        required = _validate_required_policy_ids(
            decision.required_policy_ids,
            allowed_policy_ids=allowed,
            max_context_chunks=runtime_settings.max_context_chunks,
        )
        active_manifest = (
            load_ingestion_manifest(
                runtime_settings.ingestion_manifest_path
            )
            if manifest is None
            else manifest
        )

        if not isinstance(active_manifest, IngestionManifest):
            return False

        validate_retrieval_manifest(
            active_manifest,
            embedding_model_digest=(
                active_manifest.embedding_model_digest
            ),
            runtime_settings=runtime_settings,
        )
    except Exception:
        return False

    if (
        len(policies) > runtime_settings.max_context_chunks
        or isinstance(active_manifest.chunk_count, bool)
        or not isinstance(active_manifest.chunk_count, int)
        or active_manifest.chunk_count < len(policies)
        or isinstance(active_manifest.source_document_count, bool)
        or not isinstance(active_manifest.source_document_count, int)
        or active_manifest.source_document_count < 1
        or active_manifest.source_document_count
        != len(active_manifest.policy_versions)
        or active_manifest.source_document_count
        != len(active_manifest.source_hashes)
        or not isinstance(
            active_manifest.embedding_model_digest,
            str,
        )
        or SHA256_PATTERN.fullmatch(
            active_manifest.embedding_model_digest
        )
        is None
    ):
        return False

    allowed_set = frozenset(allowed)
    retrieved_ids: set[str] = set()
    versions_by_document: dict[str, set[str]] = {}

    for policy in policies:
        if not _candidate_is_accepted(
            policy,
            allowed_policy_ids=allowed_set,
            min_relevance_score=runtime_settings.min_relevance_score,
        ):
            return False

        expected_version = active_manifest.policy_versions.get(
            policy.document_id
        )
        manifest_source_hash = active_manifest.source_hashes.get(
            policy.source_file
        )

        if (
            not isinstance(expected_version, str)
            or policy.version != expected_version
            or not isinstance(manifest_source_hash, str)
            or SHA256_PATTERN.fullmatch(manifest_source_hash) is None
        ):
            return False

        retrieved_ids.add(policy.document_id)
        versions_by_document.setdefault(
            policy.document_id,
            set(),
        ).add(policy.version)

    if not frozenset(required).issubset(retrieved_ids):
        return False

    if any(
        len(versions) > 1
        for versions in versions_by_document.values()
    ):
        return False

    return True


@lru_cache(maxsize=1)
def get_retriever() -> PolicyRetriever:
    """Open and cache the validated active local policy retriever."""

    store_dir = settings.chroma_store_dir

    if (
        not store_dir.exists()
        or not store_dir.is_dir()
        or store_dir.is_symlink()
    ):
        raise PolicyRetrievalError(
            "Active Chroma store directory is unavailable."
        )

    try:
        manifest = load_ingestion_manifest(
            settings.ingestion_manifest_path
        )
        model_digest = get_local_embedding_model_digest(
            model_name=settings.embedding_model,
            base_url=settings.ollama_base_url,
        )
        validate_retrieval_manifest(
            manifest,
            embedding_model_digest=model_digest,
        )
        vector_store = Chroma(
            collection_name=settings.collection_name,
            embedding_function=get_embeddings(),
            persist_directory=str(store_dir),
            create_collection_if_not_exists=False,
        )
        return PolicyRetriever(
            vector_store=vector_store,
            manifest=manifest,
            embedding_model_digest=model_digest,
        )
    except PolicyRetrievalError:
        raise
    except Exception as exc:
        raise PolicyRetrievalError(
            "Unable to initialize the active policy retriever."
        ) from exc


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise TypeError("Retrieval query must be a string.")

    retrieval_query = query.strip()

    if not retrieval_query:
        raise PolicyRetrievalError(
            "Retrieval query cannot be blank."
        )

    return retrieval_query


def _validate_allowed_policy_ids(
    allowed_policy_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if not isinstance(allowed_policy_ids, tuple):
        raise TypeError(
            "allowed_policy_ids must be supplied as a tuple."
        )

    if not allowed_policy_ids:
        raise PolicyRetrievalError(
            "At least one allowed policy ID is required."
        )

    if any(
        not isinstance(policy_id, str) or not policy_id.strip()
        for policy_id in allowed_policy_ids
    ):
        raise PolicyRetrievalError(
            "Allowed policy IDs must be nonblank strings."
        )

    if len(set(allowed_policy_ids)) != len(allowed_policy_ids):
        raise PolicyRetrievalError(
            "Allowed policy IDs must be unique."
        )

    unknown = set(allowed_policy_ids) - set(KNOWN_POLICY_IDS)

    if unknown:
        raise PolicyRetrievalError(
            "Retrieval policy scope contains an unknown policy ID."
        )

    return allowed_policy_ids


def _validate_required_policy_ids(
    required_policy_ids: tuple[str, ...],
    *,
    allowed_policy_ids: tuple[str, ...],
    max_context_chunks: int,
) -> tuple[str, ...]:
    if not isinstance(required_policy_ids, tuple):
        raise TypeError(
            "required_policy_ids must be supplied as a tuple."
        )

    if any(
        not isinstance(policy_id, str) or not policy_id.strip()
        for policy_id in required_policy_ids
    ):
        raise PolicyRetrievalError(
            "Required policy IDs must be nonblank strings."
        )

    if len(set(required_policy_ids)) != len(required_policy_ids):
        raise PolicyRetrievalError(
            "Required policy IDs must be unique."
        )

    unknown = set(required_policy_ids) - set(KNOWN_POLICY_IDS)

    if unknown:
        raise PolicyRetrievalError(
            "Required policy scope contains an unknown policy ID."
        )

    if not set(required_policy_ids).issubset(allowed_policy_ids):
        raise PolicyRetrievalError(
            "Required policy IDs must be within the allowed policy scope."
        )

    if len(required_policy_ids) > max_context_chunks:
        raise PolicyRetrievalError(
            "The context limit cannot represent every required policy."
        )

    return required_policy_ids


def _validate_filter_configuration(
    *,
    min_relevance_score: float,
    max_context_chunks: int,
    overlap_threshold: float,
) -> None:
    if (
        isinstance(min_relevance_score, bool)
        or not isinstance(min_relevance_score, (int, float))
        or not math.isfinite(float(min_relevance_score))
        or not 0.0 <= float(min_relevance_score) <= 1.0
    ):
        raise PolicyRetrievalError(
            "The retrieval relevance threshold is invalid."
        )

    if (
        isinstance(max_context_chunks, bool)
        or not isinstance(max_context_chunks, int)
        or max_context_chunks < 1
    ):
        raise PolicyRetrievalError(
            "The retrieval context limit is invalid."
        )

    if (
        isinstance(overlap_threshold, bool)
        or not isinstance(overlap_threshold, (int, float))
        or not math.isfinite(float(overlap_threshold))
        or not 0.0 <= float(overlap_threshold) <= 1.0
    ):
        raise PolicyRetrievalError(
            "The adjacent-chunk overlap threshold is invalid."
        )


def _candidate_is_accepted(
    candidate: object,
    *,
    allowed_policy_ids: frozenset[str],
    min_relevance_score: float,
) -> bool:
    if not isinstance(candidate, RetrievedPolicy):
        return False

    score = candidate.relevance_score

    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
        or not 0.0 <= float(score) <= 1.0
        or float(score) < float(min_relevance_score)
    ):
        return False

    text_values = (
        candidate.document_id,
        candidate.status,
        candidate.chunk_id,
        candidate.content,
        candidate.content_hash,
        candidate.section_path,
        candidate.source_file,
    )

    if any(
        not isinstance(value, str) or not value.strip()
        for value in text_values
    ):
        return False

    if (
        candidate.document_id not in KNOWN_POLICY_IDS
        or candidate.document_id not in allowed_policy_ids
        or candidate.status != "approved"
        or isinstance(candidate.chunk_index, bool)
        or not isinstance(candidate.chunk_index, int)
        or candidate.chunk_index < 0
    ):
        return False

    source_file = candidate.source_file
    return (
        bool(source_file.strip())
        and Path(source_file).name == source_file
        and "/" not in source_file
        and "\\" not in source_file
    )


def _candidate_rank_key(
    candidate: RetrievedPolicy,
) -> tuple[float, str, str, int, str]:
    return (
        -float(candidate.relevance_score),
        candidate.document_id,
        candidate.section_path.casefold(),
        candidate.chunk_index,
        candidate.chunk_id,
    )


def _normalized_tokens(text: str) -> tuple[str, ...]:
    if not isinstance(text, str):
        raise TypeError("Retrieval overlap inputs must be strings.")

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(NORMALIZED_TOKEN_PATTERN.findall(normalized))


def _is_high_overlap_adjacent_candidate(
    candidate: RetrievedPolicy,
    retained: RetrievedPolicy,
    *,
    overlap_threshold: float,
) -> bool:
    if (
        candidate.document_id != retained.document_id
        or candidate.section_path != retained.section_path
        or abs(candidate.chunk_index - retained.chunk_index) != 1
    ):
        return False

    return (
        normalized_token_overlap_ratio(
            candidate.content,
            retained.content,
        )
        > overlap_threshold
    )


def _to_retrieved_policy(
    document: Document,
    *,
    distance: float,
    allowed_policy_ids: frozenset[str],
) -> RetrievedPolicy:
    if not isinstance(document, Document):
        raise PolicyRetrievalError(
            "Vector store returned a non-Document candidate."
        )

    chunk_id = document.id
    content = document.page_content
    metadata = document.metadata

    if not isinstance(chunk_id, str) or not chunk_id:
        raise PolicyRetrievalError(
            "Retrieved policy candidate has no stable chunk ID."
        )

    if not isinstance(metadata, Mapping):
        raise PolicyRetrievalError(
            "Retrieved policy candidate metadata is malformed."
        )

    if set(metadata) != EXPECTED_CHUNK_METADATA_FIELDS:
        raise PolicyRetrievalError(
            "Retrieved policy candidate metadata fields are invalid."
        )

    _validate_candidate_integrity(
        chunk_id=chunk_id,
        content=content,
        metadata=metadata,
        allowed_policy_ids=allowed_policy_ids,
    )

    try:
        return RetrievedPolicy(
            chunk_id=chunk_id,
            document_id=str(metadata["document_id"]),
            content=content,
            source_file=str(metadata["source_file"]),
            title=str(metadata["title"]),
            section_path=str(metadata["section_path"]),
            version=str(metadata["version"]),
            effective_date=str(metadata["effective_date"]),
            review_date=str(metadata["review_date"]),
            status="approved",
            chunk_index=int(metadata["chunk_index"]),
            content_hash=str(metadata["content_hash"]),
            relevance_score=cosine_distance_to_relevance(distance),
        )
    except (TypeError, ValueError) as exc:
        raise PolicyRetrievalError(
            "Retrieved policy candidate cannot satisfy the result contract."
        ) from exc


def _validate_candidate_integrity(
    *,
    chunk_id: str,
    content: str,
    metadata: Mapping[str, object],
    allowed_policy_ids: frozenset[str],
) -> None:
    try:
        normalized_content = normalize_chunk_content(content)
    except (TypeError, ValueError) as exc:
        raise PolicyRetrievalError(
            "Retrieved policy candidate content is invalid."
        ) from exc

    if normalized_content != content:
        raise PolicyRetrievalError(
            "Retrieved policy candidate content is not canonical."
        )

    document_id = metadata["document_id"]

    if (
        not isinstance(document_id, str)
        or document_id not in KNOWN_POLICY_IDS
        or document_id not in allowed_policy_ids
    ):
        raise PolicyRetrievalError(
            "Retrieved policy candidate escaped the allowed policy filter."
        )

    if (
        metadata["status"] != "approved"
        or metadata["jurisdiction"] != "fictional_prototype"
    ):
        raise PolicyRetrievalError(
            "Retrieved policy candidate is not approved for the prototype."
        )

    required_text_fields = (
        "source_file",
        "title",
        "version",
        "effective_date",
        "review_date",
        "owner",
        "policy_type",
        "product",
        "section_path",
    )

    if any(
        not isinstance(metadata[field_name], str)
        or not str(metadata[field_name]).strip()
        for field_name in required_text_fields
    ):
        raise PolicyRetrievalError(
            "Retrieved policy candidate contains blank metadata."
        )

    for header_name in ("header_1", "header_2", "header_3"):
        if not isinstance(metadata[header_name], str):
            raise PolicyRetrievalError(
                "Retrieved policy candidate heading metadata is invalid."
            )

    source_file = str(metadata["source_file"])

    if (
        Path(source_file).name != source_file
        or "/" in source_file
        or "\\" in source_file
    ):
        raise PolicyRetrievalError(
            "Retrieved policy candidate source filename is unsafe."
        )

    source_hash = metadata["source_hash"]
    content_hash = metadata["content_hash"]

    if (
        not isinstance(source_hash, str)
        or SHA256_PATTERN.fullmatch(source_hash) is None
        or not isinstance(content_hash, str)
        or SHA256_PATTERN.fullmatch(content_hash) is None
        or compute_content_hash(content) != content_hash
    ):
        raise PolicyRetrievalError(
            "Retrieved policy candidate hashes are invalid."
        )

    chunk_index = metadata["chunk_index"]

    if (
        isinstance(chunk_index, bool)
        or not isinstance(chunk_index, int)
        or chunk_index < 0
    ):
        raise PolicyRetrievalError(
            "Retrieved policy candidate chunk index is invalid."
        )

    effective_date = _parse_candidate_date(
        metadata["effective_date"],
        field_name="effective_date",
    )
    review_date = _parse_candidate_date(
        metadata["review_date"],
        field_name="review_date",
    )

    if effective_date > review_date:
        raise PolicyRetrievalError(
            "Retrieved policy candidate dates are inconsistent."
        )

    expected_base_id = build_stable_chunk_id(
        document_id=document_id,
        section_path=str(metadata["section_path"]),
        content_hash=content_hash,
    )

    if (
        chunk_id != expected_base_id
        and not _has_valid_occurrence_suffix(
            chunk_id,
            base_id=expected_base_id,
        )
    ):
        raise PolicyRetrievalError(
            "Retrieved policy candidate stable chunk ID is invalid."
        )


def _parse_candidate_date(value: object, *, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise PolicyRetrievalError(
            f"Retrieved policy candidate {field_name} is invalid."
        ) from exc

    if parsed.isoformat() != value:
        raise PolicyRetrievalError(
            f"Retrieved policy candidate {field_name} is not canonical."
        )

    return parsed


def _has_valid_occurrence_suffix(
    chunk_id: str,
    *,
    base_id: str,
) -> bool:
    prefix = f"{base_id}-"

    if not chunk_id.startswith(prefix):
        return False

    suffix = chunk_id[len(prefix):]
    return (
        suffix.isdigit()
        and len(suffix) >= 2
        and int(suffix) >= 2
    )


__all__ = [
    "ADJACENT_CHUNK_OVERLAP_THRESHOLD",
    "PolicyRetrievalError",
    "PolicyRetriever",
    "cosine_distance_to_relevance",
    "filter_retrieval_candidates",
    "get_retriever",
    "normalized_token_overlap_ratio",
    "retrieval_is_sufficient",
    "validate_retrieval_manifest",
]
