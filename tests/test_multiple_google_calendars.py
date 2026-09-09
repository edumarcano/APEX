"""Focused regression coverage for selected Google Calendar behavior."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from fastapi import HTTPException
from clients.calendar_client import fetch_selected_calendar_events, list_readable_calendars
from core.api.routers.system import get_google_calendar_choices
from core.connectors.collect import collect_calendar
from core.settings import CalendarSettings, FeaturesSettings, ModulesSettings, SettingsPatch
from core.settings.models import CalendarPatch, RuntimeSettingsSnapshot
from core.settings.normalize import apply_patch_to_snapshot
from core.telemetry.collector import collect_connector_results


class _Request:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def execute(self) -> dict:
        return self.payload


class _CalendarList:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = iter(pages)
        self.calls: list[dict[str, object]] = []

    def list(self, **kwargs: object) -> _Request:
        self.calls.append(kwargs)
        return _Request(next(self.pages))


class _Events:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.pages = {
            calendar_id: iter(response)
            for calendar_id, response in responses.items()
            if isinstance(response, list)
        }
        self.calls: list[dict[str, object]] = []

    def list(self, *, calendarId: str, **kwargs: object) -> _Request:
        self.calls.append({"calendarId": calendarId, **kwargs})
        response = next(self.pages[calendarId]) if calendarId in self.pages else self.responses[calendarId]
        if isinstance(response, Exception):
            raise response
        return _Request(response)  # type: ignore[arg-type]


class _Service:
    def __init__(self, calendar_pages: list[dict], events: dict[str, object]) -> None:
        self._calendar_list = _CalendarList(calendar_pages)
        self._events = _Events(events)

    def calendarList(self) -> _CalendarList:
        return self._calendar_list

    def events(self) -> _Events:
        return self._events


class MultipleGoogleCalendarsTests(unittest.TestCase):
    def test_discovery_filters_unreadable_entries_and_sorts_primary_first(self) -> None:
        service = _Service([
            {"items": [
                {"id": "team", "summary": " Team\nCalendar ", "hidden": True},
                {"id": "freebusy", "summary": "Nope", "accessRole": "freeBusyReader"},
            ], "nextPageToken": "page-2"},
            {"items": [
                {"id": "owner@example.com", "summary": "Personal", "primary": True},
                {"id": "deleted", "summary": "Old", "deleted": True},
            ]},
        ], {})

        result = list_readable_calendars(service)

        self.assertEqual(result["calendars"], [
            {"id": "primary", "display_name": "Personal", "primary": True, "hidden": False},
            {"id": "team", "display_name": "Team Calendar", "primary": False, "hidden": True},
        ])
        self.assertFalse(result["truncated"])
        self.assertEqual(service.calendarList().calls[0]["showHidden"], True)

    def test_selected_fetch_merges_successes_and_keeps_partial_failure_evidence(self) -> None:
        service = _Service(
            [{"items": [{"id": "owner@example.com", "summary": "Personal", "primary": True}, {"id": "team", "summary": "Team"}]}],
            {
                "primary": {"items": [{"summary": "Later", "start": {"dateTime": "2030-01-02T10:00:00Z"}, "end": {"dateTime": "2030-01-02T11:00:00Z"}}]},
                "team": {"items": [{"summary": "Earlier", "start": {"dateTime": "2030-01-01T10:00:00Z"}, "end": {"dateTime": "2030-01-01T11:00:00Z"}}]},
                "missing": RuntimeError("not available"),
            },
        )

        result = fetch_selected_calendar_events(service, calendar_ids=("primary", "team", "missing"), days=14)

        self.assertEqual(result.selected_calendar_count, 3)
        self.assertEqual((result.successful_calendar_count, result.failed_calendar_count), (2, 1))
        self.assertEqual([event["summary"] for event in result.events], ["Earlier", "Later"])
        self.assertEqual([event["calendar_name"] for event in result.events], ["Team", "Personal"])

    def test_discovery_bounds_filtered_pages_and_reports_truncation(self) -> None:
        service = _Service(
            [
                {
                    "items": [{"id": "freebusy", "accessRole": "freeBusyReader"}],
                    "nextPageToken": f"page-{index}",
                }
                for index in range(10)
            ],
            {},
        )

        result = list_readable_calendars(service)

        self.assertEqual(result["calendars"], [])
        self.assertTrue(result["truncated"])
        self.assertEqual(len(service.calendarList().calls), 10)

    def test_selected_fetch_bounds_malformed_event_pages_and_reports_truncation(self) -> None:
        service = _Service(
            [{"items": [{"id": "owner@example.com", "summary": "Personal", "primary": True}]}],
            {
                "primary": [
                    {"items": [{"summary": "Malformed event"}], "nextPageToken": f"page-{index}"}
                    for index in range(10)
                ],
            },
        )

        result = fetch_selected_calendar_events(service, calendar_ids=("primary",))

        self.assertEqual(result.events, [])
        self.assertEqual((result.successful_calendar_count, result.failed_calendar_count), (1, 0))
        self.assertTrue(result.truncated)
        self.assertEqual(len(service.events().calls), 10)

    def test_collect_empty_selection_is_explicitly_unavailable(self) -> None:
        result = collect_calendar(settings=CalendarSettings(selected_calendar_ids=()))
        self.assertEqual((result.status, result.reason_code), ("unavailable", "no_calendars_selected"))
        self.assertEqual(result.data["selected_calendar_count"], 0)

    def test_selected_fetch_omits_attribution_when_disabled(self) -> None:
        service = _Service(
            [{"items": [{"id": "primary", "summary": "Personal", "primary": True}]}],
            {"primary": {"items": [{"summary": "Private", "start": {"dateTime": "2030-01-01T10:00:00Z"}}]}},
        )

        result = fetch_selected_calendar_events(service, calendar_ids=("primary",), show_calendar_names=False)

        self.assertNotIn("calendar_name", result.events[0])

    def test_explicit_empty_selection_remains_empty_when_applied(self) -> None:
        snapshot = apply_patch_to_snapshot(
            RuntimeSettingsSnapshot(),
            SettingsPatch(calendar=CalendarPatch(selected_calendar_ids=[], show_calendar_names=False)),
        )
        self.assertEqual(snapshot.calendar.selected_calendar_ids, ())
        self.assertFalse(snapshot.calendar.show_calendar_names)

    def test_all_failed_selected_calendars_are_unavailable(self) -> None:
        settings = CalendarSettings(selected_calendar_ids=("primary",))
        with mock.patch("core.connectors.collect.google_auth.get_service", return_value=object()), mock.patch(
            "core.connectors.collect.calendar_client.fetch_selected_calendar_events",
            return_value=mock.Mock(events=[], selected_calendar_count=1, successful_calendar_count=0, failed_calendar_count=1),
        ):
            result = collect_calendar(settings=settings, now=datetime.now(timezone.utc))
        self.assertEqual((result.status, result.reason_code), ("unavailable", "connection_error"))

    def test_telemetry_passes_selected_calendar_settings_to_collection(self) -> None:
        selected = CalendarSettings(selected_calendar_ids=("primary", "team"))
        calendar_result = mock.Mock(name="calendar")
        with mock.patch("core.telemetry.collector.collect_calendar", return_value=calendar_result) as collect:
            results = collect_connector_results(
                features=FeaturesSettings(calendar=True),
                modules=ModulesSettings(),
                calendar=selected,
                connectors=["calendar"],
            )
        collect.assert_called_once_with(settings=selected)
        self.assertIs(results["calendar"], calendar_result)

    def test_discovery_route_hides_provider_failure_details(self) -> None:
        with mock.patch("clients.google_auth.get_service", side_effect=RuntimeError("private provider detail")):
            with self.assertRaises(HTTPException) as raised:
                get_google_calendar_choices()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Google Calendar is unavailable.")
