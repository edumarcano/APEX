"""Built-in and settings-backed tool profiles for Cortex selection."""

from __future__ import annotations

from core.settings import get_settings_store
from core.settings.models import ToolProfile


def _profile(
    profile_id: str,
    name: str,
    description: str,
    tool_names: tuple[str, ...] = (),
    *,
    dynamic: bool = False,
) -> ToolProfile:
    return ToolProfile(
        id=profile_id,
        name=name,
        description=description,
        tool_names=tool_names,
        built_in=True,
        dynamic=dynamic,
    )


BUILT_IN_TOOL_PROFILES: tuple[ToolProfile, ...] = (
    _profile(
        "no_tools",
        "No Tools",
        "Answer from the conversation and explicitly attached HUD context only.",
    ),
    _profile(
        "all_allowed",
        "All Allowed",
        "Expose every tool currently allowed and available to this Agent.",
        dynamic=True,
    ),
    _profile(
        "personal_ops",
        "Personal Ops",
        "Schedule, mail, reminders, Microsoft To Do, and briefing history.",
        (
            "get_upcoming_calendar_events",
            "get_active_reminders",
            "search_gmail",
            "get_gmail_message",
            "list_microsoft_todo_lists",
            "list_microsoft_todo_tasks",
            "get_briefing_history",
        ),
    ),
    _profile(
        "daily_planning",
        "Daily Planning",
        "Schedule, Microsoft To Do, and weather planning context.",
        (
            "get_upcoming_calendar_events",
            "get_active_reminders",
            "list_microsoft_todo_lists",
            "list_microsoft_todo_tasks",
            "get_weather_forecast",
        ),
    ),
    _profile(
        "research",
        "Research",
        "Public web search and read-only GitHub research tools when connected.",
        (
            "brave_brave_web_search",
            "brave_brave_news_search",
            "github_search_repositories",
            "github_get_file_contents",
            "github_search_code",
            "github_list_issues",
            "github_issue_read",
            "github_list_pull_requests",
            "github_pull_request_read",
        ),
    ),
    _profile(
        "markets",
        "Markets",
        "Alpha Vantage market tools and optional public web search.",
        (
            "alphavantage_symbol_search",
            "alphavantage_global_quote",
            "alphavantage_time_series_daily",
            "alphavantage_company_overview",
            "alphavantage_news_sentiment",
            "brave_brave_web_search",
        ),
    ),
)

_BUILT_IN_BY_ID = {profile.id: profile for profile in BUILT_IN_TOOL_PROFILES}


def _custom_profiles() -> tuple[ToolProfile, ...]:
    try:
        snapshot = get_settings_store().get_snapshot()
        profiles = getattr(snapshot, "tool_profiles", None)
        custom = getattr(profiles, "custom_profiles", ())
        return tuple(profile for profile in custom if isinstance(profile, ToolProfile))
    except Exception:
        return ()


def list_tool_profiles() -> list[ToolProfile]:
    """Return built-ins followed by persisted custom profiles."""
    profiles = list(BUILT_IN_TOOL_PROFILES)
    profiles.extend(
        profile
        for profile in _custom_profiles()
        if profile.id not in _BUILT_IN_BY_ID
    )
    return profiles


def get_tool_profile(profile_id: str | None) -> ToolProfile | None:
    """Resolve a built-in or persisted profile by stable ID."""
    if not profile_id:
        return None
    normalized = profile_id.strip().lower()
    if normalized in _BUILT_IN_BY_ID:
        return _BUILT_IN_BY_ID[normalized]
    return next(
        (profile for profile in _custom_profiles() if profile.id == normalized),
        None,
    )


def default_profile_for_agent(agent_key: str) -> ToolProfile:
    """Return the configured default, preserving cloud/local migration defaults."""
    try:
        snapshot = get_settings_store().get_snapshot()
        defaults = getattr(
            getattr(snapshot, "tool_profiles", None),
            "default_profile_by_agent",
            {},
        )
        configured_id = defaults.get(agent_key) if isinstance(defaults, dict) else None
        configured = get_tool_profile(configured_id)
        if configured is not None:
            return configured
    except Exception:
        pass
    if agent_key in {"sorex", "mus", "apodemus"}:
        return _BUILT_IN_BY_ID["no_tools"]
    return _BUILT_IN_BY_ID["all_allowed"]


def resolve_profile_names(
    agent_key: str,
    profile_id: str,
    *,
    available_names: set[str] | None = None,
) -> list[str]:
    """Return stable names represented by a profile.

    ``All Allowed`` is intentionally dynamic.  Custom and other built-in
    profiles retain explicit names so newly discovered MCP tools do not become
    selected implicitly.
    """
    profile = get_tool_profile(profile_id)
    if profile is None:
        return []
    if profile.dynamic:
        names = sorted(available_names if available_names is not None else ())
    else:
        names = list(profile.tool_names)
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))


def default_profile_names(
    agent_key: str,
    *,
    available_names: set[str] | None = None,
) -> tuple[ToolProfile, list[str]]:
    profile = default_profile_for_agent(agent_key)
    return profile, resolve_profile_names(
        agent_key,
        profile.id,
        available_names=available_names,
    )

