"""Connector authentication and cache paths follow the selected data profile."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from clients import market_client, sports_client


class ConnectorCacheRuntimePathTests(unittest.TestCase):
    def test_market_cache_writer_creates_parent_and_keeps_atomic_file_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-market-cache-") as temporary:
            cache_path = Path(temporary) / "managed" / "clients" / ".market_cache.json"
            with patch.object(
                market_client,
                "get_runtime_paths",
                return_value=SimpleNamespace(market_cache_path=cache_path),
            ):
                self.assertTrue(market_client._write_cache(market_client._empty_cache()))
                loaded = market_client._read_cache()

            self.assertEqual(cache_path.name, ".market_cache.json")
            self.assertEqual(loaded["version"], market_client._CACHE_VERSION)
            self.assertEqual({path.name for path in cache_path.parent.iterdir()}, {cache_path.name})

    def test_sports_writers_create_selected_cache_parents_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-sports-cache-") as temporary:
            root = Path(temporary) / "managed" / "clients"
            paths = SimpleNamespace(
                f1_cache_path=root / ".f1_cache.json",
                football_cache_path=root / ".football_cache.json",
            )
            now = datetime.now(timezone.utc).replace(microsecond=0)
            kickoff = now + timedelta(days=1)
            fixture = {
                "fixture_id": "one",
                "team": "Town",
                "team_id": 1,
                "opponent": "City",
                "home_or_away": "home",
                "competition": "League",
                "competition_id": 2,
                "kickoff_at": kickoff.isoformat(),
            }
            with patch.object(sports_client, "get_runtime_paths", return_value=paths):
                sports_client._write_f1_cache({"raceName": "Test GP"})
                sports_client._write_football_cache({1: [fixture]})
                f1_payload = sports_client._read_f1_cache()
                football_payload = sports_client._read_football_cache(now=now)

            self.assertEqual(f1_payload["f1_map"]["raceName"], "Test GP")
            self.assertIn(1, football_payload)
            self.assertEqual(paths.f1_cache_path.parent, paths.football_cache_path.parent)
            self.assertEqual(
                {path.name for path in paths.f1_cache_path.parent.iterdir()},
                {".f1_cache.json", ".football_cache.json"},
            )

    def test_preflight_and_tool_catalog_check_google_markers_from_selected_profile(self) -> None:
        from core.agent import tool_catalog
        from core.telemetry import preflight

        with tempfile.TemporaryDirectory(prefix="apex-google-profile-") as temporary:
            root = Path(temporary) / "operator-data"
            paths = SimpleNamespace(
                google_credentials_path=root / "credentials.json",
                google_token_path=root / "token.json",
            )
            telemetry_service = Mock(latest=Mock(return_value=None))
            with patch.object(preflight, "get_runtime_paths", return_value=paths), patch.object(
                tool_catalog, "get_runtime_paths", return_value=paths
            ), patch(
                "core.telemetry.service.get_telemetry_service",
                return_value=telemetry_service,
            ):
                blockers = preflight._connector_credential_blockers({"email"})
                available_without_markers = tool_catalog._native_availability("search_gmail")

                root.mkdir(parents=True)
                paths.google_credentials_path.touch()
                paths.google_token_path.touch()
                available_with_markers = tool_catalog._native_availability("search_gmail")

            self.assertEqual(blockers[0].code, "missing_credentials")
            self.assertFalse(available_without_markers[0])
            self.assertTrue(available_with_markers[0])
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {"credentials.json", "token.json"},
            )


if __name__ == "__main__":
    unittest.main()
