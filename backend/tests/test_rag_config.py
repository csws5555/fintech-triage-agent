from __future__ import annotations

from dataclasses import replace

import pytest

from app.ml.rag_config import (
    RagConfigurationError,
    is_cloud_model_name,
    load_rag_settings,
    settings,
    validate_rag_settings,
)


def test_current_settings_are_valid() -> None:
    validate_rag_settings(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("ollama_base_url", "https://example.com"),
        ("chat_model", "llama3.2:cloud"),
        ("embedding_model", "unreviewed-embedder"),
        ("chroma_distance_metric", "l2"),
        ("embedding_document_prefix", "passage:"),
        ("embedding_query_prefix", "query:"),
        ("candidate_k", 0),
        ("max_context_chunks", 0),
        ("min_relevance_score", float("nan")),
        ("chunk_size", 199),
        ("chunk_overlap", -1),
        ("classifier_max_length", 513),
        ("temperature", -0.1),
        ("max_response_characters", 199),
    ),
)
def test_invalid_settings_are_rejected(field: str, value: object) -> None:
    invalid = replace(settings, **{field: value})

    with pytest.raises(RagConfigurationError):
        validate_rag_settings(invalid)


def test_candidate_k_must_cover_context_count() -> None:
    invalid = replace(settings, candidate_k=3, max_context_chunks=4)

    with pytest.raises(RagConfigurationError):
        validate_rag_settings(invalid)


@pytest.mark.parametrize(
    "base_url",
    (
        "http://127.0.0.1:not-a-port",
        "http://127.0.0.1:70000",
    ),
)
def test_malformed_ollama_ports_are_rejected(
    base_url: str,
) -> None:
    with pytest.raises(RagConfigurationError, match="port"):
        validate_rag_settings(
            replace(settings, ollama_base_url=base_url)
        )


def test_chunk_overlap_must_be_smaller_than_chunk_size() -> None:
    invalid = replace(settings, chunk_size=700, chunk_overlap=700)

    with pytest.raises(RagConfigurationError):
        validate_rag_settings(invalid)


def test_missing_environment_value_is_rejected() -> None:
    environment = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in settings_file_lines()
    }
    environment.pop("OLLAMA_CHAT_MODEL")

    with pytest.raises(
        RagConfigurationError,
        match="OLLAMA_CHAT_MODEL",
    ):
        load_rag_settings(environment)


def test_cloud_model_name_detection() -> None:
    assert is_cloud_model_name("llama3.2:cloud")
    assert is_cloud_model_name("example-cloud")
    assert not is_cloud_model_name("llama3.2:3b")


def settings_file_lines() -> tuple[str, ...]:
    from app.ml.rag_config import ENV_EXAMPLE_FILE

    return tuple(
        line.strip()
        for line in ENV_EXAMPLE_FILE.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
