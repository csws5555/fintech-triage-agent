"""
Shared typed contracts for Phase 2 triage and RAG components.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal[
    "low",
    "medium",
    "high",
    "critical",
]

TriageAction = Literal[
    "generate",
    "clarify",
    "urgent_guidance",
    "human_escalation",
    "static_response",
    "unsupported",
]

ResponseMode = Literal[
    "static_fallback",
    "deterministic_clarification",
    "deterministic_safety",
    "grounded_generation",
]


class IntentPrediction(BaseModel):
    """
    One ranked Banking77 classifier prediction.
    """

    label: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ClassificationResult(BaseModel):
    """
    Exactly three ordered classifier predictions.
    """

    predictions: tuple[
        IntentPrediction,
        IntentPrediction,
        IntentPrediction,
    ]

    uncertain: bool
    top_two_margin: float = Field(ge=0.0, le=1.0)

    @property
    def top_prediction(self) -> IntentPrediction:
        return self.predictions[0]

    @property
    def top_intent(self) -> str:
        return self.predictions[0].label

    @property
    def top_confidence(self) -> float:
        return self.predictions[0].confidence


class TriageDecision(BaseModel):
    """
    Deterministic routing result produced before retrieval.

    candidate_intents contains all three classifier labels.

    routing_intents contains only the smaller set allowed to
    influence classifier-based policy scope.

    allowed_policy_ids contains all policies retrieval may search.

    required_policy_ids contains the policies that must appear for
    retrieval to be considered sufficient.
    """

    risk_level: RiskLevel
    action: TriageAction

    candidate_intents: tuple[str, ...]
    routing_intents: tuple[str, ...]

    allowed_policy_ids: tuple[str, ...]
    required_policy_ids: tuple[str, ...]

    security_signals: tuple[str, ...]
    requires_human: bool
    reason_code: str = Field(min_length=1)


class RetrievedPolicy(BaseModel):
    """
    One accepted policy chunk returned by the retriever.
    """

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    content: str = Field(min_length=1)

    source_file: str = Field(min_length=1)
    title: str = Field(min_length=1)
    section_path: str = Field(min_length=1)

    version: str = Field(min_length=1)
    effective_date: str = Field(min_length=1)
    review_date: str = Field(min_length=1)
    status: Literal["approved"]

    chunk_index: int = Field(ge=0)
    content_hash: str = Field(min_length=1)

    relevance_score: float = Field(ge=0.0, le=1.0)


class GeneratedSupportResponse(BaseModel):
    """
    Structured internal output requested from the local LLM.
    """

    answer: str
    needs_human: bool
    insufficient_policy: bool
    claimed_completed_action: bool


class OutputValidationResult(BaseModel):
    """
    Deterministic validation result for a proposed answer.
    """

    safe: bool
    failure_codes: tuple[str, ...] = ()


class PipelineAnswer(BaseModel):
    """
    Final typed output returned by the Phase 2 pipeline.
    """

    answer: str
    response_mode: ResponseMode

    risk_level: RiskLevel
    requires_human: bool
    retrieval_sufficient: bool

    retrieved_policy_ids: tuple[str, ...]
    retrieved_chunk_ids: tuple[str, ...]

    reason_code: str = Field(min_length=1)