import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, NoReturn

from clients.sports_client import fetch_f1_driver_standings, fetch_f1_season_calendar
from clients.weather_client import fetch_weather_forecast
from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    register_capability,
)

_LOGGER = logging.getLogger(__name__)

_NATIVE_TIMEOUT_SECONDS = 30.0
_NATIVE_MAX_OUTPUT_CHARS = 50_000
_GMAIL_SEARCH_MAX_RESULTS = 20
_MICROSOFT_TODO_MAX_RESULTS = 50
_GMAIL_OUTPUT_MAX_CHARS = 50_000


def get_current_date_time() -> dict[str, str]:
    """Return the host's timezone-aware current local date and time."""
    now = datetime.now().astimezone()
    return {
        "date_time": now.isoformat(),
        "time_zone": now.tzname() or "local",
    }


def _stable_tool_result(
    result: dict[str, Any],
    *,
    tool_name: str,
    failure_message: str,
) -> dict[str, Any]:
    """Replace provider exception details with a stable Agent-tool error."""
    if "error" not in result:
        return result
    _LOGGER.warning("Agent tool unavailable: tool=%s", tool_name)
    return {"error": failure_message}


def get_weather_forecast(days: int = 5) -> dict[str, Any]:
    """Retrieve a multi-day weather forecast for the configured target location.

    Groups OpenWeatherMap 3-hour forecast entries into daily high/low
    temperature and condition summaries.

    Args:
        days: Number of forecast days to return. Values below 1 are raised to
            1; values above 5 are lowered to 5.

    Returns:
        dict: A payload with ``location`` and ``forecast`` (list of daily
            records containing ``date``, ``temp_max``, ``temp_min``, and
            ``condition``), or an ``error`` key on failure.
    """
    clamped_days = max(1, min(5, days))
    return _stable_tool_result(
        fetch_weather_forecast(clamped_days),
        tool_name="get_weather_forecast",
        failure_message="Weather forecast unavailable.",
    )


def get_f1_driver_standings() -> dict[str, Any]:
    """Retrieve current Formula 1 driver championship standings.

    Fetches the latest driver points table from the Ergast F1 API for the
    active season. No parameters are required.

    Returns:
        dict: A payload with ``season``, ``round``, and ``standings`` (list of
            driver records with ``position``, ``points``, ``wins``,
            ``driver_name``, ``driver_code``, and ``team``), or an ``error``
            key on failure.
    """
    return _stable_tool_result(
        fetch_f1_driver_standings(),
        tool_name="get_f1_driver_standings",
        failure_message="F1 standings unavailable.",
    )


def get_f1_season_calendar() -> dict[str, Any]:
    """Retrieve the full Formula 1 race calendar for the current season.

    Fetches all scheduled races from the Ergast F1 API for the active season.
    No parameters are required.

    Returns:
        dict: A payload with ``season`` and ``calendar`` (list of race records
            with ``round``, ``raceName``, ``circuitName``, ``country``,
            ``date``, and ``time``), or an ``error`` key on failure.
    """
    return _stable_tool_result(
        fetch_f1_season_calendar(),
        tool_name="get_f1_season_calendar",
        failure_message="F1 calendar unavailable.",
    )


def get_upcoming_calendar_events(days: int = 14) -> dict[str, Any]:
    """Retrieve upcoming Google Calendar events for Agent requests.

    Queries the operator's primary Google Calendar for scheduled events within
    a configurable forward-looking window independent of the HUD's seven-day
    telemetry horizon.

    Args:
        days: Number of days into the future to query. Must be between 1 and
            14 inclusive. Values outside this range are clamped. Defaults to 14.

    Returns:
        dict: On success, a payload with ``days_queried`` (int) and ``events``
            (list of dicts, each containing ``summary`` and ``start``). On
            authentication failure, ``{"error": "Calendar authentication failed
            or Google Workspace service is offline."}``. On other failures,
            ``{"error": "Calendar data unavailable."}``.
    """
    days = max(1, min(14, days))
    try:
        from clients.google_auth import get_service

        service = get_service("calendar", "v3")
        if not service:
            return {
                "error": (
                    "Calendar authentication failed or Google Workspace "
                    "service is offline."
                )
            }
    except Exception:
        return {
            "error": (
                "Calendar authentication failed or Google Workspace "
                "service is offline."
            )
        }

    try:
        from clients.calendar_client import (
            get_upcoming_calendar_events as fetch_events,
        )

        events = fetch_events(service, days=days)
        return {"days_queried": days, "events": events}
    except Exception as exc:
        _LOGGER.warning(
            "Agent tool unavailable: tool=get_upcoming_calendar_events error_type=%s",
            type(exc).__name__,
        )
        return {"error": "Calendar data unavailable."}


