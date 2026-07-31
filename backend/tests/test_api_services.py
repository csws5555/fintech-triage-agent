from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import pytest

from app.api.config import api_settings
from app.api.services import (
    ApiChatService,
    AppServices,
    ClassifierServiceError,
    PipelineServiceError,
    ServiceExecutionTimeoutError,
    ServiceQueueTimeoutError,
    ServiceReadiness,
    ServiceShuttingDownError,
)
from app.ml.triage_types import (
    ClassificationResult,
    IntentPrediction,
    PipelineAnswer,
)


def classification() -> ClassificationResult:
    return ClassificationResult(
        predictions=(
            IntentPrediction(label="card_arrival", confidence=0.8),
            IntentPrediction(label="card_delivery_tracking", confidence=0.1),
            IntentPrediction(label="cash_withdrawal", confidence=0.05),
        ),
        uncertain=False,
        top_two_margin=0.7,
    )


def pipeline_answer() -> PipelineAnswer:
    return PipelineAnswer(
        answer="Approved complete answer.",
        response_mode="grounded_generation",
        risk_level="low",
        requires_human=False,
        retrieval_sufficient=True,
        retrieved_policy_ids=("card_delivery",),
        retrieved_chunk_ids=("card-delivery-chunk",),
        reason_code="supported_policy_scope",
    )


def service_settings(
    *,
    max_concurrent_requests: int = 1,
    queue_timeout_seconds: int = 1,
    request_timeout_seconds: int = 3,
):
    return replace(
        api_settings,
        max_concurrent_requests=max_concurrent_requests,
        queue_timeout_seconds=queue_timeout_seconds,
        request_timeout_seconds=request_timeout_seconds,
    )


class FakePipeline:
    def __init__(
        self,
        *,
        result: PipelineAnswer | object | None = None,
        error: Exception | None = None,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.result = pipeline_answer() if result is None else result
        self.error = error
        self.started = started
        self.release = release
        self.calls: list[tuple[str, ClassificationResult, int]] = []

    def answer(
        self,
        *,
        query: str,
        classification: ClassificationResult,
    ) -> PipelineAnswer:
        self.calls.append((query, classification, threading.get_ident()))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=10)
        if self.error is not None:
            raise self.error
        return self.result  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_execute_calls_classifier_and_pipeline_once_off_event_loop() -> None:
    expected_classification = classification()
    classifier_calls: list[tuple[str, int]] = []
    event_loop_thread = threading.get_ident()

    def classifier(message: str) -> ClassificationResult:
        classifier_calls.append((message, threading.get_ident()))
        return expected_classification

    pipeline = FakePipeline()
    service = ApiChatService(
        classifier=classifier,
        pipeline=pipeline,
        runtime_settings=service_settings(),
    )
    try:
        execution = await service.execute("When will my card arrive?")
    finally:
        await service.shutdown()

    assert classifier_calls == [
        ("When will my card arrive?", classifier_calls[0][1])
    ]
    assert len(pipeline.calls) == 1
    assert classifier_calls[0][1] != event_loop_thread
    assert pipeline.calls[0][2] == classifier_calls[0][1]
    assert pipeline.calls[0][1] is expected_classification
    assert execution.classification is expected_classification
    assert execution.pipeline_answer is pipeline.result


@pytest.mark.asyncio
async def test_app_services_reuses_exact_shared_instances() -> None:
    def classifier(_message: str) -> ClassificationResult:
        return classification()

    pipeline = FakePipeline()
    chat_service = ApiChatService(
        classifier=classifier,
        pipeline=pipeline,
        runtime_settings=service_settings(),
    )
    readiness = ServiceReadiness(
        configuration=True,
        classifier=True,
        pipeline=True,
        vector_store=False,
        ollama_chat_model=False,
        ollama_embedding_model=False,
        failure_codes=("local_services_unavailable",),
    )
    services = AppServices(
        classifier=classifier,
        pipeline=pipeline,
        chat_service=chat_service,
        readiness=readiness,
    )
    try:
        first = await services.chat_service.execute("First request")
        second = await services.chat_service.execute("Second request")
    finally:
        await services.shutdown()

    assert services.classifier is classifier
    assert services.pipeline is pipeline
    assert services.chat_service is chat_service
    assert services.readiness is readiness
    assert not services.readiness.ready
    assert len(pipeline.calls) == 2
    assert first.classification is not second.classification


