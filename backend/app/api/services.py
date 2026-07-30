"""Shared Phase 3 services and bounded blocking-work execution."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Awaitable, Protocol

from app.api.config import ApiSettings, api_settings, validate_api_settings
from app.ml.triage_types import ClassificationResult, PipelineAnswer


ClassifierCallable = Callable[[str], ClassificationResult]
ClockCallable = Callable[[], float]


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
class OllamaModelAvailability:
    """Safe result of one read-only installed-model inventory check."""

    chat_model: bool
    embedding_model: bool

    def __post_init__(self) -> None:
        if type(self.chat_model) is not bool:
            raise TypeError("chat_model must be a boolean.")
        if type(self.embedding_model) is not bool:
            raise TypeError("embedding_model must be a boolean.")


ReadinessRecovery = Callable[
    [ServiceReadiness],
    Awaitable[ServiceReadiness],
]
OllamaModelProbe = Callable[[int], OllamaModelAvailability]


class ReadinessCoordinator:
    """Publish synchronized health snapshots and bounded optional recovery."""

    def __init__(
        self,
        *,
        initial: ServiceReadiness,
        model_probe: OllamaModelProbe,
        recover_optional: ReadinessRecovery,
        runtime_settings: ApiSettings = api_settings,
        clock: ClockCallable = time.monotonic,
    ) -> None:
        if not isinstance(initial, ServiceReadiness):
            raise TypeError("initial must be a ServiceReadiness.")
        if not callable(model_probe):
            raise TypeError("model_probe must be callable.")
        if not callable(recover_optional):
            raise TypeError("recover_optional must be callable.")
        if not isinstance(runtime_settings, ApiSettings):
            raise TypeError("runtime_settings must be an ApiSettings.")
        if not callable(clock):
            raise TypeError("clock must be callable.")

        validate_api_settings(runtime_settings)
        self._snapshot = initial
        self._model_probe = model_probe
        self._recover_optional = recover_optional
        self._health_timeout = runtime_settings.health_timeout_seconds
        self._retry_cooldown = (
            runtime_settings.readiness_retry_cooldown_seconds
        )
        self._clock = clock
        self._last_recovery_at: float | None = None
        self._lock = asyncio.Lock()
        self._inflight_check: asyncio.Task[ServiceReadiness] | None = None

    @property
    def snapshot(self) -> ServiceReadiness:
        """Return the last complete immutable readiness snapshot."""

        return self._snapshot

    async def check(self) -> ServiceReadiness:
        """Return one bounded, synchronized, safely degraded snapshot."""

        task = self._inflight_check
        if task is None or task.done():
            task = asyncio.create_task(self._run_bounded_check())
            self._inflight_check = task
        return await asyncio.shield(task)

    async def _run_bounded_check(self) -> ServiceReadiness:
        try:
            return await asyncio.wait_for(
                self._check_serialized(),
                timeout=self._health_timeout,
            )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return self._degraded_after_health_failure()

    async def _check_serialized(self) -> ServiceReadiness:
        async with self._lock:
            snapshot = self._snapshot
            now = self._clock()
            recovery_due = (
                not snapshot.ready
                and (
                    self._last_recovery_at is None
                    or now - self._last_recovery_at >= self._retry_cooldown
                )
            )
            if recovery_due:
                self._last_recovery_at = now
                recovered = await self._recover_optional(snapshot)
                if not isinstance(recovered, ServiceReadiness):
                    raise TypeError(
                        "Readiness recovery returned an invalid contract."
                    )
                snapshot = recovered

            availability = await asyncio.to_thread(
                self._model_probe,
                self._health_timeout,
            )
            if not isinstance(availability, OllamaModelAvailability):
                raise TypeError(
                    "Ollama model probe returned an invalid contract."
                )

            self._snapshot = _readiness_with_ollama_availability(
                snapshot,
                availability=availability,
            )
            return self._snapshot

    def _degraded_after_health_failure(self) -> ServiceReadiness:
        current = self._snapshot
        self._snapshot = ServiceReadiness(
            configuration=current.configuration,
            classifier=current.classifier,
            pipeline=current.pipeline,
            vector_store=current.vector_store,
            ollama_chat_model=False,
            ollama_embedding_model=False,
            failure_codes=_unique_codes(
                current.failure_codes + ("health_check_unavailable",)
            ),
        )
        return self._snapshot


def _readiness_with_ollama_availability(
    snapshot: ServiceReadiness,
    *,
    availability: OllamaModelAvailability,
) -> ServiceReadiness:
    failure_codes = tuple(
        code
        for code in snapshot.failure_codes
        if code
        not in {
            "chat_model_unavailable",
            "embedding_model_unavailable",
            "health_check_unavailable",
        }
    )
    if not availability.chat_model:
        failure_codes += ("chat_model_unavailable",)
    if not availability.embedding_model:
        failure_codes += ("embedding_model_unavailable",)
    return ServiceReadiness(
        configuration=snapshot.configuration,
        classifier=snapshot.classifier,
        pipeline=snapshot.pipeline,
        vector_store=snapshot.vector_store,
        ollama_chat_model=(
            snapshot.ollama_chat_model and availability.chat_model
        ),
        ollama_embedding_model=(
            snapshot.ollama_embedding_model and availability.embedding_model
        ),
        failure_codes=_unique_codes(failure_codes),
    )


def _unique_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


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
    readiness_coordinator: ReadinessCoordinator | None = None

    def __post_init__(self) -> None:
        if not callable(self.classifier):
            raise TypeError("classifier must be callable.")
        if not callable(getattr(self.pipeline, "answer", None)):
            raise TypeError("pipeline must provide answer().")
        if not isinstance(self.chat_service, ApiChatService):
            raise TypeError("chat_service must be an ApiChatService.")
        if not isinstance(self.readiness, ServiceReadiness):
            raise TypeError("readiness must be a ServiceReadiness.")
        if (
            self.readiness_coordinator is not None
            and not isinstance(
                self.readiness_coordinator,
                ReadinessCoordinator,
            )
        ):
            raise TypeError(
                "readiness_coordinator must be a ReadinessCoordinator."
            )
        if self.chat_service.classifier is not self.classifier:
            raise ValueError(
                "chat_service must use the container classifier."
            )
        if self.chat_service.pipeline is not self.pipeline:
            raise ValueError("chat_service must use the container pipeline.")

    async def shutdown(self) -> None:
        """Release only resources owned by the API service container."""

        await self.chat_service.shutdown()

    async def check_readiness(self) -> ServiceReadiness:
        """Publish and return the current synchronized readiness snapshot."""

        if self.readiness_coordinator is None:
            return self.readiness
        snapshot = await self.readiness_coordinator.check()
        object.__setattr__(self, "readiness", snapshot)
        return snapshot


__all__ = [
    "ApiChatService",
    "ApiServiceError",
    "AppServices",
    "ChatExecution",
    "ClassifierCallable",
    "ClassifierServiceError",
    "PipelineServiceError",
    "OllamaModelAvailability",
    "ReadinessCoordinator",
    "ServiceExecutionTimeoutError",
    "ServiceQueueTimeoutError",
    "ServiceReadiness",
    "ServiceShuttingDownError",
]
