from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.config import api_settings
from app.api.errors import ApiErrorMiddleware
from app.api.middleware import (
    API_LOG_CONTEXT_STATE_KEY,
    ChatRequestControlMiddleware,
    REQUEST_ID_HEADER,
    REQUEST_ID_STATE_KEY,
    RequestContextMiddleware,
    add_api_log_context,
    add_classification_log_context,
    configure_api_logger,
    sanitize_api_log_record,
    structured_completion_logger,
)
from app.main import create_app
from app.ml.redaction import REDACTED, UnsafeLogRecordError
from app.ml.triage_types import ClassificationResult, IntentPrediction


FIXED_REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
CHAT_PATH = f"{api_settings.api_prefix}/chat"


def http_scope(
    *,
    path: str = CHAT_PATH,
    method: str = "POST",
    headers: tuple[tuple[bytes, bytes], ...] = (),
) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": list(headers),
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "state": {},
    }


async def invoke(
    app: ASGIApp,
    scope: Scope,
    incoming: list[Message],
    *,
    events: list[str] | None = None,
) -> tuple[list[Message], int]:
    sent: list[Message] = []
    receive_calls = 0

    async def receive() -> Message:
        nonlocal receive_calls
        receive_calls += 1
        if not incoming:
            raise AssertionError("Middleware read beyond supplied messages.")
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)
        if events is not None:
            events.append(message["type"])

    await app(scope, receive, send)
    return sent, receive_calls


def response_headers(messages: list[Message]) -> dict[str, str]:
    start = next(
        message
        for message in messages
        if message["type"] == "http.response.start"
    )
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }


def response_json(messages: list[Message]) -> dict[str, Any]:
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return json.loads(body)


def control_middleware(
    downstream: ASGIApp,
    *,
    limit: int = 32,
) -> ChatRequestControlMiddleware:
    return ChatRequestControlMiddleware(
        downstream,
        api_prefix=api_settings.api_prefix,
        max_request_body_bytes=limit,
    )


@pytest.mark.asyncio
async def test_server_request_id_is_consistent_and_inbound_id_is_ignored() -> None:
    logs: list[Mapping[str, object]] = []

    async def downstream(
        scope: Scope,
        _receive: Receive,
        send: Send,
    ) -> None:
        request_id = scope["state"][REQUEST_ID_STATE_KEY]
        body = json.dumps(
            {"request_id": request_id, "event_request_id": request_id}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )

    middleware = RequestContextMiddleware(
        downstream,
        log_completion=logs.append,
        request_id_factory=lambda: FIXED_REQUEST_ID,
        monotonic=iter((1.0, 1.025)).__next__,
    )
    sent, _ = await invoke(
        middleware,
        http_scope(
            path="/health/live",
            method="GET",
            headers=((b"x-request-id", b"untrusted-client-id"),),
        ),
        [],
    )

    expected = str(FIXED_REQUEST_ID)
    assert response_headers(sent)[REQUEST_ID_HEADER.lower()] == expected
    assert response_json(sent) == {
        "request_id": expected,
        "event_request_id": expected,
    }
    assert logs[0]["request_id"] == expected
    assert "untrusted-client-id" not in json.dumps(logs[0])


@pytest.mark.asyncio
async def test_request_ids_are_unique_between_requests() -> None:
    generated = iter(
        (
            UUID("00000000-0000-4000-8000-000000000001"),
            UUID("00000000-0000-4000-8000-000000000002"),
        )
    )
    logs: list[Mapping[str, object]] = []

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        send: Send,
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": [],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )

    middleware = RequestContextMiddleware(
        downstream,
        log_completion=logs.append,
        request_id_factory=generated.__next__,
        monotonic=iter((0.0, 0.1, 1.0, 1.1)).__next__,
    )
    first, _ = await invoke(
        middleware,
        http_scope(path="/health/live", method="GET"),
        [],
    )
    second, _ = await invoke(
        middleware,
        http_scope(path="/health/live", method="GET"),
        [],
    )

    assert (
        response_headers(first)[REQUEST_ID_HEADER.lower()]
        != response_headers(second)[REQUEST_ID_HEADER.lower()]
    )


