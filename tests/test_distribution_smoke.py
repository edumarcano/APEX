from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from scripts import provision_distribution_smoke_assets as assets
from scripts import smoke_distribution as distribution


def _create_test_junction(link: Path, target: Path, workdir: Path) -> None:
    creator = workdir / "create-test-junction.ps1"
    creator.write_text(
        "param([Parameter(Mandatory=$true)][string]$Link, [Parameter(Mandatory=$true)][string]$Target)\n"
        "New-Item -ItemType Junction -Path $Link -Target $Target -ErrorAction Stop | Out-Null\n",
        encoding="utf-8-sig",
    )
    result = distribution._run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(creator), str(link), str(target)],
        cwd=workdir,
        timeout=20,
    )
    if result.returncode != 0 or not os.path.isjunction(link):
        raise AssertionError("Windows test junction could not be created")


class DistributionSmokeGuardTests(unittest.TestCase):
    def test_refuses_operator_account_even_when_profile_marker_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            local = user / "AppData" / "Local"
            local.mkdir(parents=True)
            marker = local / distribution.PROFILE_MARKER
            marker.write_text("APEX-DISTRIBUTION-SMOKE:fixture-identifier:S-1-5-21-2", encoding="utf-8")
            with patch.dict(os.environ, {
                "LOCALAPPDATA": str(local),
                "USERPROFILE": str(user),
                "APEX_DISTRIBUTION_SMOKE_PROFILE": "1",
                "APEX_DISTRIBUTION_SMOKE_OPERATOR_SID": "S-1-5-21-1",
            }), patch.object(distribution, "_current_sid", return_value="S-1-5-21-1"):
                with self.assertRaisesRegex(distribution.DistributionError, "operator's Windows account"):
                    distribution._guard_disposable_profile(local)

    def test_requires_marker_bound_to_registered_disposable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            local = user / "AppData" / "Local"
            local.mkdir(parents=True)
            (local / distribution.PROFILE_MARKER).write_text(
                "APEX-DISTRIBUTION-SMOKE:fixture-identifier:S-1-5-21-2", encoding="utf-8"
            )
            profile_info = json.dumps({"SID": "S-1-5-21-2", "LocalPath": str(user), "Special": False})
            completed = type("Result", (), {"returncode": 0, "stdout": profile_info})()
            with patch.dict(os.environ, {
                "LOCALAPPDATA": str(local),
                "USERPROFILE": str(user),
                "APEX_DISTRIBUTION_SMOKE_PROFILE": "1",
                "APEX_DISTRIBUTION_SMOKE_OPERATOR_SID": "S-1-5-21-1",
            }), patch.object(distribution, "_current_sid", return_value="S-1-5-21-2"), patch.object(
                distribution, "_run", return_value=completed,
            ):
                distribution._guard_disposable_profile(local)

    @unittest.skipUnless(os.name == "nt", "directory junction containment is a Windows path check")
    def test_guard_accepts_directory_junction_resolving_inside_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "DisposableUser"
            actual_local = user / "AppData" / "Local"
            actual_local.mkdir(parents=True)
            alias_local = root / "LocalAlias"
            _create_test_junction(alias_local, actual_local, root)
            (actual_local / distribution.PROFILE_MARKER).write_text(
                "APEX-DISTRIBUTION-SMOKE:fixture-identifier:S-1-5-21-2", encoding="utf-8"
            )
            profile_info = json.dumps({"SID": "S-1-5-21-2", "LocalPath": str(user), "Special": False})
            completed = type("Result", (), {"returncode": 0, "stdout": profile_info})()
            try:
                with patch.dict(os.environ, {
                    "LOCALAPPDATA": str(alias_local),
                    "USERPROFILE": str(user),
                    "APEX_DISTRIBUTION_SMOKE_PROFILE": "1",
                    "APEX_DISTRIBUTION_SMOKE_OPERATOR_SID": "S-1-5-21-1",
                }), patch.object(distribution, "_current_sid", return_value="S-1-5-21-2"), patch.object(
                    distribution, "_run", return_value=completed,
                ) as run:
                    distribution._guard_disposable_profile(alias_local)
                self.assertEqual(run.call_args.kwargs["cwd"], user.resolve())
            finally:
                # Remove the reparse point itself; never recurse through it.
                os.rmdir(alias_local)

    @unittest.skipUnless(os.name == "nt", "directory junction containment is a Windows path check")
    def test_guard_rejects_directory_junction_resolving_outside_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "DisposableUser"
            outside = root / "OutsideProfile"
            (user / "AppData").mkdir(parents=True)
            outside.mkdir()
            alias_local = user / "AppData" / "Local"
            _create_test_junction(alias_local, outside, root)
            (outside / distribution.PROFILE_MARKER).write_text(
                "APEX-DISTRIBUTION-SMOKE:fixture-identifier:S-1-5-21-2", encoding="utf-8"
            )
            completed = type("Result", (), {"returncode": 0, "stdout": ""})()
            try:
                with patch.dict(os.environ, {
                    "LOCALAPPDATA": str(alias_local),
                    "USERPROFILE": str(user),
                    "APEX_DISTRIBUTION_SMOKE_PROFILE": "1",
                    "APEX_DISTRIBUTION_SMOKE_OPERATOR_SID": "S-1-5-21-1",
                }), patch.object(distribution, "_current_sid", return_value="S-1-5-21-2"), patch.object(
                    distribution, "_run", return_value=completed,
                ) as run:
                    with self.assertRaisesRegex(distribution.DistributionError, "outside the current Windows user profile"):
                        distribution._guard_disposable_profile(alias_local)
                    run.assert_not_called()
            finally:
                # Remove the reparse point itself; never recurse through it.
                os.rmdir(alias_local)

    def test_owned_process_inventory_requires_creation_time_match(self) -> None:
        root = Path("C:/Users/test/AppData/Local/Programs/APEX")
        key = (42, os.path.normcase(os.path.abspath(str(root / "backend-bundle" / "apex-backend.exe"))))
        before = {key: "20261007123456.000000-240"}
        distribution._assert_owned_processes_unchanged(before, dict(before), root)
        with self.assertRaisesRegex(distribution.DistributionError, "terminated or replaced"):
            distribution._assert_owned_processes_unchanged(before, {key: "20261007123457.000000-240"}, root)

    def test_startup_effective_state_requires_exact_path_and_enabled_os_approval(self) -> None:
        executable = Path("C:/Users/test/AppData/Local/Programs/APEX/apex-desktop.exe")
        expected = f'"{executable.resolve()}" --autostart'
        enabled = bytes([2]) + bytes(11)
        with patch.object(distribution, "_run_value_and_approval", return_value=(expected, enabled)):
            self.assertTrue(distribution._startup_enabled_for(executable))
        disabled = bytes([3]) + bytes(11)
        with patch.object(distribution, "_run_value_and_approval", return_value=(expected, disabled)):
            self.assertFalse(distribution._startup_enabled_for(executable))
        with patch.object(distribution, "_run_value_and_approval", return_value=(expected + " --other", enabled)):
            self.assertFalse(distribution._startup_enabled_for(executable))

    def test_startup_fixture_cleanup_deletes_only_the_exact_owned_run_value(self) -> None:
        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        class Registry:
            HKEY_CURRENT_USER = object()
            KEY_QUERY_VALUE = 1
            KEY_SET_VALUE = 2
            REG_BINARY = 3
            values = {distribution.APP_NAME: ('"C:\\Windows\\System32\\notepad.exe" --foreign', 1)}
            open_accesses: list[int] = []

            @classmethod
            def OpenKey(cls, _root: object, _path: str, _reserved: int = 0, access: int = 0) -> Key:
                cls.open_accesses.append(access)
                return Key()

            @classmethod
            def QueryValueEx(cls, _key: Key, name: str) -> tuple[str, int]:
                return cls.values[name]

            @classmethod
            def DeleteValue(cls, _key: Key, name: str) -> None:
                del cls.values[name]

        foreign = Registry.values[distribution.APP_NAME][0]
        with patch.object(distribution, "winreg", Registry):
            with self.assertRaisesRegex(distribution.DistributionError, "fixture changed unexpectedly"):
                distribution._remove_run_value_if_matches('"C:\\Users\\test\\APEX.exe" --autostart')
            self.assertEqual(Registry.values[distribution.APP_NAME][0], foreign)
            distribution._remove_run_value_if_matches(foreign)
            Registry.values[distribution.APP_NAME] = (bytes([2]) + bytes(11), Registry.REG_BINARY)
            distribution._remove_approval_if_matches(bytes([2]) + bytes(11))
        self.assertNotIn(distribution.APP_NAME, Registry.values)
        self.assertEqual(Registry.open_accesses, [3, 3, 3])

    @unittest.skipUnless(os.name == "nt", "the current-account SID is a Windows API check")
    def test_current_sid_comes_from_windows_identity(self) -> None:
        self.assertRegex(distribution._current_sid(), r"^S-1-[0-9-]+$")

    def test_installed_backend_metadata_is_read_from_pyinstaller_internal_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            (bundle / "_internal").mkdir()
            (bundle / "build-info.json").write_text(json.dumps({"build_id": "wrong-root"}), encoding="utf-8")
            expected = {"build_id": "bundle-root", "application_version": "2.0.0", "commit": "a" * 40}
            (bundle / "_internal" / "build-info.json").write_text(json.dumps(expected), encoding="utf-8")
            build_info = distribution._bundle_build_info(bundle)
            self.assertEqual(build_info, expected)
            fixture = {"fixture_commit": "a" * 40, "backend_build_id": "bundle-root"}
            distribution._validate_previous_build(fixture, build_info, "2.0.0")
            with self.assertRaisesRegex(distribution.DistributionError, "fixture commit"):
                distribution._validate_previous_build({**fixture, "fixture_commit": "b" * 40}, build_info, "2.0.0")

    @unittest.skipUnless(os.name == "nt", "shortcut AppUserModelID is a Windows Shell property")
    def test_shortcut_property_reader_handles_apostrophe_and_spaces_without_launching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shortcut_dir = root / "O'Brien and spaces"
            shortcut_dir.mkdir()
            shortcut = shortcut_dir / "APEX fixture.lnk"
            creator = root / "create-shortcut.ps1"
            creator.write_text(
                "param([Parameter(Mandatory=$true)][string]$ShortcutPath)\n"
                "$shell = New-Object -ComObject WScript.Shell\n"
                "$link = $shell.CreateShortcut($ShortcutPath)\n"
                "$link.TargetPath = Join-Path $env:WINDIR 'System32\\notepad.exe'\n"
                "$link.Save()\n",
                encoding="utf-8-sig",
            )
            created = distribution._run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(creator), str(shortcut)],
                cwd=root,
                timeout=20,
            )
            self.assertEqual(created.returncode, 0, created.stdout)
            self.assertTrue(shortcut.is_file())
            # The fixture intentionally has no AUMID; success proves the
            # production helper safely opened the shortcut and read property.
            self.assertEqual(distribution._shortcut_app_id(shortcut, cwd=root), "")

    def test_runtime_identity_uses_production_data_root_fingerprint_contract(self) -> None:
        data = Path("C:/Users/test/AppData/Local/APEX")
        build = {"build_id": "build-identifier"}
        identity = {
            "app_id": "apex", "app_version": "2.1.0", "build_id": "build-identifier",
            "pid": 123, "launch_id": "launch-token", "hosting_mode": "managed",
            "data_root_fingerprint": distribution._data_root_fingerprint(data),
        }
        distribution._validate_runtime_identity(
            identity, app_version="2.1.0", build_info=build, data_root=data, pid=123, launch_id="launch-token",
        )
        identity["data_root_fingerprint"] = "path-string-is-not-the-contract"
        with self.assertRaisesRegex(distribution.DistributionError, "runtime identity"):
            distribution._validate_runtime_identity(
                identity, app_version="2.1.0", build_info=build, data_root=data, pid=123, launch_id="launch-token",
            )

    @unittest.skipUnless(os.name == "nt", "the embedded PE manifest is a Windows resource")
    def test_embedded_manifest_native_calls_use_pointer_sized_signatures(self) -> None:
        class NativeCall:
            def __init__(self, result: int) -> None:
                self.result = result
                self.argtypes = None
                self.restype = None

            def __call__(self, *_args: object) -> int:
                return self.result

        kernel32 = SimpleNamespace(
            LoadLibraryExW=NativeCall(0x12345678),
            FindResourceW=NativeCall(1),
            FreeLibrary=NativeCall(1),
        )
        with patch("ctypes.WinDLL", return_value=kernel32):
            self.assertTrue(distribution._has_embedded_manifest(Path("apex-desktop.exe")))
        self.assertEqual(kernel32.LoadLibraryExW.argtypes[0], __import__("ctypes").c_wchar_p)
        self.assertEqual(kernel32.LoadLibraryExW.restype, __import__("ctypes").c_void_p)
        self.assertEqual(kernel32.FindResourceW.argtypes[0], __import__("ctypes").c_void_p)
        self.assertEqual(kernel32.FindResourceW.restype, __import__("ctypes").c_void_p)
        self.assertEqual(kernel32.FreeLibrary.argtypes, [__import__("ctypes").c_void_p])


