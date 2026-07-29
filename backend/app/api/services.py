"""Shared Phase 3 services and bounded blocking-work execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from app.api.config import ApiSettings, api_settings, validate_api_settings
from app.ml.triage_types import ClassificationResult, PipelineAnswer


ClassifierCallable = Callable[[str], ClassificationResult]


class _AnswerPipeline(Protocol):
    def answer(
        self,
        *,
        query: str,
        classification: ClassificationResult,
    ) -> PipelineAnswer: ...


class ApiServiceError(RuntimeError):
    """Base class for stable API service-boundary failures."""


class ServiceQueueTimeoutError(ApiServiceError):
    """Raised when bounded compute capacity is not available in time."""


class ServiceExecutionTimeoutError(ApiServiceError):
    """Raised when the caller's bounded wait for worker execution expires."""


class ClassifierServiceError(ApiServiceError):
    """Raised when the server-owned classifier fails or returns bad output."""


class PipelineServiceError(ApiServiceError):
    """Raised when an exception escapes the Phase 2 pipeline boundary."""


class ServiceShuttingDownError(ApiServiceError):
    """Raised when new work is submitted after shutdown begins."""


@dataclass(frozen=True, slots=True)
class ServiceReadiness:
    """Safe component availability retained by the application container."""

    configuration: bool
    classifier: bool
    pipeline: bool
    vector_store: bool
    ollama_chat_model: bool
    ollama_embedding_model: bool
    failure_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        component_values = (
            self.configuration,
            self.classifier,
            self.pipeline,
            self.vector_store,
            self.ollama_chat_model,
            self.ollama_embedding_model,
        )
        if any(type(value) is not bool for value in component_values):
            raise TypeError("Readiness component values must be booleans.")
        if (
            not isinstance(self.failure_codes, tuple)
            or any(
                not isinstance(code, str)
                or not code
                or code != code.strip()
                for code in self.failure_codes
            )
            or len(set(self.failure_codes)) != len(self.failure_codes)
        ):
            raise ValueError(
                "Readiness failure codes must be unique nonblank strings."
            )

    @property
    def ready(self) -> bool:
        """Return whether every required component is currently available."""

        return (
            self.configuration
            and self.classifier
            and self.pipeline
            and self.vector_store
            and self.ollama_chat_model
            and self.ollama_embedding_model
        )


@dataclass(frozen=True, slots=True)
class ChatExecution:
    """Complete internal result from one classifier-plus-pipeline job."""

    classification: ClassificationResult
    pipeline_answer: PipelineAnswer

    def __post_init__(self) -> None:
        if not isinstance(self.classification, ClassificationResult):
            raise TypeError(
                "classification must be a ClassificationResult."
            )
        if not isinstance(self.pipeline_answer, PipelineAnswer):
            raise TypeError("pipeline_answer must be a PipelineAnswer.")


