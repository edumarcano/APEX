"""Tests for the runtime settings store foundation."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from core.settings.models import (
    AgentSettingsPatch,
    BriefingPatch,
    FeaturesPatch,
    FootballPatch,
    FootballTeamPatch,
    LynxSettingsPatch,
    MarketPatch,
    ModulesPatch,
    PantheraSettingsPatch,
    SettingsPatch,
    VoicePatch,
)
from core.settings.normalize import normalize_layer, recursive_overlay
from core.settings.store import (
    RuntimeSettingsStore,
    SettingsPersistenceError,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class SettingsStoreLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_settings_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        self.base = {
            "features": {
                "weather": True,
                "sports": True,
                "news": False,
                "email": False,
                "calendar": True,
            },
            "modules": {"football": False, "f1": True},
            "ask_apex": {
                "enabled": True,
                "default_profile": "comet",
            },
            "tts_settings": {
                "primary_tts": "google",
                "voice_gender": "female",
            },
        }
        _write_json(self.config_path, self.base)

    def _store(self) -> RuntimeSettingsStore:
        return RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )

    def test_base_only_loading(self) -> None:
        store = self._store()
        snap = store.get_snapshot()
        self.assertTrue(snap.features.weather)
        self.assertTrue(snap.features.sports)
        self.assertFalse(snap.features.news)
        self.assertFalse(snap.modules.football)
        self.assertTrue(snap.modules.f1)
        self.assertTrue(snap.ask_apex.enabled)
        self.assertEqual(snap.ask_apex.agent, "panthera")
        self.assertEqual(snap.ask_apex.panthera.model, "gpt-5.6-luna")
        self.assertEqual(snap.ask_apex.panthera.effort, "focused")
        self.assertEqual(snap.ask_apex.lynx.model, "gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(snap.user_designation, "")
        self.assertEqual(snap.voice.engine, "google")
        self.assertEqual(snap.voice.gender, "female")
        self.assertFalse(store.local_file_present)
        self.assertFalse(store.local_override_active)
        self.assertIsNone(store.load_warning)

    def test_invalid_local_model_falls_back_to_default_lynx_model(self) -> None:
        self.base["ask_apex"]["local_agent"] = "not-an-agent"
        _write_json(self.config_path, self.base)
        self.assertEqual(
            self._store().get_snapshot().ask_apex.lynx.model,
            "gemma-4-E2B-Q4_K_M.gguf",
        )

    def test_base_plus_local_loading(self) -> None:
        _write_json(
            self.local_path,
            {
                "user_designation": "  Chief  ",
                "features": {"news": True},
                "ask_apex": {"enabled": False, "default_profile": "nova"},
                "tts_settings": {"primary_tts": "kokoro"},
            },
        )
        store = self._store()
        snap = store.get_snapshot()
        self.assertTrue(snap.features.weather)
        self.assertTrue(snap.features.news)
        self.assertFalse(snap.ask_apex.enabled)
        self.assertEqual(snap.ask_apex.agent, "panthera")
        self.assertEqual(snap.voice.engine, "kokoro")
        self.assertEqual(snap.voice.gender, "female")
        self.assertEqual(snap.user_designation, "Chief")
        self.assertTrue(store.local_file_present)
        self.assertTrue(store.local_override_active)

    def test_empty_football_teams_in_base_config(self) -> None:
        self.base["football"] = {"teams": []}
        self.base["market"] = {"symbols": []}
        _write_json(self.config_path, self.base)
        store = self._store()
        snap = store.get_snapshot()
        self.assertEqual(snap.football.teams, ())
        self.assertEqual(snap.market.symbols, ())

    def test_patch_football_and_market_lists_persist_to_local_overlay(self) -> None:
        store = self._store()
        snap = store.apply_patch(
            SettingsPatch(
                football=FootballPatch(
                    teams=[FootballTeamPatch(id=81, name="Barcelona")]
                ),
                market=MarketPatch(symbols=["SPY", "AAPL"]),
            )
        )
        self.assertEqual([(team.id, team.name) for team in snap.football.teams], [(81, "Barcelona")])
        self.assertEqual(list(snap.market.symbols), ["SPY", "AAPL"])

        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(
            written["football"]["teams"],
            [{"id": 81, "name": "Barcelona"}],
        )
        self.assertEqual(written["market"]["symbols"], ["SPY", "AAPL"])

    def test_football_team_array_is_replaced_by_local_overlay(self) -> None:
        self.base["football"] = {"teams": [{"id": 1, "name": "One"}, {"id": 2, "name": "Two"}]}
        _write_json(self.config_path, self.base)
        _write_json(self.local_path, {"football": {"teams": [{"id": 3, "name": "Three"}]}})
        store = self._store()
        self.assertEqual([(team.id, team.name) for team in store.get_snapshot().football.teams], [(3, "Three")])

    def test_invalid_football_team_array_discards_local_overlay(self) -> None:
        self.base["football"] = {"teams": [{"id": 1, "name": "One"}]}
        _write_json(self.config_path, self.base)
        _write_json(self.local_path, {"football": {"teams": [{"id": 1, "name": "One"}, {"id": 1, "name": "Duplicate"}]}})
        store = self._store()
        self.assertFalse(store.local_override_active)
        self.assertEqual([(team.id, team.name) for team in store.get_snapshot().football.teams], [(1, "One")])

    def test_legacy_local_profiles_migrate_to_lynx(self) -> None:
        expectations = {
            "lynx": "gemma-4-E2B-Q4_K_M.gguf",
            "acinonyx": "gemma-4-E2B-Q4_K_M.gguf",
            "neofelis": "gemma-4-E2B-Q4_K_M.gguf",
        }
        for profile, model in expectations.items():
            with self.subTest(agent=profile):
                _write_json(
                    self.local_path,
                    {"ask_apex": {"default_profile": profile}},
                )
                store = self._store()
                snap = store.get_snapshot().ask_apex
                self.assertEqual(snap.agent, "lynx")
                self.assertEqual(snap.lynx.model, model)

    def test_recursive_precedence(self) -> None:
        base = {"features": {"weather": True, "sports": False}, "modules": {"f1": True}}
        local = {"features": {"sports": True}, "modules": {"football": True}}
        merged = recursive_overlay(base, local)
        self.assertEqual(
            merged,
            {
                "features": {"weather": True, "sports": True},
                "modules": {"f1": True, "football": True},
            },
        )

    def test_partial_schema15_agent_settings_overlay_preserves_base_selection(self) -> None:
        store = self._store()
        store.apply_patch(
            SettingsPatch(
                ask_apex=AgentSettingsPatch(
                    panthera=PantheraSettingsPatch(
                        provider="xai",
                        model="grok-4.5",
                        effort="extended",
                    ),
                    lynx=LynxSettingsPatch(
                        runtime="ollama",
                        model="qwen3:1.7b",
                    ),
                )
            )
        )
        store.apply_patch(SettingsPatch(ask_apex=AgentSettingsPatch(enabled=False)))

        agent_settings = store.get_snapshot().ask_apex

        self.assertFalse(agent_settings.enabled)
        self.assertEqual(agent_settings.panthera.model, "grok-4.5")
        self.assertEqual(agent_settings.panthera.effort, "extended")
        self.assertEqual(agent_settings.lynx.model, "qwen3:1.7b")

    def test_lynx_briefing_mode_survives_reload(self) -> None:
        store = self._store()
        store.apply_patch(
            SettingsPatch(briefing=BriefingPatch(default_mode="lynx"))
        )

        self.assertEqual(store.get_snapshot().briefing.default_mode, "lynx")
        self.assertEqual(self._store().get_snapshot().briefing.default_mode, "lynx")

    def test_immutable_snapshot(self) -> None:
        store = self._store()
        snap = store.get_snapshot()
        with self.assertRaises(ValidationError):
            snap.features.weather = False  # type: ignore[misc]
        again = store.get_snapshot()
        self.assertTrue(again.features.weather)

    def test_legacy_key_normalization_per_layer(self) -> None:
        _write_json(
            self.config_path,
            {
                "ask_apex": {"cloud_agent": "pulsar"},
                "tts_settings": {"primary_tts": "piper", "voice_gender": "male"},
            },
        )
        store = self._store()
        snap = store.get_snapshot()
        self.assertEqual(snap.ask_apex.agent, "panthera")
        self.assertEqual(snap.voice.engine, "pyttsx3")
        self.assertEqual(snap.voice.gender, "male")

    def test_new_key_precedence_when_both_exist(self) -> None:
        _write_json(
            self.config_path,
            {
                "ask_apex": {
                    "cloud_agent": "comet",
                    "default_profile": "nova",
                }
            },
        )
        store = self._store()
        self.assertEqual(store.get_snapshot().ask_apex.agent, "panthera")

        normalized = normalize_layer(
            {
                "ask_apex": {
                    "default_profile": "pulsar",
                    "cloud_agent": "comet",
                }
            },
            layer_name="test",
        )
        self.assertEqual(normalized["ask_apex"]["agent"], "panthera")

    def test_malformed_local_uses_base_with_warning(self) -> None:
        self.local_path.write_text("{not-json", encoding="utf-8")
        store = self._store()
        snap = store.get_snapshot()
        self.assertTrue(snap.features.weather)
        self.assertEqual(snap.ask_apex.agent, "panthera")
        self.assertIsNotNone(store.load_warning)
        self.assertTrue(store.local_file_present)
        self.assertFalse(store.local_override_active)

    def test_invalid_local_root_uses_base_with_warning(self) -> None:
        self.local_path.write_text("[1, 2, 3]\n", encoding="utf-8")
        store = self._store()
        self.assertTrue(store.get_snapshot().features.weather)
        self.assertIsNotNone(store.load_warning)
        self.assertTrue(store.local_file_present)
        self.assertFalse(store.local_override_active)

    def test_invalid_local_value_discards_entire_override(self) -> None:
        _write_json(
            self.local_path,
            {
                "features": {"weather": "yes", "unknown_feature": True},
                "modules": {"f1": False, "hockey": True},
                "ask_apex": {"default_profile": "not-a-profile", "mystery": 1},
                "tts_settings": {"primary_tts": "watson", "extra": True},
                "totally_unknown": {"x": 1},
            },
        )
        store = self._store()
        snap = store.get_snapshot()
        self.assertTrue(snap.features.weather)
        self.assertTrue(snap.modules.f1)
        self.assertEqual(snap.ask_apex.agent, "panthera")
        self.assertEqual(snap.voice.engine, "google")
        self.assertIsNotNone(store.load_warning)
        self.assertTrue(store.local_file_present)
        self.assertFalse(store.local_override_active)

    def test_unknown_local_keys_are_ignored_without_rejecting_layer(self) -> None:
        _write_json(
            self.local_path,
            {
                "features": {"news": True, "future_feature": True},
                "future_section": {"enabled": True},
            },
        )
        store = self._store()
        self.assertTrue(store.get_snapshot().features.news)
        self.assertIsNone(store.load_warning)
        self.assertTrue(store.local_file_present)
        self.assertTrue(store.local_override_active)


class SettingsStorePatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_settings_patch_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        _write_json(
            self.config_path,
            {
                "features": {
                    "weather": True,
                    "sports": False,
                    "news": False,
                    "email": False,
                    "calendar": False,
                },
                "modules": {"football": False, "f1": False},
                "ask_apex": {"enabled": True, "default_profile": "comet"},
                "tts_settings": {
                    "primary_tts": "google",
                    "voice_gender": "female",
                },
            },
        )

    def _store(self) -> RuntimeSettingsStore:
        return RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )

    def test_lynx_models_are_valid_patch_values(self) -> None:
        for model in ("qwen3:1.7b", "qwen3:4b-instruct", "gemma-4-E2B-Q4_K_M.gguf", "gemma-4-E4B-Q4_K_M.gguf"):
            with self.subTest(model=model):
                patch = SettingsPatch.model_validate(
                    {"ask_apex": {"lynx": {"model": model}}}
                )
                self.assertEqual(patch.ask_apex.lynx.model, model)

    def test_lynx_context_window_patch_values(self) -> None:
        patch = SettingsPatch.model_validate(
            {
                "ask_apex": {
                    "lynx": {
                        "context_window": 32768,
                    }
                }
            }
        )
        self.assertEqual(patch.ask_apex.lynx.context_window, 32768)

    def test_lynx_reasoning_mode_patch_values(self) -> None:
        patch = SettingsPatch.model_validate(
            {
                "ask_apex": {
                    "lynx": {
                        "reasoning_mode": "focused",
                    }
                }
            }
        )
        self.assertEqual(patch.ask_apex.lynx.reasoning_mode, "focused")
        with self.assertRaises(ValidationError):
            SettingsPatch.model_validate(
                {"ask_apex": {"lynx": {"reasoning_mode": "invalid"}}}
            )

    def test_atomic_persistence_and_snapshot_publication(self) -> None:
        store = self._store()
        before = store.get_snapshot()
        self.assertFalse(before.features.sports)

        after = store.apply_patch(
            SettingsPatch(features=FeaturesPatch(sports=True))
        )
        self.assertTrue(after.features.sports)
        self.assertTrue(store.get_snapshot().features.sports)
        self.assertTrue(self.local_path.is_file())
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["features"]["sports"], True)

    def test_user_designation_persists_and_can_be_cleared(self) -> None:
        store = self._store()

        store.apply_patch(SettingsPatch(user_designation="  Chief  "))
        self.assertEqual(store.get_snapshot().user_designation, "Chief")
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["user_designation"], "Chief")

        store.apply_patch(SettingsPatch(user_designation=""))
        self.assertEqual(store.get_snapshot().user_designation, "")
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["user_designation"], "")

    def test_successful_patch_clears_load_warning(self) -> None:
        self.local_path.write_text("{not-json", encoding="utf-8")
        store = self._store()
        self.assertIsNotNone(store.load_warning)
        self.assertFalse(store.local_override_active)

        snap = store.apply_patch(
            SettingsPatch(features=FeaturesPatch(sports=True))
        )

        self.assertTrue(snap.features.sports)
        self.assertIsNone(store.load_warning)
        self.assertTrue(store.local_file_present)
        self.assertTrue(store.local_override_active)

    def test_patch_repairs_invalid_football_layer_and_survives_reload(self) -> None:
        _write_json(
            self.local_path,
            {
                "football": {
                    "teams": [
                        {"id": 81, "name": "Barcelona"},
                        {"id": 81, "name": "Duplicate"},
                    ]
                },
                "features": {"news": True},
            },
        )
        store = self._store()
        self.assertFalse(store.local_override_active)

        published = store.apply_patch(
            SettingsPatch(features=FeaturesPatch(sports=True))
        )
        reloaded = self._store().get_snapshot()

        self.assertEqual(published, reloaded)
        self.assertTrue(reloaded.features.sports)
        self.assertFalse(reloaded.features.news)
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertNotIn("football", written)
        self.assertTrue(written["features"]["sports"])

    def test_patch_preserves_noneditable_and_unknown_local_keys(self) -> None:
        _write_json(
            self.local_path,
            {
                "legacy_prompt": "preserve me",
                "ask_apex": {"max_session_messages": 12},
                "future_section": {"enabled": True},
            },
        )
        store = self._store()

        store.apply_patch(SettingsPatch(features=FeaturesPatch(sports=True)))

        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["legacy_prompt"], "preserve me")
        self.assertEqual(written["ask_apex"]["max_session_messages"], 12)
        self.assertEqual(written["future_section"], {"enabled": True})
        self.assertTrue(written["features"]["sports"])

    def test_patch_preserves_external_edit_made_after_load(self) -> None:
        store = self._store()
        _write_json(self.local_path, {"future_section": {"version": 2}})

        store.apply_patch(SettingsPatch(modules=ModulesPatch(f1=True)))

        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["future_section"], {"version": 2})
        self.assertTrue(written["modules"]["f1"])

    def test_transient_replace_retry_succeeds(self) -> None:
        store = self._store()
        calls = {"n": 0}
        real_replace = __import__("os").replace

        def flaky_replace(src: str, dst: str) -> None:
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("simulated lock")
            real_replace(src, dst)

        with mock.patch("os.replace", side_effect=flaky_replace):
            snap = store.apply_patch(
                SettingsPatch(voice=VoicePatch(gender="male"))
            )
        self.assertEqual(snap.voice.gender, "male")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(store.get_snapshot().voice.gender, "male")

    def test_permanent_failure_leaves_prior_snapshot(self) -> None:
        store = self._store()
        prior = store.get_snapshot()

        with mock.patch(
            "os.replace", side_effect=PermissionError("locked")
        ):
            with self.assertRaises(SettingsPersistenceError):
                store.apply_patch(
                    SettingsPatch(ask_apex=AgentSettingsPatch(enabled=False))
                )

        after = store.get_snapshot()
        self.assertEqual(after.ask_apex.enabled, prior.ask_apex.enabled)
        self.assertTrue(after.ask_apex.enabled)
        self.assertFalse(self.local_path.is_file())

    def test_different_field_patches_preserve_both(self) -> None:
        store = self._store()
        store.apply_patch(SettingsPatch(features=FeaturesPatch(sports=True)))
        store.apply_patch(SettingsPatch(modules=ModulesPatch(f1=True)))
        snap = store.get_snapshot()
        self.assertTrue(snap.features.sports)
        self.assertTrue(snap.modules.f1)
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertTrue(written["features"]["sports"])
        self.assertTrue(written["modules"]["f1"])

    def test_same_field_last_successful_write_wins(self) -> None:
        store = self._store()
        store.apply_patch(
            SettingsPatch(
                ask_apex=AgentSettingsPatch(
                    panthera=PantheraSettingsPatch(
                        provider="gemini", model="gemini-3.6-flash"
                    )
                )
            )
        )
        store.apply_patch(
            SettingsPatch(
                ask_apex=AgentSettingsPatch(
                    panthera=PantheraSettingsPatch(
                        provider="xai", model="grok-4.5"
                    )
                )
            )
        )
        self.assertEqual(
            store.get_snapshot().ask_apex.panthera.model, "grok-4.5"
        )
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["ask_apex"]["panthera"]["model"], "grok-4.5")


class SettingsStoreConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_settings_conc_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        _write_json(
            self.config_path,
            {
                "features": {
                    "weather": False,
                    "sports": False,
                    "news": False,
                    "email": False,
                    "calendar": False,
                },
                "modules": {"football": False, "f1": False},
                "ask_apex": {"enabled": True, "default_profile": "comet"},
                "tts_settings": {
                    "primary_tts": "google",
                    "voice_gender": "female",
                },
            },
        )
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )

    def test_concurrent_readers_and_writers(self) -> None:
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def reader() -> None:
            try:
                barrier.wait(timeout=5)
                for _ in range(40):
                    snap = self.store.get_snapshot()
                    _ = snap.features.weather
                    _ = snap.ask_apex.agent
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def writer_weather() -> None:
            try:
                barrier.wait(timeout=5)
                for i in range(20):
                    self.store.apply_patch(
                        SettingsPatch(
                            features=FeaturesPatch(weather=bool(i % 2))
                        )
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def writer_module() -> None:
            try:
                barrier.wait(timeout=5)
                for i in range(20):
                    self.store.apply_patch(
                        SettingsPatch(modules=ModulesPatch(f1=bool(i % 2)))
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer_weather),
            threading.Thread(target=writer_module),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        snap = self.store.get_snapshot()
        self.assertIn(snap.features.weather, (True, False))
        self.assertIn(snap.modules.f1, (True, False))
        self.assertTrue(self.local_path.is_file())


if __name__ == "__main__":
    unittest.main()
