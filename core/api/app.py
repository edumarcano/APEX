"""FastAPI application construction, middleware, lifespan, and router registration."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from core.runtime_paths import initialize_environment

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from clients.microsoft_todo_client import MicrosoftTodoClient, set_microsoft_todo_client
from clients.http_sessions import ConnectorHttpSessions, set_connector_http_sessions

from clients.microsoft_auth import MicrosoftTodoAuthenticationService, set_microsoft_auth_service
from core.actions import ActionService, set_action_service
from core.activity import ActivityService, ActivityStore, set_activity_service
from core.activity.report_folder import (
    ActivityReportFolder,
    run_activity_report_folder_poller,
    set_activity_report_folder,
)
from core.actions.microsoft_todo import (
    CreateMicrosoftTodoTaskExecutor,
    CreateMicrosoftTodoTaskVerifier,
    MicrosoftTodoTaskMutationExecutor,
    MicrosoftTodoTaskMutationVerifier,
)
from core.api.routers import activity, actions, cortex, briefings, market, mcp, microsoft_todo, reminders, system, telemetry, voice
from core.config import (
    CORTEX_CONVERSATIONS_ARCHIVED_RETENTION_DAYS,
    CORTEX_RUNS_MAX_CONCURRENT_RUNS,
    CORTEX_RUNS_SHUTDOWN_DRAIN_SECONDS,
    DEMO_MODE,
    MAX_RECENT_CONVERSATION_MESSAGES,
    APEX_CONTEXT_VAULT_PATH,
)
from core.agent.local_runtime.coordinator import check_idle_local_models_loop
from core.agent.local_runtime.registry import any_local_runtime_enabled
from core.agent.providers.llama_cpp_supervisor import get_llama_cpp_server_supervisor
from core import database, speaker
from core.conversations import ConversationService, ConversationStore, set_conversation_service
from core.conversations.retention import purge_expired_archived_conversations
from core.runs import CortexRunCoordinator, RunService, RunStore, set_run_coordinator, set_run_service
from core.briefings.daily import generate_briefing_generation
from core.briefings.runtime import resolve_briefing_configuration
from core.briefings.service import (
    BriefingService,
    BriefingSessionQueries,
    set_briefing_service,
    set_briefing_session_queries,
)
from core.briefings.speech import BriefingSpeechService, set_briefing_speech_service
from core.briefings.store import BriefingSessionStore
from core.knowledge import KnowledgeService, KnowledgeStore, set_knowledge_service
from core.context_vault.runtime import ContextVaultRuntime, set_context_vault_runtime
from core.knowledge.capture import ContextCaptureExecutor, ContextCaptureVerifier, CAPABILITY_NAME
from core.knowledge.reconciliation import (
    CAPABILITY_NAME as RECONCILIATION_CAPABILITY_NAME,
    ContextReconciliationExecutor,
    ContextReconciliationVerifier,
)
from core.retrieval import RetrievalService, RetrievalStore, set_retrieval_service
from core.retrieval.store import RetrievalSchemaCompatibilityError
from core.mcp import load_mcp_config, set_mcp_manager
from core.mcp.manager import MCPClientManager
from core.runtime_logging import configure_logging
from core.reminders import ReminderService, set_reminder_service
from core.settings.store import get_settings_store
from core.tracing import get_tracing_service

initialize_environment()

_LOGGER = logging.getLogger(__name__)


class _HttpRequestTracker:
    """Track ASGI request tasks through cancellation and response completion."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0

    def enter(self) -> None:
        with self._condition:
            self._active += 1

    def leave(self) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            if self._active == 0:
                self._condition.notify_all()

    @property
    def active(self) -> int:
        with self._condition:
            return self._active


_HTTP_REQUEST_TRACKER = _HttpRequestTracker()


class _HttpRequestTrackingMiddleware:
    """Keep shutdown aware of in-flight HTTP handlers, including sync workers."""

    def __init__(self, app, tracker: _HttpRequestTracker) -> None:
        self.app = app
        self.tracker = tracker

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        self.tracker.enter()
        try:
            await self.app(scope, receive, send)
        finally:
            self.tracker.leave()


