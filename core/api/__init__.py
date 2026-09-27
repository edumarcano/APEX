"""FastAPI application entry points."""

from core.api.app import _app_lifespan, app, get_allowed_origins, main

__all__ = ["_app_lifespan", "app", "get_allowed_origins", "main"]
