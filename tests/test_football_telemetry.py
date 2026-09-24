"""Regression coverage for configurable football fixture telemetry."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from clients import sports_client
from core.connectors.models import ConnectorResult
from core.settings.models import FootballSettings, FootballTeamSettings, RuntimeSettingsSnapshot


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


def _settings(*teams: tuple[int, str]) -> RuntimeSettingsSnapshot:
    return RuntimeSettingsSnapshot(
        football=FootballSettings(teams=tuple(FootballTeamSettings(id=team_id, name=name) for team_id, name in teams))
    )


def _match(
    team_id: int,
    opponent_id: int,
    opponent: str,
    kickoff: datetime,
    *,
    status: str = "TIMED",
) -> dict[str, object]:
    return {
        "id": team_id * 100,
        "status": status,
        "utcDate": kickoff.isoformat(),
        "homeTeam": {"id": team_id, "name": "Provider name ignored"},
        "awayTeam": {"id": opponent_id, "name": opponent},
        "competition": {"id": 2014, "name": "La Liga"},
    }


class FootballCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="apex_football_")
        self.addCleanup(self._temp.cleanup)
        self.cache_path = str(Path(self._temp.name) / "football-cache.json")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.store = mock.Mock()
        self.patches = [
            mock.patch("clients.sports_client.get_settings_store", return_value=self.store),
            mock.patch("clients.sports_client._get_football_cache_path", return_value=self.cache_path),
            mock.patch.dict("os.environ", {"FOOTBALL_API_KEY": "test-key"}, clear=False),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_collects_each_team_orders_fixtures_and_resolves_venue(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"), (2, "Second"))
        later = _match(1, 11, "Later", self.now + timedelta(days=2))
        earlier = _match(2, 12, "Earlier", self.now + timedelta(days=1))
        with mock.patch("clients.sports_client.requests.get", side_effect=[_Response({"matches": [later]}), _Response({"matches": [earlier]})]) as request:
            result = sports_client.collect_football()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result.status, "healthy")
        self.assertEqual([fixture["team"] for fixture in result.data["fixtures"]], ["Second", "First"])
        self.assertEqual(result.data["fixtures"][0]["home_or_away"], "home")

    def test_collects_up_to_five_fixtures_per_team_within_fourteen_days(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"))
        matches = [
            _match(1, 10 + day, f"Opponent {day}", self.now + timedelta(days=day))
            for day in range(1, 7)
        ]
        matches.append(_match(1, 99, "Outside horizon", self.now + timedelta(days=15)))
        with mock.patch("clients.sports_client.requests.get", return_value=_Response({"matches": matches})):
            result = sports_client.collect_football()
        self.assertEqual(len(result.data["fixtures"]), 5)
        self.assertEqual(
            [fixture["opponent"] for fixture in result.data["fixtures"]],
            [f"Opponent {day}" for day in range(1, 6)],
        )

    def test_fresh_cache_is_reused_unless_forced(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"))
        fixture = _match(1, 11, "Opponent", self.now + timedelta(days=2))
        with mock.patch("clients.sports_client.requests.get", return_value=_Response({"matches": [fixture]})) as request:
            sports_client.collect_football()
            cached = sports_client.collect_football()
            forced = sports_client.collect_football(force=True)
        self.assertEqual(cached.freshness, "fresh_cache")
        self.assertEqual(forced.freshness, "live")
        self.assertEqual(request.call_count, 2)

    def test_stale_future_cache_degrades_after_provider_failure(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"))
        fixture = _match(1, 11, "Opponent", self.now + timedelta(days=2))
        with mock.patch("clients.sports_client.requests.get", return_value=_Response({"matches": [fixture]})):
            sports_client.collect_football()
        with mock.patch("clients.sports_client.requests.get", return_value=_Response({}, 429)):
            result = sports_client.collect_football(force=True)
        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.freshness, "stale")
        self.assertEqual(result.reason_code, "throttled")

    def test_invalid_configuration_and_missing_credentials_are_distinct(self) -> None:
        self.store.get_snapshot.return_value = _settings()
        self.assertEqual(sports_client.collect_football().reason_code, "configuration_failure")
        self.store.get_snapshot.return_value = _settings((1, "First"))
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(sports_client.collect_football().reason_code, "missing_credentials")

    def test_team_matches_request_uses_date_range_without_status_filter(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"))
        fixture = _match(1, 11, "Opponent", self.now + timedelta(days=2))
        before = datetime.now(timezone.utc).date()
        with mock.patch("clients.sports_client.requests.get", return_value=_Response({"matches": [fixture]})) as request:
            sports_client.collect_football()
        after = datetime.now(timezone.utc).date()
        query = parse_qs(urlparse(request.call_args[0][0]).query)
        date_from = date.fromisoformat(query["dateFrom"][0])
        date_to = date.fromisoformat(query["dateTo"][0])
        self.assertEqual(date_to - date_from, sports_client.FOOTBALL_HORIZON)
        self.assertLessEqual(before, date_from)
        self.assertLessEqual(date_from, after)
        self.assertNotIn("status", query)
        self.assertNotIn("limit", query)

    def test_upcoming_statuses_included_non_upcoming_skipped(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"))
        matches = [
            _match(1, 10, "Timed", self.now + timedelta(days=1), status="TIMED"),
            _match(1, 11, "Scheduled", self.now + timedelta(days=2), status="SCHEDULED"),
            _match(1, 12, "Finished", self.now + timedelta(days=3), status="FINISHED"),
            _match(1, 13, "Postponed", self.now + timedelta(days=4), status="POSTPONED"),
            _match(1, 14, "Live", self.now + timedelta(days=5), status="IN_PLAY"),
        ]
        with mock.patch("clients.sports_client.requests.get", return_value=_Response({"matches": matches})):
            result = sports_client.collect_football()
        opponents = {fixture["opponent"] for fixture in result.data["fixtures"]}
        self.assertEqual(opponents, {"Timed", "Scheduled"})

    def test_no_eligible_fixtures_returns_healthy_empty_display(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"))
        outside = _match(1, 11, "Far", self.now + timedelta(days=15), status="TIMED")
        finished = _match(1, 12, "Done", self.now + timedelta(days=2), status="FINISHED")
        cases = (
            {"matches": [outside, finished]},
            {"matches": []},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with mock.patch("clients.sports_client.requests.get", return_value=_Response(payload)):
                    result = sports_client.collect_football()
                self.assertEqual(result.status, "healthy")
                self.assertEqual(result.reason_code, "ok")
                self.assertEqual(result.data["fixtures"], [])
                self.assertEqual(result.display_text, "No upcoming football fixtures.")

    def test_malformed_payload_when_structure_is_invalid(self) -> None:
        self.store.get_snapshot.return_value = _settings((1, "First"))
        cases = (
            {"matches": "nope"},
            {"matches": [{"utcDate": self.now.isoformat(), "awayTeam": {}, "competition": {"id": 1, "name": "X"}}]},
            {"matches": [_match(99, 11, "Other team", self.now + timedelta(days=1))]},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with mock.patch("clients.sports_client.requests.get", return_value=_Response(payload)):
                    result = sports_client.collect_football()
                self.assertEqual(result.status, "unavailable")
                self.assertEqual(result.reason_code, "malformed_payload")


class FootballSynthesisTests(unittest.TestCase):
    def test_selects_earliest_fixture_within_seven_days(self) -> None:
        from core.api.briefing import _build_synthesis_input

        now = datetime.now(timezone.utc)
        fixtures = [
            {"team": "Later", "opponent": "B", "home_or_away": "away", "competition": "Cup", "kickoff_at": (now + timedelta(days=8)).isoformat()},
            {"team": "Soon", "opponent": "C", "home_or_away": "home", "competition": "League", "kickoff_at": (now + timedelta(days=1)).isoformat()},
        ]
        result = ConnectorResult(name="football", status="healthy", freshness="live", reason_code="ok", display_text="", data={"fixtures": fixtures})
        source = _build_synthesis_input(results={"football": result}, failed_connectors=[])
        self.assertIsNotNone(source.football_next_fixture)
        self.assertEqual(source.football_next_fixture.team, "Soon")
