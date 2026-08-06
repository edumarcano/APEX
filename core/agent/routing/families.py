"""Central capability-family taxonomy for smart tool routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityFamilyDefinition:
    key: str
    label: str
    description: str
    semantic_examples: tuple[str, ...]
    local_command_enabled: bool
    local_auto_enabled: bool
    cloud_auto_enabled: bool
    tool_priority: tuple[str, ...] = ()


CAPABILITY_FAMILIES: tuple[CapabilityFamilyDefinition, ...] = (
    CapabilityFamilyDefinition(
        key="schedule",
        label="Schedule",
        description=(
            "Calendar events, upcoming meetings, and active APEX reminders."
        ),
        semantic_examples=(
            "What is on my calendar tomorrow?",
            "Do I have any meetings this afternoon?",
            "Show pending reminders I have not cleared yet.",
            "When is my dentist appointment?",
            "Am I free on Friday evening?",
            "List events coming up in the next two weeks.",
            "What did I ask APEX to remind me about?",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=("get_upcoming_calendar_events", "get_active_reminders"),
    ),
    CapabilityFamilyDefinition(
        key="weather",
        label="Weather",
        description="Multi-day weather forecast for the configured location.",
        semantic_examples=(
            "What is the weather forecast this week?",
            "Will it rain tomorrow?",
            "How warm will it get on Saturday?",
            "Give me a five-day outlook.",
            "Is it going to be windy tonight?",
            "Do I need an umbrella for the commute?",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=("get_weather_forecast",),
    ),
    CapabilityFamilyDefinition(
        key="f1",
        label="Formula 1",
        description="Formula 1 driver standings and season race calendar.",
        semantic_examples=(
            "Who leads the F1 championship?",
            "Show the current driver standings.",
            "When is the next Grand Prix?",
            "What races are left this season?",
            "How many points does Verstappen have?",
            "List the remaining races on the calendar.",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=("get_f1_driver_standings", "get_f1_season_calendar"),
    ),
    CapabilityFamilyDefinition(
        key="mail",
        label="Mail",
        description="Search and read Gmail messages.",
        semantic_examples=(
            "Find emails from Sarah about the budget.",
            "Search my inbox for unread travel confirmations.",
            "Open that message.",
            "Show the latest note my manager sent.",
            "Look for receipts from last month.",
            "Read the email with the contract attachment reference.",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=("search_gmail", "get_gmail_message"),
    ),
    CapabilityFamilyDefinition(
        key="search",
        label="Web Search",
        description="Public web and news search through Brave.",
        semantic_examples=(
            "Search the web for recent Mars rover updates.",
            "What are journalists saying about the new policy?",
            "Look up the official documentation for this API.",
            "Find current news about the product launch.",
            "Who won the game last night?",
            "Search for reviews of the latest phone.",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=("brave_brave_web_search", "brave_brave_news_search"),
    ),
    CapabilityFamilyDefinition(
        key="market",
        label="Market",
        description=(
            "Stock quotes, symbol lookup, price history, company overview, "
            "and market news."
        ),
        semantic_examples=(
            "What is Apple's stock price right now?",
            "Look up the ticker for Microsoft.",
            "Show me Tesla's recent daily prices.",
            "Give me an overview of NVIDIA.",
            "What is the market saying about energy stocks?",
            "Find news sentiment for AMZN.",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=(
            "alphavantage_global_quote",
            "alphavantage_symbol_search",
            "alphavantage_time_series_daily",
            "alphavantage_company_overview",
            "alphavantage_news_sentiment",
        ),
    ),
    CapabilityFamilyDefinition(
        key="briefings",
        label="Briefings",
        description="Persisted APEX briefing history and digests.",
        semantic_examples=(
            "What did my last briefing cover?",
            "Show recent APEX briefings.",
            "Summarize the morning digest from earlier this week.",
            "What topics appeared in yesterday's briefing?",
            "Pull up the last few briefing records.",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=("get_briefing_history",),
    ),
    CapabilityFamilyDefinition(
        key="todo",
        label="Microsoft To Do",
        description="Read-only Microsoft To Do lists and tasks.",
        semantic_examples=(
            "What is on my Microsoft To Do list?",
            "Show tasks in my work list.",
            "List incomplete items from To Do.",
            "What did I leave open in Microsoft tasks?",
            "Show completed and open tasks for groceries.",
        ),
        local_command_enabled=True,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=("list_microsoft_todo_lists", "list_microsoft_todo_tasks"),
    ),
    CapabilityFamilyDefinition(
        key="github",
        label="GitHub",
        description=(
            "Read-only GitHub repository, issue, pull request, and code search."
        ),
        semantic_examples=(
            "List open issues in the APEX repository.",
            "Show recent pull requests for this repo.",
            "Search code for the routing service implementation.",
            "Read the README from the main branch.",
            "Find repositories about semantic search.",
            "What is the status of PR 42?",
        ),
        local_command_enabled=False,
        local_auto_enabled=False,
        cloud_auto_enabled=True,
        tool_priority=(
            "github_search_repositories",
            "github_list_issues",
            "github_issue_read",
            "github_list_pull_requests",
            "github_pull_request_read",
            "github_search_code",
            "github_get_file_contents",
        ),
    ),
    CapabilityFamilyDefinition(
        key="none",
        label="No Tool",
        description=(
            "Requests answerable from conversation, general knowledge, "
            "explanation, rewriting, or arithmetic without live APEX data."
        ),
        semantic_examples=(
            "Explain how gradient descent works.",
            "Rewrite this paragraph more concisely.",
            "What is 17 times 23?",
            "Thanks, that helps.",
            "Summarize what we already discussed.",
            "Translate this sentence to Spanish.",
            "Why did the author choose that metaphor?",
            "Help me brainstorm names for a project.",
        ),
        local_command_enabled=False,
        local_auto_enabled=True,
        cloud_auto_enabled=True,
        tool_priority=(),
    ),
)

_FAMILIES_BY_KEY = {family.key: family for family in CAPABILITY_FAMILIES}

ROUTING_FAMILY_KEYS: frozenset[str] = frozenset(_FAMILIES_BY_KEY)


def get_family(key: str) -> CapabilityFamilyDefinition | None:
    """Return the family definition for *key*, or ``None`` if unknown."""
    return _FAMILIES_BY_KEY.get(key)


def is_known_routing_family(key: str | None) -> bool:
    """Return whether *key* is a registered routing family (excluding pseudo-none)."""
    return key is not None and key in _FAMILIES_BY_KEY and key != "none"
