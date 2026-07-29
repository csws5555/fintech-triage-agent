from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.ml.rag_config import settings
from scripts import check_ollama
from scripts.check_ollama import (
    OllamaHealthCheckError,
    run_ollama_health_checks,
)


CHAT_DIGEST = "a" * 64
EMBEDDING_DIGEST = "b" * 64
GENERATED_PROBE = "probe output that must not be printed"


class FakeOllamaClient:
    def __init__(
        self,
        *,
        models: object | None = None,
        list_error: Exception | None = None,
        embed_response: object | None = None,
        embed_error: Exception | None = None,
        generation_response: object | None = None,
        generation_error: Exception | None = None,
    ) -> None:
        self.models = (
            [
                {
                    "model": settings.chat_model,
                    "digest": CHAT_DIGEST,
                },
                {
                    "model": f"{settings.embedding_model}:latest",
                    "digest": EMBEDDING_DIGEST,
                },
            ]
            if models is None
            else models
        )
        self.list_error = list_error
        self.embed_response = (
            {"embeddings": [[0.25, -0.5, 0.75]]}
            if embed_response is None
            else embed_response
        )
        self.embed_error = embed_error
        self.generation_response = (
            {"response": GENERATED_PROBE}
            if generation_response is None
            else generation_response
        )
        self.generation_error = generation_error
        self.embed_calls: list[dict[str, Any]] = []
        self.generate_calls: list[dict[str, Any]] = []

    def list(self) -> dict[str, object]:
        if self.list_error is not None:
            raise self.list_error
        return {"models": self.models}

    def embed(self, **kwargs: Any) -> object:
        self.embed_calls.append(kwargs)
        if self.embed_error is not None:
            raise self.embed_error
        return self.embed_response

    def generate(self, **kwargs: Any) -> object:
        self.generate_calls.append(kwargs)
        if self.generation_error is not None:
            raise self.generation_error
        return self.generation_response


class RecordingClientFactory:
    def __init__(
        self,
        client: object | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.client = FakeOllamaClient() if client is None else client
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.client


def test_health_check_uses_validated_settings_and_safe_probes() -> None:
    client = FakeOllamaClient()
    factory = RecordingClientFactory(client)

    report = run_ollama_health_checks(
        settings,
        client_factory=factory,
    )

    assert report.chat_model == settings.chat_model
    assert report.embedding_model == settings.embedding_model
    assert report.embedding_dimensions == 3
    assert factory.calls == [{
        "host": settings.ollama_base_url,
        "timeout": settings.request_timeout_seconds,
    }]
    assert client.embed_calls == [{
        "model": settings.embedding_model,
        "input": (
            f"{settings.embedding_query_prefix} "
            f"{check_ollama.HEALTH_EMBEDDING_TEXT}"
        ),
    }]
    assert client.generate_calls == [{
        "model": settings.chat_model,
        "prompt": check_ollama.HEALTH_GENERATION_PROMPT,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": settings.context_length,
            "num_predict": 16,
        },
    }]


def test_main_prints_only_the_required_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeOllamaClient()

    monkeypatch.setattr(
        check_ollama,
        "run_ollama_health_checks",
        lambda: run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(client),
        ),
    )

    assert check_ollama.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "PASS Ollama reachable",
        f"PASS local chat model installed: {settings.chat_model}",
        (
            "PASS local embedding model installed: "
            f"{settings.embedding_model}"
        ),
        "PASS chat model digest recorded",
        "PASS embedding model digest recorded",
        "PASS test embedding",
        "PASS test generation",
        "PASS no cloud-tagged model configured",
    ]
    assert CHAT_DIGEST not in captured.out
    assert EMBEDDING_DIGEST not in captured.out
    assert "0.25" not in captured.out
    assert GENERATED_PROBE not in captured.out


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("ollama_base_url", "https://example.com:11434"),
        ("chat_model", "llama3.2:cloud"),
        ("chat_model", "unapproved-chat"),
        ("embedding_model", "nomic-embed-text:cloud"),
        ("embedding_model", "unapproved-embedding"),
    ),
)
def test_invalid_or_nonlocal_configuration_fails_before_client_construction(
    field: str,
    value: str,
) -> None:
    factory = RecordingClientFactory()

    with pytest.raises(
        OllamaHealthCheckError,
        match="configuration is invalid",
    ):
        run_ollama_health_checks(
            replace(settings, **{field: value}),
            client_factory=factory,
        )

    assert factory.calls == []