def _validate_persistence_before_startup(
    *, connection: sqlite3.Connection | None = None, include_actions: bool
) -> bool:
    """Check core schemas and classify optional retrieval without opening writes."""
    owns_connection = connection is None
    if connection is None:
        db_path = Path(database.DB_NAME)
        # A missing database is a fresh install. Validate it against an empty
        # in-memory connection rather than opening SQLite in create mode.
        if db_path.exists():
            connection = sqlite3.connect(
                f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=30.0
            )
        else:
            connection = sqlite3.connect(":memory:")
    try:
        database.validate_schema(connection, include_actions=include_actions)
        ConversationStore.validate_schema(connection)
        RunStore.validate_schema(connection)
        BriefingSessionStore.validate_schema(connection)
        KnowledgeStore.validate_schema(connection)
        ActivityStore.validate_schema(connection)
        try:
            RetrievalStore.validate_schema(connection)
        except RetrievalSchemaCompatibilityError as exc:
            _LOGGER.error(
                "Unsupported retrieval persistence schema; retrieval is disabled for this run: %s",
                exc,
            )
            return False
        return True
    finally:
        if owns_connection:
            connection.close()


async def _drain_application_tasks(
    tasks: list[asyncio.Task[None]], *, timeout_seconds: float
) -> bool:
    """Wait a bounded interval for application-owned tasks without cancelling work."""
    if not tasks:
        return True

    done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout_seconds))
    if pending:
        _LOGGER.error(
            "Application task shutdown drain timed out after %.2fs; dependencies "
            "must stay open: tasks=%s",
            timeout_seconds,
            [task.get_name() for task in pending],
        )
        return False

    for task in done:
        try:
            task.result()
        except asyncio.CancelledError:
            _LOGGER.warning("Application-owned task was cancelled during shutdown")
        except Exception:
            _LOGGER.exception("Application-owned task failed before shutdown completed")
    return True