@pytest.mark.asyncio
async def test_classifier_failures_use_stable_service_exception() -> None:
    def classifier(_message: str) -> ClassificationResult:
        raise OSError("private classifier detail")

    pipeline = FakePipeline()
    service = ApiChatService(
        classifier=classifier,
        pipeline=pipeline,
        runtime_settings=service_settings(),
    )
    try:
        with pytest.raises(
            ClassifierServiceError,
            match="Classifier execution failed",
        ) as captured:
            await service.execute("Valid request")
    finally:
        await service.shutdown()

    assert "private classifier detail" not in str(captured.value)
    assert pipeline.calls == []


@pytest.mark.asyncio
async def test_escaped_pipeline_failures_use_stable_service_exception() -> None:
    pipeline = FakePipeline(error=OSError("private pipeline detail"))
    service = ApiChatService(
        classifier=lambda _message: classification(),
        pipeline=pipeline,
        runtime_settings=service_settings(),
    )
    try:
        with pytest.raises(
            PipelineServiceError,
            match="Support pipeline execution failed",
        ) as captured:
            await service.execute("Valid request")
    finally:
        await service.shutdown()

    assert "private pipeline detail" not in str(captured.value)
    assert len(pipeline.calls) == 1


@pytest.mark.asyncio
async def test_execution_timeout_retains_capacity_until_worker_finishes() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    classifier_calls: list[str] = []

    def classifier(message: str) -> ClassificationResult:
        classifier_calls.append(message)
        return classification()

    pipeline = FakePipeline(started=first_started, release=release_first)
    service = ApiChatService(
        classifier=classifier,
        pipeline=pipeline,
        runtime_settings=service_settings(request_timeout_seconds=1),
    )
    try:
        with pytest.raises(ServiceExecutionTimeoutError):
            await service.execute("First request")
        assert first_started.is_set()

        with pytest.raises(ServiceQueueTimeoutError):
            await service.execute("Second request")

        release_first.set()
        execution = await service.execute("Third request")
    finally:
        release_first.set()
        await service.shutdown()

    assert execution.pipeline_answer is pipeline.result
    assert [call[0] for call in pipeline.calls] == [
        "First request",
        "Third request",
    ]
    assert classifier_calls == [
        "First request",
        "Third request",
    ]


@pytest.mark.asyncio
async def test_cancellation_retains_capacity_until_worker_finishes() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    pipeline = FakePipeline(started=first_started, release=release_first)
    service = ApiChatService(
        classifier=lambda _message: classification(),
        pipeline=pipeline,
        runtime_settings=service_settings(request_timeout_seconds=3),
    )
    first_task = asyncio.create_task(service.execute("First request"))
    try:
        assert await asyncio.to_thread(first_started.wait, 2)
        first_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_task

        with pytest.raises(ServiceQueueTimeoutError):
            await service.execute("Second request")

        release_first.set()
        await service.execute("Third request")
    finally:
        release_first.set()
        if not first_task.done():
            first_task.cancel()
        await service.shutdown()

    assert [call[0] for call in pipeline.calls] == [
        "First request",
        "Third request",
    ]