def _gmail_service() -> Any:
    from google.auth.exceptions import GoogleAuthError

    try:
        from clients.google_auth import get_service

        service = get_service("gmail", "v1")
    except (FileNotFoundError, GoogleAuthError) as exc:
        raise CapabilityError(
            CapabilityErrorCategory.AUTHENTICATION,
            "Gmail authentication is required.",
        ) from exc
    except Exception as exc:
        _LOGGER.warning(
            "Agent tool unavailable: tool=gmail error_type=%s",
            type(exc).__name__,
        )
        raise CapabilityError(
            CapabilityErrorCategory.UNAVAILABLE,
            "Gmail service is unavailable.",
        ) from exc
    if not service:
        raise CapabilityError(
            CapabilityErrorCategory.AUTHENTICATION,
            "Gmail authentication is required.",
        )
    return service


def _raise_gmail_capability_error(exc: Exception) -> NoReturn:
    from clients.gmail_client import (
        GmailAuthenticationRequiredError,
        GmailInsufficientScopeError,
    )

    error_category = CapabilityErrorCategory.AUTHENTICATION
    if isinstance(exc, GmailAuthenticationRequiredError):
        message = "Gmail authentication is required."
    elif isinstance(exc, GmailInsufficientScopeError):
        message = "Gmail read permission is required."
    else:
        error_category = CapabilityErrorCategory.UPSTREAM_FAILURE
        message = "Gmail data is unavailable."
        _LOGGER.warning(
            "Agent tool unavailable: tool=gmail error_type=%s",
            type(exc).__name__,
        )
    raise CapabilityError(
        error_category,
        message,
    ) from exc


