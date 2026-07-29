"""
Central configuration for the Phase 2 local RAG system.

This module:

- Resolves project paths with pathlib.
- Loads backend/.env explicitly.
- Exposes immutable application settings.
- Validates all environment variables at startup.
- Restricts Ollama to explicitly approved local models.
- Rejects cloud-tagged Ollama models.
- Restricts the Ollama endpoint to the local machine.
- Exposes shared paths for policy ingestion, Chroma persistence,
  evaluation data, and the saved Phase 1 classifier.

The module intentionally does not:

- Contact Ollama.
- Create directories.
- Connect to Chroma.
- Load the classifier.
- Modify any model or policy files.

Those responsibilities belong to later modules and scripts.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv


# ============================================================
# Project paths
# ============================================================

# This file is:
# backend/app/ml/rag_config.py
RAG_CONFIG_FILE = Path(__file__).resolve()

ML_DIR = RAG_CONFIG_FILE.parent
APP_DIR = ML_DIR.parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE_FILE = BACKEND_DIR / ".env.example"

DATA_DIR = APP_DIR / "data"
POLICIES_DIR = DATA_DIR / "policies"

CHROMA_STORE_DIR = DATA_DIR / "chromadb_store"
CHROMA_TEMP_DIR = DATA_DIR / "chromadb_store_tmp"
CHROMA_BACKUP_DIR = DATA_DIR / "chromadb_store_backup"

INGESTION_MANIFEST_PATH = (
    CHROMA_STORE_DIR / "ingestion_manifest.json"
)

SCRIPTS_DIR = BACKEND_DIR / "scripts"
TESTS_DIR = BACKEND_DIR / "tests"
TEST_DATA_DIR = TESTS_DIR / "data"

RAG_EVALUATION_CASES_PATH = (
    TEST_DATA_DIR / "rag_evaluation_cases.json"
)

SAVED_MODELS_DIR = BACKEND_DIR / "saved_models"
CLASSIFIER_MODEL_DIR = (
    SAVED_MODELS_DIR / "distilbert_fintech_pt"
)


# ============================================================
# Approved local models
# ============================================================

# These strict allowlists ensure that the prototype only uses
# explicitly reviewed local Ollama models.
#
# Adding another model should require an explicit code change and
# review rather than only an environment-variable modification.
ALLOWED_CHAT_MODELS: frozenset[str] = frozenset(
    {
        "llama3.2:3b",
    }
)

ALLOWED_EMBEDDING_MODELS: frozenset[str] = frozenset(
    {
        "nomic-embed-text",
    }
)


# The allowlists above are the main security control.
#
# These patterns provide an additional explicit check and clearer
# error messages when a model name appears to contain a cloud tag.
CLOUD_MODEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r":cloud(?:$|[-:@/])",
        re.IGNORECASE,
    ),
    re.compile(
        r"-cloud(?:$|[-:@/])",
        re.IGNORECASE,
    ),
    re.compile(
        r"/cloud(?:$|[-:@/])",
        re.IGNORECASE,
    ),
)


# ============================================================
# Configuration errors
# ============================================================


class RagConfigurationError(ValueError):
    """Raised when Phase 2 configuration is missing or invalid."""


# ============================================================
# Immutable settings
# ============================================================


@dataclass(frozen=True, slots=True)
class RagSettings:
    """
    Validated runtime configuration for the local RAG pipeline.

    All values originate from backend/.env or operating-system
    environment variables.

    The dataclass is frozen so runtime components cannot
    accidentally modify the configuration after startup.
    """

    ollama_base_url: str
    chat_model: str
    embedding_model: str

    collection_name: str
    chroma_distance_metric: str

    candidate_k: int
    max_context_chunks: int
    min_relevance_score: float

    chunk_size: int
    chunk_overlap: int

    embedding_document_prefix: str
    embedding_query_prefix: str

    classifier_confidence_threshold: float
    classifier_margin_threshold: float
    classifier_max_length: int
    routing_secondary_min_confidence: float

    temperature: float
    context_length: int
    max_output_tokens: int
    request_timeout_seconds: int

    max_customer_message_length: int
    max_response_characters: int

    @property
    def policies_dir(self) -> Path:
        """Directory containing approved Markdown policy files."""
        return POLICIES_DIR

    @property
    def chroma_store_dir(self) -> Path:
        """Active persistent Chroma database directory."""
        return CHROMA_STORE_DIR

    @property
    def chroma_temp_dir(self) -> Path:
        """Temporary directory used during a staged rebuild."""
        return CHROMA_TEMP_DIR

    @property
    def chroma_backup_dir(self) -> Path:
        """Backup directory used during a staged rebuild."""
        return CHROMA_BACKUP_DIR

    @property
    def ingestion_manifest_path(self) -> Path:
        """Manifest stored beside the active Chroma database."""
        return INGESTION_MANIFEST_PATH

    @property
    def classifier_model_dir(self) -> Path:
        """Location of the protected Phase 1 classifier."""
        return CLASSIFIER_MODEL_DIR

    @property
    def evaluation_cases_path(self) -> Path:
        """Location of the Phase 2 RAG evaluation dataset."""
        return RAG_EVALUATION_CASES_PATH


# ============================================================
# Environment loading
# ============================================================

# Load the precise backend/.env file rather than searching upward
# from the current working directory.
#
# override=False means an operating-system environment variable,
# when deliberately supplied, takes precedence over .env.
load_dotenv(
    dotenv_path=ENV_FILE,
    override=False,
    encoding="utf-8",
)


# ============================================================
# Parsing helpers
# ============================================================


def _required_string(
    source: Mapping[str, str],
    name: str,
) -> str:
    """
    Read a required non-empty string from an environment mapping.
    """

    raw_value = source.get(name)

    if raw_value is None:
        raise RagConfigurationError(
            f"Missing required environment variable: {name}"
        )

    value = raw_value.strip()

    if not value:
        raise RagConfigurationError(
            f"Environment variable {name} cannot be empty."
        )

    return value


def _required_int(
    source: Mapping[str, str],
    name: str,
) -> int:
    """
    Read and parse a required integer environment variable.
    """

    raw_value = _required_string(source, name)

    try:
        return int(raw_value)
    except ValueError as exc:
        raise RagConfigurationError(
            f"{name} must be an integer; "
            f"received {raw_value!r}."
        ) from exc


def _required_float(
    source: Mapping[str, str],
    name: str,
) -> float:
    """
    Read and parse a required finite floating-point value.
    """

    raw_value = _required_string(source, name)

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RagConfigurationError(
            f"{name} must be a number; "
            f"received {raw_value!r}."
        ) from exc

    if not math.isfinite(value):
        raise RagConfigurationError(
            f"{name} must be a finite number; "
            f"received {raw_value!r}."
        )

    return value


# ============================================================
# Model validation
# ============================================================


def is_cloud_model_name(model_name: str) -> bool:
    """
    Return True when an Ollama model name appears cloud-tagged.

    The explicit model allowlists remain the primary control.
    """

    normalized = model_name.strip()

    return any(
        pattern.search(normalized) is not None
        for pattern in CLOUD_MODEL_PATTERNS
    )


def _validate_model_configuration(
    *,
    chat_model: str,
    embedding_model: str,
) -> None:
    """
    Enforce local-only, explicitly approved Ollama model names.
    """

    if is_cloud_model_name(chat_model):
        raise RagConfigurationError(
            "OLLAMA_CHAT_MODEL cannot reference a cloud model. "
            f"Received: {chat_model!r}"
        )

    if is_cloud_model_name(embedding_model):
        raise RagConfigurationError(
            "OLLAMA_EMBEDDING_MODEL cannot reference a cloud "
            f"model. Received: {embedding_model!r}"
        )

    if chat_model not in ALLOWED_CHAT_MODELS:
        allowed = ", ".join(
            sorted(ALLOWED_CHAT_MODELS)
        )

        raise RagConfigurationError(
            "OLLAMA_CHAT_MODEL is not approved. "
            f"Received {chat_model!r}; "
            f"allowed values: {allowed}"
        )

    if embedding_model not in ALLOWED_EMBEDDING_MODELS:
        allowed = ", ".join(
            sorted(ALLOWED_EMBEDDING_MODELS)
        )

        raise RagConfigurationError(
            "OLLAMA_EMBEDDING_MODEL is not approved. "
            f"Received {embedding_model!r}; "
            f"allowed values: {allowed}"
        )


# ============================================================
# URL validation
# ============================================================


def _validate_ollama_base_url(base_url: str) -> None:
    """
    Ensure the configured Ollama endpoint is a local HTTP endpoint.

    This prototype is designed to communicate only with Ollama
    running on the same machine.
    """

    parsed = urlparse(base_url)

    if parsed.scheme not in {"http", "https"}:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL must use http or https."
        )

    if not parsed.hostname:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL must include a hostname."
        )

    allowed_hosts = {
        "127.0.0.1",
        "localhost",
        "::1",
    }

    if parsed.hostname.lower() not in allowed_hosts:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL must point to the local machine. "
            "Allowed hosts are 127.0.0.1, localhost, and ::1."
        )

    if (
        parsed.username is not None
        or parsed.password is not None
    ):
        raise RagConfigurationError(
            "OLLAMA_BASE_URL must not contain credentials."
        )

    if parsed.query or parsed.fragment:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL must not contain a query string "
            "or URL fragment."
        )

    if parsed.path not in {"", "/"}:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL must be the server base URL and "
            "must not include an API path."
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL contains a malformed port."
        ) from exc

    if port is None:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL must include the Ollama port."
        )

    if not 1 <= port <= 65535:
        raise RagConfigurationError(
            "OLLAMA_BASE_URL contains an invalid port."
        )


# ============================================================
# Chroma validation
# ============================================================


def _validate_collection_name(
    collection_name: str,
) -> None:
    """
    Perform conservative validation of the Chroma collection name.
    """

    if len(collection_name) < 3:
        raise RagConfigurationError(
            "CHROMA_COLLECTION_NAME must contain at least "
            "3 characters."
        )

    if len(collection_name) > 512:
        raise RagConfigurationError(
            "CHROMA_COLLECTION_NAME cannot exceed "
            "512 characters."
        )

    allowed_pattern = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )

    if allowed_pattern.fullmatch(collection_name) is None:
        raise RagConfigurationError(
            "CHROMA_COLLECTION_NAME may contain only letters, "
            "numbers, periods, underscores, and hyphens, and "
            "must begin with a letter or number."
        )


# ============================================================
# Complete settings validation
# ============================================================


def validate_rag_settings(
    settings: RagSettings,
) -> None:
    """
    Validate a complete RagSettings instance.

    This function is public so unit tests can construct settings
    directly without modifying the real process environment.
    """

    _validate_ollama_base_url(
        settings.ollama_base_url
    )

    _validate_model_configuration(
        chat_model=settings.chat_model,
        embedding_model=settings.embedding_model,
    )

    _validate_collection_name(
        settings.collection_name
    )

    if settings.chroma_distance_metric != "cosine":
        raise RagConfigurationError(
            "CHROMA_DISTANCE_METRIC must be cosine for this "
            "prototype."
        )

    if settings.candidate_k < 1:
        raise RagConfigurationError(
            "RAG_CANDIDATE_K must be at least 1."
        )

    if settings.max_context_chunks < 1:
        raise RagConfigurationError(
            "RAG_MAX_CONTEXT_CHUNKS must be at least 1."
        )

    if settings.candidate_k < settings.max_context_chunks:
        raise RagConfigurationError(
            "RAG_CANDIDATE_K must be greater than or equal to "
            "RAG_MAX_CONTEXT_CHUNKS."
        )

    if not (
        0.0
        <= settings.min_relevance_score
        <= 1.0
    ):
        raise RagConfigurationError(
            "RAG_MIN_RELEVANCE_SCORE must be between 0 and 1."
        )

    if settings.chunk_size < 200:
        raise RagConfigurationError(
            "RAG_CHUNK_SIZE must be at least 200."
        )

    if settings.chunk_overlap < 0:
        raise RagConfigurationError(
            "RAG_CHUNK_OVERLAP cannot be negative."
        )

    if settings.chunk_overlap >= settings.chunk_size:
        raise RagConfigurationError(
            "RAG_CHUNK_OVERLAP must be smaller than "
            "RAG_CHUNK_SIZE."
        )

    if (
        settings.embedding_document_prefix
        != "search_document:"
    ):
        raise RagConfigurationError(
            "EMBEDDING_DOCUMENT_PREFIX must be "
            "'search_document:' when using nomic-embed-text."
        )

    if (
        settings.embedding_query_prefix
        != "search_query:"
    ):
        raise RagConfigurationError(
            "EMBEDDING_QUERY_PREFIX must be "
            "'search_query:' when using nomic-embed-text."
        )

    if not (
        0.0
        <= settings.classifier_confidence_threshold
        <= 1.0
    ):
        raise RagConfigurationError(
            "CLASSIFIER_CONFIDENCE_THRESHOLD must be "
            "between 0 and 1."
        )

    if not (
        0.0
        <= settings.classifier_margin_threshold
        <= 1.0
    ):
        raise RagConfigurationError(
            "CLASSIFIER_MARGIN_THRESHOLD must be "
            "between 0 and 1."
        )

    if not 8 <= settings.classifier_max_length <= 512:
        raise RagConfigurationError(
            "CLASSIFIER_MAX_LENGTH must be between 8 and 512."
        )

    if not (
        0.0
        <= settings.routing_secondary_min_confidence
        <= 1.0
    ):
        raise RagConfigurationError(
            "ROUTING_SECONDARY_MIN_CONFIDENCE must be "
            "between 0 and 1."
        )

    if settings.temperature < 0.0:
        raise RagConfigurationError(
            "OLLAMA_TEMPERATURE cannot be negative."
        )

    if settings.context_length < 1:
        raise RagConfigurationError(
            "OLLAMA_CONTEXT_LENGTH must be at least 1."
        )

    if settings.max_output_tokens < 1:
        raise RagConfigurationError(
            "OLLAMA_MAX_OUTPUT_TOKENS must be at least 1."
        )

    if (
        settings.max_output_tokens
        > settings.context_length
    ):
        raise RagConfigurationError(
            "OLLAMA_MAX_OUTPUT_TOKENS cannot exceed "
            "OLLAMA_CONTEXT_LENGTH."
        )

    if settings.request_timeout_seconds < 1:
        raise RagConfigurationError(
            "OLLAMA_REQUEST_TIMEOUT_SECONDS must be "
            "at least 1."
        )

    if settings.max_customer_message_length < 100:
        raise RagConfigurationError(
            "MAX_CUSTOMER_MESSAGE_LENGTH must be at least 100."
        )

    if settings.max_response_characters < 200:
        raise RagConfigurationError(
            "MAX_RESPONSE_CHARACTERS must be at least 200."
        )


# ============================================================
# Settings construction
# ============================================================


def load_rag_settings(
    environ: Mapping[str, str] | None = None,
) -> RagSettings:
    """
    Build and validate RagSettings.

    Args:
        environ:
            Optional environment mapping. When omitted,
            os.environ is used.

            Passing a custom mapping is useful for unit tests and
            does not modify the process environment.

    Returns:
        A fully validated immutable RagSettings instance.

    Raises:
        RagConfigurationError:
            If any required setting is missing or invalid.
    """

    source = (
        os.environ
        if environ is None
        else environ
    )

    settings = RagSettings(
        ollama_base_url=_required_string(
            source,
            "OLLAMA_BASE_URL",
        ).rstrip("/"),

        chat_model=_required_string(
            source,
            "OLLAMA_CHAT_MODEL",
        ),

        embedding_model=_required_string(
            source,
            "OLLAMA_EMBEDDING_MODEL",
        ),

        collection_name=_required_string(
            source,
            "CHROMA_COLLECTION_NAME",
        ),

        chroma_distance_metric=_required_string(
            source,
            "CHROMA_DISTANCE_METRIC",
        ).lower(),

        candidate_k=_required_int(
            source,
            "RAG_CANDIDATE_K",
        ),

        max_context_chunks=_required_int(
            source,
            "RAG_MAX_CONTEXT_CHUNKS",
        ),

        min_relevance_score=_required_float(
            source,
            "RAG_MIN_RELEVANCE_SCORE",
        ),

        chunk_size=_required_int(
            source,
            "RAG_CHUNK_SIZE",
        ),

        chunk_overlap=_required_int(
            source,
            "RAG_CHUNK_OVERLAP",
        ),

        embedding_document_prefix=_required_string(
            source,
            "EMBEDDING_DOCUMENT_PREFIX",
        ),

        embedding_query_prefix=_required_string(
            source,
            "EMBEDDING_QUERY_PREFIX",
        ),

        classifier_confidence_threshold=_required_float(
            source,
            "CLASSIFIER_CONFIDENCE_THRESHOLD",
        ),

        classifier_margin_threshold=_required_float(
            source,
            "CLASSIFIER_MARGIN_THRESHOLD",
        ),

        classifier_max_length=_required_int(
            source,
            "CLASSIFIER_MAX_LENGTH",
        ),

        routing_secondary_min_confidence=_required_float(
            source,
            "ROUTING_SECONDARY_MIN_CONFIDENCE",
        ),

        temperature=_required_float(
            source,
            "OLLAMA_TEMPERATURE",
        ),

        context_length=_required_int(
            source,
            "OLLAMA_CONTEXT_LENGTH",
        ),

        max_output_tokens=_required_int(
            source,
            "OLLAMA_MAX_OUTPUT_TOKENS",
        ),

        request_timeout_seconds=_required_int(
            source,
            "OLLAMA_REQUEST_TIMEOUT_SECONDS",
        ),

        max_customer_message_length=_required_int(
            source,
            "MAX_CUSTOMER_MESSAGE_LENGTH",
        ),

        max_response_characters=_required_int(
            source,
            "MAX_RESPONSE_CHARACTERS",
        ),
    )

    validate_rag_settings(settings)

    return settings


# ============================================================
# Shared application settings
# ============================================================

# Later modules can use:
#
# from app.ml.rag_config import settings
#
# Invalid configuration therefore fails immediately when the
# application starts rather than during a customer request.
settings = load_rag_settings()