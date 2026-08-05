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
from clients.microsoft_todo_client import MicrosoftTodoClient, set_microsoft_todo_client

from clients.microsoft_auth import MicrosoftTodoAuthenticationService, set_microsoft_auth_service
from core.api.routers import cortex, briefings, market, mcp, microsoft_todo, reminders, system, telemetry, voice
from core.config import ENV_PATH, OLLAMA_ENABLED
from core.agent.local_runtime import check_idle_models_loop
from core import database
from core.mcp import load_mcp_config, set_mcp_manager
from core.mcp.manager import MCPClientManager
from core.runtime_logging import configure_logging

load_dotenv(dotenv_path=ENV_PATH)

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Start background workers on API boot and cancel them on shutdown."""
    configure_logging()
    idle_model_task: asyncio.Task[None] | None = None
    mcp_manager: MCPClientManager | None = None
    microsoft_auth = MicrosoftTodoAuthenticationService()
    microsoft_todo_client = MicrosoftTodoClient(microsoft_auth)
    set_microsoft_auth_service(microsoft_auth)
    set_microsoft_todo_client(microsoft_todo_client)
    database.initialize_db()

    if OLLAMA_ENABLED:
        idle_model_task = asyncio.create_task(check_idle_models_loop())
        _LOGGER.info("Started Ollama idle model monitor")

    mcp_config = load_mcp_config()
    mcp_manager = MCPClientManager(mcp_config)
    set_mcp_manager(mcp_manager)
    await mcp_manager.start()
    if mcp_config.enabled:
        _LOGGER.info("Started MCP client runtime")

    yield

    if mcp_manager is not None:
        await mcp_manager.shutdown()
        set_mcp_manager(None)
        _LOGGER.info("Stopped MCP client runtime")

    await microsoft_auth.shutdown()
    microsoft_todo_client.close()
    set_microsoft_todo_client(None)
    set_microsoft_auth_service(None)

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
app.include_router(cortex.router)
app.include_router(market.router)
app.include_router(mcp.router)
app.include_router(microsoft_todo.router)
app.include_router(telemetry.router)
app.include_router(voice.router)


def main() -> None:
    """Run the API server bound to localhost."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
