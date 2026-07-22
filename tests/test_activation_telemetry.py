"""Activation telemetry snapshot, refresh, and preflight coverage."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.connectors.models import ConnectorResult, utc_now_iso
from core.settings.models import SettingsPatch
from core.settings.store import RuntimeSettingsStore, reset_settings_store_for_tests
from core.telemetry.models import FRESHNESS_WINDOW_SECONDS, PreflightRequest
from core.telemetry.service import reset_telemetry_service_for_tests
from core.telemetry.store import build_snapshot_from_results


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _result(
    name: str,
    status: str,
    *,
    reason_code: str = "ok",
    freshness: str = "live",
    display_text: str | None = None,
    observed_at: str | None = None,
) -> ConnectorResult:
    return ConnectorResult(
        name=name,
        status=status,  # type: ignore[arg-type]
        freshness=freshness,  # type: ignore[arg-type]
        reason_code=reason_code,
        observed_at=observed_at or utc_now_iso(),
        display_text=display_text or f"{name}:{status}",
        data={"marker": name},
    )


class SnapshotStoreUnitTests(unittest.TestCase):
    def test_partial_failure_retains_prior_healthy_module(self) -> None:
        prior = build_snapshot_from_results(
            {
                "weather": _result("weather", "healthy", display_text="72 clear"),
                "news": _result("news", "healthy"),
            }
        )
        merged = build_snapshot_from_results(
            {
                "weather": _result(
                    "weather",
                    "unavailable",
                    reason_code="network_error",
                    display_text="",
                )
            },
            prior=prior,
        )
        weather = merged.modules["weather"]
        self.assertEqual(weather.status, "healthy")
        self.assertEqual(weather.freshness, "stale")
        self.assertEqual(weather.display_text, "72 clear")
        self.assertEqual(weather.reason_code, "network_error")
        self.assertEqual(merged.modules["news"].status, "healthy")

    def test_partial_failure_replaces_prior_degraded_reason(self) -> None:
        prior = build_snapshot_from_results(
            {
                "news": _result(
                    "news",
                    "degraded",
                    reason_code="partial_payload",
                    display_text="keep-me",
                )
            }
        )
        merged = build_snapshot_from_results(
            {
                "news": _result(
                    "news",
                    "unavailable",
                    reason_code="network_error",
                    display_text="",
                )
            },
            prior=prior,
        )

        news = merged.modules["news"]
        self.assertEqual(news.status, "degraded")
        self.assertEqual(news.freshness, "stale")
        self.assertEqual(news.display_text, "keep-me")
        self.assertEqual(news.reason_code, "network_error")

    def test_disabled_excluded_from_sync_health_denominator(self) -> None:
        from core.connectors.scoring import compute_sync_health

        report = compute_sync_health(
            {
                "weather": _result("weather", "healthy"),
                "news": _result("news", "disabled", reason_code="disabled"),
                "email": None,
            }
        )
        self.assertEqual(report.sync_health_score, 100.0)
        self.assertEqual(
            [entry.name for entry in report.connector_health],
            ["weather", "news"],
        )


class TelemetryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_telemetry_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        self.db_path = self._dir / "apex_memory.db"
        _write_json(
            self.config_path,
            {
                "features": {
                    "weather": True,
                    "sports": False,
                    "news": True,
                    "email": False,
                    "calendar": False,
                    "market": False,
                },
                "modules": {"football": False, "f1": False},
                "ask_apex": {"enabled": True, "default_profile": "comet"},
                "tts_settings": {
                    "primary_tts": "pyttsx3",
                    "voice_gender": "female",
                },
                "ollama": {"enabled": False},
            },
        )
        reset_settings_store_for_tests()
        reset_telemetry_service_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store", return_value=self.store
            ),
            mock.patch("core.api.briefing.get_settings_store", return_value=self.store),
            mock.patch(
                "core.telemetry.service.get_settings_store", return_value=self.store
            ),
            mock.patch(
                "core.telemetry.preflight.get_settings_store", return_value=self.store
            ),
            mock.patch("core.database.DB_NAME", str(self.db_path)),
            mock.patch("core.api.app.OLLAMA_ENABLED", False),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)
        self.addCleanup(reset_telemetry_service_for_tests)

        from core import database
        from core.api import app

        database.initialize_db()
        self.client = TestClient(app, raise_server_exceptions=True)

    def test_latest_404_when_empty(self) -> None:
        response = self.client.get("/api/v1/telemetry/latest")
        self.assertEqual(response.status_code, 404)

    def test_refresh_all_and_latest(self) -> None:
        weather = _result("weather", "healthy", display_text="70 sunny")
        news = _result("news", "healthy", display_text="headline")
        reminders = _result("reminders", "healthy", display_text="none")

        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            return_value=weather,
        ), mock.patch(
            "core.telemetry.collector.news_client.collect_news",
            return_value=news,
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=reminders,
        ):
            response = self.client.post("/api/v1/telemetry/refresh", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("snapshot_id", payload)
        self.assertIn("collected_at", payload)
        self.assertEqual(payload["modules"]["weather"]["status"], "healthy")
        self.assertEqual(payload["modules"]["email"]["status"], "disabled")
        self.assertEqual(payload["modules"]["email"]["reason_code"], "disabled")
        latest = self.client.get("/api/v1/telemetry/latest")
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["snapshot_id"], payload["snapshot_id"])

    def test_freshness_window_skips_connector_calls(self) -> None:
        weather = _result("weather", "healthy")
        news = _result("news", "healthy")
        reminders = _result("reminders", "healthy")
        collect_weather = mock.Mock(return_value=weather)
        collect_news = mock.Mock(return_value=news)
        collect_reminders = mock.Mock(return_value=reminders)

        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            collect_weather,
        ), mock.patch(
            "core.telemetry.collector.news_client.collect_news",
            collect_news,
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            collect_reminders,
        ):
            first = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
            second = self.client.post("/api/v1/telemetry/refresh", json={})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["snapshot_id"], second.json()["snapshot_id"])
        self.assertEqual(collect_weather.call_count, 1)
        self.assertEqual(collect_news.call_count, 1)

    def test_force_refresh_bypasses_freshness(self) -> None:
        weather = _result("weather", "healthy")
        news = _result("news", "healthy")
        reminders = _result("reminders", "healthy")
        collect_weather = mock.Mock(return_value=weather)

        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            collect_weather,
        ), mock.patch(
            "core.telemetry.collector.news_client.collect_news",
            return_value=news,
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=reminders,
        ):
            first = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
            second = self.client.post("/api/v1/telemetry/refresh", json={"force": True})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["snapshot_id"], second.json()["snapshot_id"])
        self.assertEqual(collect_weather.call_count, 2)

    def test_partial_refresh_does_not_make_old_modules_fresh(self) -> None:
        old_observation = (
            datetime.now(timezone.utc)
            - timedelta(seconds=FRESHNESS_WINDOW_SECONDS + 1)
        ).isoformat()
        weather = _result("weather", "healthy")
        old_news = _result("news", "healthy", observed_at=old_observation)
        reminders = _result("reminders", "healthy")
        collect_weather = mock.Mock(return_value=weather)
        collect_news = mock.Mock(return_value=old_news)

        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            collect_weather,
        ), mock.patch(
            "core.telemetry.collector.news_client.collect_news",
            collect_news,
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=reminders,
        ):
            seed = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
            partial = self.client.post(
                "/api/v1/telemetry/refresh",
                json={"connectors": ["weather"], "force": True},
            )
            refreshed = self.client.post("/api/v1/telemetry/refresh", json={})

        self.assertEqual(seed.status_code, 200)
        self.assertEqual(partial.status_code, 200)
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(collect_news.call_count, 2)

    def test_setting_change_replaces_cached_connector_with_disabled_state(self) -> None:
        collect_weather = mock.Mock(return_value=_result("weather", "healthy"))
        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            collect_weather,
        ), mock.patch(
            "core.telemetry.collector.news_client.collect_news",
            return_value=_result("news", "healthy"),
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=_result("reminders", "healthy"),
        ):
            seeded = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
            self.store.apply_patch(
                SettingsPatch.model_validate({"features": {"weather": False}})
            )
            refreshed = self.client.post("/api/v1/telemetry/refresh", json={})

        self.assertEqual(seeded.status_code, 200)
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.json()["modules"]["weather"]["status"], "disabled")
        self.assertEqual(collect_weather.call_count, 1)

    def test_partial_refresh_merge_and_retain_on_failure(self) -> None:
        weather = _result("weather", "healthy", display_text="keep-me")
        news = _result("news", "healthy")
        reminders = _result("reminders", "healthy")

        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            return_value=weather,
        ), mock.patch(
            "core.telemetry.collector.news_client.collect_news",
            return_value=news,
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=reminders,
        ):
            seed = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
        self.assertEqual(seed.status_code, 200)

        failed_weather = _result(
            "weather", "unavailable", reason_code="timeout", display_text=""
        )
        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            return_value=failed_weather,
        ):
            refreshed = self.client.post(
                "/api/v1/telemetry/refresh",
                json={"connectors": ["weather"], "force": True},
            )

        self.assertEqual(refreshed.status_code, 200)
        module = refreshed.json()["modules"]["weather"]
        self.assertEqual(module["status"], "healthy")
        self.assertEqual(module["freshness"], "stale")
        self.assertEqual(module["display_text"], "keep-me")
        self.assertEqual(refreshed.json()["modules"]["news"]["status"], "healthy")

    def test_concurrent_refresh_returns_409(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        results: list[int] = []

        def _slow_weather() -> ConnectorResult:
            entered.set()
            gate.wait(timeout=5)
            return _result("weather", "healthy")

        def _first() -> None:
            with mock.patch(
                "core.telemetry.collector.weather_client.collect_weather",
                side_effect=_slow_weather,
            ), mock.patch(
                "core.telemetry.collector.news_client.collect_news",
                return_value=_result("news", "healthy"),
            ), mock.patch(
                "core.telemetry.collector.collect_reminders",
                return_value=_result("reminders", "healthy"),
            ):
                response = self.client.post(
                    "/api/v1/telemetry/refresh", json={"force": True}
                )
            results.append(response.status_code)

        worker = threading.Thread(target=_first)
        worker.start()
        self.assertTrue(entered.wait(timeout=5))
        second = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
        results.append(second.status_code)
        gate.set()
        worker.join(timeout=5)

        self.assertIn(409, results)
        self.assertIn(200, results)

    def test_invalid_connector_rejected_before_freshness_shortcut(self) -> None:
        with mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            return_value=_result("weather", "healthy"),
        ), mock.patch(
            "core.telemetry.collector.news_client.collect_news",
            return_value=_result("news", "healthy"),
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=_result("reminders", "healthy"),
        ):
            seed = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
        self.assertEqual(seed.status_code, 200)

        response = self.client.post(
            "/api/v1/telemetry/refresh",
            json={"connectors": ["not_a_connector"]},
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_connector_rejected_in_demo_mode(self) -> None:
        with mock.patch("core.telemetry.service.config.DEMO_MODE", True):
            response = self.client.post(
                "/api/v1/telemetry/refresh",
                json={"connectors": ["not_a_connector"]},
            )
        self.assertEqual(response.status_code, 400)

    def test_demo_mode_static_snapshot_no_connectors(self) -> None:
        collect_weather = mock.Mock()
        with mock.patch("core.telemetry.service.config.DEMO_MODE", True), mock.patch(
            "core.telemetry.collector.weather_client.collect_weather",
            collect_weather,
        ):
            response = self.client.post("/api/v1/telemetry/refresh", json={"force": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["modules"]["weather"]["status"], "healthy")
        collect_weather.assert_not_called()

    def test_preflight_network_and_battery_warnings(self) -> None:
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=False), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ), mock.patch(
            "core.scanner.get_current_ssid", return_value="OtherNet"
        ), mock.patch.dict(
            "os.environ", {"HOME_SSID": "HomeNet"}, clear=False
        ), mock.patch(
            "core.scanner.get_power_state", return_value="battery"
        ), mock.patch(
            "core.telemetry.preflight._evaluate_local_profile_blockers",
            return_value=([], True),
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={
                    "operation": "activate",
                    "synthesis_profile": "lynx",
                    "involves_cloud": False,
                },
            )
        self.assertEqual(response.status_code, 200)
        codes = {item["code"] for item in response.json()["warnings"]}
        self.assertIn("outside_configured_network", codes)
        self.assertIn("running_on_battery", codes)

    def test_preflight_unknown_ssid_and_cloud_disclosure(self) -> None:
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=False), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ), mock.patch(
            "core.scanner.get_current_ssid", return_value=None
        ), mock.patch.dict(
            "os.environ", {"HOME_SSID": "HomeNet"}, clear=False
        ), mock.patch(
            "core.scanner.get_power_state", return_value="plugged"
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={
                    "operation": "generate_briefing",
                    "involves_cloud": True,
                    "cloud_disclosure_acknowledged": False,
                },
            )
        codes = {item["code"] for item in response.json()["warnings"]}
        self.assertIn("network_trust_unknown", codes)
        self.assertIn("cloud_data_disclosure", codes)

    def test_preflight_acknowledgement_suppresses_warning(self) -> None:
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={
                    "operation": "assistant_query",
                    "involves_cloud": True,
                    "acknowledged_warnings": ["cloud_data_disclosure"],
                },
            )
        codes = {item["code"] for item in response.json()["warnings"]}
        self.assertNotIn("cloud_data_disclosure", codes)

    def test_preflight_rapid_refresh_warning(self) -> None:
        from core.telemetry.service import get_telemetry_service

        service = get_telemetry_service()
        service.store.mark_forced_refresh(datetime.now(timezone.utc))

        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={"operation": "refresh_telemetry", "force": True},
            )
        codes = {item["code"] for item in response.json()["warnings"]}
        self.assertIn("rapid_connector_refresh", codes)

        # Outside window — no warning
        service.store.mark_forced_refresh(
            datetime.now(timezone.utc) - timedelta(seconds=FRESHNESS_WINDOW_SECONDS + 1)
        )
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={"operation": "refresh_telemetry", "force": True},
            )
        codes = {item["code"] for item in response.json()["warnings"]}
        self.assertNotIn("rapid_connector_refresh", codes)

    def test_preflight_does_not_warn_for_forced_local_or_non_refresh_work(self) -> None:
        from core.telemetry.service import get_telemetry_service

        get_telemetry_service().store.mark_forced_refresh(datetime.now(timezone.utc))
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ):
            reminders = self.client.post(
                "/api/v1/preflight",
                json={
                    "operation": "refresh_telemetry",
                    "connectors": ["reminders"],
                    "force": True,
                },
            )
            briefing = self.client.post(
                "/api/v1/preflight",
                json={"operation": "generate_briefing", "force": True},
            )

        reminder_codes = {item["code"] for item in reminders.json()["warnings"]}
        briefing_codes = {item["code"] for item in briefing.json()["warnings"]}
        self.assertNotIn("rapid_connector_refresh", reminder_codes)
        self.assertNotIn("rapid_connector_refresh", briefing_codes)

    def test_forced_reminders_refresh_does_not_start_rapid_refresh_window(self) -> None:
        from core.telemetry.service import get_telemetry_service

        with mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=_result("reminders", "healthy"),
        ):
            response = self.client.post(
                "/api/v1/telemetry/refresh",
                json={"connectors": ["reminders"], "force": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_telemetry_service().had_forced_refresh_within_window())

    def test_preflight_loaded_local_model_skips_cold_load_checks(self) -> None:
        local_snapshot = {
            "reachable": True,
            "installed_tags": ["qwen3:1.7b"],
            "loaded_models": [{"name": "qwen3:1.7b", "model": "qwen3:1.7b"}],
            "vitals": {"ram": 99.0, "cpu": 99.0},
            "sampled_at": 0.0,
        }
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ), mock.patch(
            "core.telemetry.preflight.OLLAMA_ENABLED", True
        ), mock.patch(
            "core.telemetry.preflight.is_local_execution_active", return_value=False
        ), mock.patch(
            "core.telemetry.preflight.get_status_snapshot", return_value=local_snapshot
        ), mock.patch(
            "core.telemetry.preflight.check_resource_gate"
        ) as resource_gate, mock.patch(
            "core.scanner.get_power_state", return_value="battery"
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={"operation": "assistant_query", "synthesis_profile": "lynx"},
            )

        payload = response.json()
        self.assertTrue(payload["can_proceed"])
        self.assertNotIn("running_on_battery", {item["code"] for item in payload["warnings"]})
        resource_gate.assert_not_called()

    def test_preflight_blocks_missing_connector_credentials(self) -> None:
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ), mock.patch.dict(
            "os.environ",
            {"OPENWEATHER_API_KEY": "", "TARGET_LOCATION": ""},
            clear=False,
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={
                    "operation": "refresh_telemetry",
                    "connectors": ["weather"],
                },
            )

        payload = response.json()
        self.assertFalse(payload["can_proceed"])
        self.assertIn("missing_credentials", {item["code"] for item in payload["blockers"]})

    def test_preflight_rejects_unknown_synthesis_profile(self) -> None:
        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={"operation": "assistant_query", "synthesis_profile": "unknown"},
            )

        payload = response.json()
        self.assertFalse(payload["can_proceed"])
        self.assertIn("invalid_input", {item["code"] for item in payload["blockers"]})

    def test_preflight_hard_blocker_not_overridable(self) -> None:
        def _getenv(key: str, default: object = None) -> object:
            if key == "GEMINI_API_KEY":
                return None
            import os

            return os.environ.get(key, default)

        with mock.patch("core.telemetry.preflight.is_dev_mode", return_value=True), mock.patch(
            "core.telemetry.preflight.config.DEMO_MODE", False
        ), mock.patch(
            "core.telemetry.preflight.os.getenv",
            side_effect=_getenv,
        ):
            response = self.client.post(
                "/api/v1/preflight",
                json={
                    "operation": "generate_briefing",
                    "involves_cloud": True,
                    "acknowledged_warnings": [
                        "cloud_data_disclosure",
                        "outside_configured_network",
                        "network_trust_unknown",
                        "running_on_battery",
                        "rapid_connector_refresh",
                        "high_resource_local_profile",
                    ],
                    "cloud_disclosure_acknowledged": True,
                },
            )
        payload = response.json()
        self.assertFalse(payload["can_proceed"])
        self.assertTrue(
            any(item["code"] == "missing_credentials" for item in payload["blockers"])
        )

    def test_preflight_demo_mode_quiet(self) -> None:
        with mock.patch("core.telemetry.preflight.config.DEMO_MODE", True):
            response = self.client.post(
                "/api/v1/preflight",
                json={"operation": "activate", "involves_cloud": True, "force": True},
            )
        self.assertEqual(response.json(), {"warnings": [], "blockers": [], "can_proceed": True})

    def test_preflight_invalid_connectors_block(self) -> None:
        result = PreflightRequest(
            operation="refresh_telemetry",
            connectors=["not_a_connector"],
        )
        from core.telemetry.preflight import evaluate_preflight

        with mock.patch("core.telemetry.preflight.config.DEMO_MODE", False), mock.patch(
            "core.telemetry.preflight.is_dev_mode", return_value=True
        ):
            response = evaluate_preflight(result)
        self.assertFalse(response.can_proceed)
        self.assertEqual(response.blockers[0].code, "invalid_input")


class TriggerWithoutGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_trigger_gate_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        self.db_path = self._dir / "apex_memory.db"
        _write_json(
            self.config_path,
            {
                "features": {
                    "weather": False,
                    "sports": False,
                    "news": False,
                    "email": False,
                    "calendar": False,
                    "market": False,
                },
                "modules": {"football": False, "f1": False},
                "ask_apex": {"enabled": True, "default_profile": "comet"},
                "tts_settings": {
                    "primary_tts": "pyttsx3",
                    "voice_gender": "female",
                },
                "ollama": {"enabled": False},
            },
        )
        reset_settings_store_for_tests()
        reset_telemetry_service_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store", return_value=self.store
            ),
            mock.patch("core.api.briefing.get_settings_store", return_value=self.store),
            mock.patch(
                "core.telemetry.service.get_settings_store", return_value=self.store
            ),
            mock.patch("core.speaker.get_settings_store", return_value=self.store),
            mock.patch("core.database.DB_NAME", str(self.db_path)),
            mock.patch("core.api.app.OLLAMA_ENABLED", False),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)
        self.addCleanup(reset_telemetry_service_for_tests)

        from core import database
        from core.api import app, global_pipeline_state

        database.initialize_db()
        global_pipeline_state.reset()
        self.client = TestClient(app, raise_server_exceptions=True)

    def test_trigger_no_longer_blocked_by_scanner_gate(self) -> None:
        from core.synthesis.models import SynthesisResult

        def _immediate_thread(*_a: object, target=None, kwargs=None, **_k: object):
            thread = mock.Mock()

            def start() -> None:
                if target is not None:
                    target(**(kwargs or {}))

            thread.start = start
            thread.join = mock.Mock()
            return thread

        synthesis = SynthesisResult(
            briefing="Gate removed briefing.",
            insights=["Insight"],
            provider="raw",
            fallback_reason="configured_raw",
        )

        with mock.patch("core.api.briefing.DEMO_MODE", False), mock.patch(
            "core.api.briefing.is_dev_mode", return_value=True
        ), mock.patch("core.api.briefing.DEV_AI_SYNTHESIS", "raw"), mock.patch(
            "core.api.briefing.DEV_TTS_PLAYBACK", "pyttsx3"
        ), mock.patch(
            "core.telemetry.collector.collect_reminders",
            return_value=_result("reminders", "healthy"),
        ), mock.patch(
            "core.api.briefing.brain.process_telemetry",
            return_value=synthesis.model_dump(),
        ), mock.patch("core.api.briefing.speaker.speak"), mock.patch(
            "core.api.state.speaker.speak"
        ), mock.patch(
            "core.api.briefing.threading.Thread", side_effect=_immediate_thread
        ), mock.patch(
            "core.api.briefing.SynthesisRouter.prepare", return_value=None
        ), mock.patch(
            "core.api.tts.scanner.is_system_throttled", return_value=False
        ):
            response = self.client.post("/api/v1/trigger")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["briefing"], "Gate removed briefing.")
        self.assertIn("telemetry", response.json())
        latest = self.client.get("/api/v1/telemetry/latest")
        self.assertEqual(latest.status_code, 200)


class PowerStateTests(unittest.TestCase):
    def test_unknown_battery_sensor_is_not_battery(self) -> None:
        from core import scanner

        with mock.patch("core.scanner.psutil.sensors_battery", return_value=None):
            self.assertEqual(scanner.get_power_state(), "unknown")
            self.assertTrue(scanner.check_power())

    def test_on_battery_detected(self) -> None:
        from core import scanner

        battery = mock.Mock(power_plugged=False)
        with mock.patch("core.scanner.psutil.sensors_battery", return_value=battery):
            self.assertEqual(scanner.get_power_state(), "battery")
            self.assertFalse(scanner.check_power())


if __name__ == "__main__":
    unittest.main()
