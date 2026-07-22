"""Synchronous connector collection for telemetry snapshots."""

from __future__ import annotations

import logging

from clients import news_client, sports_client, weather_client
from core.connectors.collect import collect_calendar, collect_email, collect_reminders
from core.connectors.models import CONNECTOR_NAMES, ConnectorResult, utc_now_iso
from core.settings import FeaturesSettings, ModulesSettings

_LOGGER = logging.getLogger(__name__)


def is_connector_enabled(
    name: str,
    *,
    features: FeaturesSettings,
    modules: ModulesSettings,
) -> bool:
    """Return whether a connector is enabled in the current runtime settings."""
    if name == "weather":
        return features.weather
    if name == "news":
        return features.news
    if name == "email":
        return features.email
    if name == "calendar":
        return features.calendar
    if name == "f1":
        return features.sports and modules.f1
    if name == "football":
        return features.sports and modules.football
    if name == "reminders":
        return True
    raise ValueError(f"Unknown connector name: {name!r}")


def enabled_connector_names(
    *,
    features: FeaturesSettings,
    modules: ModulesSettings,
) -> set[str]:
    """Return enabled connector names for a runtime settings snapshot."""
    return {
        name
        for name in CONNECTOR_NAMES
        if is_connector_enabled(name, features=features, modules=modules)
    }


def disabled_result(name: str) -> ConnectorResult:
    """Return an explicit disabled module result."""
    return ConnectorResult(
        name=name,
        status="disabled",
        freshness="none",
        reason_code="disabled",
        observed_at=utc_now_iso(),
        display_text="",
        data={},
    )


def empty_results() -> dict[str, ConnectorResult]:
    """Return a full module map of disabled stubs."""
    return {name: disabled_result(name) for name in CONNECTOR_NAMES}


def collect_connector_results(
    *,
    features: FeaturesSettings,
    modules: ModulesSettings,
    connectors: list[str] | None = None,
) -> dict[str, ConnectorResult]:
    """
    Collect enabled connectors synchronously.

    When ``connectors`` is provided, only those names are collected; others are
    omitted from the returned map (caller merges into an existing snapshot).
    Disabled connectors are returned with an explicit disabled state when they
    are in the collection set.
    """
    target = set(connectors) if connectors else set(CONNECTOR_NAMES)
    unknown = target - set(CONNECTOR_NAMES)
    if unknown:
        raise ValueError(f"Unknown connector names: {sorted(unknown)}")

    results: dict[str, ConnectorResult] = {}

    def _wanted(name: str) -> bool:
        return name in target

    if _wanted("weather"):
        if is_connector_enabled("weather", features=features, modules=modules):
            results["weather"] = weather_client.collect_weather()
        else:
            _LOGGER.info("Weather module bypassed via user preference")
            results["weather"] = disabled_result("weather")

    if _wanted("f1"):
        if is_connector_enabled("f1", features=features, modules=modules):
            results["f1"] = sports_client.collect_f1()
        else:
            if features.sports and not modules.f1:
                _LOGGER.info("F1 module bypassed via user preference")
            elif not features.sports:
                _LOGGER.info("Sports module bypassed via user preference")
            results["f1"] = disabled_result("f1")

    if _wanted("football"):
        if is_connector_enabled("football", features=features, modules=modules):
            results["football"] = sports_client.collect_football()
        else:
            if features.sports and not modules.football:
                _LOGGER.info("Football module bypassed via user preference")
            results["football"] = disabled_result("football")

    if _wanted("news"):
        if is_connector_enabled("news", features=features, modules=modules):
            results["news"] = news_client.collect_news()
        else:
            _LOGGER.info("News module bypassed via user preference")
            results["news"] = disabled_result("news")

    if _wanted("email"):
        if is_connector_enabled("email", features=features, modules=modules):
            results["email"] = collect_email()
        else:
            _LOGGER.info("Email module bypassed via user preference")
            results["email"] = disabled_result("email")

    if _wanted("calendar"):
        if is_connector_enabled("calendar", features=features, modules=modules):
            results["calendar"] = collect_calendar()
        else:
            _LOGGER.info("Calendar module bypassed via user preference")
            results["calendar"] = disabled_result("calendar")

    if _wanted("reminders"):
        # Reminders remain a local DB read and are always collected when requested.
        results["reminders"] = collect_reminders()

    return results
