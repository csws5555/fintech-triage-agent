"""Thin typed transport routes for complete and buffered customer chat."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.api.dependencies import get_chat_service
from app.api.errors import record_internal_error_code
from app.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    StreamChunkEvent,
    StreamDoneEvent,
    StreamMetadataEvent,
    chat_response_from_pipeline_answer,
    stream_interrupted_event,
    stream_metadata_from_chat_response,
)
from app.api.middleware import (
    add_classification_log_context,
    add_pipeline_answer_log_context,
    get_request_id,
)
from app.api.services import ApiChatService
from app.ml.rag_pipeline import STREAM_CHUNK_CHARACTERS


router = APIRouter(tags=["chat"])
_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
_CONTROLLED_ERROR_RESPONSES = {
    413: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
    504: {"model": ErrorResponse},
}


class _PolledStreamingResponse(StreamingResponse):
    """Stream with one receive-channel owner for explicit disconnect polls."""

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope, receive
        try:
            await self.stream_response(send)
        except OSError:
            return
        background: BackgroundTask | None = self.background
        if background is not None:
            await background()


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses=_CONTROLLED_ERROR_RESPONSES,
)
async def chat(
    chat_request: ChatRequest,
    request: Request,
    service: Annotated[ApiChatService, Depends(get_chat_service)],
) -> ChatResponse:
    """Return one complete safe answer from the shared execution service."""

    execution = await service.execute(chat_request.message)
    add_classification_log_context(request, execution.classification)
    add_pipeline_answer_log_context(request, execution.pipeline_answer)
    return chat_response_from_pipeline_answer(
        request_id=get_request_id(request),
        pipeline_answer=execution.pipeline_answer,
    )


def _iter_answer_chunks(answer: str) -> Iterator[str]:
    for offset in range(0, len(answer), STREAM_CHUNK_CHARACTERS):
        yield answer[offset : offset + STREAM_CHUNK_CHARACTERS]


def _sse_frame(event_name: str, payload: BaseModel) -> str:
    return (
        f"event: {event_name}\n"
        f"data: {payload.model_dump_json()}\n\n"
    )


async def _is_disconnected(request: Request) -> bool:
    try:
        return await request.is_disconnected()
    except asyncio.CancelledError:
        raise
    except Exception:
        return False


async def _stream_approved_answer(
    *,
    request: Request,
    request_id: str,
    metadata: StreamMetadataEvent,
    answer: str,
) -> AsyncIterator[str]:
    try:
        if await _is_disconnected(request):
            return
        yield _sse_frame("metadata", metadata)

        chunk_count = 0
        for sequence, text in enumerate(_iter_answer_chunks(answer)):
            if await _is_disconnected(request):
                return
            yield _sse_frame(
                "chunk",
                StreamChunkEvent(
                    request_id=request_id,
                    sequence=sequence,
                    text=text,
                ),
            )
            chunk_count += 1
            await asyncio.sleep(0)

        if await _is_disconnected(request):
            return
        yield _sse_frame(
            "done",
            StreamDoneEvent(
                request_id=request_id,
                chunks=chunk_count,
            ),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        record_internal_error_code(
            request.scope,
            "stream_delivery_failed",
        )
        if await _is_disconnected(request):
            return
        yield _sse_frame(
            "error",
            stream_interrupted_event(request_id=request_id),
        )


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Validated buffered Server-Sent Events. The complete answer "
                "is computed and approved before response headers; SSE makes "
                "only delivery of that approved answer incremental. Events "
                "are `metadata` (safe answer metadata), ordered `chunk` "
                "(approved answer text), terminal `done` (chunk count), and "
                "terminal `error` (a safe interruption error)."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            },
        },
        **_CONTROLLED_ERROR_RESPONSES,
    },
)
async def stream_chat(
    chat_request: ChatRequest,
    request: Request,
    service: Annotated[ApiChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    """Deliver validated text/event-stream metadata, chunk, done/error events."""

    execution = await service.execute(chat_request.message)
    add_classification_log_context(request, execution.classification)
    add_pipeline_answer_log_context(request, execution.pipeline_answer)

    request_id = get_request_id(request)
    response = chat_response_from_pipeline_answer(
        request_id=request_id,
        pipeline_answer=execution.pipeline_answer,
    )
    metadata = stream_metadata_from_chat_response(response)
    return _PolledStreamingResponse(
        _stream_approved_answer(
            request=request,
            request_id=request_id,
            metadata=metadata,
            answer=execution.pipeline_answer.answer,
        ),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


__all__ = ["chat", "router", "stream_chat"]