class ApiChatService:
    """Run synchronous chat computation in one bounded application executor."""

    def __init__(
        self,
        *,
        classifier: ClassifierCallable,
        pipeline: _AnswerPipeline,
        runtime_settings: ApiSettings = api_settings,
    ) -> None:
        if not callable(classifier):
            raise TypeError("classifier must be callable.")
        if not callable(getattr(pipeline, "answer", None)):
            raise TypeError("pipeline must provide answer().")
        if not isinstance(runtime_settings, ApiSettings):
            raise TypeError("runtime_settings must be an ApiSettings instance.")

        validate_api_settings(runtime_settings)

        self._classifier = classifier
        self._pipeline = pipeline
        self._settings = runtime_settings
        self._capacity = asyncio.Semaphore(
            runtime_settings.max_concurrent_requests
        )
        self._executor = ThreadPoolExecutor(
            max_workers=runtime_settings.max_concurrent_requests,
            thread_name_prefix="fintech-api-compute",
        )
        self._shutdown_started = False
        self._shutdown_task: asyncio.Task[None] | None = None

    @property
    def classifier(self) -> ClassifierCallable:
        """Return the shared high-level classifier callable."""

        return self._classifier

    @property
    def pipeline(self) -> _AnswerPipeline:
        """Return the shared Phase 2 pipeline instance."""

        return self._pipeline

    @property
    def shutdown_started(self) -> bool:
        """Return whether this service has stopped accepting new work."""

        return self._shutdown_started

    async def execute(self, message: str) -> ChatExecution:
        """Run one complete chat job without blocking the event-loop thread."""

        if not isinstance(message, str):
            raise TypeError("message must be a string.")
        if not message.strip():
            raise ValueError("message cannot be blank.")
        if self._shutdown_started:
            raise ServiceShuttingDownError(
                "The chat service is shutting down."
            )

        try:
            await asyncio.wait_for(
                self._capacity.acquire(),
                timeout=self._settings.queue_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ServiceQueueTimeoutError(
                "Compute capacity was not available before the queue timeout."
            ) from exc

        if self._shutdown_started:
            self._capacity.release()
            raise ServiceShuttingDownError(
                "The chat service is shutting down."
            )

        loop = asyncio.get_running_loop()
        try:
            worker_future = loop.run_in_executor(
                self._executor,
                self._execute_blocking,
                message,
            )
        except RuntimeError as exc:
            self._capacity.release()
            raise ServiceShuttingDownError(
                "The chat service is shutting down."
            ) from exc

        worker_future.add_done_callback(self._release_capacity)

        try:
            return await asyncio.wait_for(
                asyncio.shield(worker_future),
                timeout=self._settings.request_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ServiceExecutionTimeoutError(
                "Chat execution exceeded the request timeout."
            ) from exc

    async def shutdown(self) -> None:
        """Stop new work, cancel queued jobs, and await running worker jobs."""

        self._shutdown_started = True
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(
                asyncio.to_thread(
                    self._executor.shutdown,
                    wait=True,
                    cancel_futures=True,
                )
            )
        await asyncio.shield(self._shutdown_task)

    def _execute_blocking(self, message: str) -> ChatExecution:
        try:
            classification = self._classifier(message)
            if not isinstance(classification, ClassificationResult):
                raise TypeError(
                    "Classifier returned an invalid result contract."
                )
        except Exception as exc:
            raise ClassifierServiceError(
                "Classifier execution failed."
            ) from exc

        try:
            pipeline_answer = self._pipeline.answer(
                query=message,
                classification=classification,
            )
            if not isinstance(pipeline_answer, PipelineAnswer):
                raise TypeError(
                    "Pipeline returned an invalid answer contract."
                )
        except Exception as exc:
            raise PipelineServiceError(
                "Support pipeline execution failed."
            ) from exc

        return ChatExecution(
            classification=classification,
            pipeline_answer=pipeline_answer,
        )

    def _release_capacity(self, _future: asyncio.Future[object]) -> None:
        self._capacity.release()


@dataclass(frozen=True, slots=True)
class AppServices:
    """One per-application container for shared Phase 3 dependencies."""

    classifier: ClassifierCallable
    pipeline: _AnswerPipeline
    chat_service: ApiChatService
    readiness: ServiceReadiness

    def __post_init__(self) -> None:
        if not callable(self.classifier):
            raise TypeError("classifier must be callable.")
        if not callable(getattr(self.pipeline, "answer", None)):
            raise TypeError("pipeline must provide answer().")
        if not isinstance(self.chat_service, ApiChatService):
            raise TypeError("chat_service must be an ApiChatService.")
        if not isinstance(self.readiness, ServiceReadiness):
            raise TypeError("readiness must be a ServiceReadiness.")
        if self.chat_service.classifier is not self.classifier:
            raise ValueError(
                "chat_service must use the container classifier."
            )
        if self.chat_service.pipeline is not self.pipeline:
            raise ValueError("chat_service must use the container pipeline.")

    async def shutdown(self) -> None:
        """Release only resources owned by the API service container."""

        await self.chat_service.shutdown()


__all__ = [
    "ApiChatService",
    "ApiServiceError",
    "AppServices",
    "ChatExecution",
    "ClassifierCallable",
    "ClassifierServiceError",
    "PipelineServiceError",
    "ServiceExecutionTimeoutError",
    "ServiceQueueTimeoutError",
    "ServiceReadiness",
    "ServiceShuttingDownError",
]
