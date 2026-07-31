"""Pure ASGI request controls and aggregate-only API logging."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from numbers import Real
from typing import Protocol
from uuid import UUID, uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import (
    ApiFailure,
    PAYLOAD_TOO_LARGE,
    UNSUPPORTED_MEDIA_TYPE,
    error_response_bytes,
    record_internal_error,
)
from app.ml.redaction import (
    UnsafeLogRecordError,
    redact_sensitive_data,
    rounded_confidence_ranges,
)
from app.ml.triage_types import ClassificationResult, PipelineAnswer


REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_STATE_KEY = "request_id"
API_LOG_CONTEXT_STATE_KEY = "api_log_context"

SAFE_API_LOG_FIELDS = frozenset(
    {
        "request_id",
        "timestamp",
        "http_method",
        "endpoint",
        "status_code",
        "disconnect",
        "queue_wait_ms",
        "latency_ms",
        "top_intent_labels",
        "confidence_ranges",
        "uncertain",
        "risk_level",
        "response_mode",
        "requires_human",
        "internal_error_code",
    }
)
ROUTE_API_LOG_FIELDS = frozenset(
    {
        "queue_wait_ms",
        "top_intent_labels",
        "confidence_ranges",
        "uncertain",
        "risk_level",
        "response_mode",
        "requires_human",
        "internal_error_code",
    }
)

_LOGGER_NAME = "fintech_triage.api"
_HANDLER_MARKER = "_fintech_api_json_handler"


class _CompletionLogger(Protocol):
    def __call__(self, record: Mapping[str, object]) -> None: ...


def _sanitize_api_log_value(value: object) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return redact_sensitive_data(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise UnsafeLogRecordError(
                "API log numeric values must be finite."
            )
        return numeric
    if isinstance(value, tuple):
        return tuple(_sanitize_api_log_value(item) for item in value)
    if isinstance(value, list):
        return [_sanitize_api_log_value(item) for item in value]
    raise UnsafeLogRecordError(
        "API log values must use JSON-safe scalar or sequence types."
    )


def sanitize_api_log_record(
    record: Mapping[str, object],
) -> dict[str, object]:
    """Validate one API log record against the transport-only allowlist."""

    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping.")
    if any(
        not isinstance(key, str) or key not in SAFE_API_LOG_FIELDS
        for key in record
    ):
        raise UnsafeLogRecordError(
            "API log record contains an unapproved field."
        )
    return {
        key: _sanitize_api_log_value(value)
        for key, value in record.items()
    }


def _json_log_message(record: Mapping[str, object]) -> str:
    safe_record = sanitize_api_log_record(record)
    return json.dumps(
        safe_record,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def configure_api_logger(log_level: str) -> logging.Logger:
    """Configure the single process API logger without duplicate handlers."""

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(log_level)
    logger.propagate = False

    if not any(
        getattr(handler, _HANDLER_MARKER, False)
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    return logger


def structured_completion_logger(
    logger: logging.Logger,
) -> _CompletionLogger:
    """Bind safe JSON serialization to one configured standard logger."""

    if not isinstance(logger, logging.Logger):
        raise TypeError("logger must be a logging.Logger.")

    def emit(record: Mapping[str, object]) -> None:
        logger.info(_json_log_message(record), stack_info=False)

    return emit


def get_request_id(request: Request) -> str:
    """Return the server-owned request ID from ASGI request state."""

    request_id = getattr(request.state, REQUEST_ID_STATE_KEY, None)
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError("Server request ID is unavailable.")
    return request_id


def add_api_log_context(
    request: Request,
    values: Mapping[str, object],
) -> None:
    """Add only route-approved aggregate fields to request log context."""

    if not isinstance(request, Request):
        raise TypeError("request must be a Request.")
    if not isinstance(values, Mapping):
        raise TypeError("values must be a mapping.")
    if any(
        not isinstance(key, str) or key not in ROUTE_API_LOG_FIELDS
        for key in values
    ):
        raise UnsafeLogRecordError(
            "Route log context contains an unapproved field."
        )

    safe_values = sanitize_api_log_record(values)
    context = getattr(request.state, API_LOG_CONTEXT_STATE_KEY, None)
    if not isinstance(context, dict):
        raise RuntimeError("API log context is unavailable.")
    context.update(safe_values)


def add_classification_log_context(
    request: Request,
    classification: ClassificationResult,
) -> None:
    """Add bucketed classifier metadata without exact confidence values."""

    if not isinstance(classification, ClassificationResult):
        raise TypeError("classification must be a ClassificationResult.")
    add_api_log_context(
        request,
        {
            "top_intent_labels": tuple(
                prediction.label
                for prediction in classification.predictions
            ),
            "confidence_ranges": rounded_confidence_ranges(
                tuple(
                    prediction.confidence
                    for prediction in classification.predictions
                )
            ),
            "uncertain": classification.uncertain,
        },
    )


def add_pipeline_answer_log_context(
    request: Request,
    pipeline_answer: PipelineAnswer,
) -> None:
    """Add only presentation-safe aggregate answer metadata."""

    if not isinstance(pipeline_answer, PipelineAnswer):
        raise TypeError("pipeline_answer must be a PipelineAnswer.")
    add_api_log_context(
        request,
        {
            "risk_level": pipeline_answer.risk_level,
            "response_mode": pipeline_answer.response_mode,
            "requires_human": pipeline_answer.requires_human,
        },
    )


def _state_for_scope(scope: Scope) -> dict[str, object]:
    state = scope.setdefault("state", {})
    if not isinstance(state, dict):
        raise RuntimeError("ASGI request state must be a dictionary.")
    return state


class RequestContextMiddleware:
    """Own request IDs, response observation, and completion logging."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        log_completion: _CompletionLogger,
        request_id_factory: Callable[[], UUID] = uuid4,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(log_completion):
            raise TypeError("log_completion must be callable.")
        if not callable(request_id_factory) or not callable(monotonic):
            raise TypeError("Middleware factories must be callable.")
        self.app = app
        self._log_completion = log_completion
        self._request_id_factory = request_id_factory
        self._monotonic = monotonic

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = _state_for_scope(scope)
        request_id = str(self._request_id_factory())
        state[REQUEST_ID_STATE_KEY] = request_id
        state[API_LOG_CONTEXT_STATE_KEY] = {}

        started_at = self._monotonic()
        status_code = 500
        disconnected = False
        final_body_sent = False

        async def observed_receive() -> Message:
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def observed_send(message: Message) -> None:
            nonlocal status_code, final_body_sent, disconnected
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                message.setdefault("headers", [])
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            elif (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                final_body_sent = True
            try:
                await send(message)
            except (BrokenPipeError, ConnectionError, OSError):
                disconnected = True
                raise

        try:
            await self.app(scope, observed_receive, observed_send)
        except asyncio.CancelledError:
            disconnected = True
            raise
        finally:
            finished_at = self._monotonic()
            route_context = state.get(API_LOG_CONTEXT_STATE_KEY)
            safe_route_context = (
                dict(route_context)
                if isinstance(route_context, dict)
                else {}
            )
            completion_record: dict[str, object] = {
                "request_id": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "http_method": str(scope.get("method", "")),
                "endpoint": str(scope.get("path", "")),
                "status_code": status_code,
                "disconnect": disconnected or not final_body_sent,
                "latency_ms": round(
                    max(0.0, (finished_at - started_at) * 1000),
                    3,
                ),
                **safe_route_context,
            }
            self._log_completion(
                sanitize_api_log_record(completion_record)
            )


class ChatRequestControlMiddleware:
    """Bound and replay planned chat POST bodies before route parsing."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str,
        max_request_body_bytes: int,
    ) -> None:
        if (
            not isinstance(api_prefix, str)
            or not api_prefix.startswith("/")
            or api_prefix.endswith("/")
        ):
            raise ValueError("api_prefix must be an absolute path prefix.")
        if (
            isinstance(max_request_body_bytes, bool)
            or not isinstance(max_request_body_bytes, int)
            or max_request_body_bytes < 1
        ):
            raise ValueError("max_request_body_bytes must be positive.")
        self.app = app
        self._chat_paths = frozenset(
            {
                f"{api_prefix}/chat",
                f"{api_prefix}/chat/stream",
            }
        )
        self._max_request_body_bytes = max_request_body_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in self._chat_paths
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = None
            if (
                declared_length is not None
                and declared_length >= 0
                and declared_length > self._max_request_body_bytes
            ):
                await self._send_error(
                    scope,
                    send,
                    failure=PAYLOAD_TOO_LARGE,
                )
                return

        content_type = headers.get("content-type")
        media_type = (
            content_type.split(";", 1)[0].strip().lower()
            if content_type is not None
            else ""
        )
        if media_type != "application/json":
            await self._send_error(
                scope,
                send,
                failure=UNSUPPORTED_MEDIA_TYPE,
            )
            return

        accepted_messages: list[Message] = []
        received_bytes = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                raise RuntimeError("Unexpected ASGI request message.")

            body = message.get("body", b"")
            if not isinstance(body, bytes):
                raise RuntimeError("ASGI request body must be bytes.")
            received_bytes += len(body)
            if received_bytes > self._max_request_body_bytes:
                await self._send_error(
                    scope,
                    send,
                    failure=PAYLOAD_TOO_LARGE,
                )
                return

            accepted_messages.append(dict(message))
            if not message.get("more_body", False):
                break

        next_message = 0

        async def replay_receive() -> Message:
            nonlocal next_message
            if next_message >= len(accepted_messages):
                return await receive()
            message = accepted_messages[next_message]
            next_message += 1
            return message

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_error(
        scope: Scope,
        send: Send,
        *,
        failure: ApiFailure,
    ) -> None:
        record_internal_error(scope, failure)
        body = error_response_bytes(scope, failure)
        await send(
            {
                "type": "http.response.start",
                "status": failure.status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )


__all__ = [
    "API_LOG_CONTEXT_STATE_KEY",
    "ChatRequestControlMiddleware",
    "REQUEST_ID_HEADER",
    "REQUEST_ID_STATE_KEY",
    "ROUTE_API_LOG_FIELDS",
    "RequestContextMiddleware",
    "SAFE_API_LOG_FIELDS",
    "add_api_log_context",
    "add_classification_log_context",
    "add_pipeline_answer_log_context",
    "configure_api_logger",
    "get_request_id",
    "sanitize_api_log_record",
    "structured_completion_logger",
]
