from __future__ import annotations

import pytest
from langchain_ollama import ChatOllama

from app.ml.chat_model import build_chat_model
from app.ml.rag_config import settings


@pytest.mark.integration
def test_live_approved_chat_model_initializes() -> None:
    model = build_chat_model(settings)

    assert isinstance(model, ChatOllama)
    assert model.model == settings.chat_model
    assert model.base_url == settings.ollama_base_url
    assert model.temperature == settings.temperature
    assert model.num_ctx == settings.context_length
    assert model.num_predict == settings.max_output_tokens
    assert model.validate_model_on_init is True
    assert model.client_kwargs == {
        "timeout": settings.request_timeout_seconds,
    }
