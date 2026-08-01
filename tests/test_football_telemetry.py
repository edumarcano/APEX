"""Regression coverage for configurable football fixture telemetry."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

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


def _match(team_id: int, opponent_id: int, opponent: str, kickoff: datetime) -> dict[str, object]:
    return {
        "id": team_id * 100,
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
