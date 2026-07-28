from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.ml import chat_model as chat_model_module
from app.ml.chat_model import (
    ChatModelInitializationError,
    build_chat_model,
)
from app.ml.rag_config import (
    RagConfigurationError,
    settings,
)


class FakeChatModel:
    def invoke(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def ainvoke(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        return None

    def stream(self, *_args: object, **_kwargs: object):
        return iter(())

    async def astream(
        self,
        *_args: object,
        **_kwargs: object,
    ):
        if False:
            yield None

    def with_structured_output(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> FakeChatModel:
        return self


class RecordingFactory:
    def __init__(
        self,
        *,
        result: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = FakeChatModel() if result is None else result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        return self.result


def test_build_chat_model_uses_exact_validated_settings() -> None:
    factory = RecordingFactory()

    model = build_chat_model(
        settings,
        model_factory=factory,
    )

    assert model is factory.result
    assert factory.calls == [
        {
            "model": settings.chat_model,
            "base_url": settings.ollama_base_url,
            "temperature": settings.temperature,
            "num_ctx": settings.context_length,
            "num_predict": settings.max_output_tokens,
            "validate_model_on_init": True,
            "client_kwargs": {
                "timeout": settings.request_timeout_seconds,
            },
        }
    ]


def test_invalid_settings_fail_before_factory_call() -> None:
    factory = RecordingFactory()
    invalid = replace(
        settings,
        chat_model="unapproved-model",
    )

    with pytest.raises(RagConfigurationError):
        build_chat_model(
            invalid,
            model_factory=factory,
        )

    assert factory.calls == []


def test_non_settings_input_is_rejected() -> None:
    factory = RecordingFactory()

    with pytest.raises(TypeError, match="RagSettings"):
        build_chat_model(
            object(),  # type: ignore[arg-type]
            model_factory=factory,
        )

    assert factory.calls == []


def test_non_callable_factory_is_rejected() -> None:
    with pytest.raises(TypeError, match="callable"):
        build_chat_model(
            settings,
            model_factory=None,  # type: ignore[arg-type]
        )


def test_provider_failure_is_wrapped_without_details() -> None:
    factory = RecordingFactory(
        error=RuntimeError(
            "provider detail that must not escape"
        )
    )

    with pytest.raises(
        ChatModelInitializationError,
        match="approved local chat model",
    ) as captured:
        build_chat_model(
            settings,
            model_factory=factory,
        )

    assert "provider detail" not in str(captured.value)


def test_malformed_provider_interface_fails_closed() -> None:
    factory = RecordingFactory(result=object())

    with pytest.raises(
        ChatModelInitializationError,
        match="required interface",
    ):
        build_chat_model(
            settings,
            model_factory=factory,
        )


def test_get_chat_model_is_lazy_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = FakeChatModel()
    calls: list[object] = []

    def fake_build(runtime_settings):
        calls.append(runtime_settings)
        return created

    chat_model_module.get_chat_model.cache_clear()
    monkeypatch.setattr(
        chat_model_module,
        "build_chat_model",
        fake_build,
    )

    try:
        first = chat_model_module.get_chat_model()
        second = chat_model_module.get_chat_model()
    finally:
        chat_model_module.get_chat_model.cache_clear()

    assert first is created
    assert second is created
    assert calls == [settings]
