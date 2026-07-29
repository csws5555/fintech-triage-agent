"""FastAPI transport contracts and shared-service dependencies."""

from app.api.dependencies import get_app_services, get_chat_service

__all__ = [
    "get_app_services",
    "get_chat_service",
]