@pytest.mark.asyncio
async def test_accepted_multiframe_body_is_replayed_exactly() -> None:
    observed: list[Message] = []
    invoked = 0

    async def downstream(
        _scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        nonlocal invoked
        invoked += 1
        while True:
            message = await receive()
            observed.append(message)
            if not message.get("more_body", False):
                break
        await send(
            {"type": "http.response.start", "status": 204, "headers": []}
        )
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )

    original = [
        {
            "type": "http.request",
            "body": b'{"message":',
            "more_body": True,
        },
        {
            "type": "http.request",
            "body": b'"hello"}',
            "more_body": False,
        },
    ]
    sent, receive_calls = await invoke(
        control_middleware(downstream),
        http_scope(headers=((b"content-type", b"application/json"),)),
        [dict(message) for message in original],
    )

    assert invoked == 1
    assert receive_calls == 2
    assert observed == original
    assert sent[0]["status"] == 204


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_length", "messages", "expected_reads"),
    (
        ("33", [], 0),
        (
            None,
            [
                {
                    "type": "http.request",
                    "body": b"x" * 20,
                    "more_body": True,
                },
                {
                    "type": "http.request",
                    "body": b"y" * 20,
                    "more_body": True,
                },
                {
                    "type": "http.request",
                    "body": b"must-not-drain",
                    "more_body": False,
                },
            ],
            2,
        ),
        (
            "4",
            [
                {
                    "type": "http.request",
                    "body": b"x" * 40,
                    "more_body": False,
                }
            ],
            1,
        ),
    ),
)
async def test_oversized_body_rejects_before_downstream_and_does_not_drain(
    content_length: str | None,
    messages: list[Message],
    expected_reads: int,
) -> None:
    invoked = False

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        _send: Send,
    ) -> None:
        nonlocal invoked
        invoked = True

    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    scope = http_scope(headers=tuple(headers))
    scope["state"][REQUEST_ID_STATE_KEY] = str(FIXED_REQUEST_ID)

    sent, receive_calls = await invoke(
        control_middleware(downstream),
        scope,
        list(messages),
    )

    assert not invoked
    assert receive_calls == expected_reads
    assert sent[0]["status"] == 413
    assert response_json(sent)["request_id"] == str(FIXED_REQUEST_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize("content_length", (None, "invalid", "-5", "100"))
async def test_missing_malformed_or_dishonest_content_length_never_replaces_counting(
    content_length: str | None,
) -> None:
    calls = 0

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        send: Send,
    ) -> None:
        nonlocal calls
        calls += 1
        await send(
            {"type": "http.response.start", "status": 204, "headers": []}
        )
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )

    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    sent, _ = await invoke(
        control_middleware(downstream, limit=128),
        http_scope(headers=tuple(headers)),
        [
            {
                "type": "http.request",
                "body": b'{"message":"ok"}',
                "more_body": False,
            }
        ],
    )

    assert calls == 1
    assert sent[0]["status"] == 204


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "expected_status"),
    (
        ("application/json", 204),
        ("Application/JSON; charset=utf-8", 204),
        (None, 415),
        ("text/plain", 415),
        ("application/json-patch+json", 415),
    ),
)
async def test_chat_content_type_is_enforced(
    content_type: str | None,
    expected_status: int,
) -> None:
    invoked = 0

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        send: Send,
    ) -> None:
        nonlocal invoked
        invoked += 1
        await send(
            {"type": "http.response.start", "status": 204, "headers": []}
        )
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )

    headers = (
        ((b"content-type", content_type.encode()),)
        if content_type is not None
        else ()
    )
    incoming = (
        [
            {
                "type": "http.request",
                "body": b"{}",
                "more_body": False,
            }
        ]
        if content_type is not None
        and content_type.lower().startswith("application/json")
        else []
    )
    sent, _ = await invoke(
        control_middleware(downstream),
        http_scope(headers=headers),
        incoming,
    )

    assert sent[0]["status"] == expected_status
    assert invoked == (1 if expected_status == 204 else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "method"),
    (
        ("/health/live", "GET"),
        ("/health/ready", "POST"),
        (CHAT_PATH, "OPTIONS"),
    ),
)
async def test_health_and_options_bypass_body_controls(
    path: str,
    method: str,
) -> None:
    invoked = 0

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        send: Send,
    ) -> None:
        nonlocal invoked
        invoked += 1
        await send(
            {"type": "http.response.start", "status": 204, "headers": []}
        )
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )

    sent, reads = await invoke(
        control_middleware(downstream),
        http_scope(path=path, method=method),
        [],
    )

    assert invoked == 1
    assert reads == 0
    assert sent[0]["status"] == 204