def _ensure_host_context(_app: FastAPI):
    """Acquire or validate the exclusive profile lease before startup work."""
    from core.host.identity import create_host_context
    from core.runtime_paths import get_runtime_paths

    context = getattr(_app.state, "host_context", None)
    owns_context = context is None
    if context is None:
        context = create_host_context(
            get_runtime_paths(),
            shutdown_timeout_seconds=(
                int(CORTEX_RUNS_SHUTDOWN_DRAIN_SECONDS) + 5 + 20 + 5
            ),
        )
        _app.state.host_context = context
    if not context.profile_lock.acquired:
        raise RuntimeError("APEX host profile lease is not acquired.")
    expected_root = get_runtime_paths().data_root.resolve(strict=False)
    if context.profile_lock.data_root != expected_root:
        raise RuntimeError("APEX host profile lease does not match the selected data profile.")
    _app.state.lifecycle_entered = True
    _app.state.lifecycle_established = False
    _app.state.lifecycle_cleanup_complete = False
    _app.state.http_request_tracker = _HTTP_REQUEST_TRACKER
    _app.state.http_shutdown_timed_out = False
    return context, owns_context


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Start application-owned resources and release them in dependency order."""
    host_context, owns_host_context = _ensure_host_context(_app)
    idle_model_task: asyncio.Task[None] | None = None
    idle_model_stop: asyncio.Event | None = None
    startup_tasks: list[asyncio.Task[None]] = []
    mcp_manager: MCPClientManager | None = None
    microsoft_auth: MicrosoftTodoAuthenticationService | None = None
    microsoft_todo_client: MicrosoftTodoClient | None = None
    connector_sessions: ConnectorHttpSessions | None = None
    demo_db: sqlite3.Connection | None = None
    demo_db_lock: threading.RLock | None = None
    conversation_store: ConversationStore | None = None
    run_store: RunStore | None = None
    briefing_session_store: BriefingSessionStore | None = None
    briefing_speech_service: BriefingSpeechService | None = None
    run_coordinator: CortexRunCoordinator | None = None
    retrieval_store: RetrievalStore | None = None
    knowledge_store: KnowledgeStore | None = None
    activity_store: ActivityStore | None = None
    activity_report_folder: ActivityReportFolder | None = None
    activity_report_folder_stop: asyncio.Event | None = None
    activity_report_folder_task: asyncio.Task[None] | None = None
    context_vault_runtime: ContextVaultRuntime | None = None
    conversation_retention_stop: asyncio.Event | None = None
    llama_supervisor = None
    lifecycle_error: BaseException | None = None
    retrieval_schema_supported = True

    try:
        configure_logging()
        get_tracing_service().initialize()
        llama_supervisor = get_llama_cpp_server_supervisor()
        if DEMO_MODE:
            demo_db = sqlite3.connect(":memory:", check_same_thread=False)
            demo_db.execute("PRAGMA foreign_keys=ON;")
            demo_db_lock = threading.RLock()
        retrieval_schema_supported = await asyncio.to_thread(
            _validate_persistence_before_startup,
            connection=demo_db,
            include_actions=not DEMO_MODE,
        )
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
            lock=demo_db_lock,
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
            lock=demo_db_lock,
        )
        run_store.initialize()
        run_service = RunService(run_store)
        if not DEMO_MODE:
            run_service.recover_interrupted()
        set_run_service(run_service)
        run_coordinator = CortexRunCoordinator(
            run_service,
            max_workers=CORTEX_RUNS_MAX_CONCURRENT_RUNS,
            completion_sink=getattr(_app.state, "completion_sink", None),
        )
        set_run_coordinator(run_coordinator)
        briefing_session_store = BriefingSessionStore(
            None if DEMO_MODE else database.DB_NAME,
            connection=demo_db,
            lock=demo_db_lock,
        )
        briefing_session_store.initialize()
        set_briefing_session_queries(
            BriefingSessionQueries(
                briefing_session_store,
                partition_getter=conversation_service.partition,
                coordinator=run_coordinator,
            )
        )
        retrieval_store = RetrievalStore(
            None if DEMO_MODE else database.DB_NAME,
            connection=demo_db,
            lock=demo_db_lock,
        )
        retrieval_service = RetrievalService(
            retrieval_store,
            conversation_store,
            enabled=not DEMO_MODE and retrieval_schema_supported,
            initialization_error=(
                None if retrieval_schema_supported else "retrieval_initialization_failed"
            ),
        )
        try:
            await asyncio.to_thread(retrieval_service.initialize)
        except Exception:
            # Retrieval is optional and repairable; it must never block Cortex readiness.
            pass
        set_retrieval_service(retrieval_service)
        if not DEMO_MODE and retrieval_service.enabled:
            async def _warm_retrieval() -> None:
                try:
                    await asyncio.to_thread(
                        lambda: retrieval_service.prepare(allow_download=False)
                    )
                except Exception:
                    _LOGGER.exception("Retrieval warmup failed; continuing with lexical search")

            startup_tasks.append(asyncio.create_task(_warm_retrieval()))
        knowledge_store = KnowledgeStore(
            None if DEMO_MODE else database.DB_NAME,
            connection=demo_db,
            lock=demo_db_lock,
            retrieval_enabled=retrieval_service.enabled,
        )
        knowledge_store.initialize()
        set_knowledge_service(KnowledgeService(knowledge_store))
        activity_store = ActivityStore(
            None if DEMO_MODE else database.DB_NAME,
            connection=demo_db,
            lock=demo_db_lock,
        )
        activity_store.initialize()
        activity_service = ActivityService(
            activity_store,
            demo_mode=DEMO_MODE,
        )
        set_activity_service(activity_service)
        activity_report_folder = ActivityReportFolder(
            activity_service,
            settings_getter=lambda: get_settings_store().get_snapshot().activity_report_folder,
            partition_getter=conversation_service.partition,
            demo_mode=DEMO_MODE,
        )
        set_activity_report_folder(activity_report_folder)
        activity_report_folder_stop = asyncio.Event()
        activity_report_folder_task = asyncio.create_task(
            run_activity_report_folder_poller(activity_report_folder, activity_report_folder_stop),
            name="activity-report-folder-poller",
        )
        if not DEMO_MODE:
            assert microsoft_todo_client is not None
            action_service = ActionService()
            action_service.register_handler(
                CAPABILITY_NAME,
                executor=ContextCaptureExecutor(knowledge_store),
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
        assert briefing_session_store is not None
        assert conversation_store is not None
        assert run_coordinator is not None
        set_briefing_service(
            BriefingService(
                store=briefing_session_store,
                conversations=conversation_store,
                runs=run_service,
                coordinator=run_coordinator,
                partition_getter=conversation_service.partition,
                resolve_configuration=resolve_briefing_configuration,
                execute_generation=generate_briefing_generation,
            )
        )
        briefing_speech_service = BriefingSpeechService(
            briefing_session_store,
            partition_getter=conversation_service.partition,
        )
        set_briefing_speech_service(briefing_speech_service)
        if not DEMO_MODE:
            assert conversation_store is not None
            conversation_retention_stop = asyncio.Event()

            async def _run_conversation_retention() -> None:
                while not conversation_retention_stop.is_set():
                    try:
                        deleted = await purge_expired_archived_conversations(
                            conversation_store,
                            retention_days=CORTEX_CONVERSATIONS_ARCHIVED_RETENTION_DAYS,
                            stop_event=conversation_retention_stop,
                        )
                        if deleted:
                            _LOGGER.info(
                                "Purged %s expired archived Cortex conversations.", deleted
                            )
                    except Exception:
                        # Retention is maintenance work; a failed sweep must not
                        # prevent startup and will be retried after the interval.
                        _LOGGER.exception(
                            "Archived Cortex conversation retention sweep failed"
                        )
                    try:
                        await asyncio.wait_for(
                            conversation_retention_stop.wait(), timeout=24 * 60 * 60
                        )
                    except asyncio.TimeoutError:
                        pass

            startup_tasks.append(
                asyncio.create_task(
                    _run_conversation_retention(),
                    name="cortex-conversation-retention",
                )
            )
        if not DEMO_MODE:
            context_vault_runtime = ContextVaultRuntime(
                knowledge=KnowledgeService(knowledge_store),
                settings_getter=lambda: get_settings_store().get_snapshot().context_vault,
                database_path=database.DB_NAME,
                destination=APEX_CONTEXT_VAULT_PATH,
                production_allowed=lambda: conversation_service.partition() == "production",
            )
            knowledge_store.set_context_vault_change_callback(
                context_vault_runtime.notify_knowledge_change
            )
            set_context_vault_runtime(context_vault_runtime)
            startup_tasks.append(context_vault_runtime.start())
        speaker.initialize()

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

        startup_tasks.append(asyncio.create_task(_managed_llama_startup()))
        if any_local_runtime_enabled():
            idle_model_stop = asyncio.Event()
            idle_model_task = asyncio.create_task(
                check_idle_local_models_loop(idle_model_stop)
            )
            _LOGGER.info("Started local runtime idle model monitor")

        mcp_config = load_mcp_config()
        mcp_manager = MCPClientManager(mcp_config)
        set_mcp_manager(mcp_manager)
        await mcp_manager.start()
        if mcp_config.enabled:
            _LOGGER.info("Started MCP client runtime")

        connector_sessions = ConnectorHttpSessions()
        set_connector_http_sessions(connector_sessions)
        _app.state.lifecycle_established = True
        yield
    except BaseException as exc:
        _app.state.lifecycle_established = False
        lifecycle_error = exc
        raise
    finally:
        _app.state.lifecycle_established = False
        cleanup_error: Exception | None = None

        async def _cleanup(step: str, operation):
            nonlocal cleanup_error
            try:
                result = operation()
                if hasattr(result, "__await__"):
                    return await result
                return result
            except Exception as exc:
                _LOGGER.exception("Error while %s", step)
                cleanup_error = cleanup_error or exc
                return None

        shutdown_deadline = (
            asyncio.get_running_loop().time() + CORTEX_RUNS_SHUTDOWN_DRAIN_SECONDS
        )

        def _remaining_shutdown_seconds() -> float:
            return max(0.0, shutdown_deadline - asyncio.get_running_loop().time())

        if briefing_speech_service is not None:
            await asyncio.to_thread(briefing_speech_service.request_shutdown)
        if run_coordinator is not None:
            try:
                runs_drained = await asyncio.to_thread(
                    run_coordinator.close,
                    timeout_seconds=_remaining_shutdown_seconds(),
                )
            except Exception as exc:
                _LOGGER.exception("Error while draining active Cortex runs")
                raise RuntimeError(
                    "Cortex run shutdown drain failed; application dependencies remain open."
                ) from exc
            if runs_drained is not True:
                raise RuntimeError(
                    "Cortex run shutdown drain timed out; application dependencies remain open."
                )
        if idle_model_stop is not None:
            idle_model_stop.set()
        if activity_report_folder_stop is not None:
            activity_report_folder_stop.set()
        if conversation_retention_stop is not None:
            conversation_retention_stop.set()
        if context_vault_runtime is not None:
            context_vault_runtime.request_stop()
        application_tasks = startup_tasks + (
            [idle_model_task] if idle_model_task is not None else []
        )
        if activity_report_folder_task is not None:
            application_tasks.append(activity_report_folder_task)
        if not await _drain_application_tasks(
            application_tasks,
            timeout_seconds=_remaining_shutdown_seconds(),
        ):
            raise RuntimeError(
                "Application task shutdown drain timed out; dependencies remain open."
            )
        if activity_report_folder is not None and not await activity_report_folder.wait_for_idle(
            _remaining_shutdown_seconds()
        ):
            raise RuntimeError(
                "Activity report folder shutdown drain timed out; dependencies remain open."
            )
        if briefing_speech_service is not None:
            speech_drained = await asyncio.to_thread(
                briefing_speech_service.close,
                timeout_seconds=_remaining_shutdown_seconds(),
            )
            if speech_drained is not True:
                raise RuntimeError(
                    "Briefing speech shutdown drain timed out; application dependencies remain open."
                )
        if _HTTP_REQUEST_TRACKER.active or getattr(
            _app.state, "http_shutdown_timed_out", False
        ):
            raise RuntimeError(
                "HTTP request shutdown drain timed out; application dependencies remain open."
            )
        await _cleanup("stopping speech runtime", speaker.shutdown)
        if mcp_manager is not None:
            await _cleanup("stopping MCP client runtime", mcp_manager.shutdown)
            set_mcp_manager(None)
            _LOGGER.info("Stopped MCP client runtime")
        if llama_supervisor is not None:
            await _cleanup(
                "stopping owned llama.cpp process",
                lambda: asyncio.to_thread(llama_supervisor.shutdown_owned),
            )
        if microsoft_auth is not None:
            await _cleanup("stopping Microsoft authentication", microsoft_auth.shutdown)
        if microsoft_todo_client is not None:
            await _cleanup("closing Microsoft To Do client", microsoft_todo_client.close)
        if connector_sessions is not None:
            await _cleanup("closing connector HTTP sessions", connector_sessions.close)

        set_connector_http_sessions(None)
        set_microsoft_todo_client(None)
        set_microsoft_auth_service(None)
        set_action_service(None)
        set_reminder_service(None)
        set_conversation_service(None)
        set_run_service(None)
        set_run_coordinator(None)
        set_briefing_service(None)
        set_briefing_speech_service(None)
        set_briefing_session_queries(None)
        set_retrieval_service(None)
        set_knowledge_service(None)
        if knowledge_store is not None:
            knowledge_store.set_context_vault_change_callback(None)
        set_context_vault_runtime(None)
        set_activity_service(None)
        set_activity_report_folder(None)
        if conversation_store is not None:
            await _cleanup("closing conversation store", conversation_store.close)
        if briefing_session_store is not None:
            await _cleanup("closing briefing session store", briefing_session_store.close)
        if run_store is not None:
            await _cleanup("closing run store", run_store.close)
        if retrieval_store is not None:
            await _cleanup("closing retrieval store", retrieval_store.close)
        if knowledge_store is not None:
            await _cleanup("closing knowledge store", knowledge_store.close)
        if activity_store is not None:
            await _cleanup("closing activity store", activity_store.close)
        if demo_db is not None:
            await _cleanup("closing demo database", demo_db.close)
        await _cleanup("stopping tracing", get_tracing_service().shutdown)
        if cleanup_error is not None and lifecycle_error is None:
            raise cleanup_error
        _app.state.lifecycle_cleanup_complete = cleanup_error is None
        if cleanup_error is None and owns_host_context:
            host_context.release()
            _app.state.host_context = None


app = FastAPI(title="APEX API", lifespan=_app_lifespan)
app.add_middleware(_HttpRequestTrackingMiddleware, tracker=_HTTP_REQUEST_TRACKER)


DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://tauri.localhost",
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
app.include_router(activity.router)
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
    """Run the standalone API through the lifecycle-owning host."""
    from core.backend_host import main as host_main

    raise SystemExit(host_main(["serve", "--standalone"]))


if __name__ == "__main__":
    main()
