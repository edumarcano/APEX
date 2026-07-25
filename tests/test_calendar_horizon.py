"""Regression coverage for the seven-day calendar telemetry contract."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from clients import calendar_client
from core.agent import tools as agent_tools
from core.connectors import collect


class _CalendarRequest:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def execute(self) -> dict[str, object]:
        return self._payload


class _CalendarEvents:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls: list[dict[str, object]] = []

    def list(self, **kwargs: object) -> _CalendarRequest:
        self.calls.append(kwargs)
        return _CalendarRequest(self._payload)


class _CalendarService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.resource = _CalendarEvents(payload)

    def events(self) -> _CalendarEvents:
        return self.resource


def _event(
    summary: str,
    start: str,
    *,
    end: str | None = None,
    all_day: bool = False,
) -> dict[str, object]:
    return {
        "summary": summary,
        "start": start,
        "end": end,
        "all_day": all_day,
        "time_zone": "UTC",
    }


class CalendarClientTests(unittest.TestCase):
    def test_fetches_once_for_seven_days_and_normalizes_events(self) -> None:
        service = _CalendarService(
            {
                "timeZone": "America/New_York",
                "items": [
                    {
                        "summary": "Timed",
                        "start": {"dateTime": "2026-07-25T09:30:00"},
                        "end": {"dateTime": "2026-07-25T10:00:00"},
                    },
                    {
                        "summary": "All day",
                        "start": {"date": "2026-07-26"},
                        "end": {"date": "2026-07-27"},
                    },
                ],
            }
        )

        with mock.patch.object(calendar_client, "is_dev_mode", return_value=False):
            events = calendar_client.get_upcoming_calendar_events(service)

        self.assertEqual(len(service.resource.calls), 1)
        call = service.resource.calls[0]
        time_min = datetime.fromisoformat(str(call["timeMin"]))
        time_max = datetime.fromisoformat(str(call["timeMax"]))
        self.assertEqual(time_max - time_min, timedelta(days=7))
        self.assertTrue(call["singleEvents"])
        self.assertEqual(call["orderBy"], "startTime")
        self.assertEqual(
            events,
            [
                {
                    "summary": "Timed",
                    "start": "2026-07-25T09:30:00-04:00",
                    "end": "2026-07-25T10:00:00-04:00",
                    "all_day": False,
                    "time_zone": "America/New_York",
                },
                {
                    "summary": "All day",
                    "start": "2026-07-26",
                    "end": "2026-07-27",
                    "all_day": True,
                    "time_zone": "America/New_York",
                },
            ],
        )

    def test_dev_mode_preserves_masking_with_normalized_shape(self) -> None:
        service = _CalendarService(
            {
                "items": [
                    {
                        "summary": "Private title",
                        "start": {"dateTime": "2026-07-25T09:30:00Z"},
                    }
                ]
            }
        )

        with mock.patch.object(calendar_client, "is_dev_mode", return_value=True):
            events = calendar_client.get_upcoming_calendar_events(service)

        self.assertEqual(len(events), 1)
        self.assertIn("[HIDDEN]", events[0]["summary"])
        self.assertNotIn("Private title", str(events))
        self.assertEqual(events[0]["all_day"], False)
        self.assertIsNone(events[0]["end"])


class CalendarTelemetryTests(unittest.TestCase):
    def test_uses_half_open_48_hour_boundary(self) -> None:
        now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
        data = collect._calendar_data(
            [
                _event("At start", now.isoformat()),
                _event("Inside", (now + timedelta(hours=47, minutes=59)).isoformat()),
                _event("At boundary", (now + timedelta(hours=48)).isoformat()),
                _event("Later", (now + timedelta(days=6)).isoformat()),
            ],
            now=now,
        )

        self.assertEqual(data["window_days"], 7)
        self.assertEqual(data["display_window_hours"], 48)
        self.assertEqual(data["total_count"], 4)
        self.assertEqual(data["display_count"], 2)
        self.assertEqual(data["overflow_count"], 2)
        self.assertEqual(
            [event["summary"] for event in data["display_events"]],
            ["At start", "Inside"],
        )

    def test_excludes_events_already_in_progress_from_future_counts(self) -> None:
        now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
        ongoing_timed = _event(
            "Ongoing meeting",
            (now - timedelta(hours=1)).isoformat(),
            end=(now + timedelta(hours=1)).isoformat(),
        )
        ongoing_all_day = _event(
            "Today off-site",
            "2026-07-24",
            end="2026-07-25",
            all_day=True,
        )

        data = collect._calendar_data(
            [ongoing_timed, ongoing_all_day],
            now=now,
        )

        self.assertEqual(data["events"], [])
        self.assertEqual(data["total_count"], 0)
        self.assertEqual(data["display_count"], 0)
        self.assertEqual(data["overflow_count"], 0)

    def test_counts_all_day_and_recurring_instances_once(self) -> None:
        now = datetime(2026, 7, 24, tzinfo=timezone.utc)
        all_day = _event("All day", "2026-07-24", end="2026-07-25", all_day=True)
        recurring_instance = _event(
            "Weekly review",
            (now + timedelta(days=3)).isoformat(),
        )
        recurring_instance["recurring_event_id"] = "weekly-review"

        data = collect._calendar_data(
            [all_day, recurring_instance],
            now=now,
        )

        self.assertEqual(data["total_count"], 2)
        self.assertEqual(data["display_count"], 1)
        self.assertEqual(data["overflow_count"], 1)

    def test_collector_fetches_once_and_returns_complete_contract(self) -> None:
        now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
        events = [
            _event("Soon", (now + timedelta(hours=1)).isoformat()),
            _event("Later", (now + timedelta(days=4)).isoformat()),
        ]

        with mock.patch.object(
            collect.google_auth,
            "get_service",
            return_value=object(),
        ), mock.patch.object(
            collect.calendar_client,
            "get_upcoming_calendar_events",
            return_value=events,
        ) as fetch:
            result = collect.collect_calendar(now=now)

        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs, {"days": 7})
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.data["total_count"], 2)
        self.assertEqual(result.data["display_count"], 1)
        self.assertEqual(result.data["overflow_count"], 1)
        self.assertEqual(len(result.data["events"]), 2)
        self.assertEqual(len(result.data["display_events"]), 1)

    def test_empty_display_window_can_still_have_overflow(self) -> None:
        now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
        data = collect._calendar_data(
            [_event("Later", (now + timedelta(days=4)).isoformat())],
            now=now,
        )

        self.assertEqual(data["display_events"], [])
        self.assertEqual(data["display_count"], 0)
        self.assertEqual(data["overflow_count"], 1)


class CalendarAssistantToolTests(unittest.TestCase):
    def test_default_query_returns_the_complete_seven_day_result(self) -> None:
        events = [
            _event("Day six", "2026-07-30T12:00:00+00:00"),
        ]
        with mock.patch(
            "clients.google_auth.get_service",
            return_value=object(),
        ), mock.patch(
            "clients.calendar_client.get_upcoming_calendar_events",
            return_value=events,
        ) as fetch:
            result = agent_tools.get_upcoming_calendar_events()

        fetch.assert_called_once_with(mock.ANY, days=7)
        self.assertEqual(result, {"days_queried": 7, "events": events})


if __name__ == "__main__":
    unittest.main()
