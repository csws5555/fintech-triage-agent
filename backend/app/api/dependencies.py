"""Typed FastAPI dependencies for shared application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.services import ApiChatService, AppServices


def get_app_services(request: Request) -> AppServices:
    """Return the one service container initialized by application lifespan."""

    services = getattr(request.app.state, "services", None)
    if not isinstance(services, AppServices):
        raise RuntimeError("Application services are unavailable.")
    if services.chat_service.shutdown_started:
        raise RuntimeError("Application services are unavailable.")
    return services


def get_chat_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ApiChatService:
    """Return the shared bounded chat execution service."""

    return services.chat_service


__all__ = [
    "get_app_services",
    "get_chat_service",
]
