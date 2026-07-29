from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.ml import classifier as classifier_module
from app.ml.classifier import (
    ClassifierInferenceError,
    _normalize_predictions,
    classify_intent,
)
from app.ml.rag_config import settings


class FakeClassifier:
    def __init__(self, output: list[dict[str, Any]]) -> None:
        self.output = output
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(
        self,
        text: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.calls.append((text, kwargs))
        return self.output


def test_predictions_are_sorted_and_classifier_arguments_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClassifier(
        [
            {"label": "third", "score": 0.1},
            {"label": "first", "score": 0.8},
            {"label": "second", "score": 0.3},
        ]
    )
    monkeypatch.setattr(
        classifier_module,
        "get_classifier",
        lambda: fake,
    )

    result = classify_intent("  a long customer message  ")

    assert [item.label for item in result.predictions] == [
        "first",
        "second",
        "third",
    ]
    assert fake.calls == [
        (
            "a long customer message",
            {
                "top_k": 3,
                "truncation": True,
                "max_length": 128,
            },
        )
    ]


@pytest.mark.parametrize(
    "output",
    (
        [],
        [{"label": "one", "score": 0.5}],
        [
            {"label": "one", "score": 0.4},
            {"label": "two", "score": 0.3},
            {"label": "three", "score": 0.2},
            {"label": "four", "score": 0.1},
        ],
        [
            {"label": "same", "score": 0.7},
            {"label": "same", "score": 0.2},
            {"label": "other", "score": 0.1},
        ],
        [
            {"label": "one", "score": -0.1},
            {"label": "two", "score": 0.2},
            {"label": "three", "score": 0.1},
        ],
        [
            {"label": "one", "score": 1.1},
            {"label": "two", "score": 0.2},
            {"label": "three", "score": 0.1},
        ],
        [
            {"label": "one", "score": float("nan")},
            {"label": "two", "score": 0.2},
            {"label": "three", "score": 0.1},
        ],
        [
            {"label": "one", "score": float("inf")},
            {"label": "two", "score": 0.2},
            {"label": "three", "score": 0.1},
        ],
    ),
)
def test_malformed_predictions_are_rejected(
    output: list[dict[str, Any]],
) -> None:
    with pytest.raises(ClassifierInferenceError):
        _normalize_predictions(output)


def test_long_input_uses_configured_token_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClassifier(
        [
            {"label": "one", "score": 0.8},
            {"label": "two", "score": 0.1},
            {"label": "three", "score": 0.05},
        ]
    )
    monkeypatch.setattr(
        classifier_module,
        "get_classifier",
        lambda: fake,
    )
    long_message = " ".join(["customer"] * 200)

    classify_intent(long_message)

    assert fake.calls == [
        (
            long_message,
            {
                "top_k": 3,
                "truncation": True,
                "max_length": settings.classifier_max_length,
            },
        )
    ]
    assert settings.classifier_max_length == 128


def test_low_confidence_sets_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClassifier(
        [
            {"label": "one", "score": 0.60},
            {"label": "two", "score": 0.20},
            {"label": "three", "score": 0.10},
        ]
    )
    monkeypatch.setattr(
        classifier_module,
        "get_classifier",
        lambda: fake,
    )

    assert classify_intent("message").uncertain is True


def test_small_margin_sets_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClassifier(
        [
            {"label": "one", "score": 0.80},
            {"label": "two", "score": 0.70},
            {"label": "three", "score": 0.05},
        ]
    )
    monkeypatch.setattr(
        classifier_module,
        "get_classifier",
        lambda: fake,
    )

    result = classify_intent("message")

    assert result.uncertain is True
    assert result.top_two_margin == pytest.approx(0.10)


def test_classifier_loader_uses_only_local_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_calls: list[tuple[object, dict[str, Any]]] = []
    tokenizer_calls: list[tuple[object, dict[str, Any]]] = []
    pipeline_calls: list[dict[str, Any]] = []

    labels = {
        index: (
            "lost_or_stolen_card"
            if index == 0
            else f"label_{index}"
        )
        for index in range(77)
    }
    fake_model = SimpleNamespace(
        config=SimpleNamespace(
            num_labels=77,
            id2label=labels,
        ),
        eval=lambda: None,
    )
    fake_tokenizer = object()
    fake_pipeline = object()

    def fake_model_loader(
        path: object,
        **kwargs: Any,
    ) -> object:
        model_calls.append((path, kwargs))
        return fake_model

    def fake_tokenizer_loader(
        path: object,
        **kwargs: Any,
    ) -> object:
        tokenizer_calls.append((path, kwargs))
        return fake_tokenizer

    def fake_pipeline_builder(**kwargs: Any) -> object:
        pipeline_calls.append(kwargs)
        return fake_pipeline

    classifier_module.get_classifier.cache_clear()
    monkeypatch.setattr(
        classifier_module.AutoModelForSequenceClassification,
        "from_pretrained",
        fake_model_loader,
    )
    monkeypatch.setattr(
        classifier_module.AutoTokenizer,
        "from_pretrained",
        fake_tokenizer_loader,
    )
    monkeypatch.setattr(
        classifier_module,
        "pipeline",
        fake_pipeline_builder,
    )

    try:
        loaded = classifier_module.get_classifier()
    finally:
        classifier_module.get_classifier.cache_clear()

    assert loaded is fake_pipeline
    assert model_calls == [
        (
            settings.classifier_model_dir,
            {"local_files_only": True},
        )
    ]
    assert tokenizer_calls == [
        (
            settings.classifier_model_dir,
            {"local_files_only": True},
        )
    ]
    assert pipeline_calls[0]["device"] == -1
