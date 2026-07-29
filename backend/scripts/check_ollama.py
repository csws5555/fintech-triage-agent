"""Read-only health checks for the approved local Ollama service.

Run from the backend directory:

    python scripts/check_ollama.py

The command never starts Ollama, changes installed models, opens Chroma, or
prints model digests, embedding values, or generated probe text.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ollama

# Direct script execution initially places backend/scripts on sys.path. Add the
# backend package root so the documented command works from backend/.
SCRIPT_FILE = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ml.rag_config import (  # noqa: E402
    ALLOWED_CHAT_MODELS,
    ALLOWED_EMBEDDING_MODELS,
    RagSettings,
    is_cloud_model_name,
    settings,
    validate_rag_settings,
)
from app.ml.policy_loader import SHA256_PATTERN  # noqa: E402


HEALTH_EMBEDDING_TEXT = "Ollama health check."
HEALTH_GENERATION_PROMPT = "Reply with the single word OK."


class OllamaHealthCheckError(RuntimeError):
    """Raised when any required local Ollama health check fails."""


@dataclass(frozen=True, slots=True)
class OllamaHealthReport:
    """Safe summary of a successful Ollama health check."""

    chat_model: str
    embedding_model: str
    embedding_dimensions: int


ClientFactory = Callable[..., object]


def run_ollama_health_checks(
    runtime_settings: RagSettings = settings,
    *,
    client_factory: ClientFactory = ollama.Client,
) -> OllamaHealthReport:
    """Run every Step 27 check and return only non-sensitive facts."""

    if not isinstance(runtime_settings, RagSettings):
        raise TypeError("runtime_settings must be a RagSettings instance.")

    if not callable(client_factory):
        raise TypeError("client_factory must be callable.")

    try:
        validate_rag_settings(runtime_settings)
    except Exception as exc:
        raise OllamaHealthCheckError(
            "The Ollama configuration is invalid."
        ) from exc

    _validate_approved_model_names(runtime_settings)

    try:
        client = client_factory(
            host=runtime_settings.ollama_base_url,
            timeout=runtime_settings.request_timeout_seconds,
        )
    except Exception as exc:
        raise OllamaHealthCheckError(
            "The local Ollama client could not be initialized."
        ) from exc

    installed_models = _inspect_installed_models(client)
    _require_installed_model(
        installed_models,
        configured_name=runtime_settings.chat_model,
        model_role="chat",
    )
    _require_installed_model(
        installed_models,
        configured_name=runtime_settings.embedding_model,
        model_role="embedding",
    )

    embedding_dimensions = _check_embedding(
        client,
        runtime_settings=runtime_settings,
    )
    _check_generation(
        client,
        runtime_settings=runtime_settings,
    )

    return OllamaHealthReport(
        chat_model=runtime_settings.chat_model,
        embedding_model=runtime_settings.embedding_model,
        embedding_dimensions=embedding_dimensions,
    )


def main() -> int:
    """Run the health check and return a process exit status."""

    try:
        report = run_ollama_health_checks()
    except OllamaHealthCheckError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "FAIL Unexpected local Ollama health-check error.",
            file=sys.stderr,
        )
        return 1

    print("PASS Ollama reachable")
    print(f"PASS local chat model installed: {report.chat_model}")
    print(
        "PASS local embedding model installed: "
        f"{report.embedding_model}"
    )
    print("PASS chat model digest recorded")
    print("PASS embedding model digest recorded")
    print("PASS test embedding")
    print("PASS test generation")
    print("PASS no cloud-tagged model configured")
    return 0


def _validate_approved_model_names(
    runtime_settings: RagSettings,
) -> None:
    chat_model = runtime_settings.chat_model
    embedding_model = runtime_settings.embedding_model

    if (
        is_cloud_model_name(chat_model)
        or is_cloud_model_name(embedding_model)
    ):
        raise OllamaHealthCheckError(
            "A cloud-tagged Ollama model is configured."
        )

    if (
        chat_model not in ALLOWED_CHAT_MODELS
        or embedding_model not in ALLOWED_EMBEDDING_MODELS
    ):
        raise OllamaHealthCheckError(
            "An Ollama model is outside the approved allowlist."
        )


def _inspect_installed_models(client: object) -> list[object]:
    list_models = getattr(client, "list", None)

    if not callable(list_models):
        raise OllamaHealthCheckError(
            "The local Ollama client cannot inspect installed models."
        )

    try:
        response = list_models()
    except Exception as exc:
        raise OllamaHealthCheckError(
            "Ollama did not respond to installed-model inspection."
        ) from exc

    models = _record_value(response, "models")

    if not isinstance(models, list):
        raise OllamaHealthCheckError(
            "Ollama returned a malformed installed-model response."
        )

    return models


def _require_installed_model(
    installed_models: list[object],
    *,
    configured_name: str,
    model_role: str,
) -> None:
    matches = [
        model
        for model in installed_models
        if _model_names_match(
            configured_name,
            _record_value(model, "model"),
        )
    ]

    if len(matches) != 1:
        raise OllamaHealthCheckError(
            f"The configured {model_role} model must be installed exactly once."
        )

    digest = _record_value(matches[0], "digest")

    if (
        not isinstance(digest, str)
        or SHA256_PATTERN.fullmatch(digest) is None
    ):
        raise OllamaHealthCheckError(
            f"The installed {model_role} model digest is missing or invalid."
        )


def _check_embedding(
    client: object,
    *,
    runtime_settings: RagSettings,
) -> int:
    embed = getattr(client, "embed", None)

    if not callable(embed):
        raise OllamaHealthCheckError(
            "The local Ollama client does not support embeddings."
        )

    input_text = (
        f"{runtime_settings.embedding_query_prefix} "
        f"{HEALTH_EMBEDDING_TEXT}"
    )

    try:
        response = embed(
            model=runtime_settings.embedding_model,
            input=input_text,
        )
    except Exception as exc:
        raise OllamaHealthCheckError(
            "The test embedding request failed."
        ) from exc

    embeddings = _record_value(response, "embeddings")

    if (
        not isinstance(embeddings, Sequence)
        or isinstance(embeddings, (str, bytes))
        or len(embeddings) != 1
    ):
        raise OllamaHealthCheckError(
            "The test embedding response is malformed."
        )

    vector = embeddings[0]

    if (
        not isinstance(vector, Sequence)
        or isinstance(vector, (str, bytes))
        or not vector
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in vector
        )
    ):
        raise OllamaHealthCheckError(
            "The test embedding vector is empty or invalid."
        )

    return len(vector)


def _check_generation(
    client: object,
    *,
    runtime_settings: RagSettings,
) -> None:
    generate = getattr(client, "generate", None)

    if not callable(generate):
        raise OllamaHealthCheckError(
            "The local Ollama client does not support generation."
        )

    try:
        result = generate(
            model=runtime_settings.chat_model,
            prompt=HEALTH_GENERATION_PROMPT,
            stream=False,
            options={
                "temperature": 0.0,
                "num_ctx": runtime_settings.context_length,
                "num_predict": min(
                    runtime_settings.max_output_tokens,
                    16,
                ),
            },
        )
    except Exception as exc:
        raise OllamaHealthCheckError(
            "The test generation request failed."
        ) from exc

    response_text = _record_value(result, "response")

    if (
        not isinstance(response_text, str)
        or not response_text.strip()
    ):
        raise OllamaHealthCheckError(
            "The test generation response is empty or malformed."
        )


def _record_value(record: object, field_name: str) -> object:
    if isinstance(record, Mapping):
        return record.get(field_name)

    return getattr(record, field_name, None)


def _model_names_match(
    configured_name: str,
    installed_name: object,
) -> bool:
    if not isinstance(installed_name, str):
        return False

    if installed_name == configured_name:
        return True

    return (
        ":" not in configured_name
        and installed_name == f"{configured_name}:latest"
    )


if __name__ == "__main__":
    raise SystemExit(main())
