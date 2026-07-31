"""Safe, centralized HTTP error translation for the Phase 3 API."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.models import ErrorDetail, ErrorResponse
from app.api.services import (
    ApiServiceError,
    ClassifierServiceError,
    PipelineServiceError,
    ServiceExecutionTimeoutError,
    ServiceQueueTimeoutError,
    ServiceShuttingDownError,
)
from app.ml.chat_model import ChatModelInitializationError
from app.ml.classifier import ClassifierInferenceError, ClassifierLoadError
from app.ml.embeddings import EmbeddingValidationError
from app.ml.retriever import PolicyRetrievalError


_SAFE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_REQUEST_ID_STATE_KEY = "request_id"
_API_LOG_CONTEXT_STATE_KEY = "api_log_context"


@dataclass(frozen=True, slots=True)
class ApiFailure:
    """One immutable public mapping plus its log-only internal code."""

    status_code: int
    public_code: str
    public_message: str
    retryable: bool
    internal_code: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 400 <= self.status_code <= 599
        ):
            raise ValueError("status_code must be an HTTP error status.")
        for field_name in (
            "public_code",
            "internal_code",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or _SAFE_CODE_PATTERN.fullmatch(value) is None
            ):
                raise ValueError(
                    f"{field_name} must be a stable lowercase code."
                )
        if (
            not isinstance(self.public_message, str)
            or not self.public_message
            or self.public_message != self.public_message.strip()
        ):
            raise ValueError("public_message must be a nonblank trimmed string.")
        if type(self.retryable) is not bool:
            raise TypeError("retryable must be a boolean.")


INVALID_REQUEST: Final = ApiFailure(
    status_code=422,
    public_code="invalid_request",
    public_message="The request is invalid.",
    retryable=False,
    internal_code="request_validation_failed",
)
PAYLOAD_TOO_LARGE: Final = ApiFailure(
    status_code=413,
    public_code="payload_too_large",
    public_message="The request body is too large.",
    retryable=False,
    internal_code="request_body_too_large",
)
UNSUPPORTED_MEDIA_TYPE: Final = ApiFailure(
    status_code=415,
    public_code="unsupported_media_type",
    public_message="Chat requests require application/json.",
    retryable=False,
    internal_code="unsupported_media_type",
)
SERVICE_BUSY: Final = ApiFailure(
    status_code=503,
    public_code="service_busy",
    public_message="The support service is busy. Please try again.",
    retryable=True,
    internal_code="service_queue_timeout",
)
CLASSIFIER_UNAVAILABLE: Final = ApiFailure(
    status_code=503,
    public_code="classifier_unavailable",
    public_message=(
        "The classifier is temporarily unavailable. Please try again."
    ),
    retryable=True,
    internal_code="classifier_failure",
)
REQUEST_TIMEOUT: Final = ApiFailure(
    status_code=504,
    public_code="request_timeout",
    public_message="The request timed out. Please try again.",
    retryable=True,
    internal_code="service_execution_timeout",
)
SUPPORT_SERVICE_UNAVAILABLE: Final = ApiFailure(
    status_code=503,
    public_code="support_service_unavailable",
    public_message=(
        "The support service is temporarily unavailable. Please try again "
        "or use an official support channel."
    ),
    retryable=True,
    internal_code="pipeline_failure",
)
INTERNAL_ERROR: Final = ApiFailure(
    status_code=500,
    public_code="internal_error",
    public_message="The request could not be completed.",
    retryable=False,
    internal_code="unexpected_api_exception",
)
NOT_FOUND: Final = ApiFailure(
    status_code=404,
    public_code="not_found",
    public_message="The requested resource was not found.",
    retryable=False,
    internal_code="route_not_found",
)
METHOD_NOT_ALLOWED: Final = ApiFailure(
    status_code=405,
    public_code="method_not_allowed",
    public_message="The request method is not allowed for this resource.",
    retryable=False,
    internal_code="method_not_allowed",
)


def failure_for_exception(exception: BaseException) -> ApiFailure:
    """Map an escaping boundary exception without using its message."""

    if isinstance(
        exception,
        (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
    ):
        raise exception
    if isinstance(exception, ServiceQueueTimeoutError):
        return SERVICE_BUSY
    if isinstance(
        exception,
        (
            ClassifierServiceError,
            ClassifierLoadError,
            ClassifierInferenceError,
        ),
    ):
        return CLASSIFIER_UNAVAILABLE
    if isinstance(exception, ServiceExecutionTimeoutError):
        return REQUEST_TIMEOUT
    if isinstance(
        exception,
        (
            PipelineServiceError,
            ServiceShuttingDownError,
            PolicyRetrievalError,
            EmbeddingValidationError,
            ChatModelInitializationError,
        ),
    ):
        return SUPPORT_SERVICE_UNAVAILABLE
    if isinstance(exception, ApiServiceError):
        return SUPPORT_SERVICE_UNAVAILABLE
    return INTERNAL_ERROR


def failure_for_http_status(status_code: int) -> ApiFailure:
    """Return a controlled mapping for Starlette HTTP exceptions."""

    if status_code == 404:
        return NOT_FOUND
    if status_code == 405:
        return METHOD_NOT_ALLOWED
    if status_code == 413:
        return PAYLOAD_TOO_LARGE
    if status_code == 415:
        return UNSUPPORTED_MEDIA_TYPE
    if status_code == 422:
        return INVALID_REQUEST
    if 400 <= status_code <= 499:
        return ApiFailure(
            status_code=status_code,
            public_code="invalid_request",
            public_message="The request is invalid.",
            retryable=False,
            internal_code="http_request_rejected",
        )
    return INTERNAL_ERROR


def request_id_for_scope(scope: Scope) -> str:
    """Return the server request ID, creating one only as a safe fallback."""

    state = scope.setdefault("state", {})
    if not isinstance(state, dict):
        raise RuntimeError("ASGI request state must be a dictionary.")
    request_id = state.get(_REQUEST_ID_STATE_KEY)
    if isinstance(request_id, str) and request_id:
        return request_id

    generated = str(uuid4())
    state[_REQUEST_ID_STATE_KEY] = generated
    return generated


def record_internal_error_code(scope: Scope, internal_code: str) -> None:
    """Store one validated internal code in the aggregate log context."""

    if (
        not isinstance(internal_code, str)
        or _SAFE_CODE_PATTERN.fullmatch(internal_code) is None
    ):
        raise ValueError("internal_code must be a stable lowercase code.")
    state = scope.get("state")
    if not isinstance(state, dict):
        return
    context = state.get(_API_LOG_CONTEXT_STATE_KEY)
    if isinstance(context, dict):
        context["internal_error_code"] = internal_code


def record_internal_error(scope: Scope, failure: ApiFailure) -> None:
    """Store only the stable mapped code in the aggregate log context."""

    if not isinstance(failure, ApiFailure):
        raise TypeError("failure must be an ApiFailure.")
    record_internal_error_code(scope, failure.internal_code)


def error_response_model(scope: Scope, failure: ApiFailure) -> ErrorResponse:
    """Build the strict public model for one translated failure."""

    if not isinstance(failure, ApiFailure):
        raise TypeError("failure must be an ApiFailure.")
    return ErrorResponse(
        request_id=request_id_for_scope(scope),
        error=ErrorDetail(
            code=failure.public_code,
            message=failure.public_message,
            retryable=failure.retryable,
        ),
    )


def error_response_bytes(scope: Scope, failure: ApiFailure) -> bytes:
    """Serialize the public error model for pure-ASGI middleware."""

    return (
        error_response_model(scope, failure)
        .model_dump_json()
        .encode("utf-8")
    )


def _json_error_response(scope: Scope, failure: ApiFailure) -> JSONResponse:
    record_internal_error(scope, failure)
    model = error_response_model(scope, failure)
    return JSONResponse(
        status_code=failure.status_code,
        content=model.model_dump(mode="json"),
    )


async def _request_validation_handler(
    request: Request,
    _exception: RequestValidationError,
) -> JSONResponse:
    return _json_error_response(request.scope, INVALID_REQUEST)


async def _http_exception_handler(
    request: Request,
    exception: StarletteHTTPException,
) -> JSONResponse:
    failure = failure_for_http_status(exception.status_code)
    return _json_error_response(request.scope, failure)


def register_api_error_handlers(application: FastAPI) -> None:
    """Install safe handlers for exceptions consumed inside FastAPI."""

    if not isinstance(application, FastAPI):
        raise TypeError("application must be a FastAPI instance.")
    application.add_exception_handler(
        RequestValidationError,
        _request_validation_handler,
    )
    application.add_exception_handler(
        StarletteHTTPException,
        _http_exception_handler,
    )


class ApiErrorMiddleware:
    """Translate exceptions that escape FastAPI before server-error handling."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def observed_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except ClientDisconnect:
            record_internal_error_code(scope, "client_disconnect")
            return
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            record_internal_error_code(scope, "request_cancelled")
            raise
        except Exception as exception:
            failure = failure_for_exception(exception)
            record_internal_error(scope, failure)
            if response_started:
                raise
            response = _json_error_response(scope, failure)
            await response(scope, receive, send)


__all__ = [
    "ApiErrorMiddleware",
    "ApiFailure",
    "CLASSIFIER_UNAVAILABLE",
    "INTERNAL_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_ALLOWED",
    "NOT_FOUND",
    "PAYLOAD_TOO_LARGE",
    "REQUEST_TIMEOUT",
    "SERVICE_BUSY",
    "SUPPORT_SERVICE_UNAVAILABLE",
    "UNSUPPORTED_MEDIA_TYPE",
    "error_response_bytes",
    "error_response_model",
    "failure_for_exception",
    "failure_for_http_status",
    "record_internal_error",
    "record_internal_error_code",
    "register_api_error_handlers",
    "request_id_for_scope",
]
