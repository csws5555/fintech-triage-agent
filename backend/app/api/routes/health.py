"""Cheap, typed operational health endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_app_services
from app.api.models import (
    LivenessResponse,
    ReadinessComponents,
    ReadinessResponse,
)
from app.api.services import AppServices, ServiceReadiness


router = APIRouter(prefix="/health", tags=["health"])


def _component_status(ready: bool) -> str:
    return "ready" if ready else "unavailable"


def _public_readiness(snapshot: ServiceReadiness) -> ReadinessResponse:
    return ReadinessResponse(
        status="ready" if snapshot.ready else "degraded",
        components=ReadinessComponents(
            configuration=_component_status(snapshot.configuration),
            classifier=_component_status(snapshot.classifier),
            pipeline=_component_status(snapshot.pipeline),
            vector_store=_component_status(snapshot.vector_store),
            ollama_chat_model=_component_status(
                snapshot.ollama_chat_model
            ),
            ollama_embedding_model=_component_status(
                snapshot.ollama_embedding_model
            ),
        ),
    )


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Report only whether the API process is serving requests."""

    return LivenessResponse(
        status="alive",
        service="fintech-triage-api",
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ReadinessResponse | JSONResponse:
    """Return the synchronized safe component-availability snapshot."""

    snapshot = await services.check_readiness()
    response = _public_readiness(snapshot)
    if response.status == "ready":
        return response
    return JSONResponse(
        status_code=503,
        content=response.model_dump(mode="json"),
    )


__all__ = ["liveness", "readiness", "router"]
