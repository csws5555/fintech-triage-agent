"""Phase 4-facing OpenAPI contract tests for the assembled API."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.api.config import api_settings
from app.main import ServiceBuilder, create_app


APPLICATION_METHODS = {
    "/health/live": {"get"},
    "/health/ready": {"get"},
    f"{api_settings.api_prefix}/chat": {"post"},
    f"{api_settings.api_prefix}/chat/stream": {"post"},
}
PUBLIC_SCHEMAS = {
    "ChatRequest",
    "ChatResponse",
    "ErrorDetail",
    "ErrorResponse",
    "LivenessResponse",
    "ReadinessComponents",
    "ReadinessResponse",
}
CONTROLLED_CHAT_STATUSES = {
    "200",
    "413",
    "415",
    "422",
    "500",
    "503",
    "504",
}
FORBIDDEN_INTERNAL_TERMS = {
    "classificationresult",
    "intentprediction",
    "triagedecision",
    "retrievedpolicy",
    "generatedsupportresponse",
    "outputvalidationresult",
    "pipelineanswer",
    "reason_code",
    "retrieval_sufficient",
    "retrieved_policy_ids",
    "retrieved_chunk_ids",
    "allowed_policy_ids",
    "required_policy_ids",
    "chunk_id",
    "document_id",
    "source_file",
    "content_hash",
    "relevance_score",
    "failure_codes",
    "claimed_completed_action",
    "insufficient_policy",
}


def _forbidden_constructor(name: str) -> Callable[..., object]:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            f"OpenAPI generation must not initialize {name}."
        )

    return fail


def _schema_without_live_services() -> dict[str, object]:
    forbidden = _forbidden_constructor
    builder = ServiceBuilder(
        warm_classifier=forbidden("classifier"),
        classifier=forbidden("classifier inference"),
        inspect_vector_store=forbidden("Chroma or its manifest"),
        build_retriever=forbidden("retriever"),
        build_embeddings=forbidden("embeddings"),
        build_chat_model=forbidden("chat model"),
        build_pipeline=forbidden("pipeline"),
        probe_ollama_models=forbidden("Ollama"),
    )
    return create_app(service_builder=builder).openapi()


def _ref_name(operation: dict[str, object], status: str) -> str:
    responses = operation["responses"]
    assert isinstance(responses, dict)
    response = responses[status]
    assert isinstance(response, dict)
    content = response["content"]
    assert isinstance(content, dict)
    media = content["application/json"]
    assert isinstance(media, dict)
    schema = media["schema"]
    assert isinstance(schema, dict)
    reference = schema["$ref"]
    assert isinstance(reference, str)
    return reference.rsplit("/", maxsplit=1)[-1]


def test_openapi_generation_is_service_free_and_has_exact_paths() -> None:
    schema = _schema_without_live_services()

    assert schema["info"] == {
        "title": "Fintech Triage API",
        "version": "0.1.0",
    }
    paths = schema["paths"]
    assert isinstance(paths, dict)
    assert {
        path: set(operations)
        for path, operations in paths.items()
    } == APPLICATION_METHODS


def test_openapi_exposes_only_strict_public_components() -> None:
    schema = _schema_without_live_services()
    components = schema["components"]
    assert isinstance(components, dict)
    public_schemas = components["schemas"]
    assert isinstance(public_schemas, dict)

    assert set(public_schemas) == PUBLIC_SCHEMAS
    for component in public_schemas.values():
        assert isinstance(component, dict)
        assert component["type"] == "object"
        assert component["additionalProperties"] is False
        assert set(component["required"]) == set(component["properties"])

    assert public_schemas["ChatRequest"]["properties"] == {
        "message": {"title": "Message", "type": "string"}
    }
    assert set(public_schemas["ChatResponse"]["properties"]) == {
        "request_id",
        "answer",
        "status",
        "response_mode",
        "risk_level",
        "requires_human",
    }


def test_openapi_documents_health_and_chat_response_contracts() -> None:
    schema = _schema_without_live_services()
    paths = schema["paths"]
    assert isinstance(paths, dict)

    live = paths["/health/live"]["get"]
    ready = paths["/health/ready"]["get"]
    chat = paths[f"{api_settings.api_prefix}/chat"]["post"]
    stream = paths[f"{api_settings.api_prefix}/chat/stream"]["post"]

    assert set(live["responses"]) == {"200"}
    assert _ref_name(live, "200") == "LivenessResponse"
    assert set(ready["responses"]) == {"200", "503"}
    assert _ref_name(ready, "200") == "ReadinessResponse"
    assert _ref_name(ready, "503") == "ReadinessResponse"

    for operation in (chat, stream):
        assert operation["requestBody"]["required"] is True
        request_schema = operation["requestBody"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        assert request_schema.endswith("/ChatRequest")
        assert set(operation["responses"]) == CONTROLLED_CHAT_STATUSES
        for status in CONTROLLED_CHAT_STATUSES - {"200"}:
            assert _ref_name(operation, status) == "ErrorResponse"

    assert _ref_name(chat, "200") == "ChatResponse"


def test_openapi_documents_validated_sse_media_type_and_events() -> None:
    schema = _schema_without_live_services()
    operation = schema["paths"][
        f"{api_settings.api_prefix}/chat/stream"
    ]["post"]
    success = operation["responses"]["200"]

    assert set(success["content"]) == {"text/event-stream"}
    assert success["content"]["text/event-stream"]["schema"] == {
        "type": "string"
    }
    documentation = (
        f"{operation['description']} {success['description']}".lower()
    )
    assert "text/event-stream" in documentation
    for event_name in ("metadata", "chunk", "done", "error"):
        assert event_name in documentation
    assert "complete answer" in documentation
    assert "approved" in documentation


def test_openapi_contains_no_internal_phase2_schema_or_field() -> None:
    serialized = json.dumps(
        _schema_without_live_services(),
        sort_keys=True,
    ).lower()

    for forbidden in FORBIDDEN_INTERNAL_TERMS:
        assert forbidden not in serialized
