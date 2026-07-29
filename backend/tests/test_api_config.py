from __future__ import annotations

import os
from dataclasses import FrozenInstanceError, replace

import pytest


DEFAULT_API_ENVIRONMENT = {
    "API_ENVIRONMENT": "development",
    "API_HOST": "127.0.0.1",
    "API_PORT": "8000",
    "API_PREFIX": "/api/v1",
    "API_CORS_ORIGINS": (
        "http://localhost:5173,http://127.0.0.1:5173"
    ),
    "API_REQUEST_TIMEOUT_SECONDS": "90",
    "API_QUEUE_TIMEOUT_SECONDS": "5",
    "API_MAX_CONCURRENT_REQUESTS": "1",
    "API_MAX_REQUEST_BODY_BYTES": "4096",
    "API_HEALTH_TIMEOUT_SECONDS": "3",
    "API_READINESS_RETRY_COOLDOWN_SECONDS": "10",
    "API_LOG_LEVEL": "INFO",
}

# Never inspect or depend on the developer's ignored backend/.env in unit tests.
for _name, _value in DEFAULT_API_ENVIRONMENT.items():
    os.environ.setdefault(_name, _value)

from app.api.config import (  # noqa: E402
    ApiConfigurationError,
    api_settings,
    load_api_settings,
    validate_api_settings,
)


def test_default_configuration_is_valid() -> None:
    loaded = load_api_settings(DEFAULT_API_ENVIRONMENT)

    assert loaded.environment == "development"
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8000
    assert loaded.api_prefix == "/api/v1"
    assert loaded.cors_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    assert loaded.request_timeout_seconds == 90
    assert loaded.queue_timeout_seconds == 5
    assert loaded.max_concurrent_requests == 1
    assert loaded.max_request_body_bytes == 4096
    assert loaded.health_timeout_seconds == 3
    assert loaded.readiness_retry_cooldown_seconds == 10
    assert loaded.log_level == "INFO"
    validate_api_settings(loaded)
    validate_api_settings(api_settings)


def test_custom_mapping_overrides_are_used() -> None:
    custom = {
        **DEFAULT_API_ENVIRONMENT,
        "API_ENVIRONMENT": "test",
        "API_HOST": "localhost",
        "API_PORT": "9000",
        "API_PREFIX": "/custom/v2",
        "API_CORS_ORIGINS": "https://example.test/",
        "API_LOG_LEVEL": "warning",
    }

    loaded = load_api_settings(custom)

    assert loaded.environment == "test"
    assert loaded.host == "localhost"
    assert loaded.port == 9000
    assert loaded.api_prefix == "/custom/v2"
    assert loaded.cors_origins == ("https://example.test",)
    assert loaded.log_level == "WARNING"


def test_os_environment_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "8765")

    assert load_api_settings().port == 8765


def test_settings_are_immutable() -> None:
    loaded = load_api_settings(DEFAULT_API_ENVIRONMENT)

    with pytest.raises(FrozenInstanceError):
        loaded.port = 9000  # type: ignore[misc]

    assert not hasattr(loaded, "__dict__")


@pytest.mark.parametrize("missing_name", tuple(DEFAULT_API_ENVIRONMENT))
def test_missing_required_values_are_rejected(missing_name: str) -> None:
    environment = {
        name: value
        for name, value in DEFAULT_API_ENVIRONMENT.items()
        if name != missing_name
    }

    with pytest.raises(ApiConfigurationError, match=missing_name):
        load_api_settings(environment)


@pytest.mark.parametrize("blank_name", tuple(DEFAULT_API_ENVIRONMENT))
def test_blank_required_values_are_rejected(blank_name: str) -> None:
    environment = {**DEFAULT_API_ENVIRONMENT, blank_name: "   "}

    with pytest.raises(ApiConfigurationError, match=blank_name):
        load_api_settings(environment)