def cors_stack(
    downstream: ASGIApp,
    logs: list[Mapping[str, object]],
) -> ASGIApp:
    controlled = ChatRequestControlMiddleware(
        downstream,
        api_prefix=api_settings.api_prefix,
        max_request_body_bytes=32,
    )
    cors = CORSMiddleware(
        controlled,
        allow_origins=api_settings.cors_origins,
        allow_methods=("GET", "POST", "OPTIONS"),
        allow_headers=("Accept", "Content-Type"),
        expose_headers=(REQUEST_ID_HEADER,),
        allow_credentials=False,
    )
    return RequestContextMiddleware(
        cors,
        log_completion=logs.append,
        request_id_factory=lambda: FIXED_REQUEST_ID,
        monotonic=iter((1.0, 1.01)).__next__,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "expected_status", "approved"),
    (
        (api_settings.cors_origins[0], 200, True),
        ("https://unapproved.example", 400, False),
    ),
)
async def test_cors_preflight_is_restrictive_and_bypasses_downstream(
    origin: str,
    expected_status: int,
    approved: bool,
) -> None:
    invoked = False
    logs: list[Mapping[str, object]] = []

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        _send: Send,
    ) -> None:
        nonlocal invoked
        invoked = True

    sent, reads = await invoke(
        cors_stack(downstream, logs),
        http_scope(
            method="OPTIONS",
            headers=(
                (b"origin", origin.encode()),
                (b"access-control-request-method", b"POST"),
                (
                    b"access-control-request-headers",
                    b"Accept, Content-Type",
                ),
            ),
        ),
        [],
    )

    headers = response_headers(sent)
    assert sent[0]["status"] == expected_status
    assert not invoked
    assert reads == 0
    if approved:
        assert headers["access-control-allow-origin"] == origin
    else:
        assert "access-control-allow-origin" not in headers
    assert headers["access-control-allow-methods"] == "GET, POST, OPTIONS"
    assert "Accept" in headers["access-control-allow-headers"]
    assert "Content-Type" in headers["access-control-allow-headers"]
    assert "access-control-allow-credentials" not in headers
    assert headers[REQUEST_ID_HEADER.lower()] == str(FIXED_REQUEST_ID)
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_unapproved_cors_origin_gets_no_approval_header() -> None:
    logs: list[Mapping[str, object]] = []

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        send: Send,
    ) -> None:
        await send(
            {"type": "http.response.start", "status": 204, "headers": []}
        )
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )

    sent, _ = await invoke(
        cors_stack(downstream, logs),
        http_scope(
            path="/health/live",
            method="GET",
            headers=((b"origin", b"https://unapproved.example"),),
        ),
        [],
    )

    headers = response_headers(sent)
    assert "access-control-allow-origin" not in headers
    assert headers["access-control-expose-headers"] == REQUEST_ID_HEADER
    assert "access-control-allow-credentials" not in headers


@pytest.mark.asyncio
async def test_cors_headers_are_present_on_body_control_errors() -> None:
    logs: list[Mapping[str, object]] = []

    async def downstream(
        _scope: Scope,
        _receive: Receive,
        _send: Send,
    ) -> None:
        raise AssertionError("Rejected request reached downstream.")

    sent, _ = await invoke(
        cors_stack(downstream, logs),
        http_scope(
            headers=(
                (b"origin", api_settings.cors_origins[0].encode()),
                (b"content-type", b"text/plain"),
            )
        ),
        [],
    )

    headers = response_headers(sent)
    assert sent[0]["status"] == 415
    assert headers["access-control-allow-origin"] == (
        api_settings.cors_origins[0]
    )
    assert headers[REQUEST_ID_HEADER.lower()] == str(FIXED_REQUEST_ID)
    assert response_json(sent)["request_id"] == str(FIXED_REQUEST_ID)


@pytest.mark.asyncio
async def test_completion_log_occurs_once_after_stream_final_frame() -> None:
    events: list[str] = []
    records: list[Mapping[str, object]] = []

    def log_completion(record: Mapping[str, object]) -> None:
        events.append("log")
        records.append(record)

    async def streaming(
        _scope: Scope,
        _receive: Receive,
        send: Send,
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"event: chunk\n\n",
                "more_body": True,
            }
        )
        assert not records
        await send(
            {
                "type": "http.response.body",
                "body": b"event: done\n\n",
                "more_body": False,
            }
        )

    middleware = RequestContextMiddleware(
        streaming,
        log_completion=log_completion,
        request_id_factory=lambda: FIXED_REQUEST_ID,
        monotonic=iter((2.0, 2.5)).__next__,
    )
    await invoke(
        middleware,
        http_scope(path=f"{api_settings.api_prefix}/chat/stream"),
        [],
        events=events,
    )

    assert events == [
        "http.response.start",
        "http.response.body",
        "http.response.body",
        "log",
    ]
    assert len(records) == 1
    assert records[0]["status_code"] == 200
    assert records[0]["disconnect"] is False
    assert records[0]["latency_ms"] == 500.0


