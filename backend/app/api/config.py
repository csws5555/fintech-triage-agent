"""Immutable configuration for the Phase 3 FastAPI transport layer."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv

from app.ml.rag_config import ENV_FILE, settings


_API_PREFIX_PATTERN = re.compile(
    r"/[A-Za-z0-9](?:[A-Za-z0-9._~-]*[A-Za-z0-9])?"
    r"(?:/[A-Za-z0-9](?:[A-Za-z0-9._~-]*[A-Za-z0-9])?)*"
)
_KNOWN_LOG_LEVELS = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)
_JSON_BODY_OVERHEAD_BYTES = 256


class ApiConfigurationError(ValueError):
    """Raised when Phase 3 API configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Validated runtime settings owned by the HTTP API layer."""

    environment: str
    host: str
    port: int
    api_prefix: str
    cors_origins: tuple[str, ...]
    request_timeout_seconds: int
    queue_timeout_seconds: int
    max_concurrent_requests: int
    max_request_body_bytes: int
    health_timeout_seconds: int
    readiness_retry_cooldown_seconds: int
    log_level: str


def _required_string(source: Mapping[str, str], name: str) -> str:
    raw_value = source.get(name)
    if raw_value is None:
        raise ApiConfigurationError(
            f"Missing required environment variable: {name}"
        )

    value = raw_value.strip()
    if not value:
        raise ApiConfigurationError(
            f"Environment variable {name} cannot be empty."
        )
    return value


def _required_int(source: Mapping[str, str], name: str) -> int:
    raw_value = _required_string(source, name)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ApiConfigurationError(
            f"{name} must be an integer; received {raw_value!r}."
        ) from exc


def _parse_cors_origins(raw_value: str) -> tuple[str, ...]:
    origins: list[str] = []
    seen: set[str] = set()

    for raw_origin in raw_value.split(","):
        origin = raw_origin.strip()
        if not origin:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS cannot contain blank origins."
            )
        if "*" in origin:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS cannot contain wildcard origins."
            )

        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"}:
            raise ApiConfigurationError(
                "Each API_CORS_ORIGINS value must use http or https."
            )
        if not parsed.hostname:
            raise ApiConfigurationError(
                "Each API_CORS_ORIGINS value must include a hostname."
            )
        if parsed.username is not None or parsed.password is not None:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS values must not contain credentials."
            )
        if parsed.path not in {"", "/"}:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS values must not contain a path."
            )
        if parsed.query or parsed.fragment:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS values must not contain a query or fragment."
            )

        try:
            port = parsed.port
        except ValueError as exc:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS contains a malformed port."
            ) from exc
        if port is not None and not 1 <= port <= 65535:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS contains an invalid port."
            )

        normalized = origin[:-1] if parsed.path == "/" else origin
        if normalized in seen:
            raise ApiConfigurationError(
                "API_CORS_ORIGINS cannot contain duplicate origins."
            )
        seen.add(normalized)
        origins.append(normalized)

    return tuple(origins)


def validate_api_settings(api_runtime_settings: ApiSettings) -> None:
    """Validate a complete API settings value without external side effects."""

    for field_name in ("environment", "host"):
        value = getattr(api_runtime_settings, field_name)
        if not value or value != value.strip():
            raise ApiConfigurationError(
                f"{field_name} must be a non-empty trimmed string."
            )

    if not 1 <= api_runtime_settings.port <= 65535:
        raise ApiConfigurationError("API_PORT must be between 1 and 65535.")

    if (
        _API_PREFIX_PATTERN.fullmatch(api_runtime_settings.api_prefix)
        is None
    ):
        raise ApiConfigurationError(
            "API_PREFIX must be an absolute path without a trailing slash."
        )

    positive_timeouts = (
        (
            "API_REQUEST_TIMEOUT_SECONDS",
            api_runtime_settings.request_timeout_seconds,
        ),
        (
            "API_QUEUE_TIMEOUT_SECONDS",
            api_runtime_settings.queue_timeout_seconds,
        ),
        (
            "API_HEALTH_TIMEOUT_SECONDS",
            api_runtime_settings.health_timeout_seconds,
        ),
        (
            "API_READINESS_RETRY_COOLDOWN_SECONDS",
            api_runtime_settings.readiness_retry_cooldown_seconds,
        ),
    )
    for name, value in positive_timeouts:
        if value < 1:
            raise ApiConfigurationError(f"{name} must be at least 1.")

    if not 1 <= api_runtime_settings.max_concurrent_requests <= 4:
        raise ApiConfigurationError(
            "API_MAX_CONCURRENT_REQUESTS must be between 1 and 4."
        )

    minimum_body_bytes = (
        settings.max_customer_message_length + _JSON_BODY_OVERHEAD_BYTES
    )
    if api_runtime_settings.max_request_body_bytes <= minimum_body_bytes:
        raise ApiConfigurationError(
            "API_MAX_REQUEST_BODY_BYTES must exceed the maximum customer "
            f"message length plus {_JSON_BODY_OVERHEAD_BYTES} bytes."
        )

    if not api_runtime_settings.cors_origins:
        raise ApiConfigurationError(
            "API_CORS_ORIGINS must contain at least one exact origin."
        )
    reparsed_origins = _parse_cors_origins(
        ",".join(api_runtime_settings.cors_origins)
    )
    if reparsed_origins != api_runtime_settings.cors_origins:
        raise ApiConfigurationError(
            "API_CORS_ORIGINS must contain normalized exact origins."
        )

    if api_runtime_settings.log_level not in _KNOWN_LOG_LEVELS:
        allowed = ", ".join(sorted(_KNOWN_LOG_LEVELS))
        raise ApiConfigurationError(
            f"API_LOG_LEVEL must be one of: {allowed}."
        )


def load_api_settings(
    environ: Mapping[str, str] | None = None,
) -> ApiSettings:
    """Load and validate API settings from a mapping or process environment."""

    source = os.environ if environ is None else environ
    api_runtime_settings = ApiSettings(
        environment=_required_string(source, "API_ENVIRONMENT"),
        host=_required_string(source, "API_HOST"),
        port=_required_int(source, "API_PORT"),
        api_prefix=_required_string(source, "API_PREFIX"),
        cors_origins=_parse_cors_origins(
            _required_string(source, "API_CORS_ORIGINS")
        ),
        request_timeout_seconds=_required_int(
            source, "API_REQUEST_TIMEOUT_SECONDS"
        ),
        queue_timeout_seconds=_required_int(
            source, "API_QUEUE_TIMEOUT_SECONDS"
        ),
        max_concurrent_requests=_required_int(
            source, "API_MAX_CONCURRENT_REQUESTS"
        ),
        max_request_body_bytes=_required_int(
            source, "API_MAX_REQUEST_BODY_BYTES"
        ),
        health_timeout_seconds=_required_int(
            source, "API_HEALTH_TIMEOUT_SECONDS"
        ),
        readiness_retry_cooldown_seconds=_required_int(
            source, "API_READINESS_RETRY_COOLDOWN_SECONDS"
        ),
        log_level=_required_string(source, "API_LOG_LEVEL").upper(),
    )
    validate_api_settings(api_runtime_settings)
    return api_runtime_settings


# Use the same explicit backend/.env source and operating-system precedence as
# Phase 2. Repeating this call is safe and keeps this module's contract clear.
load_dotenv(
    dotenv_path=ENV_FILE,
    override=False,
    encoding="utf-8",
)

api_settings = load_api_settings()
