"""Focused checks for the synthetic installer fixture's safe overlay behavior."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_distribution_fixture import (
    BASELINE_COMMIT,
    FixtureBuildError,
    _apply_overlay,
    _fixture_sidecar,
    _overlay_digest,
    _validate_external_output,
)


class DistributionFixtureOverlayTests(unittest.TestCase):
    def test_overlay_preserves_baseline_versions_and_unrelated_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "current"
            checkout = root / "baseline"
            for relative in (
                "frontend/scripts/build-desktop.mjs",
                "frontend/scripts/prepare-desktop.mjs",
                "frontend/src-tauri/nsis/installer.nsi",
                "frontend/src-tauri/nsis/installer.nsi.upstream",
                "frontend/src-tauri/nsis/PROVENANCE.md",
                "frontend/src-tauri/tauri.conf.json",
                "frontend/package.json",
                "rust-toolchain.toml",
            ):
                (source / relative).parent.mkdir(parents=True, exist_ok=True)
                (source / relative).write_text(relative, encoding="utf-8")

            checkout_tauri = checkout / "frontend/src-tauri/tauri.conf.json"
            checkout_package = checkout / "frontend/package.json"
            checkout_tauri.parent.mkdir(parents=True, exist_ok=True)
            checkout_package.parent.mkdir(parents=True, exist_ok=True)
            checkout_tauri.write_text(json.dumps({
                "version": "2.0.0",
                "bundle": {"active": True, "resources": {"bundle/": "bundle/"}},
                "app": {"security": {"csp": "baseline-policy"}},
            }), encoding="utf-8")
            checkout_package.write_text(json.dumps({
                "name": "frontend",
                "scripts": {"build": "vite build"},
                "dependencies": {"react": "locked-version"},
            }), encoding="utf-8")
            (checkout / "pyproject.toml").write_text('[project]\nversion = "2.0.0"\n', encoding="utf-8")
            (checkout / "frontend/src-tauri/Cargo.toml").write_text('[package]\nname = "apex-desktop"\nversion = "2.0.0"\n', encoding="utf-8")
            (checkout / "frontend/src-tauri/Cargo.lock").write_text('[[package]]\nname = "apex-desktop"\nversion = "2.0.0"\n', encoding="utf-8")
            (checkout / "uv.lock").write_text('[[package]]\nname = "apex"\nversion = "2.0.0"\n', encoding="utf-8")

            current_tauri = json.loads(checkout_tauri.read_text(encoding="utf-8"))
            current_tauri["version"] = "2.1.0"
            current_tauri["bundle"]["windows"] = {"nsis": {"displayLanguageSelector": False}}
            (source / "frontend/src-tauri/tauri.conf.json").write_text(json.dumps(current_tauri), encoding="utf-8")
            current_package = {
                "name": "frontend",
                "scripts": {"build": "vite build", "desktop:package": "node scripts/build-desktop.mjs --package"},
                "dependencies": {"react": "newer-version-that-must-not-copy"},
            }
            (source / "frontend/package.json").write_text(json.dumps(current_package), encoding="utf-8")

            _apply_overlay(source, checkout, [
                "frontend/scripts/build-desktop.mjs",
                "frontend/scripts/prepare-desktop.mjs",
                "frontend/src-tauri/nsis/PROVENANCE.md",
                "frontend/src-tauri/nsis/installer.nsi",
                "frontend/src-tauri/nsis/installer.nsi.upstream",
                "frontend/src-tauri/tauri.conf.json",
                "frontend/package.json",
                "rust-toolchain.toml",
            ])

            result_tauri = json.loads(checkout_tauri.read_text(encoding="utf-8"))
            result_package = json.loads(checkout_package.read_text(encoding="utf-8"))
            self.assertEqual(result_tauri["version"], "2.0.0")
            self.assertEqual(result_tauri["app"]["security"]["csp"], "baseline-policy")
            self.assertEqual(result_tauri["bundle"]["resources"], {"bundle/": "bundle/"})
            self.assertEqual(result_tauri["bundle"]["windows"], {"nsis": {"displayLanguageSelector": False}})
            self.assertEqual(result_package["scripts"]["build"], "vite build")
            self.assertIn("desktop:package", result_package["scripts"])
            self.assertEqual(result_package["dependencies"], {"react": "locked-version"})

    def test_overlay_digest_uses_sorted_relative_paths_and_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "b.txt").write_bytes(b"second")
            (root / "a.txt").write_bytes(b"first")
            first = _overlay_digest(root, ["b.txt", "a.txt"])
            self.assertEqual(first, _overlay_digest(root, ["a.txt", "b.txt"]))
            (root / "a.txt").write_bytes(b"changed")
            self.assertNotEqual(first, _overlay_digest(root, ["a.txt", "b.txt"]))

    def test_fixture_output_must_be_empty_and_outside_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            with self.assertRaises(FixtureBuildError):
                _validate_external_output(repo / "build", repo)
            nonempty = root / "nonempty"
            nonempty.mkdir()
            (nonempty / "keep.txt").write_text("operator data", encoding="utf-8")
            with self.assertRaises(FixtureBuildError):
                _validate_external_output(nonempty, repo)
            self.assertEqual((nonempty / "keep.txt").read_text(encoding="utf-8"), "operator data")

    def test_sidecar_records_approved_baseline_and_installer_identity(self) -> None:
        sidecar = _fixture_sidecar(
            base_commit=BASELINE_COMMIT,
            fixture_commit="a" * 40,
            overlay_sha256="b" * 64,
            backend_build_id="build-identifier",
            installer_name="APEX_2.0.0_x64-setup.exe",
            installer_sha256="c" * 64,
        )
        self.assertEqual(sidecar["kind"], "synthetic_upgrade_fixture")
        self.assertEqual(sidecar["app_version"], "2.0.0")
        self.assertEqual(sidecar["base_commit"], BASELINE_COMMIT)
        self.assertEqual(sidecar["installer_name"], "APEX_2.0.0_x64-setup.exe")


if __name__ == "__main__":
    unittest.main()
