"""
Local Banking77 intent classifier.

This module loads the trained Phase 1 DistilBERT model from local
storage and exposes a typed Phase 2 classification interface.

It does not train, download, save, resave, or overwrite the model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    TextClassificationPipeline,
    pipeline,
)

from app.ml.rag_config import settings
from app.ml.triage_types import (
    ClassificationResult,
    IntentPrediction,
)


EXPECTED_LABEL_COUNT = 77
EXPECTED_PREDICTION_COUNT = 3


class ClassifierLoadError(RuntimeError):
    """Raised when the saved Phase 1 classifier cannot be loaded."""


class ClassifierInferenceError(RuntimeError):
    """Raised when classifier output is malformed or incomplete."""


def _validate_input(text: str) -> str:
    """
    Validate and normalize customer text before classification.
    """

    if not isinstance(text, str):
        raise TypeError("Classifier input must be a string.")

    normalized = text.strip()

    if not normalized:
        raise ValueError("Classifier input cannot be empty.")

    if len(normalized) > settings.max_customer_message_length:
        raise ValueError(
            "Classifier input exceeds the configured maximum "
            f"length of {settings.max_customer_message_length} "
            "characters."
        )

    return normalized


def _validate_threshold(
    value: float,
    *,
    name: str,
) -> float:
    """
    Validate a caller-supplied classifier threshold.
    """

    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number.")

    resolved = float(value)

    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be finite.")

    if not 0.0 <= resolved <= 1.0:
        raise ValueError(
            f"{name} must be between 0 and 1."
        )

    return resolved


@lru_cache(maxsize=1)
def get_classifier() -> TextClassificationPipeline:
    """
    Load and cache the protected local Phase 1 classifier.

    The model is loaded once per Python process. Multiple server
    worker processes will each load their own model instance.
    """

    model_dir = settings.classifier_model_dir

    if not model_dir.exists():
        raise ClassifierLoadError(
            "Saved Phase 1 model directory does not exist: "
            f"{model_dir}"
        )

    if not model_dir.is_dir():
        raise ClassifierLoadError(
            "Saved Phase 1 model path is not a directory: "
            f"{model_dir}"
        )

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_dir,
            local_files_only=True,
        )

        model = AutoModelForSequenceClassification.from_pretrained(
            model_dir,
            local_files_only=True,
        )

    except (OSError, TypeError, ValueError) as exc:
        raise ClassifierLoadError(
            "Unable to load the saved Phase 1 classifier from "
            f"{model_dir}. Confirm that the model and tokenizer "
            "files were saved successfully."
        ) from exc

    if model.config.num_labels != EXPECTED_LABEL_COUNT:
        raise ClassifierLoadError(
            "Unexpected classifier label count. "
            f"Expected {EXPECTED_LABEL_COUNT}, received "
            f"{model.config.num_labels}."
        )

    label_names = {
        str(label)
        for label in model.config.id2label.values()
    }

    if len(label_names) != EXPECTED_LABEL_COUNT:
        raise ClassifierLoadError(
            "The saved classifier does not contain 77 unique "
            "readable label names."
        )

    required_label = "lost_or_stolen_card"

    if required_label not in label_names:
        raise ClassifierLoadError(
            "The saved classifier does not contain the expected "
            f"Banking77 label {required_label!r}."
        )

    model.eval()

    return pipeline(
        task="text-classification",
        model=model,
        tokenizer=tokenizer,
        device=-1,
    )


def _normalize_predictions(
    raw_output: Any,
) -> list[dict[str, Any]]:
    """
    Normalize and validate Hugging Face pipeline output.
    """

    if not isinstance(raw_output, list):
        raise ClassifierInferenceError(
            "Classifier returned an unexpected result type."
        )

    if (
        len(raw_output) == 1
        and isinstance(raw_output[0], list)
    ):
        raw_output = raw_output[0]

    if len(raw_output) != EXPECTED_PREDICTION_COUNT:
        raise ClassifierInferenceError(
            "Classifier must return exactly three predictions. "
            f"Received {len(raw_output)}."
        )

    parsed: list[dict[str, Any]] = []
    seen_labels: set[str] = set()

    for item in raw_output:
        if not isinstance(item, Mapping):
            raise ClassifierInferenceError(
                "Classifier prediction entries must be mappings."
            )

        if "label" not in item or "score" not in item:
            raise ClassifierInferenceError(
                "Classifier prediction is missing label or score."
            )

        label = str(item["label"]).strip()

        if not label:
            raise ClassifierInferenceError(
                "Classifier returned an empty label."
            )

        try:
            score = float(item["score"])
        except (TypeError, ValueError) as exc:
            raise ClassifierInferenceError(
                "Classifier returned a non-numeric score."
            ) from exc

        if not math.isfinite(score):
            raise ClassifierInferenceError(
                "Classifier returned a non-finite score."
            )

        if not 0.0 <= score <= 1.0:
            raise ClassifierInferenceError(
                "Classifier returned a score outside [0, 1]."
            )

        if label in seen_labels:
            raise ClassifierInferenceError(
                "Classifier returned duplicate intent labels."
            )

        seen_labels.add(label)

        parsed.append(
            {
                "label": label,
                "score": score,
            }
        )

    parsed.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return parsed


def classify_intent(
    text: str,
    confidence_threshold: float | None = None,
    margin_threshold: float | None = None,
) -> ClassificationResult:
    """
    Return the top three Banking77 intent predictions.

    Input tokenization uses the same maximum token length as the
    Phase 1 training run.

    The result is uncertain when either:

    - the highest score is below the confidence threshold; or
    - the difference between the first and second scores is below
      the margin threshold.
    """

    normalized_text = _validate_input(text)

    resolved_confidence_threshold = _validate_threshold(
        (
            settings.classifier_confidence_threshold
            if confidence_threshold is None
            else confidence_threshold
        ),
        name="confidence_threshold",
    )

    resolved_margin_threshold = _validate_threshold(
        (
            settings.classifier_margin_threshold
            if margin_threshold is None
            else margin_threshold
        ),
        name="margin_threshold",
    )

    classifier = get_classifier()

    raw_output = classifier(
        normalized_text,
        top_k=EXPECTED_PREDICTION_COUNT,
        truncation=True,
        max_length=settings.classifier_max_length,
    )

    predictions = _normalize_predictions(raw_output)

    top_score = predictions[0]["score"]
    second_score = predictions[1]["score"]

    top_two_margin = max(
        0.0,
        min(1.0, top_score - second_score),
    )

    uncertain = (
        top_score < resolved_confidence_threshold
        or top_two_margin < resolved_margin_threshold
    )

    return ClassificationResult(
        predictions=tuple(
            IntentPrediction(
                label=item["label"],
                confidence=item["score"],
            )
            for item in predictions
        ),
        uncertain=uncertain,
        top_two_margin=top_two_margin,
    )