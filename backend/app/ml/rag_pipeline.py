"""Synchronous safety-first orchestration for Phase 2 support answers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.ml.grounding_prompt import build_grounding_prompt
from app.ml.output_validator import (
    OutputValidator,
    output_validator as default_output_validator,
)
from app.ml.rag_config import (
    RagSettings,
    settings,
    validate_rag_settings,
)
from app.ml.response_templates import (
    account_operation_limitation_response,
    atm_retained_card_response,
    card_delivery_clarification,
    classifier_uncertainty_clarification,
    compromised_card_response,
    critical_account_access_response,
    hypothetical_stolen_card_response,
    insufficient_policy_response,
    internal_information_response,
    international_fee_clarification,
    login_problem_clarification,
    minimum_stolen_card_response,
    negated_security_incident_response,
    pin_or_passcode_clarification,
    replacement_card_guidance,
    unrecognized_transaction_response,
    unrecognized_withdrawal_response,
    unsupported_policy_response,
    unverified_action_status_response,
)
from app.ml.retriever import get_retriever
from app.ml.risk_router import (
    RiskRouter,
    risk_router as default_risk_router,
)
from app.ml.structured_generation import (
    StructuredGenerationResult,
    generate_structured_response,
)
from app.ml.triage_types import (
    ClassificationResult,
    GeneratedSupportResponse,
    OutputValidationResult,
    PipelineAnswer,
    RetrievedPolicy,
    TriageDecision,
)


ROUTING_FAILED = "routing_failed"
UNMAPPED_STATIC_RESPONSE = "unmapped_static_response"
RETRIEVAL_FAILED = "retrieval_failed"
RETRIEVAL_INSUFFICIENT = "retrieval_insufficient"
URGENT_RETRIEVAL_FAILED = "urgent_retrieval_failed"
URGENT_RETRIEVAL_INSUFFICIENT = (
    "urgent_retrieval_insufficient"
)
GROUNDING_PROMPT_FAILED = "grounding_prompt_failed"
STRUCTURED_GENERATION_INVALID = (
    "structured_generation_invalid"
)
OUTPUT_VALIDATION_FAILED = "output_validation_failed"


class _RiskRouter(Protocol):
    def route_message(
        self,
        message: str,
        classification: ClassificationResult,
    ) -> TriageDecision: ...


class _Retriever(Protocol):
    def retrieve(
        self,
        *,
        query: str,
        allowed_policy_ids: tuple[str, ...],
        required_policy_ids: tuple[str, ...] = (),
    ) -> tuple[RetrievedPolicy, ...]: ...

    def retrieval_is_sufficient(
        self,
        policies: Sequence[RetrievedPolicy],
        decision: TriageDecision,
    ) -> bool: ...


class _OutputValidator(Protocol):
    def validate(
        self,
        generated: object,
        *,
        decision: object,
        policies: object = (),
    ) -> OutputValidationResult: ...


class FintechRagPipeline:
    """Coordinate routing, retrieval, generation, and validation."""

    def __init__(
        self,
        *,
        risk_router: _RiskRouter = default_risk_router,
        retriever: _Retriever | None = None,
        llm: object | None = None,
        output_validator: _OutputValidator = (
            default_output_validator
        ),
        runtime_settings: RagSettings = settings,
    ) -> None:
        if not isinstance(runtime_settings, RagSettings):
            raise TypeError(
                "runtime_settings must be a RagSettings instance."
            )

        validate_rag_settings(runtime_settings)
        _require_method(
            risk_router,
            "route_message",
            component_name="risk_router",
        )

        if retriever is not None:
            _require_method(
                retriever,
                "retrieve",
                component_name="retriever",
            )
            _require_method(
                retriever,
                "retrieval_is_sufficient",
                component_name="retriever",
            )

        _require_method(
            output_validator,
            "validate",
            component_name="output_validator",
        )

        self._risk_router = risk_router
        self._retriever = retriever
        self._llm = llm
        self._output_validator = output_validator
        self._settings = runtime_settings

    def answer(
        self,
        *,
        query: str,
        classification: ClassificationResult,
    ) -> PipelineAnswer:
        """Return one fully buffered deterministic or validated answer."""

        normalized_query = self._validate_and_normalize_query(
            query
        )
        validated_classification = _validate_classification(
            classification
        )
        decision = self._route(
            normalized_query,
            validated_classification,
        )

        if decision is None:
            return _pipeline_answer(
                answer=critical_account_access_response(),
                response_mode="deterministic_safety",
                risk_level="critical",
                requires_human=True,
                retrieval_sufficient=False,
                policies=(),
                reason_code=ROUTING_FAILED,
            )

        if decision.action == "human_escalation":
            return _pipeline_answer(
                answer=critical_account_access_response(),
                response_mode="deterministic_safety",
                risk_level=decision.risk_level,
                requires_human=True,
                retrieval_sufficient=False,
                policies=(),
                reason_code=decision.reason_code,
            )

        if decision.action == "static_response":
            return self._static_response(decision)

        if decision.action == "unsupported":
            return _pipeline_answer(
                answer=unsupported_policy_response(),
                response_mode="static_fallback",
                risk_level=decision.risk_level,
                requires_human=True,
                retrieval_sufficient=False,
                policies=(),
                reason_code=decision.reason_code,
            )

        if decision.action == "clarify":
            return self._clarification_response(decision)

        policies, sufficient, retrieval_failed = self._retrieve(
            query=normalized_query,
            decision=decision,
        )

        if decision.action == "urgent_guidance":
            if sufficient:
                return _pipeline_answer(
                    answer=_detailed_urgent_response(decision),
                    response_mode="deterministic_safety",
                    risk_level=decision.risk_level,
                    requires_human=decision.requires_human,
                    retrieval_sufficient=True,
                    policies=policies,
                    reason_code=decision.reason_code,
                )

            return _pipeline_answer(
                answer=_minimum_urgent_response(decision),
                response_mode="deterministic_safety",
                risk_level=decision.risk_level,
                requires_human=True,
                retrieval_sufficient=False,
                policies=policies,
                reason_code=(
                    URGENT_RETRIEVAL_FAILED
                    if retrieval_failed
                    else URGENT_RETRIEVAL_INSUFFICIENT
                ),
            )

        if decision.action != "generate":
            return _pipeline_answer(
                answer=critical_account_access_response(),
                response_mode="deterministic_safety",
                risk_level="critical",
                requires_human=True,
                retrieval_sufficient=False,
                policies=(),
                reason_code=ROUTING_FAILED,
            )

        if not sufficient:
            return _pipeline_answer(
                answer=insufficient_policy_response(),
                response_mode="static_fallback",
                risk_level=decision.risk_level,
                requires_human=True,
                retrieval_sufficient=False,
                policies=policies,
                reason_code=(
                    RETRIEVAL_FAILED
                    if retrieval_failed
                    else RETRIEVAL_INSUFFICIENT
                ),
            )

        return self._generate_answer(
            query=normalized_query,
            decision=decision,
            policies=policies,
        )

    def _route(
        self,
        query: str,
        classification: ClassificationResult,
    ) -> TriageDecision | None:
        try:
            decision = self._risk_router.route_message(
                query,
                classification,
            )
            return _validate_decision(decision)
        except Exception:
            return None

    def _retrieve(
        self,
        *,
        query: str,
        decision: TriageDecision,
    ) -> tuple[tuple[RetrievedPolicy, ...], bool, bool]:
        try:
            retriever = (
                get_retriever()
                if self._retriever is None
                else self._retriever
            )
            policies = retriever.retrieve(
                query=query,
                allowed_policy_ids=(
                    decision.allowed_policy_ids
                ),
                required_policy_ids=(
                    decision.required_policy_ids
                ),
            )

            if (
                not isinstance(policies, Sequence)
                or isinstance(policies, (str, bytes))
                or any(
                    not isinstance(policy, RetrievedPolicy)
                    for policy in policies
                )
            ):
                return (), False, True

            accepted = tuple(policies)
            sufficient = retriever.retrieval_is_sufficient(
                accepted,
                decision,
            )

            if not isinstance(sufficient, bool):
                return accepted, False, True

            if sufficient and not accepted:
                return accepted, False, True

            return accepted, sufficient, False
        except Exception:
            return (), False, True

    def _generate_answer(
        self,
        *,
        query: str,
        decision: TriageDecision,
        policies: tuple[RetrievedPolicy, ...],
    ) -> PipelineAnswer:
        try:
            messages = build_grounding_prompt(
                query,
                decision,
                policies,
                runtime_settings=self._settings,
            )
        except Exception:
            return self._generation_fallback(
                decision=decision,
                policies=policies,
                reason_code=GROUNDING_PROMPT_FAILED,
            )

        try:
            generation = generate_structured_response(
                messages,
                chat_model=self._llm,
            )
        except Exception:
            return self._generation_fallback(
                decision=decision,
                policies=policies,
                reason_code=STRUCTURED_GENERATION_INVALID,
            )

        if not _generation_result_is_valid(generation):
            return self._generation_fallback(
                decision=decision,
                policies=policies,
                reason_code=STRUCTURED_GENERATION_INVALID,
            )

        if generation.used_fallback:
            return self._generation_fallback(
                decision=decision,
                policies=policies,
                reason_code=generation.failure_codes[0],
            )

        generated = generation.response

        try:
            validation = self._output_validator.validate(
                generated,
                decision=decision,
                policies=policies,
            )
        except Exception:
            validation = None

        if not _validation_result_is_safe(validation):
            return self._generation_fallback(
                decision=decision,
                policies=policies,
                reason_code=OUTPUT_VALIDATION_FAILED,
            )

        return _pipeline_answer(
            answer=generated.answer,
            response_mode="grounded_generation",
            risk_level=decision.risk_level,
            requires_human=(
                decision.requires_human
                or generated.needs_human
            ),
            retrieval_sufficient=True,
            policies=policies,
            reason_code=decision.reason_code,
        )

    @staticmethod
    def _generation_fallback(
        *,
        decision: TriageDecision,
        policies: tuple[RetrievedPolicy, ...],
        reason_code: str,
    ) -> PipelineAnswer:
        return _pipeline_answer(
            answer=insufficient_policy_response(),
            response_mode="static_fallback",
            risk_level=decision.risk_level,
            requires_human=True,
            retrieval_sufficient=True,
            policies=policies,
            reason_code=reason_code,
        )

    @staticmethod
    def _static_response(
        decision: TriageDecision,
    ) -> PipelineAnswer:
        templates = {
            "hypothetical_card_security_guidance": (
                hypothetical_stolen_card_response
            ),
            "negated_security_incident": (
                negated_security_incident_response
            ),
            "internal_information_request": (
                internal_information_response
            ),
            "unverified_action_status_request": (
                unverified_action_status_response
            ),
            "account_operation_request": (
                account_operation_limitation_response
            ),
        }
        template = templates.get(decision.reason_code)

        if template is None:
            return _pipeline_answer(
                answer=unsupported_policy_response(),
                response_mode="static_fallback",
                risk_level=decision.risk_level,
                requires_human=True,
                retrieval_sufficient=False,
                policies=(),
                reason_code=UNMAPPED_STATIC_RESPONSE,
            )

        return _pipeline_answer(
            answer=template(),
            response_mode="deterministic_safety",
            risk_level=decision.risk_level,
            requires_human=decision.requires_human,
            retrieval_sufficient=False,
            policies=(),
            reason_code=decision.reason_code,
        )

    @staticmethod
    def _clarification_response(
        decision: TriageDecision,
    ) -> PipelineAnswer:
        templates = {
            "international_fee_type_ambiguous": (
                international_fee_clarification
            ),
            "pin_or_passcode_ambiguous": (
                pin_or_passcode_clarification
            ),
            "card_delivery_type_ambiguous": (
                card_delivery_clarification
            ),
            "account_access_issue_ambiguous": (
                login_problem_clarification
            ),
            "classifier_uncertain": (
                classifier_uncertainty_clarification
            ),
        }
        template = templates.get(
            decision.reason_code,
            classifier_uncertainty_clarification,
        )
        return _pipeline_answer(
            answer=template(),
            response_mode="deterministic_clarification",
            risk_level=decision.risk_level,
            requires_human=decision.requires_human,
            retrieval_sufficient=False,
            policies=(),
            reason_code=decision.reason_code,
        )

    def _validate_and_normalize_query(
        self,
        query: object,
    ) -> str:
        if not isinstance(query, str):
            raise TypeError("query must be a string.")

        normalized = query.strip()

        if not normalized:
            raise ValueError("query cannot be blank.")

        if (
            len(normalized)
            > self._settings.max_customer_message_length
        ):
            raise ValueError(
                "query exceeds the configured message limit."
            )

        return normalized


def _require_method(
    component: object,
    method_name: str,
    *,
    component_name: str,
) -> None:
    if not callable(getattr(component, method_name, None)):
        raise TypeError(
            f"{component_name} must provide {method_name}()."
        )


def _validate_classification(
    classification: object,
) -> ClassificationResult:
    if not isinstance(classification, ClassificationResult):
        raise TypeError(
            "classification must be a ClassificationResult."
        )

    try:
        validated = ClassificationResult.model_validate(
            classification.model_dump(mode="python")
        )
    except Exception as exc:
        raise ValueError("classification is malformed.") from exc

    return validated


def _validate_decision(
    decision: object,
) -> TriageDecision | None:
    if not isinstance(decision, TriageDecision):
        return None

    try:
        return TriageDecision.model_validate(
            decision.model_dump(mode="python")
        )
    except Exception:
        return None


def _generation_result_is_valid(
    result: object,
) -> bool:
    if not isinstance(result, StructuredGenerationResult):
        return False

    if (
        not isinstance(result.response, GeneratedSupportResponse)
        or not isinstance(result.response.answer, str)
        or not isinstance(result.response.needs_human, bool)
        or not isinstance(
            result.response.insufficient_policy,
            bool,
        )
        or not isinstance(
            result.response.claimed_completed_action,
            bool,
        )
        or not isinstance(result.used_fallback, bool)
        or not isinstance(result.failure_codes, tuple)
        or any(
            not isinstance(code, str) or not code.strip()
            for code in result.failure_codes
        )
    ):
        return False

    return (
        (result.used_fallback and bool(result.failure_codes))
        or (
            not result.used_fallback
            and not result.failure_codes
        )
    )


def _validation_result_is_safe(
    result: object,
) -> bool:
    return (
        isinstance(result, OutputValidationResult)
        and isinstance(result.safe, bool)
        and isinstance(result.failure_codes, tuple)
        and result.safe
        and not result.failure_codes
    )


def _detailed_urgent_response(
    decision: TriageDecision,
) -> str:
    signals = frozenset(decision.security_signals)

    if (
        "atm_retained_card" in signals
        or decision.reason_code == "atm_retained_card"
    ):
        return atm_retained_card_response(
            requires_human=decision.requires_human
        )

    if "unknown_withdrawal" in signals:
        return unrecognized_withdrawal_response(
            requires_human=decision.requires_human
        )

    if "unknown_transaction" in signals:
        return unrecognized_transaction_response(
            requires_human=decision.requires_human
        )

    if "compromised_card" in signals:
        return compromised_card_response(
            requires_human=decision.requires_human
        )

    return replacement_card_guidance(
        requires_human=decision.requires_human
    )


def _minimum_urgent_response(
    decision: TriageDecision,
) -> str:
    if (
        "atm_retained_card" in decision.security_signals
        or decision.reason_code == "atm_retained_card"
    ):
        return atm_retained_card_response(requires_human=True)

    return minimum_stolen_card_response(requires_human=True)


def _pipeline_answer(
    *,
    answer: str,
    response_mode: str,
    risk_level: str,
    requires_human: bool,
    retrieval_sufficient: bool,
    policies: Sequence[RetrievedPolicy],
    reason_code: str,
) -> PipelineAnswer:
    policy_ids = tuple(
        dict.fromkeys(
            policy.document_id
            for policy in policies
        )
    )
    chunk_ids = tuple(
        dict.fromkeys(
            policy.chunk_id
            for policy in policies
        )
    )
    return PipelineAnswer(
        answer=answer,
        response_mode=response_mode,
        risk_level=risk_level,
        requires_human=requires_human,
        retrieval_sufficient=retrieval_sufficient,
        retrieved_policy_ids=policy_ids,
        retrieved_chunk_ids=chunk_ids,
        reason_code=reason_code,
    )


rag_pipeline = FintechRagPipeline()


__all__ = [
    "FintechRagPipeline",
    "GROUNDING_PROMPT_FAILED",
    "OUTPUT_VALIDATION_FAILED",
    "RETRIEVAL_FAILED",
    "RETRIEVAL_INSUFFICIENT",
    "ROUTING_FAILED",
    "STRUCTURED_GENERATION_INVALID",
    "UNMAPPED_STATIC_RESPONSE",
    "URGENT_RETRIEVAL_FAILED",
    "URGENT_RETRIEVAL_INSUFFICIENT",
    "rag_pipeline",
]
