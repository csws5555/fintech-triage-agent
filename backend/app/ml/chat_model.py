"""Lazy, validated construction of the approved local chat model."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.ml.rag_config import (
    RagSettings,
    settings,
    validate_rag_settings,
)


class ChatModelInitializationError(RuntimeError):
    """Raised when the approved local chat model cannot be initialized."""


ChatModelFactory = Callable[..., object]
REQUIRED_CHAT_MODEL_METHODS = (
    "invoke",
    "ainvoke",
    "stream",
    "astream",
    "with_structured_output",
)


def build_chat_model(
    runtime_settings: RagSettings,
    *,
    model_factory: ChatModelFactory = ChatOllama,
) -> BaseChatModel:
    """Construct one validated loopback-only ChatOllama client."""

    if not isinstance(runtime_settings, RagSettings):
        raise TypeError(
            "runtime_settings must be a RagSettings instance."
        )

    if not callable(model_factory):
        raise TypeError("model_factory must be callable.")

    validate_rag_settings(runtime_settings)

    try:
        model = model_factory(
            model=runtime_settings.chat_model,
            base_url=runtime_settings.ollama_base_url,
            temperature=runtime_settings.temperature,
            num_ctx=runtime_settings.context_length,
            num_predict=runtime_settings.max_output_tokens,
            validate_model_on_init=True,
            client_kwargs={
                "timeout": (
                    runtime_settings.request_timeout_seconds
                ),
            },
        )
    except Exception as exc:
        raise ChatModelInitializationError(
            "Unable to initialize the approved local chat model."
        ) from exc

    if any(
        not callable(getattr(model, method_name, None))
        for method_name in REQUIRED_CHAT_MODEL_METHODS
    ):
        raise ChatModelInitializationError(
            "Local chat model does not provide the required interface."
        )

    return cast(BaseChatModel, model)


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    """Return the process-wide approved local chat model."""

    return build_chat_model(settings)


__all__ = [
    "ChatModelInitializationError",
    "build_chat_model",
    "get_chat_model",
]
