"""Tests for the runtime settings store foundation."""

from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from core.settings.models import (
    AssistantPatch,
    FeaturesPatch,
    ModulesPatch,
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
        import tempfile

        self._dir = Path(tempfile.mkdtemp(prefix="apex_settings_"))
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
                "default_cloud_profile": "comet",
            },
            "tts_settings": {
                "primary_tts": "google",
                "voice_gender": "female",
            },
            "system_prompt": "ignored by settings store",
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
        self.assertTrue(snap.assistant.enabled)
        self.assertEqual(snap.assistant.default_profile, "comet")
        self.assertEqual(snap.voice.engine, "google")
        self.assertEqual(snap.voice.gender, "female")
        self.assertFalse(store.local_file_present)
        self.assertIsNone(store.load_warning)

    def test_base_plus_local_loading(self) -> None:
        _write_json(
            self.local_path,
            {
                "features": {"news": True},
                "ask_apex": {"enabled": False, "default_profile": "nova"},
                "tts_settings": {"primary_tts": "kokoro"},
            },
        )
        store = self._store()
        snap = store.get_snapshot()
        self.assertTrue(snap.features.weather)
        self.assertTrue(snap.features.news)
        self.assertFalse(snap.assistant.enabled)
        self.assertEqual(snap.assistant.default_profile, "nova")
        self.assertEqual(snap.voice.engine, "kokoro")
        self.assertEqual(snap.voice.gender, "female")
        self.assertTrue(store.local_file_present)

    def test_local_agent_profile_loading(self) -> None:
        for profile in ("lynx", "acinonyx", "neofelis"):
            with self.subTest(profile=profile):
                _write_json(
                    self.local_path,
                    {"ask_apex": {"default_profile": profile}},
                )
                store = self._store()
                self.assertEqual(
                    store.get_snapshot().assistant.default_profile, profile
                )

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
                "ask_apex": {"default_cloud_profile": "pulsar"},
                "tts_settings": {"primary_tts": "piper", "voice_gender": "male"},
            },
        )
        store = self._store()
        snap = store.get_snapshot()
        self.assertEqual(snap.assistant.default_profile, "pulsar")
        self.assertEqual(snap.voice.engine, "pyttsx3")
        self.assertEqual(snap.voice.gender, "male")

    def test_new_key_precedence_when_both_exist(self) -> None:
        _write_json(
            self.config_path,
            {
                "ask_apex": {
                    "default_cloud_profile": "comet",
                    "default_profile": "nova",
                }
            },
        )
        store = self._store()
        self.assertEqual(store.get_snapshot().assistant.default_profile, "nova")

        normalized = normalize_layer(
            {
                "ask_apex": {
                    "default_profile": "pulsar",
                    "default_cloud_profile": "comet",
                }
            },
            layer_name="test",
        )
        self.assertEqual(normalized["ask_apex"]["default_profile"], "pulsar")

    def test_missing_local_file(self) -> None:
        store = self._store()
        self.assertFalse(store.local_file_present)
        self.assertIsNone(store.load_warning)

    def test_malformed_local_uses_base_with_warning(self) -> None:
        self.local_path.write_text("{not-json", encoding="utf-8")
        store = self._store()
        snap = store.get_snapshot()
        self.assertTrue(snap.features.weather)
        self.assertEqual(snap.assistant.default_profile, "comet")
        self.assertIsNotNone(store.load_warning)
        self.assertFalse(store.local_file_present)

    def test_invalid_local_root_uses_base_with_warning(self) -> None:
        self.local_path.write_text("[1, 2, 3]\n", encoding="utf-8")
        store = self._store()
        self.assertTrue(store.get_snapshot().features.weather)
        self.assertIsNotNone(store.load_warning)

    def test_invalid_local_value_discards_entire_override(self) -> None:
        _write_json(
            self.local_path,
            {
                "features": {"weather": "yes", "unknown_feature": True},
                "modules": {"f1": True, "hockey": True},
                "ask_apex": {"default_profile": "not-a-profile", "mystery": 1},
                "tts_settings": {"primary_tts": "watson", "extra": True},
                "totally_unknown": {"x": 1},
            },
        )
        store = self._store()
        snap = store.get_snapshot()
        # Invalid weather ignored → base True remains.
        self.assertTrue(snap.features.weather)
        self.assertTrue(snap.modules.f1)
        # Invalid profile ignored → base comet remains.
        self.assertEqual(snap.assistant.default_profile, "comet")
        # Invalid engine ignored → base google remains.
        self.assertEqual(snap.voice.engine, "google")
        self.assertIsNotNone(store.load_warning)
        self.assertFalse(store.local_file_present)

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


class SettingsStorePatchTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = Path(tempfile.mkdtemp(prefix="apex_settings_patch_"))
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
                "ask_apex": {"enabled": True, "default_cloud_profile": "comet"},
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

    def test_strict_rejection_of_unknown_patch_fields(self) -> None:
        with self.assertRaises(ValidationError):
            SettingsPatch.model_validate({"features": {"weather": True, "xyz": True}})
        with self.assertRaises(ValidationError):
            SettingsPatch.model_validate({"unknown_root": {"a": 1}})

    def test_local_profiles_are_valid_patch_values(self) -> None:
        for profile in ("lynx", "acinonyx", "neofelis"):
            with self.subTest(profile=profile):
                patch = SettingsPatch.model_validate(
                    {"assistant": {"default_profile": profile}}
                )
                self.assertEqual(patch.assistant.default_profile, profile)

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
                    SettingsPatch(assistant=AssistantPatch(enabled=False))
                )

        after = store.get_snapshot()
        self.assertEqual(after.assistant.enabled, prior.assistant.enabled)
        self.assertTrue(after.assistant.enabled)
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
            SettingsPatch(assistant=AssistantPatch(default_profile="nova"))
        )
        store.apply_patch(
            SettingsPatch(assistant=AssistantPatch(default_profile="pulsar"))
        )
        self.assertEqual(
            store.get_snapshot().assistant.default_profile, "pulsar"
        )
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["ask_apex"]["default_profile"], "pulsar")
        self.assertNotIn("default_cloud_profile", written["ask_apex"])


class SettingsStoreConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = Path(tempfile.mkdtemp(prefix="apex_settings_conc_"))
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
                "ask_apex": {"enabled": True, "default_cloud_profile": "comet"},
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
                    _ = snap.assistant.default_profile
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
        # Both writers should have left the store in a valid state.
        self.assertIn(snap.features.weather, (True, False))
        self.assertIn(snap.modules.f1, (True, False))
        self.assertTrue(self.local_path.is_file())

    def test_concurrent_same_field_last_write_semantics(self) -> None:
        results: list[str] = []
        lock = threading.Lock()
        start = threading.Barrier(2)

        def write_profile(profile: str, delay: float) -> None:
            start.wait(timeout=5)
            time.sleep(delay)
            snap = self.store.apply_patch(
                SettingsPatch(
                    assistant=AssistantPatch(default_profile=profile)  # type: ignore[arg-type]
                )
            )
            with lock:
                results.append(snap.assistant.default_profile)

        t1 = threading.Thread(target=write_profile, args=("nova", 0.0))
        t2 = threading.Thread(target=write_profile, args=("pulsar", 0.05))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertEqual(len(results), 2)
        # Last successful write should be reflected in the published snapshot.
        self.assertEqual(self.store.get_snapshot().assistant.default_profile, "pulsar")


if __name__ == "__main__":
    unittest.main()