class DistributionAssetManifestTests(unittest.TestCase):
    def test_pinned_assets_have_immutable_hashes_and_bounded_lengths(self) -> None:
        manifest = assets._source_manifest()
        for source in manifest["assets"].values():
            for name, item in source["files"].items():
                self.assertTrue(name)
                self.assertGreater(item["bytes"], 0)
                self.assertRegex(item["sha256"], r"^[a-f0-9]{64}$")
            self.assertRegex(source["revision"], r"^[a-f0-9]{40}$")

    def test_asset_verification_rejects_tampered_or_truncated_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.onnx"
            payload = b"synthetic model asset"
            path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            assets._verify_asset(path, len(payload), digest)
            with self.assertRaises(assets.ProvisionError):
                assets._verify_asset(path, len(payload) + 1, digest)
            path.write_bytes(payload + b"!")
            with self.assertRaises(assets.ProvisionError):
                assets._verify_asset(path, len(payload) + 1, digest)

    def test_fastembed_offline_default_ref_points_to_only_the_pinned_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            revision = "1" * 40
            snapshot = cache / "models--qdrant--bge-small-en-v1.5-onnx-q" / "snapshots" / revision
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            ref = assets._write_fastembed_default_ref(cache, "qdrant/bge-small-en-v1.5-onnx-q", revision)
            self.assertEqual(ref.relative_to(cache).as_posix(), "models--qdrant--bge-small-en-v1.5-onnx-q/refs/main")
            self.assertEqual(ref.read_bytes(), revision.encode("ascii"))
            from huggingface_hub import snapshot_download

            resolved = Path(snapshot_download(
                repo_id="qdrant/bge-small-en-v1.5-onnx-q",
                revision="main",
                cache_dir=str(cache),
                local_files_only=True,
            ))
            self.assertEqual(resolved.resolve(), snapshot.resolve())
            self.assertEqual((resolved / "config.json").read_text(encoding="utf-8"), "{}")
            with self.assertRaises(assets.ProvisionError):
                assets._write_fastembed_default_ref(cache, "qdrant/bge-small-en-v1.5-onnx-q", "2" * 40)

    def test_notification_history_delta_and_copy_require_exact_generic_text(self) -> None:
        old = {"records": ["<toast><text>old</text></toast>"]}
        new = {"records": ["<toast><text>old</text></toast>", "<toast><text>APEX</text><text>An APEX run has completed.</text></toast>"]}
        additions = distribution._added_toasts(old, new)
        self.assertEqual(len(additions), 1)
        distribution._require_generic_apex_toast(additions[0])
        with self.assertRaisesRegex(distribution.DistributionError, "approved generic"):
            distribution._require_generic_apex_toast("<toast><text>APEX</text><text>Private prompt text</text></toast>")

    def test_refuses_destination_inside_repository(self) -> None:
        with self.assertRaisesRegex(assets.ProvisionError, "outside the repository"):
            assets.provision(assets.REPOSITORY_ROOT / "build" / "distribution-test-assets")


if __name__ == "__main__":
    unittest.main()