@pytest.mark.asyncio
async def test_simultaneous_requests_respect_configured_bound() -> None:
    condition = threading.Condition()
    running = 0
    maximum_running = 0
    release_workers = threading.Event()

    class CountingPipeline(FakePipeline):
        def answer(
            self,
            *,
            query: str,
            classification: ClassificationResult,
        ) -> PipelineAnswer:
            nonlocal running, maximum_running
            with condition:
                running += 1
                maximum_running = max(maximum_running, running)
                condition.notify_all()
            assert release_workers.wait(timeout=10)
            with condition:
                running -= 1
            return super().answer(
                query=query,
                classification=classification,
            )

    pipeline = CountingPipeline()
    service = ApiChatService(
        classifier=lambda _message: classification(),
        pipeline=pipeline,
        runtime_settings=service_settings(
            max_concurrent_requests=2,
            queue_timeout_seconds=3,
            request_timeout_seconds=3,
        ),
    )
    tasks = [
        asyncio.create_task(service.execute(f"Request {index}"))
        for index in range(4)
    ]
    try:
        reached_bound = await asyncio.to_thread(
            _wait_for_running_count,
            condition,
            lambda: running,
            2,
        )
        assert reached_bound
        assert maximum_running == 2
        assert len(pipeline.calls) == 0
        release_workers.set()
        await asyncio.gather(*tasks)
    finally:
        release_workers.set()
        await service.shutdown()

    assert maximum_running == 2
    assert len(pipeline.calls) == 4


def _wait_for_running_count(
    condition: threading.Condition,
    current_count,
    expected: int,
) -> bool:
    with condition:
        return condition.wait_for(
            lambda: current_count() == expected,
            timeout=2,
        )


@pytest.mark.asyncio
async def test_shutdown_rejects_new_work_and_waits_for_running_job() -> None:
    started = threading.Event()
    release = threading.Event()
    pipeline = FakePipeline(started=started, release=release)
    service = ApiChatService(
        classifier=lambda _message: classification(),
        pipeline=pipeline,
        runtime_settings=service_settings(request_timeout_seconds=3),
    )
    running_task = asyncio.create_task(service.execute("Running request"))
    assert await asyncio.to_thread(started.wait, 2)

    shutdown_task = asyncio.create_task(service.shutdown())
    await asyncio.sleep(0)
    assert service.shutdown_started
    assert not shutdown_task.done()
    with pytest.raises(ServiceShuttingDownError):
        await service.execute("Rejected request")

    release.set()
    await running_task
    await shutdown_task
    await service.shutdown()

    assert len(pipeline.calls) == 1


@pytest.mark.asyncio
async def test_shutdown_cancels_queued_request_and_awaits_running_job() -> None:
    running_started = threading.Event()
    release_running = threading.Event()
    pipeline = FakePipeline(
        started=running_started,
        release=release_running,
    )
    service = ApiChatService(
        classifier=lambda _message: classification(),
        pipeline=pipeline,
        runtime_settings=service_settings(
            queue_timeout_seconds=3,
            request_timeout_seconds=3,
        ),
    )
    running_task = asyncio.create_task(
        service.execute("Running request")
    )
    assert await asyncio.to_thread(running_started.wait, 2)

    queued_task = asyncio.create_task(service.execute("Queued request"))
    await asyncio.sleep(0)
    assert not queued_task.done()
    assert [call[0] for call in pipeline.calls] == ["Running request"]

    shutdown_task = asyncio.create_task(service.shutdown())
    await asyncio.sleep(0)
    assert service.shutdown_started
    assert not shutdown_task.done()

    release_running.set()
    await running_task
    with pytest.raises(ServiceShuttingDownError):
        await queued_task
    await shutdown_task

    assert [call[0] for call in pipeline.calls] == ["Running request"]


def test_service_readiness_is_strict_and_immutable() -> None:
    readiness = ServiceReadiness(
        configuration=True,
        classifier=True,
        pipeline=True,
        vector_store=True,
        ollama_chat_model=True,
        ollama_embedding_model=True,
    )

    assert readiness.ready
    with pytest.raises((AttributeError, TypeError)):
        readiness.pipeline = False  # type: ignore[misc]
    with pytest.raises(TypeError, match="booleans"):
        ServiceReadiness(
            configuration=1,  # type: ignore[arg-type]
            classifier=True,
            pipeline=True,
            vector_store=True,
            ollama_chat_model=True,
            ollama_embedding_model=True,
        )
