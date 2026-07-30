"""Focused service-free tests for centralized API error translation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.requests import ClientDisconnect
from starlette.types import Message, Receive, Scope, Send

from app.api.config import api_settings
from app.api.errors import (
    ApiErrorMiddleware,
    ApiFailure,
    CLASSIFIER_UNAVAILABLE,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    PAYLOAD_TOO_LARGE,
    REQUEST_TIMEOUT,
    SERVICE_BUSY,
    SUPPORT_SERVICE_UNAVAILABLE,
    UNSUPPORTED_MEDIA_TYPE,
    failure_for_exception,
    register_api_error_handlers,
)
from app.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.api.models import (
    ChatRequest,
    chat_response_from_pipeline_answer,
)
from app.api.services import (
    ClassifierServiceError,
    PipelineServiceError,
    ServiceExecutionTimeoutError,
    ServiceQueueTimeoutError,
)
from app.main import create_app
from app.ml.chat_model import ChatModelInitializationError
from app.ml.classifier import ClassifierInferenceError, ClassifierLoadError
from app.ml.embeddings import EmbeddingValidationError
from app.ml.retriever import PolicyRetrievalError
from app.ml.triage_types import PipelineAnswer


FIXED_REQUEST_ID = UUID("00000000-0000-4000-8000-000000000007")


def _error_app(logs: list[Mapping[str, object]]) -> FastAPI:
    application = FastAPI(
        middleware=[
            Middleware(
                RequestContextMiddleware,
                log_completion=logs.append,
                request_id_factory=lambda: FIXED_REQUEST_ID,
            ),
            Middleware(ApiErrorMiddleware),
        ]
    )
    register_api_error_handlers(application)
    return application


def _expected_error(
    *,
    code: str,
    message: str,
    retryable: bool,
) -> dict[str, object]:
    return {
        "request_id": str(FIXED_REQUEST_ID),
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }


@pytest.mark.parametrize(
    ("exception", "expected"),
    (
        (ServiceQueueTimeoutError("private"), SERVICE_BUSY),
        (ClassifierServiceError("private"), CLASSIFIER_UNAVAILABLE),
        (ClassifierLoadError("private"), CLASSIFIER_UNAVAILABLE),
        (ClassifierInferenceError("private"), CLASSIFIER_UNAVAILABLE),
        (ServiceExecutionTimeoutError("private"), REQUEST_TIMEOUT),
        (PipelineServiceError("private"), SUPPORT_SERVICE_UNAVAILABLE),
        (PolicyRetrievalError("private"), SUPPORT_SERVICE_UNAVAILABLE),
        (EmbeddingValidationError("private"), SUPPORT_SERVICE_UNAVAILABLE),
        (
            ChatModelInitializationError("private"),
            SUPPORT_SERVICE_UNAVAILABLE,
        ),
        (RuntimeError("private"), INTERNAL_ERROR),
    ),
)
def test_exception_mapping_uses_stable_definitions(
    exception: Exception,
    expected: ApiFailure,
) -> None:
    assert failure_for_exception(exception) is expected


@pytest.mark.parametrize(
    "exception",
    (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()),
)
def test_process_control_exceptions_are_never_translated(
    exception: BaseException,
) -> None:
    with pytest.raises(type(exception)):
        failure_for_exception(exception)


@pytest.mark.parametrize(
    "payload",
    (
        b'{"message":',
        json.dumps(
            {
                "message": "password=do-not-echo",
                "prompt": "hidden-system-prompt",
            }
        ).encode(),
        json.dumps({"message": "   "}).encode(),
        json.dumps({"message": 123456}).encode(),
    ),
)
def test_request_validation_is_generic_and_omits_rejected_input(
    payload: bytes,
) -> None:
    logs: list[Mapping[str, object]] = []
    application = _error_app(logs)

    @application.post("/validate")
    async def validate_request(_request: ChatRequest) -> dict[str, bool]:
        return {"accepted": True}

    with TestClient(application) as client:
        response = client.post(
            "/validate",
            content=payload,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json() == _expected_error(
        code="invalid_request",
        message="The request is invalid.",
        retryable=False,
    )
    assert response.headers[REQUEST_ID_HEADER] == str(FIXED_REQUEST_ID)
    serialized = response.text
    for forbidden in (
        "do-not-echo",
        "hidden-system-prompt",
        "password",
        "prompt",
        "loc",
        "input",
    ):
        assert forbidden not in serialized
    assert logs[-1]["internal_error_code"] == "request_validation_failed"
    assert logs[-1]["status_code"] == 422


@pytest.mark.parametrize(
    ("exception_factory", "status_code", "code", "retryable", "internal_code"),
    (
        (
            lambda: ServiceQueueTimeoutError("queue secret"),
            503,
            "service_busy",
            True,
            "service_queue_timeout",
        ),
        (
            lambda: ClassifierServiceError(
                r"classifier failed at C:\private\model"
            ),
            503,
            "classifier_unavailable",
            True,
            "classifier_failure",
        ),
        (
            lambda: ServiceExecutionTimeoutError("timeout internals"),
            504,
            "request_timeout",
            True,
            "service_execution_timeout",
        ),
        (
            lambda: PipelineServiceError("system prompt and policy contents"),
            503,
            "support_service_unavailable",
            True,
            "pipeline_failure",
        ),
        (
            lambda: RuntimeError(
                "Traceback (most recent call last): "
                r"unexpected C:\Users\private\.env bearer secret-token"
            ),
            500,
            "internal_error",
            False,
            "unexpected_api_exception",
        ),
    ),
)
def test_every_runtime_mapping_is_safe_and_logged(
    exception_factory: Callable[[], Exception],
    status_code: int,
    code: str,
    retryable: bool,
    internal_code: str,
) -> None:
    logs: list[Mapping[str, object]] = []
    application = _error_app(logs)

    @application.get("/failure")
    async def fail() -> None:
        raise exception_factory()

    with TestClient(application) as client:
        response = client.get(
            "/failure",
            headers={"X-Request-ID": "untrusted-client-id"},
        )

    expected_failure = failure_for_exception(exception_factory())
    assert response.status_code == status_code
    assert response.json() == _expected_error(
        code=code,
        message=expected_failure.public_message,
        retryable=retryable,
    )
    assert response.headers[REQUEST_ID_HEADER] == str(FIXED_REQUEST_ID)
    serialized = response.text
    for forbidden in (
        "C:\\",
        ".env",
        "secret-token",
        "system prompt",
        "policy contents",
        "queue secret",
        "timeout internals",
        "Traceback",
        "requires_human",
        "untrusted-client-id",
    ):
        assert forbidden not in serialized
    assert logs == [
        {
            **logs[0],
            "request_id": str(FIXED_REQUEST_ID),
            "status_code": status_code,
            "disconnect": False,
            "internal_error_code": internal_code,
        }
    ]
    assert "exception" not in logs[0]


def test_framework_http_errors_use_safe_contract_without_raw_detail() -> None:
    logs: list[Mapping[str, object]] = []
    application = _error_app(logs)

    @application.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(
            status_code=418,
            detail=r"password=secret C:\private\prompt.txt",
        )

    with TestClient(application) as client:
        rejected = client.get("/teapot")
        missing = client.get("/does-not-exist")

    assert rejected.status_code == 418
    assert rejected.json()["error"] == {
        "code": "invalid_request",
        "message": "The request is invalid.",
        "retryable": False,
    }
    assert "secret" not in rejected.text
    assert "prompt.txt" not in rejected.text
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "not_found",
        "message": "The requested resource was not found.",
        "retryable": False,
    }


def test_translated_failures_preserve_configured_cors_headers() -> None:
    application = create_app()

    @application.get("/failure")
    async def fail() -> None:
        raise PipelineServiceError("private pipeline detail")

    client = TestClient(application, raise_server_exceptions=False)
    try:
        response = client.get(
            "/failure",
            headers={"Origin": api_settings.cors_origins[0]},
        )
    finally:
        client.close()

    assert response.status_code == 503
    assert response.headers["access-control-allow-origin"] == (
        api_settings.cors_origins[0]
    )
    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_pre_route_body_and_media_errors_use_the_central_contract() -> None:
    application = create_app()
    client = TestClient(application, raise_server_exceptions=False)
    try:
        unsupported = client.post(
            f"{api_settings.api_prefix}/chat",
            content="plain text",
            headers={"Content-Type": "text/plain"},
        )
        oversized = client.post(
            f"{api_settings.api_prefix}/chat",
            content=b"x" * (api_settings.max_request_body_bytes + 1),
            headers={"Content-Type": "application/json"},
        )
    finally:
        client.close()

    assert unsupported.status_code == UNSUPPORTED_MEDIA_TYPE.status_code
    assert unsupported.json()["error"] == {
        "code": "unsupported_media_type",
        "message": "Chat requests require application/json.",
        "retryable": False,
    }
    assert oversized.status_code == PAYLOAD_TOO_LARGE.status_code
    assert oversized.json()["error"] == {
        "code": "payload_too_large",
        "message": "The request body is too large.",
        "retryable": False,
    }
    assert unsupported.json()["request_id"] == unsupported.headers[
        REQUEST_ID_HEADER
    ]
    assert oversized.json()["request_id"] == oversized.headers[
        REQUEST_ID_HEADER
    ]


def test_phase2_safe_fallback_remains_http_200_service_fallback() -> None:
    logs: list[Mapping[str, object]] = []
    application = _error_app(logs)
    answer = PipelineAnswer(
        answer="Use an official support channel if you still need help.",
        response_mode="static_fallback",
        risk_level="low",
        requires_human=True,
        retrieval_sufficient=False,
        retrieved_policy_ids=(),
        retrieved_chunk_ids=(),
        reason_code="retrieval_failed",
    )

    @application.get("/safe-fallback")
    async def safe_fallback() -> dict[str, object]:
        response = chat_response_from_pipeline_answer(
            request_id=str(FIXED_REQUEST_ID),
            pipeline_answer=answer,
        )
        return response.model_dump(mode="json")

    with TestClient(application) as client:
        response = client.get("/safe-fallback")

    assert response.status_code == 200
    assert response.json()["status"] == "service_fallback"
    assert response.json()["requires_human"] is True
    assert "reason_code" not in response.text
    assert "internal_error_code" not in logs[0]


def _http_scope() -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/failure",
        "raw_path": b"/failure",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "state": {},
    }


@pytest.mark.asyncio
async def test_client_disconnect_produces_no_response_and_is_logged() -> None:
    logs: list[Mapping[str, object]] = []
    sent: list[Message] = []

    async def disconnecting(
        _scope: Scope,
        _receive: Receive,
        _send: Send,
    ) -> None:
        raise ClientDisconnect()

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    application = RequestContextMiddleware(
        ApiErrorMiddleware(disconnecting),
        log_completion=logs.append,
        request_id_factory=lambda: FIXED_REQUEST_ID,
    )
    await application(_http_scope(), receive, send)

    assert sent == []
    assert logs[0]["disconnect"] is True
    assert logs[0]["status_code"] == 500
    assert logs[0]["internal_error_code"] == "client_disconnect"


@pytest.mark.asyncio
async def test_api_error_middleware_does_not_swallow_cancellation() -> None:
    sent: list[Message] = []

    async def cancelled(
        _scope: Scope,
        _receive: Receive,
        _send: Send,
    ) -> None:
        raise asyncio.CancelledError

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    with pytest.raises(asyncio.CancelledError):
        await ApiErrorMiddleware(cancelled)(_http_scope(), receive, send)

    assert sent == []


def test_application_registers_central_error_boundary_and_handlers() -> None:
    application = create_app()

    assert ApiErrorMiddleware in [
        middleware.cls for middleware in application.user_middleware
    ]
    assert RequestValidationError in application.exception_handlers
    assert StarletteHTTPException in application.exception_handlers
