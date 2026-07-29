from __future__ import annotations

import threading

import pytest

from app.ml.output_validator import output_validator
from app.ml.rag_pipeline import STREAM_CHUNK_CHARACTERS
from app.ml.response_templates import insufficient_policy_response
from app.ml.triage_types import PipelineAnswer
from tests.test_rag_pipeline import (
    FakeLlm,
    FakeRetriever,
    build_pipeline,
    classification,
    decision,
    generated,
    policy,
)


@pytest.mark.asyncio
async def test_astream_answer_reconstructs_approved_text() -> None:
    approved = (
        "The estimated delivery date appears while ordering. "
        "Tracking may become available after dispatch, and support can "
        "help if the displayed estimate has passed."
    )
    pipeline, _, _, _, _ = build_pipeline(
        decision(),
        retriever=FakeRetriever((policy(),), sufficient=True),
        llm=FakeLlm((generated(approved),)),
    )

    chunks = [
        chunk
        async for chunk in pipeline.astream_answer(
            query="When will my card arrive?",
            classification=classification(),
        )
    ]

    assert "".join(chunks) == approved
    assert len(chunks) > 1
    assert all(
        chunk and len(chunk) <= STREAM_CHUNK_CHARACTERS
        for chunk in chunks
    )


@pytest.mark.asyncio
async def test_astream_answer_never_yields_rejected_text() -> None:
    rejected = "I froze your card."
    pipeline, _, _, _, _ = build_pipeline(
        decision(),
        retriever=FakeRetriever((policy(),), sufficient=True),
        llm=FakeLlm((generated(rejected),)),
        validator=output_validator,
    )

    chunks = [
        chunk
        async for chunk in pipeline.astream_answer(
            query="When will my card arrive?",
            classification=classification(),
        )
    ]
    delivered = "".join(chunks)

    assert delivered == insufficient_policy_response()
    assert rejected not in delivered


@pytest.mark.asyncio
async def test_astream_answer_offloads_complete_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, _, _, _, _ = build_pipeline(
        decision(action="unsupported")
    )
    event_loop_thread = threading.get_ident()
    answer_threads: list[int] = []
    approved = "Approved buffered response."

    def fake_answer(**_kwargs: object) -> PipelineAnswer:
        answer_threads.append(threading.get_ident())
        return PipelineAnswer(
            answer=approved,
            response_mode="static_fallback",
            risk_level="low",
            requires_human=False,
            retrieval_sufficient=False,
            retrieved_policy_ids=(),
            retrieved_chunk_ids=(),
            reason_code="test_approved_response",
        )

    monkeypatch.setattr(pipeline, "answer", fake_answer)

    chunks = [
        chunk
        async for chunk in pipeline.astream_answer(
            query="A valid query",
            classification=classification(),
        )
    ]

    assert "".join(chunks) == approved
    assert answer_threads
    assert answer_threads[0] != event_loop_thread


@pytest.mark.asyncio
async def test_astream_answer_yields_nothing_when_answer_fails() -> None:
    pipeline, _, _, _, _ = build_pipeline(
        decision(action="unsupported")
    )
    chunks: list[str] = []

    with pytest.raises(ValueError, match="blank"):
        async for chunk in pipeline.astream_answer(
            query="   ",
            classification=classification(),
        ):
            chunks.append(chunk)

    assert chunks == []