def _invoke_gmail(
    operation: Callable[..., dict[str, Any]],
    /,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return operation(_gmail_service(), *args, **kwargs)
    except CapabilityError:
        raise
    except Exception as exc:
        _raise_gmail_capability_error(exc)


def search_gmail(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search Gmail without changing any messages.

    Args:
        query: Gmail search expression, such as ``from:example.com is:unread``.
        max_results: Maximum number of results to return, clamped to 1–20.

    Returns:
        A bounded list of message identifiers, thread identifiers, sender,
        subject, date, labels, and snippets.
    """
    from clients.gmail_client import search_gmail as fetch_messages

    query = query.strip()
    if not query:
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            "Gmail search query cannot be empty.",
        )
    return _invoke_gmail(
        fetch_messages,
        query,
        max_results=max(1, min(_GMAIL_SEARCH_MAX_RESULTS, max_results)),
    )


def get_gmail_message(message_id: str) -> dict[str, Any]:
    """Retrieve one Gmail message as bounded, sanitized plain text.

    Attachments, embedded resources, active HTML, and raw MIME data are never
    returned.
    """
    from clients.gmail_client import get_gmail_message as fetch_message

    message_id = message_id.strip()
    if not message_id:
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            "Gmail message identifier cannot be empty.",
        )
    return _invoke_gmail(fetch_message, message_id)


def _raise_microsoft_todo_capability_error(exc: Exception) -> NoReturn:
    from clients.microsoft_auth import (
        MicrosoftTodoAuthenticationRequiredError,
        MicrosoftTodoNotConfiguredError,
    )
    from clients.microsoft_todo_client import (
        MicrosoftTodoInvalidInputError,
        MicrosoftTodoUpstreamError,
    )

    if isinstance(exc, MicrosoftTodoAuthenticationRequiredError):
        category = CapabilityErrorCategory.AUTHENTICATION
        message = str(exc)
    elif isinstance(exc, MicrosoftTodoNotConfiguredError):
        category = CapabilityErrorCategory.UNAVAILABLE
        message = "Microsoft To Do is not configured."
    elif isinstance(exc, MicrosoftTodoInvalidInputError):
        category = CapabilityErrorCategory.INVALID_INPUT
        message = str(exc)
    elif isinstance(exc, TimeoutError):
        category = CapabilityErrorCategory.TIMEOUT
        message = "Microsoft To Do request timed out."
    elif isinstance(exc, MicrosoftTodoUpstreamError):
        category = CapabilityErrorCategory.UPSTREAM_FAILURE
        message = "Microsoft To Do data is unavailable."
    else:
        category = CapabilityErrorCategory.UNAVAILABLE
        message = "Microsoft To Do is unavailable."
    if category not in {
        CapabilityErrorCategory.AUTHENTICATION,
        CapabilityErrorCategory.INVALID_INPUT,
    }:
        _LOGGER.warning(
            "Agent tool unavailable: tool=microsoft_todo error_type=%s",
            type(exc).__name__,
        )
    raise CapabilityError(category, message) from exc


def _invoke_microsoft_todo(
    operation: Callable[..., Any], /, *args: Any, **kwargs: Any
) -> Any:
    try:
        return operation(*args, **kwargs)
    except CapabilityError:
        raise
    except Exception as exc:
        _raise_microsoft_todo_capability_error(exc)


def list_microsoft_todo_lists() -> dict[str, Any]:
    """List Microsoft To Do lists without modifying remote data."""
    from clients.microsoft_todo_client import get_microsoft_todo_client

    return _invoke_microsoft_todo(lambda: get_microsoft_todo_client().list_task_lists()).to_dict()


def list_microsoft_todo_tasks(
    list_id: str,
    include_completed: bool = False,
    max_results: int = 20,
) -> dict[str, Any]:
    """Read bounded tasks from one Microsoft To Do list."""
    from clients.microsoft_todo_client import get_microsoft_todo_client

    return _invoke_microsoft_todo(
        lambda: get_microsoft_todo_client().list_tasks(
            list_id,
            include_completed=include_completed,
            max_results=max(1, min(_MICROSOFT_TODO_MAX_RESULTS, max_results)),
        )
    ).to_dict()


def get_active_reminders() -> list[dict[str, Any]]:
    """Retrieve all pending (unread) reminders from the APEX task ledger.

    Returns every active reminder stored in the local SQLite database where
    ``is_read = 0``. Enables the agent to perform semantic search,
    categorization, keyword clustering, and priority grouping over outstanding
    operator tasks without mirroring on-screen HUD state.

    Returns:
        list[dict]: A list of reminder records, each containing ``id`` (int)
            and ``note`` (str). Returns an empty list on failure or when no
            unread reminders exist.
    """
    try:
        from core import database

        records = database.fetch_unread_reminders()
        return [{"id": row_id, "note": note} for row_id, note in records]
    except Exception:
        return []


def get_briefing_history(limit: int = 5) -> dict[str, Any]:
    """Retrieve recent APEX briefing digests for episodic memory queries.

    Fetches structured historical briefing records from the SQLite ledger,
    allowing the agent to perform temporal comparative analysis across past
    runs. Only essential metadata fields are returned to preserve the model's
    token context window.

    Args:
        limit: Maximum number of historical briefing records to retrieve.
            Must be between 1 and 5 inclusive. Values outside this range are
            clamped. Defaults to 5.

    Returns:
        dict: On success with records, ``{"limit_requested": limit,
            "briefings": [<records>]}`` where each record contains ``id``,
            ``timestamp``, ``briefing``, and ``insights`` (list). When no
            records exist, ``{"message": "No briefings have been recorded in
            the system ledger yet."}``. On failure, returns the stable message
            ``{"error": "Briefing history unavailable."}``.
    """
    limit = max(1, min(5, limit))
    try:
        from core import database

        rows = database.fetch_briefing_history(limit=limit)
        if not rows:
            return {
                "message": (
                    "No briefings have been recorded in the system ledger yet."
                )
            }

        briefings: list[dict[str, Any]] = []
        for record in rows:
            digest = record.get("digest", {})
            briefings.append(
                {
                    "id": record["id"],
                    "timestamp": record["timestamp"],
                    "briefing": record["briefing"],
                    "insights": digest.get("insights", []),
                }
            )
        return {"limit_requested": limit, "briefings": briefings}
    except Exception as exc:
        _LOGGER.warning(
            "Agent tool unavailable: tool=get_briefing_history error_type=%s",
            type(exc).__name__,
        )
        return {"error": "Briefing history unavailable."}


def register_native_capabilities() -> None:
    """Register the built-in read-only Agent capabilities when absent."""
    from core.agent import capabilities as capabilities_module

    # Direct registry probe avoids re-entering ensure while registering.
    if "get_weather_forecast" in capabilities_module._REGISTRY._entries:
        return

    native_common = {
        "origin": "native",
        "risk": "read",
        "expose_to_agent": True,
        "expose_to_mcp_server": False,
        "expose_to_client_display": True,
        "timeout_seconds": _NATIVE_TIMEOUT_SECONDS,
        "max_output_chars": _NATIVE_MAX_OUTPUT_CHARS,
    }

    register_capability(
        CapabilityDescriptor(
            name="get_current_date_time",
            title="Current Date and Time",
            description="Return the host's timezone-aware current local date and time.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            **native_common,
        ),
        get_current_date_time,
    )
    register_capability(
        CapabilityDescriptor(
            name="get_weather_forecast",
            title="Weather Forecast",
            description=(
                "Retrieve a multi-day weather forecast for the configured "
                "target location."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": (
                            "Number of forecast days to return. Values below 1 "
                            "are raised to 1; values above 5 are lowered to 5."
                        ),
                        "minimum": 1,
                        "maximum": 5,
                        "default": 5,
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            **native_common,
        ),
        get_weather_forecast,
    )
    register_capability(
        CapabilityDescriptor(
            name="get_f1_driver_standings",
            title="F1 Driver Standings",
            description=(
                "Retrieve current Formula 1 driver championship standings."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            **native_common,
        ),
        get_f1_driver_standings,
    )
    register_capability(
        CapabilityDescriptor(
            name="get_f1_season_calendar",
            title="F1 Season Calendar",
            description=(
                "Retrieve the full Formula 1 race calendar for the current season."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            **native_common,
        ),
        get_f1_season_calendar,
    )
    register_capability(
        CapabilityDescriptor(
            name="get_upcoming_calendar_events",
            title="Upcoming Calendar Events",
            description=(
                "Retrieve upcoming Google Calendar events for Agent requests."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": (
                            "Number of days into the future to query. Must be "
                            "between 1 and 14 inclusive. Values outside this "
                            "range are clamped. Defaults to 14."
                        ),
                        "minimum": 1,
                        "maximum": 14,
                        "default": 14,
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            **native_common,
        ),
        get_upcoming_calendar_events,
    )
    register_capability(
        CapabilityDescriptor(
            name="get_active_reminders",
            title="Active Reminders",
            description=(
                "Retrieve all pending (unread) reminders from the APEX task ledger."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            **native_common,
        ),
        get_active_reminders,
    )
    register_capability(
        CapabilityDescriptor(
            name="get_briefing_history",
            title="Briefing History",
            description=(
                "Retrieve recent APEX briefing digests for episodic memory queries."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of historical briefing records to "
                            "retrieve. Must be between 1 and 5 inclusive. Values "
                            "outside this range are clamped. Defaults to 5."
                        ),
                        "minimum": 1,
                        "maximum": 5,
                        "default": 5,
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            **native_common,
        ),
        get_briefing_history,
    )
    register_capability(
        CapabilityDescriptor(
            name="search_gmail",
            title="Search Gmail",
            description=(
                "Search the operator's Gmail mailbox with Gmail query syntax. "
                "Returns bounded read-only message metadata and snippets; it "
                "cannot modify email."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Gmail search expression, such as "
                            "'from:example.com is:unread'."
                        ),
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum messages to return, between 1 and 20. "
                            "Defaults to 10."
                        ),
                        "minimum": 1,
                        "maximum": _GMAIL_SEARCH_MAX_RESULTS,
                        "default": 10,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            **{
                **native_common,
                "max_output_chars": _GMAIL_OUTPUT_MAX_CHARS,
            },
        ),
        search_gmail,
    )
    register_capability(
        CapabilityDescriptor(
            name="get_gmail_message",
            title="Read Gmail Message",
            description=(
                "Read one Gmail message selected by message identifier. "
                "Returns bounded sanitized plain text without attachments, "
                "embedded resources, active HTML, or raw MIME data."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": (
                            "Gmail message identifier returned by search_gmail."
                        ),
                        "minLength": 1,
                        "maxLength": 256,
                    }
                },
                "required": ["message_id"],
                "additionalProperties": False,
            },
            **{
                **native_common,
                "max_output_chars": _GMAIL_OUTPUT_MAX_CHARS,
            },
        ),
        get_gmail_message,
    )

    register_capability(
        CapabilityDescriptor(
            name="list_microsoft_todo_lists",
            title="Microsoft To Do Lists",
            description=(
                "List the operator's Microsoft To Do lists using delegated "
                "read-only access. It cannot modify tasks or APEX reminders."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            **native_common,
        ),
        list_microsoft_todo_lists,
    )
    register_capability(
        CapabilityDescriptor(
            name="list_microsoft_todo_tasks",
            title="Microsoft To Do Tasks",
            description=(
                "Read tasks from one Microsoft To Do list selected by its "
                "identifier. It cannot create, update, complete, or delete tasks."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "list_id": {
                        "type": "string",
                        "description": (
                            "Opaque list identifier returned by "
                            "list_microsoft_todo_lists."
                        ),
                        "minLength": 1,
                        "maxLength": 512,
                    },
                    "include_completed": {
                        "type": "boolean",
                        "description": "Whether completed tasks should be included.",
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum tasks to return, between 1 and 50.",
                        "minimum": 1,
                        "maximum": _MICROSOFT_TODO_MAX_RESULTS,
                        "default": 20,
                    },
                },
                "required": ["list_id"],
                "additionalProperties": False,
            },
            **native_common,
        ),
        list_microsoft_todo_tasks,
    )


register_native_capabilities()
