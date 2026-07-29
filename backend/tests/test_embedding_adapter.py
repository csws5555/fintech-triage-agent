from __future__ import annotations

import pytest
from langchain_core.embeddings import Embeddings

from app.ml.embeddings import (
    EmbeddingValidationError,
    NomicRagEmbeddings,
)


class RecordingEmbeddings(Embeddings):
    def __init__(self) -> None:
        self.documents: list[list[str]] = []
        self.queries: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.append(list(texts))
        return [[float(index), 2.0] for index, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [3.0, 4.0]


class FailingEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ConnectionError("local Ollama unavailable")

    def embed_query(self, text: str) -> list[float]:
        raise ConnectionError("local Ollama unavailable")


def make_adapter(
    base: Embeddings,
) -> NomicRagEmbeddings:
    return NomicRagEmbeddings(
        base,
        document_prefix="search_document:",
        query_prefix="search_query:",
    )


def test_document_prefix_is_applied_exactly_once() -> None:
    base = RecordingEmbeddings()
    adapter = make_adapter(base)

    vectors = adapter.embed_documents(
        [
            "Approved policy text.",
            " search_document: Already prefixed. ",
        ]
    )

    assert base.documents == [[
        "search_document: Approved policy text.",
        "search_document: Already prefixed.",
    ]]
    assert vectors == [[0.0, 2.0], [1.0, 2.0]]


def test_query_prefix_is_applied_exactly_once() -> None:
    base = RecordingEmbeddings()
    adapter = make_adapter(base)

    assert adapter.embed_query("Card fraud") == [3.0, 4.0]
    assert adapter.embed_query(
        " search_query: Card delivery "
    ) == [3.0, 4.0]
    assert base.queries == [
        "search_query: Card fraud",
        "search_query: Card delivery",
    ]


@pytest.mark.parametrize(
    "value",
    ("", " ", "\n\t", "search_query:", "search_query:   "),
)
def test_blank_or_prefix_only_query_is_rejected(value: str) -> None:
    with pytest.raises(EmbeddingValidationError):
        make_adapter(RecordingEmbeddings()).embed_query(value)


def test_empty_document_list_is_rejected() -> None:
    with pytest.raises(
        EmbeddingValidationError,
        match="At least one",
    ):
        make_adapter(RecordingEmbeddings()).embed_documents([])


@pytest.mark.parametrize("value", ("", " ", "\n\t"))
def test_blank_document_text_is_rejected(value: str) -> None:
    with pytest.raises(EmbeddingValidationError, match="blank"):
        make_adapter(RecordingEmbeddings()).embed_documents([value])


def test_malformed_existing_prefix_is_rejected() -> None:
    with pytest.raises(
        EmbeddingValidationError,
        match="malformed",
    ):
        make_adapter(RecordingEmbeddings()).embed_query(
            "search_query:card fraud"
        )


def test_base_adapter_exception_propagates() -> None:
    adapter = make_adapter(FailingEmbeddings())

    with pytest.raises(
        ConnectionError,
        match="Ollama unavailable",
    ):
        adapter.embed_query("Card fraud")


def test_invalid_output_dimensions_fail_closed() -> None:
    class InconsistentEmbeddings(RecordingEmbeddings):
        def embed_documents(
            self,
            texts: list[str],
        ) -> list[list[float]]:
            return [[1.0], [1.0, 2.0]]

    with pytest.raises(
        EmbeddingValidationError,
        match="inconsistent",
    ):
        make_adapter(InconsistentEmbeddings()).embed_documents(
            ["one", "two"]
        )
