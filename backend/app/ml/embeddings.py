"""Shared local Nomic embedding adapter for ingestion and retrieval."""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

from app.ml.rag_config import RagSettings, settings


class EmbeddingValidationError(ValueError):
    """Raised when embedding input or output is unsafe or malformed."""


class NomicRagEmbeddings(Embeddings):
    """Apply Nomic's asymmetric retrieval prefixes exactly once."""

    def __init__(
        self,
        base_embeddings: Embeddings,
        *,
        document_prefix: str,
        query_prefix: str,
    ) -> None:
        if not isinstance(base_embeddings, Embeddings):
            raise TypeError("base_embeddings must implement Embeddings.")

        self._base_embeddings = base_embeddings
        self._document_prefix = _validate_prefix(
            document_prefix,
            name="document_prefix",
        )
        self._query_prefix = _validate_prefix(
            query_prefix,
            name="query_prefix",
        )

        if self._document_prefix == self._query_prefix:
            raise EmbeddingValidationError(
                "Document and query prefixes must be different."
            )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list):
            raise TypeError("Document texts must be supplied as a list.")

        if not texts:
            raise EmbeddingValidationError(
                "At least one document text is required."
            )

        prepared = [
            _apply_prefix_once(
                text,
                prefix=self._document_prefix,
                input_name=f"document text {index}",
            )
            for index, text in enumerate(texts)
        ]
        vectors = self._base_embeddings.embed_documents(prepared)
        return _validate_vectors(
            vectors,
            expected_count=len(prepared),
        )

    def embed_query(self, text: str) -> list[float]:
        prepared = _apply_prefix_once(
            text,
            prefix=self._query_prefix,
            input_name="query text",
        )
        vector = self._base_embeddings.embed_query(prepared)
        return _validate_vectors(
            [vector],
            expected_count=1,
        )[0]


@lru_cache(maxsize=1)
def get_embeddings() -> NomicRagEmbeddings:
    """Return the process-wide validated local embedding adapter."""

    return build_embeddings(settings)


def build_embeddings(
    runtime_settings: RagSettings,
) -> NomicRagEmbeddings:
    """Construct an adapter from already validated application settings."""

    base_embeddings = OllamaEmbeddings(
        model=runtime_settings.embedding_model,
        base_url=runtime_settings.ollama_base_url,
        validate_model_on_init=True,
    )
    return NomicRagEmbeddings(
        base_embeddings,
        document_prefix=runtime_settings.embedding_document_prefix,
        query_prefix=runtime_settings.embedding_query_prefix,
    )


def _validate_prefix(prefix: str, *, name: str) -> str:
    if not isinstance(prefix, str):
        raise TypeError(f"{name} must be a string.")

    normalized = prefix.strip()

    if not normalized or not normalized.endswith(":"):
        raise EmbeddingValidationError(
            f"{name} must be a nonblank prefix ending with ':'."
        )

    if any(character.isspace() for character in normalized):
        raise EmbeddingValidationError(
            f"{name} cannot contain whitespace."
        )

    return normalized


def _apply_prefix_once(
    text: str,
    *,
    prefix: str,
    input_name: str,
) -> str:
    if not isinstance(text, str):
        raise TypeError(f"{input_name} must be a string.")

    normalized = text.strip()

    if not normalized:
        raise EmbeddingValidationError(
            f"{input_name} cannot be blank."
        )

    if normalized == prefix:
        raise EmbeddingValidationError(
            f"{input_name} cannot contain only an embedding prefix."
        )

    if normalized.startswith(prefix):
        remainder = normalized[len(prefix):]

        if not remainder or not remainder[0].isspace():
            raise EmbeddingValidationError(
                f"{input_name} has a malformed existing prefix."
            )

        content = remainder.strip()

        if not content:
            raise EmbeddingValidationError(
                f"{input_name} cannot contain only an embedding prefix."
            )

        return f"{prefix} {content}"

    return f"{prefix} {normalized}"


def _validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
) -> list[list[float]]:
    if not isinstance(vectors, Sequence) or isinstance(
        vectors,
        (str, bytes),
    ):
        raise EmbeddingValidationError(
            "Embedding provider returned a non-sequence result."
        )

    if len(vectors) != expected_count:
        raise EmbeddingValidationError(
            "Embedding provider returned an unexpected vector count."
        )

    validated: list[list[float]] = []
    dimensions: int | None = None

    for index, vector in enumerate(vectors):
        if not isinstance(vector, Sequence) or isinstance(
            vector,
            (str, bytes),
        ):
            raise EmbeddingValidationError(
                f"Embedding vector {index} is not a numeric sequence."
            )

        values = list(vector)

        if not values:
            raise EmbeddingValidationError(
                f"Embedding vector {index} is empty."
            )

        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in values
        ):
            raise EmbeddingValidationError(
                f"Embedding vector {index} contains an invalid value."
            )

        if dimensions is None:
            dimensions = len(values)
        elif len(values) != dimensions:
            raise EmbeddingValidationError(
                "Embedding provider returned inconsistent dimensions."
            )

        validated.append([float(value) for value in values])

    return validated


__all__ = [
    "EmbeddingValidationError",
    "NomicRagEmbeddings",
    "build_embeddings",
    "get_embeddings",
]
