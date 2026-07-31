"""Focused service-free tests for validated buffered SSE delivery."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.config import api_settings
from app.api.dependencies import get_chat_service
from app.api.middleware import (
    API_LOG_CONTEXT_STATE_KEY,
    REQUEST_ID_HEADER,
    REQUEST_ID_STATE_KEY,
)
from app.api.models import (
    StreamMetadataEvent,
    stream_interrupted_event,
)
from app.api.routes import chat as chat_module
from app.api.services import (
    ApiChatService,
    ChatExecution,
    PipelineServiceError,
    ServiceExecutionTimeoutError,
)
from app.main import create_app
from app.ml.rag_pipeline import STREAM_CHUNK_CHARACTERS
from app.ml.triage_types import ClassificationResult, PipelineAnswer
from tests.test_api_chat import (
    FakeChatService,
    classification,
    pipeline_answer,
)
from tests.test_api_services import FakePipeline, service_settings


STREAM_PATH = f"{api_settings.api_prefix}/chat/stream"
INTERNAL_VALUES = (
    "private_reason_code",
    "private_policy_identifier",
    "private_chunk_identifier",
    "retrieval_sufficient",
    "retrieved_policy_ids",
    "retrieved_chunk_ids",
    "predictions",
    "confidence",
    "top_two_margin",
)


def _service_for_answer(
    answer: str,
    *,
    response_mode: str = "grounded_generation",
    risk_level: str = "low",
    requires_human: bool = False,
    retrieval_sufficient: bool = True,
    reason_code: str = "private_reason_code",
) -> FakeChatService:
    return FakeChatService(
        execution=ChatExecution(
            classification=classification(),
            pipeline_answer=pipeline_answer(
                answer=answer,
                response_mode=response_mode,
                risk_level=risk_level,
                requires_human=requires_human,
                retrieval_sufficient=retrieval_sufficient,
                reason_code=reason_code,
            ),
        )
    )


def _post_with_service(
    service: FakeChatService,
    *,
    message: str = "Customer message",
) -> Any:
    application = create_app()
    application.dependency_overrides[get_chat_service] = lambda: service
    client = TestClient(
        application,
        raise_server_exceptions=False,
    )
    try:
        return client.post(
            STREAM_PATH,
            json={"message": message},
            headers={"Accept": "text/event-stream"},
        )
    finally:
        client.close()


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    assert body.endswith("\n\n")
    parsed: list[tuple[str, dict[str, object]]] = []
    for frame in body.removesuffix("\n\n").split("\n\n"):
        lines = frame.splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        parsed.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return parsed


def _request(
    disconnected: AsyncIterator[bool] | None = None,
) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": STREAM_PATH,
        "raw_path": STREAM_PATH.encode(),
        "query_string": b"",
        "headers": (),
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {
            REQUEST_ID_STATE_KEY: "request-id",
            API_LOG_CONTEXT_STATE_KEY: {},
        },
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)
    if disconnected is not None:
        request.is_disconnected = disconnected.__anext__  # type: ignore[method-assign]
    return request


async def _flags(*values: bool) -> AsyncIterator[bool]:
    for value in values:
        yield value


async def _collect(
    stream: AsyncIterator[str],
) -> list[str]:
    return [frame async for frame in stream]


@pytest.mark.parametrize(
    (
        "response_mode",
        "risk_level",
        "requires_human",
        "retrieval_sufficient",
        "reason_code",
        "status",
    ),
    (
        (
            "grounded_generation",
            "low",
            False,
            True,
            "private_reason_code",
            "answered",
        ),
        (
            "deterministic_safety",
            "high",
            True,
            False,
            "direct_stolen_card_signal",
            "safety_guidance",
        ),
    ),
)
def test_stream_endpoint_delivers_exact_approved_text_and_safe_metadata(
    response_mode: str,
    risk_level: str,
    requires_human: bool,
    retrieval_sufficient: bool,
    reason_code: str,
    status: str,
) -> None:
    answer = (
        'Approved "quoted" guidance with a newline:\n'
        + "x" * (STREAM_CHUNK_CHARACTERS + 9)
    )
    service = _service_for_answer(
        answer,
        response_mode=response_mode,
        risk_level=risk_level,
        requires_human=requires_human,
        retrieval_sufficient=retrieval_sufficient,
        reason_code=reason_code,
    )

    response = _post_with_service(
        service,
        message=" \tKeep   internal spacing.\n ",
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert service.calls == ["Keep   internal spacing."]

    events = _parse_sse(response.text)
    assert [name for name, _payload in events] == [
        "metadata",
        "chunk",
        "chunk",
        "done",
    ]
    request_id = response.headers[REQUEST_ID_HEADER]
    assert events[0][1] == {
        "request_id": request_id,
        "status": status,
        "response_mode": response_mode,
        "risk_level": risk_level,
        "requires_human": requires_human,
    }
    chunks = events[1:-1]
    assert [payload["sequence"] for _name, payload in chunks] == [0, 1]
    assert "".join(
        str(payload["text"]) for _name, payload in chunks
    ) == answer
    assert all(
        0 < len(str(payload["text"])) <= STREAM_CHUNK_CHARACTERS
        for _name, payload in chunks
    )
    assert events[-1][1] == {
        "request_id": request_id,
        "chunks": 2,
    }
    assert "\ndata: {" in response.text
    assert "\n\n" in response.text
    for forbidden in INTERNAL_VALUES:
        assert forbidden not in response.text


def test_stream_precomputation_failure_is_normal_json_http_error() -> None:
    service = FakeChatService(
        exception=PipelineServiceError(
            r"private C:\Users\name\.env prompt and policy"
        )
    )

    response = _post_with_service(service)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"] == {
        "code": "support_service_unavailable",
        "message": (
            "The support service is temporarily unavailable. Please try "
            "again or use an official support channel."
        ),
        "retryable": True,
    }
    assert service.calls == ["Customer message"]
    assert "private" not in response.text
    assert "event:" not in response.text


def test_stream_execution_timeout_before_headers_is_json_error() -> None:
    service = FakeChatService(
        exception=ServiceExecutionTimeoutError(
            "private worker detail"
        )
    )

    response = _post_with_service(service)

    assert response.status_code == 504
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"] == {
        "code": "request_timeout",
        "message": "The request timed out. Please try again.",
        "retryable": True,
    }
    assert service.calls == ["Customer message"]
    assert "private" not in response.text
    assert "event:" not in response.text


@pytest.mark.asyncio
async def test_stream_disconnect_before_metadata_emits_nothing() -> None:
    request = _request(_flags(True))
    metadata = StreamMetadataEvent(
        request_id="request-id",
        status="answered",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
    )

    frames = await _collect(
        chat_module._stream_approved_answer(
            request=request,
            request_id="request-id",
            metadata=metadata,
            answer="Approved answer.",
        )
    )

    assert frames == []


@pytest.mark.asyncio
async def test_stream_disconnect_between_chunks_has_no_terminal_frame() -> None:
    request = _request(_flags(False, False, True))
    metadata = StreamMetadataEvent(
        request_id="request-id",
        status="answered",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
    )

    frames = await _collect(
        chat_module._stream_approved_answer(
            request=request,
            request_id="request-id",
            metadata=metadata,
            answer="x" * (STREAM_CHUNK_CHARACTERS + 1),
        )
    )

    assert [name for name, _payload in _parse_sse("".join(frames))] == [
        "metadata",
        "chunk",
    ]


@pytest.mark.asyncio
async def test_unexpected_post_header_failure_emits_one_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_after_one(_answer: str) -> Iterator[str]:
        yield "Approved first chunk."
        raise RuntimeError(r"private C:\policy prompt")

    monkeypatch.setattr(chat_module, "_iter_answer_chunks", fail_after_one)
    request = _request(_flags(False, False, False))
    metadata = StreamMetadataEvent(
        request_id="request-id",
        status="answered",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
    )

    frames = await _collect(
        chat_module._stream_approved_answer(
            request=request,
            request_id="request-id",
            metadata=metadata,
            answer="Approved answer.",
        )
    )

    events = _parse_sse("".join(frames))
    assert [name for name, _payload in events] == [
        "metadata",
        "chunk",
        "error",
    ]
    assert events[-1][1] == stream_interrupted_event(
        request_id="request-id"
    ).model_dump(mode="json")
    assert request.state.api_log_context == {
        "internal_error_code": "stream_delivery_failed"
    }
    assert "private" not in "".join(frames)
    assert "policy" not in "".join(frames)
    assert "prompt" not in "".join(frames)


@pytest.mark.asyncio
async def test_stream_reraises_cancellation_without_terminal_event() -> None:
    async def cancelled() -> bool:
        raise asyncio.CancelledError

    request = _request()
    request.is_disconnected = cancelled  # type: ignore[method-assign]
    metadata = StreamMetadataEvent(
        request_id="request-id",
        status="answered",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
    )

    stream = chat_module._stream_approved_answer(
        request=request,
        request_id="request-id",
        metadata=metadata,
        answer="Approved answer.",
    )
    with pytest.raises(asyncio.CancelledError):
        await stream.__anext__()


@pytest.mark.asyncio
async def test_cancellation_remains_primary_when_polling_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unsupported_poll() -> bool:
        raise RuntimeError("test transport does not support polling")

    async def cancelled_sleep(_delay: float) -> None:
        raise asyncio.CancelledError

    request = _request()
    request.is_disconnected = unsupported_poll  # type: ignore[method-assign]
    monkeypatch.setattr(chat_module.asyncio, "sleep", cancelled_sleep)
    metadata = StreamMetadataEvent(
        request_id="request-id",
        status="answered",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
    )
    frames: list[str] = []

    with pytest.raises(asyncio.CancelledError):
        async for frame in chat_module._stream_approved_answer(
            request=request,
            request_id="request-id",
            metadata=metadata,
            answer="Approved answer.",
        ):
            frames.append(frame)

    assert [name for name, _payload in _parse_sse("".join(frames))] == [
        "metadata",
        "chunk",
    ]
    assert "event: done" not in "".join(frames)
    assert "event: error" not in "".join(frames)


@pytest.mark.asyncio
async def test_multiple_buffered_streams_deliver_after_bounded_compute() -> None:
    running = 0
    maximum_running = 0
    counter_lock = threading.Lock()
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()

    class SequencedPipeline(FakePipeline):
        def answer(
            self,
            *,
            query: str,
            classification: ClassificationResult,
        ) -> PipelineAnswer:
            nonlocal running, maximum_running
            with counter_lock:
                running += 1
                maximum_running = max(maximum_running, running)

            if query == "First request":
                first_started.set()
                assert release_first.wait(timeout=10)
            elif query == "Second request":
                second_started.set()
                assert release_second.wait(timeout=10)
            else:
                raise AssertionError("Unexpected test query.")

            try:
                return super().answer(
                    query=query,
                    classification=classification,
                )
            finally:
                with counter_lock:
                    running -= 1

    pipeline = SequencedPipeline()
    service = ApiChatService(
        classifier=lambda _message: classification(),
        pipeline=pipeline,
        runtime_settings=service_settings(
            max_concurrent_requests=1,
            queue_timeout_seconds=3,
            request_timeout_seconds=3,
        ),
    )
    first_task = asyncio.create_task(service.execute("First request"))
    try:
        assert await asyncio.to_thread(first_started.wait, 2)
        second_task = asyncio.create_task(
            service.execute("Second request")
        )
        await asyncio.sleep(0)
        assert not second_started.is_set()

        release_first.set()
        first_execution = await first_task
        assert await asyncio.to_thread(second_started.wait, 2)
        release_second.set()
        second_execution = await second_task

        delivery_gate = asyncio.Event()
        delivery_arrivals = 0

        def coordinated_poller():
            calls = 0

            async def poll() -> bool:
                nonlocal calls, delivery_arrivals
                calls += 1
                if calls == 2:
                    delivery_arrivals += 1
                    if delivery_arrivals == 2:
                        delivery_gate.set()
                    await delivery_gate.wait()
                return False

            return poll

        first_request = _request()
        first_request.is_disconnected = (  # type: ignore[method-assign]
            coordinated_poller()
        )
        second_request = _request()
        second_request.is_disconnected = (  # type: ignore[method-assign]
            coordinated_poller()
        )
        metadata = StreamMetadataEvent(
            request_id="request-id",
            status="answered",
            response_mode="grounded_generation",
            risk_level="low",
            requires_human=False,
        )

        first_frames, second_frames = await asyncio.gather(
            _collect(
                chat_module._stream_approved_answer(
                    request=first_request,
                    request_id="request-id",
                    metadata=metadata,
                    answer=first_execution.pipeline_answer.answer,
                )
            ),
            _collect(
                chat_module._stream_approved_answer(
                    request=second_request,
                    request_id="request-id",
                    metadata=metadata,
                    answer=second_execution.pipeline_answer.answer,
                )
            ),
        )
    finally:
        release_first.set()
        release_second.set()
        if not first_task.done():
            first_task.cancel()
        await service.shutdown()

    assert maximum_running == 1
    assert [call[0] for call in pipeline.calls] == [
        "First request",
        "Second request",
    ]
    assert delivery_arrivals == 2
    for frames in (first_frames, second_frames):
        assert [
            name for name, _payload in _parse_sse("".join(frames))
        ] == ["metadata", "chunk", "done"]


def test_stream_route_uses_execute_only_and_not_raw_stream_interfaces() -> None:
    service = _service_for_answer("Approved answer.")

    async def forbidden_astream(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Raw async streaming must not be called.")

    def forbidden_stream(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Raw streaming must not be called.")

    service.astream = forbidden_astream  # type: ignore[attr-defined]
    service.stream = forbidden_stream  # type: ignore[attr-defined]

    response = _post_with_service(service)

    assert response.status_code == 200
    assert service.calls == ["Customer message"]
    assert "event: done" in response.text
