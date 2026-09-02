"""FastAPI application construction, middleware, lifespan, and router registration."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
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
    CreateMicrosoftTodoTaskExecutor,
    CreateMicrosoftTodoTaskVerifier,
    MicrosoftTodoTaskMutationExecutor,
    MicrosoftTodoTaskMutationVerifier,
)
from core.api.routers import actions, cortex, briefings, market, mcp, microsoft_todo, reminders, system, telemetry, voice
from core.config import DEMO_MODE, ENV_PATH, MAX_RECENT_CONVERSATION_MESSAGES
from core.agent.local_runtime.coordinator import check_idle_local_models_loop
from core.agent.local_runtime.registry import any_local_runtime_enabled
from core.agent.providers.llama_cpp_supervisor import get_llama_cpp_server_supervisor
from core import database, speaker
from core.conversations import ConversationService, ConversationStore, set_conversation_service
from core.runs import RunService, RunStore, set_run_service
from core.knowledge import KnowledgeService, KnowledgeStore, set_knowledge_service
from core.knowledge.capture import ContextCaptureExecutor, ContextCaptureVerifier, CAPABILITY_NAME
from core.knowledge.reconciliation import (
    CAPABILITY_NAME as RECONCILIATION_CAPABILITY_NAME,
    ContextReconciliationExecutor,
    ContextReconciliationVerifier,
)
from core.retrieval import RetrievalService, RetrievalStore, set_retrieval_service
from core.mcp import load_mcp_config, set_mcp_manager
from core.mcp.manager import MCPClientManager
from core.runtime_logging import configure_logging
from core.reminders import ReminderService, set_reminder_service
from core.settings.store import get_settings_store

load_dotenv(dotenv_path=ENV_PATH)

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Start application-owned runtime resources and release them on shutdown."""
    configure_logging()
    idle_model_task: asyncio.Task[None] | None = None
    mcp_manager: MCPClientManager | None = None
    microsoft_auth: MicrosoftTodoAuthenticationService | None = None
    microsoft_todo_client: MicrosoftTodoClient | None = None
    demo_db: sqlite3.Connection | None = None
    if DEMO_MODE:
        demo_db = sqlite3.connect(":memory:", check_same_thread=False)
        demo_db.execute("PRAGMA foreign_keys=ON;")
    conversation_store: ConversationStore | None = None
    run_store: RunStore | None = None
    retrieval_store: RetrievalStore | None = None
    knowledge_store: KnowledgeStore | None = None
    if not DEMO_MODE:
        microsoft_auth = MicrosoftTodoAuthenticationService()
        await microsoft_auth.initialize()
        microsoft_todo_client = MicrosoftTodoClient(microsoft_auth)
        set_microsoft_auth_service(microsoft_auth)
        set_microsoft_todo_client(microsoft_todo_client)
    database.initialize_db(
        include_actions=not DEMO_MODE,
        connection=demo_db if DEMO_MODE else None,
    )
    conversation_store = ConversationStore(
        None if DEMO_MODE else database.DB_NAME,
        connection=demo_db,
    )
    conversation_store.initialize()
    conversation_service = ConversationService(
        conversation_store,
        history_limit=MAX_RECENT_CONVERSATION_MESSAGES,
    )
    if not DEMO_MODE:
        conversation_service.recover_interrupted()
    set_conversation_service(conversation_service)
    run_store = RunStore(
        None if DEMO_MODE else database.DB_NAME,
        connection=demo_db,
    )
    run_store.initialize()
    run_service = RunService(run_store)
    if not DEMO_MODE:
        run_service.recover_interrupted()
    set_run_service(run_service)
    retrieval_store = RetrievalStore(
        None if DEMO_MODE else database.DB_NAME,
        connection=demo_db,
    )
    retrieval_service = RetrievalService(
        retrieval_store,
        conversation_store,
        enabled=not DEMO_MODE,
    )
    try:
        await asyncio.to_thread(retrieval_service.initialize)
    except Exception:
        # Retrieval is optional and repairable; it must never block Cortex readiness.
        pass
    set_retrieval_service(retrieval_service)
    if not DEMO_MODE:
        async def _warm_retrieval() -> None:
            try:
                await asyncio.to_thread(lambda: retrieval_service.prepare(allow_download=False))
            except Exception:
                pass

        asyncio.create_task(_warm_retrieval())
    knowledge_store = KnowledgeStore(
        None if DEMO_MODE else database.DB_NAME,
        connection=demo_db,
    )
    knowledge_store.initialize()
    set_knowledge_service(KnowledgeService(knowledge_store))
    if not DEMO_MODE:
        assert microsoft_todo_client is not None
        action_service = ActionService()
        action_service.register_handler(
            CAPABILITY_NAME,
            executor=ContextCaptureExecutor(knowledge_store, conversation_service),
            verifier=ContextCaptureVerifier(knowledge_store),
        )
        action_service.register_handler(
            RECONCILIATION_CAPABILITY_NAME,
            executor=ContextReconciliationExecutor(knowledge_store),
            verifier=ContextReconciliationVerifier(knowledge_store),
        )
        action_service.register_handler(
            "create_microsoft_todo_task",
            executor=CreateMicrosoftTodoTaskExecutor(microsoft_todo_client),
            verifier=CreateMicrosoftTodoTaskVerifier(microsoft_todo_client),
        )
        for capability_name in (
            "update_microsoft_todo_task",
            "complete_microsoft_todo_task",
            "reopen_microsoft_todo_task",
            "delete_microsoft_todo_task",
        ):
            action_service.register_handler(
                capability_name,
                executor=MicrosoftTodoTaskMutationExecutor(
                    microsoft_todo_client, capability_name
                ),
                verifier=MicrosoftTodoTaskMutationVerifier(
                    microsoft_todo_client, capability_name
                ),
            )
        action_service.recover_interrupted()
        set_action_service(action_service)
        reminder_service = ReminderService(microsoft_todo_client, action_service)
        reminder_service.reconcile()
        set_reminder_service(reminder_service)
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
                        if microsoft_auth is not None:
                            await microsoft_auth.shutdown()
                    finally:
                        try:
                            if microsoft_todo_client is not None:
                                microsoft_todo_client.close()
                        finally:
                            set_microsoft_todo_client(None)
                            set_microsoft_auth_service(None)
                            try:
                                connector_sessions.close()
                            finally:
                                set_connector_http_sessions(None)
                                set_action_service(None)
                                set_reminder_service(None)
                                set_conversation_service(None)
                                set_run_service(None)
                                set_retrieval_service(None)
                                set_knowledge_service(None)
                                if conversation_store is not None:
                                    conversation_store.close()
                                if run_store is not None:
                                    run_store.close()
                                if retrieval_store is not None:
                                    retrieval_store.close()
                                if knowledge_store is not None:
                                    knowledge_store.close()
                                if demo_db is not None:
                                    demo_db.close()
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