def test_client_initialization_failure_is_safely_wrapped() -> None:
    factory = RecordingClientFactory(
        error=RuntimeError("private provider detail"),
    )

    with pytest.raises(
        OllamaHealthCheckError,
        match="could not be initialized",
    ) as captured:
        run_ollama_health_checks(
            settings,
            client_factory=factory,
        )

    assert "private provider detail" not in str(captured.value)


@pytest.mark.parametrize(
    "client",
    (
        FakeOllamaClient(
            list_error=ConnectionError("private connection detail"),
        ),
        object(),
    ),
)
def test_unreachable_or_uninspectable_ollama_fails_closed(
    client: object,
) -> None:
    with pytest.raises(OllamaHealthCheckError):
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(client),
        )


def test_malformed_installed_model_response_fails_closed() -> None:
    class MalformedListClient(FakeOllamaClient):
        def list(self) -> dict[str, object]:
            return {"models": "not-a-list"}

    with pytest.raises(
        OllamaHealthCheckError,
        match="malformed installed-model",
    ):
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(
                MalformedListClient()
            ),
        )


@pytest.mark.parametrize(
    "models",
    (
        [
            {
                "model": f"{settings.embedding_model}:latest",
                "digest": EMBEDDING_DIGEST,
            }
        ],
        [
            {
                "model": settings.chat_model,
                "digest": CHAT_DIGEST,
            }
        ],
        [
            {
                "model": settings.chat_model,
                "digest": CHAT_DIGEST,
            },
            {
                "model": settings.chat_model,
                "digest": CHAT_DIGEST,
            },
            {
                "model": f"{settings.embedding_model}:latest",
                "digest": EMBEDDING_DIGEST,
            },
        ],
    ),
)
def test_missing_or_duplicate_required_model_fails_closed(
    models: list[dict[str, str]],
) -> None:
    with pytest.raises(
        OllamaHealthCheckError,
        match="must be installed exactly once",
    ):
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(
                FakeOllamaClient(models=models)
            ),
        )


@pytest.mark.parametrize("model_index", (0, 1))
def test_missing_or_invalid_digest_fails_closed(
    model_index: int,
) -> None:
    models = [
        {
            "model": settings.chat_model,
            "digest": CHAT_DIGEST,
        },
        {
            "model": f"{settings.embedding_model}:latest",
            "digest": EMBEDDING_DIGEST,
        },
    ]
    models[model_index]["digest"] = "not-a-digest"

    with pytest.raises(
        OllamaHealthCheckError,
        match="digest is missing or invalid",
    ):
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(
                FakeOllamaClient(models=models)
            ),
        )


@pytest.mark.parametrize(
    "embed_response",
    (
        {"embeddings": []},
        {"embeddings": [[]]},
        {"embeddings": [[float("nan")]]},
        {"embeddings": [[True]]},
        {"embedding": [[1.0]]},
    ),
)
def test_empty_or_malformed_embedding_fails_closed(
    embed_response: object,
) -> None:
    with pytest.raises(OllamaHealthCheckError):
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(
                FakeOllamaClient(embed_response=embed_response)
            ),
        )


def test_embedding_request_failure_is_safely_wrapped() -> None:
    with pytest.raises(
        OllamaHealthCheckError,
        match="embedding request failed",
    ) as captured:
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(
                FakeOllamaClient(
                    embed_error=RuntimeError(
                        "private embedding detail"
                    )
                )
            ),
        )

    assert "private embedding detail" not in str(captured.value)


@pytest.mark.parametrize(
    "generation_response",
    (
        {"response": ""},
        {"response": "   "},
        {"text": "OK"},
    ),
)
def test_empty_or_malformed_generation_fails_closed(
    generation_response: object,
) -> None:
    with pytest.raises(
        OllamaHealthCheckError,
        match="response is empty or malformed",
    ):
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(
                FakeOllamaClient(
                    generation_response=generation_response
                )
            ),
        )


def test_generation_request_failure_is_safely_wrapped() -> None:
    with pytest.raises(
        OllamaHealthCheckError,
        match="generation request failed",
    ) as captured:
        run_ollama_health_checks(
            settings,
            client_factory=RecordingClientFactory(
                FakeOllamaClient(
                    generation_error=RuntimeError(
                        "private generation detail"
                    )
                )
            ),
        )

    assert "private generation detail" not in str(captured.value)


def test_main_returns_nonzero_without_provider_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> None:
        raise OllamaHealthCheckError("The test embedding request failed.")

    monkeypatch.setattr(
        check_ollama,
        "run_ollama_health_checks",
        fail,
    )

    assert check_ollama.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "FAIL The test embedding request failed.\n"
