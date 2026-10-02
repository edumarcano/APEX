from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.runtime_paths import RuntimePaths, resolve_runtime_paths
from core.config_documents import load_config_documents


class RuntimePathResolutionTests(unittest.TestCase):
    def test_invalid_optional_document_does_not_replace_valid_lower_layer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = root / "resources.json"
            operator = root / "operator.json"
            local = root / "local.json"
            defaults.write_text(
                '{"agent_system_prompt":"Keep the bundled prompt",'
                '"features":{"weather":false}}',
                encoding="utf-8",
            )
            operator.write_text("{broken", encoding="utf-8")
            local.write_text('{"features":{"weather":true}}', encoding="utf-8")
            merged = load_config_documents(defaults, operator, local)
            self.assertEqual(merged["agent_system_prompt"], "Keep the bundled prompt")
            self.assertTrue(merged["features"]["weather"])

    def test_source_defaults_and_absolute_override_are_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkout"
            override = Path(directory) / "operator-data"
            paths = resolve_runtime_paths({}, resource_root=root, frozen=False)
            self.assertEqual(paths, RuntimePaths(root.resolve(), root.resolve()))
            self.assertEqual(
                resolve_runtime_paths(
                    {"APEX_DATA_DIR": str(override)},
                    resource_root=root,
                    frozen=False,
                ).data_root,
                override.resolve(),
            )
            self.assertFalse(root.exists())
            self.assertFalse(override.exists())

    def test_selector_must_be_absolute_and_blank_uses_source_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkout"
            self.assertEqual(
                resolve_runtime_paths(
                    {"APEX_DATA_DIR": "  "}, resource_root=root, frozen=False
                ).data_root,
                root.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                resolve_runtime_paths(
                    {"APEX_DATA_DIR": "relative"}, resource_root=root, frozen=False
                )
            for invalid in ("C:/data/NUL", "C:/data/CON", "C:/data/bad\0name"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    resolve_runtime_paths(
                        {"APEX_DATA_DIR": invalid}, resource_root=root, frozen=False
                    )

    def test_frozen_profile_uses_localappdata_and_rejects_install_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resources = base / "install" / "_internal"
            executable = base / "install" / "APEX.exe"
            paths = resolve_runtime_paths(
                {"LOCALAPPDATA": str(base / "local")},
                resource_root=resources,
                frozen=True,
                executable_path=executable,
            )
            self.assertEqual(paths.data_root, (base / "local" / "APEX").resolve())
            for unsafe in (resources / "state", base / "install" / "state"):
                with self.subTest(unsafe=unsafe), self.assertRaisesRegex(
                    ValueError, "cannot be inside the frozen"
                ):
                    resolve_runtime_paths(
                        {"APEX_DATA_DIR": str(unsafe)},
                        resource_root=resources,
                        frozen=True,
                        executable_path=executable,
                    )

    def test_dotenv_cannot_retarget_profile_and_keeps_process_interpolation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected"
            other = root / "other"
            selected.mkdir()
            other.mkdir()
            (selected / ".env").write_text(
                f"APEX_DATA_DIR={other}\nBASE=file\nDERIVED=${{BASE}}\n",
                encoding="utf-8",
            )
            script = (
                "from core.runtime_paths import get_runtime_paths, initialize_environment; "
                "p=initialize_environment(); "
                "import subprocess,sys; "
                "child='from core.runtime_paths import get_runtime_paths; print(get_runtime_paths().data_root)'; "
                "print(p.data_root); print(__import__('os').environ['DERIVED']); "
                "print(subprocess.check_output([sys.executable,'-c',child], text=True).strip())"
            )
            env = os.environ.copy()
            env["APEX_DATA_DIR"] = str(selected)
            env["BASE"] = "process"
            env.pop("DERIVED", None)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            lines = completed.stdout.splitlines()
            self.assertEqual(lines[0], str(selected.resolve()))
            self.assertEqual(lines[1], "process")
            self.assertEqual(lines[2], str(selected.resolve()))
            self.assertFalse((other / "config.json").exists())

    def test_profile_dotenv_cannot_retarget_inherited_frozen_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_app_data = root / "local-app-data"
            selected = local_app_data / "APEX"
            other = root / "other"
            selected.mkdir(parents=True)
            other.mkdir()
            (selected / ".env").write_text(
                f"APEX_DATA_DIR={other}\n", encoding="utf-8"
            )
            child = (
                "import os,sys; sys.frozen=True; "
                "sys._MEIPASS=os.environ['TEST_RESOURCE_ROOT']; "
                "sys.executable=os.environ['TEST_EXECUTABLE']; "
                "from core.runtime_paths import get_runtime_paths; "
                "print(get_runtime_paths().data_root)"
            )
            script = (
                "import os,sys,subprocess; sys.frozen=True; "
                "sys._MEIPASS=os.environ['TEST_RESOURCE_ROOT']; "
                "sys.executable=os.environ['TEST_EXECUTABLE']; "
                "from core.runtime_paths import initialize_environment; "
                "p=initialize_environment(); print(p.data_root); child="
                + repr(child)
                + "; print(subprocess.check_output([os.environ['TEST_PYTHON'],'-c',child], text=True).strip()); "
                "print(os.environ.get('APEX_DATA_DIR','<missing>'))"
            )
            env = os.environ.copy()
            env.pop("APEX_DATA_DIR", None)
            env["LOCALAPPDATA"] = str(local_app_data)
            env["TEST_RESOURCE_ROOT"] = str(root / "resources")
            env["TEST_EXECUTABLE"] = str(root / "install" / "APEX.exe")
            env["TEST_PYTHON"] = sys.executable
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                completed.stdout.splitlines(),
                [str(selected.resolve()), str(selected.resolve()), "<missing>"],
            )

    def test_dotenv_disabled_flag_prevents_profile_values_from_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile"
            profile.mkdir()
            (profile / ".env").write_text("PROFILE_TEST_VALUE=from-file\n", encoding="utf-8")
            script = (
                "from core.runtime_paths import initialize_environment; initialize_environment(); "
                "import os; print(os.environ.get('PROFILE_TEST_VALUE', '<missing>'))"
            )
            env = os.environ.copy()
            env["APEX_DATA_DIR"] = str(profile)
            env["PYTHON_DOTENV_DISABLED"] = "YeS"
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env.pop("PROFILE_TEST_VALUE", None)
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.stdout.strip(), "<missing>")

    def test_malformed_local_tts_shape_does_not_block_config_or_store_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "config.local.json").write_text(
                '{"tts_settings": []}\n', encoding="utf-8"
            )
            script = (
                "import core.config; "
                "from core.settings.store import RuntimeSettingsStore; "
                "print(core.config.PRIMARY_TTS); "
                "print(RuntimeSettingsStore().local_override_active)"
            )
            env = os.environ.copy()
            env["APEX_DATA_DIR"] = str(profile)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env.pop("PYTHON_DOTENV_DISABLED", None)
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=profile.parent,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.stdout.splitlines(), ["pyttsx3", "False"])


if __name__ == "__main__":
    unittest.main()
