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
from clients.http_sessions import ConnectorHttpSessions, set_connector_http_sessions

from clients.microsoft_auth import MicrosoftTodoAuthenticationService, set_microsoft_auth_service
from core.actions import ActionService, set_action_service
from core.actions.microsoft_todo import (
    CompleteMicrosoftTodoTaskExecutor,
    CompleteMicrosoftTodoTaskVerifier,
    CreateMicrosoftTodoTaskExecutor,
    CreateMicrosoftTodoTaskVerifier,
    DeleteMicrosoftTodoTaskExecutor,
    DeleteMicrosoftTodoTaskVerifier,
    ReopenMicrosoftTodoTaskExecutor,
    ReopenMicrosoftTodoTaskVerifier,
    UpdateMicrosoftTodoTaskExecutor,
    UpdateMicrosoftTodoTaskVerifier,
)
from core.api.routers import actions, cortex, briefings, market, mcp, microsoft_todo, reminders, system, telemetry, voice
from core.config import ENV_PATH
from core.config import DEMO_MODE
from core.agent.local_runtime.coordinator import check_idle_local_models_loop
from core.agent.local_runtime.registry import any_local_runtime_enabled
from core.agent.providers.llama_cpp_supervisor import get_llama_cpp_server_supervisor
from core import database, speaker
from core.mcp import load_mcp_config, set_mcp_manager
from core.mcp.manager import MCPClientManager
from core.runtime_logging import configure_logging
from core.settings.store import get_settings_store

load_dotenv(dotenv_path=ENV_PATH)

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Start application-owned runtime resources and release them on shutdown."""
    configure_logging()
    idle_model_task: asyncio.Task[None] | None = None
    mcp_manager: MCPClientManager | None = None
    microsoft_auth = MicrosoftTodoAuthenticationService()
    await microsoft_auth.initialize()
    microsoft_todo_client = MicrosoftTodoClient(microsoft_auth)
    set_microsoft_auth_service(microsoft_auth)
    set_microsoft_todo_client(microsoft_todo_client)
    database.initialize_db()
    if not DEMO_MODE:
        action_service = ActionService()
        action_service.register_handler(
            "create_microsoft_todo_task",
            executor=CreateMicrosoftTodoTaskExecutor(microsoft_todo_client),
            verifier=CreateMicrosoftTodoTaskVerifier(microsoft_todo_client),
        )
        for capability_name, executor, verifier in (
            ("update_microsoft_todo_task", UpdateMicrosoftTodoTaskExecutor, UpdateMicrosoftTodoTaskVerifier),
            ("complete_microsoft_todo_task", CompleteMicrosoftTodoTaskExecutor, CompleteMicrosoftTodoTaskVerifier),
            ("reopen_microsoft_todo_task", ReopenMicrosoftTodoTaskExecutor, ReopenMicrosoftTodoTaskVerifier),
            ("delete_microsoft_todo_task", DeleteMicrosoftTodoTaskExecutor, DeleteMicrosoftTodoTaskVerifier),
        ):
            action_service.register_handler(
                capability_name,
                executor=executor(microsoft_todo_client),
                verifier=verifier(microsoft_todo_client),
            )
        action_service.recover_interrupted()
        set_action_service(action_service)
    get_settings_store()
    speaker.initialize()

    llama_supervisor = get_llama_cpp_server_supervisor()

    async def _managed_llama_startup() -> None:
        try:
            await asyncio.to_thread(
                lambda: llama_supervisor.ensure_ready(allow_restart=False)
            )
        except Exception:
            _LOGGER.exception(
                "Managed llama.cpp startup failed; continuing APEX boot without local "
                "llama.cpp Agents"
            )

    asyncio.create_task(_managed_llama_startup())

    if any_local_runtime_enabled():
        idle_model_task = asyncio.create_task(check_idle_local_models_loop())
        _LOGGER.info("Started local runtime idle model monitor")

    mcp_config = load_mcp_config()
    mcp_manager = MCPClientManager(mcp_config)
    set_mcp_manager(mcp_manager)
    await mcp_manager.start()
    if mcp_config.enabled:
        _LOGGER.info("Started MCP client runtime")

    connector_sessions = ConnectorHttpSessions()
    set_connector_http_sessions(connector_sessions)
    try:
        yield
    finally:
        try:
            speaker.shutdown()
        finally:
            try:
                if mcp_manager is not None:
                    try:
                        await mcp_manager.shutdown()
                    finally:
                        set_mcp_manager(None)
                        _LOGGER.info("Stopped MCP client runtime")
            finally:
                try:
                    try:
                        await asyncio.to_thread(llama_supervisor.shutdown_owned)
                    except Exception:
                        _LOGGER.exception("Error while stopping owned llama.cpp process")
                finally:
                    try:
                        await microsoft_auth.shutdown()
                    finally:
                        try:
                            microsoft_todo_client.close()
                        finally:
                            set_microsoft_todo_client(None)
                            set_microsoft_auth_service(None)
                            try:
                                connector_sessions.close()
                            finally:
                                set_connector_http_sessions(None)
                                set_action_service(None)
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
app.include_router(actions.router)
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