@pytest.mark.parametrize(
    "name",
    (
        "API_PORT",
        "API_REQUEST_TIMEOUT_SECONDS",
        "API_QUEUE_TIMEOUT_SECONDS",
        "API_MAX_CONCURRENT_REQUESTS",
        "API_MAX_REQUEST_BODY_BYTES",
        "API_HEALTH_TIMEOUT_SECONDS",
        "API_READINESS_RETRY_COOLDOWN_SECONDS",
    ),
)
def test_malformed_numbers_are_rejected(name: str) -> None:
    environment = {**DEFAULT_API_ENVIRONMENT, name: "not-a-number"}

    with pytest.raises(ApiConfigurationError, match=name):
        load_api_settings(environment)


@pytest.mark.parametrize(
    "name",
    (
        "API_REQUEST_TIMEOUT_SECONDS",
        "API_QUEUE_TIMEOUT_SECONDS",
        "API_HEALTH_TIMEOUT_SECONDS",
        "API_READINESS_RETRY_COOLDOWN_SECONDS",
    ),
)
@pytest.mark.parametrize("value", ("0", "-1"))
def test_non_positive_timeouts_are_rejected(
    name: str,
    value: str,
) -> None:
    environment = {**DEFAULT_API_ENVIRONMENT, name: value}

    with pytest.raises(ApiConfigurationError, match=name):
        load_api_settings(environment)


@pytest.mark.parametrize("port", ("0", "65536", "-1"))
def test_invalid_ports_are_rejected(port: str) -> None:
    environment = {**DEFAULT_API_ENVIRONMENT, "API_PORT": port}

    with pytest.raises(ApiConfigurationError, match="API_PORT"):
        load_api_settings(environment)


@pytest.mark.parametrize(
    "prefix",
    ("api/v1", "/", "/api/", "/api//v1", "/api v1", "/api?version=1"),
)
def test_invalid_api_prefixes_are_rejected(prefix: str) -> None:
    environment = {**DEFAULT_API_ENVIRONMENT, "API_PREFIX": prefix}

    with pytest.raises(ApiConfigurationError, match="API_PREFIX"):
        load_api_settings(environment)


@pytest.mark.parametrize("concurrency", ("0", "5", "-1"))
def test_concurrency_outside_one_to_four_is_rejected(
    concurrency: str,
) -> None:
    environment = {
        **DEFAULT_API_ENVIRONMENT,
        "API_MAX_CONCURRENT_REQUESTS": concurrency,
    }

    with pytest.raises(
        ApiConfigurationError,
        match="API_MAX_CONCURRENT_REQUESTS",
    ):
        load_api_settings(environment)


@pytest.mark.parametrize("body_limit", ("2000", "2256"))
def test_request_body_limit_requires_json_headroom(
    body_limit: str,
) -> None:
    environment = {
        **DEFAULT_API_ENVIRONMENT,
        "API_MAX_REQUEST_BODY_BYTES": body_limit,
    }

    with pytest.raises(
        ApiConfigurationError,
        match="API_MAX_REQUEST_BODY_BYTES",
    ):
        load_api_settings(environment)


@pytest.mark.parametrize(
    "origins",
    (
        "*",
        "http://*.example.test",
        "http://localhost:5173,http://localhost:5173",
        "http://user:secret@localhost:5173",
        "http://localhost:5173/api",
        "http://localhost:5173?query=value",
        "http://localhost:5173#fragment",
        "localhost:5173",
        "http:///missing-host",
        "http://localhost:not-a-port",
        "http://localhost:70000",
        "http://localhost:5173,",
    ),
)
def test_invalid_cors_origins_are_rejected(origins: str) -> None:
    environment = {
        **DEFAULT_API_ENVIRONMENT,
        "API_CORS_ORIGINS": origins,
    }

    with pytest.raises(ApiConfigurationError, match="API_CORS_ORIGINS"):
        load_api_settings(environment)


def test_directly_constructed_invalid_cors_tuple_is_rejected() -> None:
    invalid = replace(
        load_api_settings(DEFAULT_API_ENVIRONMENT),
        cors_origins=("http://localhost:5173/",),
    )

    with pytest.raises(ApiConfigurationError, match="normalized"):
        validate_api_settings(invalid)


def test_unknown_log_level_is_rejected() -> None:
    environment = {
        **DEFAULT_API_ENVIRONMENT,
        "API_LOG_LEVEL": "TRACE",
    }

    with pytest.raises(ApiConfigurationError, match="API_LOG_LEVEL"):
        load_api_settings(environment)