@pytest.mark.asyncio
async def test_disconnect_is_logged_without_a_completion_frame() -> None:
    logs: list[Mapping[str, object]] = []

    async def downstream(
        _scope: Scope,
        receive: Receive,
        _send: Send,
    ) -> None:
        assert (await receive())["type"] == "http.disconnect"

    middleware = RequestContextMiddleware(
        downstream,
        log_completion=logs.append,
        request_id_factory=lambda: FIXED_REQUEST_ID,
        monotonic=iter((4.0, 4.01)).__next__,
    )
    await invoke(
        middleware,
        http_scope(path="/health/live", method="GET"),
        [{"type": "http.disconnect"}],
    )

    assert len(logs) == 1
    assert logs[0]["disconnect"] is True


def test_api_log_allowlist_redaction_and_route_context_are_fail_closed() -> None:
    safe = sanitize_api_log_record(
        {
            "request_id": "req",
            "endpoint": "/api/password=secret-value",
            "status_code": 200,
            "disconnect": False,
        }
    )
    assert REDACTED in safe["endpoint"]

    with pytest.raises(UnsafeLogRecordError, match="unapproved"):
        sanitize_api_log_record({"message": "raw customer message"})
    with pytest.raises(UnsafeLogRecordError, match="unapproved"):
        sanitize_api_log_record({"retrieval_scores": [0.9]})
    with pytest.raises(UnsafeLogRecordError, match="finite"):
        sanitize_api_log_record({"latency_ms": float("inf")})

    scope = http_scope(path="/health/live", method="GET")
    scope["state"] = {
        REQUEST_ID_STATE_KEY: "req",
        API_LOG_CONTEXT_STATE_KEY: {},
    }
    request = Request(scope)
    with pytest.raises(UnsafeLogRecordError, match="unapproved"):
        add_api_log_context(request, {"answer": "complete model answer"})


def test_classification_context_uses_rounded_ranges_only() -> None:
    scope = http_scope(path="/health/live", method="GET")
    scope["state"] = {
        REQUEST_ID_STATE_KEY: "req",
        API_LOG_CONTEXT_STATE_KEY: {},
    }
    request = Request(scope)
    classification = ClassificationResult(
        predictions=(
            IntentPrediction(label="first", confidence=0.81),
            IntentPrediction(label="second", confidence=0.15),
            IntentPrediction(label="third", confidence=0.04),
        ),
        uncertain=False,
        top_two_margin=0.66,
    )

    add_classification_log_context(request, classification)

    assert request.state.api_log_context == {
        "top_intent_labels": ("first", "second", "third"),
        "confidence_ranges": ("0.8-0.9", "0.1-0.2", "0.0-0.1"),
        "uncertain": False,
    }
    assert "0.81" not in json.dumps(request.state.api_log_context)


def test_structured_logger_is_idempotent_and_emits_safe_json() -> None:
    logger = configure_api_logger("INFO")
    existing_handlers = tuple(logger.handlers)
    assert tuple(configure_api_logger("INFO").handlers) == existing_handlers

    messages: list[str] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    capture = CaptureHandler()
    logger.addHandler(capture)
    try:
        structured_completion_logger(logger)(
            {
                "request_id": "req",
                "endpoint": "/password=secret-value",
                "status_code": 200,
                "disconnect": False,
            }
        )
    finally:
        logger.removeHandler(capture)

    assert len(messages) == 1
    payload = json.loads(messages[0])
    assert payload["endpoint"] == f"/password={REDACTED}"
    assert "secret-value" not in messages[0]


def test_application_registers_required_middleware_order_and_settings() -> None:
    created = create_app(
        api_runtime_settings=replace(
            api_settings,
            cors_origins=("https://phase4.example",),
        )
    )

    assert [item.cls for item in created.user_middleware] == [
        RequestContextMiddleware,
        CORSMiddleware,
        ApiErrorMiddleware,
        ChatRequestControlMiddleware,
    ]
    cors_options = created.user_middleware[1].kwargs
    assert cors_options["allow_origins"] == ("https://phase4.example",)
    assert cors_options["allow_methods"] == ("GET", "POST", "OPTIONS")
    assert cors_options["allow_headers"] == ("Accept", "Content-Type")
    assert cors_options["expose_headers"] == (REQUEST_ID_HEADER,)
    assert cors_options["allow_credentials"] is False
    assert "*" not in cors_options["allow_origins"]
