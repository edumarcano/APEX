"""FastAPI application construction, middleware, lifespan, and router registration."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.api.routers import assistant, briefings, market, reminders, system, telemetry, voice
from core.config import ENV_PATH, OLLAMA_ENABLED
from core.agent.providers.ollama_lifecycle import check_idle_models_loop
from core import database
from core.runtime_logging import configure_logging

load_dotenv(dotenv_path=ENV_PATH)

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Start background workers on API boot and cancel them on shutdown."""
    configure_logging()
    idle_model_task: asyncio.Task[None] | None = None
    database.initialize_db()

    if OLLAMA_ENABLED:
        idle_model_task = asyncio.create_task(check_idle_models_loop())
        _LOGGER.info("Started Ollama idle model monitor")

    yield

    if idle_model_task is not None:
        idle_model_task.cancel()
        try:
            await idle_model_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="APEX API", lifespan=_app_lifespan)


DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


def get_allowed_origins() -> list[str]:
    """Return allowed CORS origins from env, or local defaults."""
    configured_origins = os.getenv("APEX_ALLOWED_ORIGINS", "").strip()
    if not configured_origins:
        return list(DEFAULT_ALLOWED_ORIGINS)

    parsed_origins = [
        origin.strip() for origin in configured_origins.split(",")
    ]
    filtered_origins = [origin for origin in parsed_origins if origin]
    return filtered_origins or list(DEFAULT_ALLOWED_ORIGINS)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(briefings.router)
app.include_router(reminders.router)
app.include_router(assistant.router)
app.include_router(market.router)
app.include_router(telemetry.router)
app.include_router(voice.router)


def main() -> None:
    """Run the API server bound to localhost."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
