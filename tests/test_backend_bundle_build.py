from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

from scripts import build_backend_bundle as builder


ROOT = Path(__file__).resolve().parents[1]
COLLECTION_PATH = ROOT / "packaging" / "windows" / "collection.py"
COLLECTION_SPEC = importlib.util.spec_from_file_location(
    "apex_test_bundle_collection", COLLECTION_PATH
)
assert COLLECTION_SPEC is not None and COLLECTION_SPEC.loader is not None
COLLECTION = importlib.util.module_from_spec(COLLECTION_SPEC)
COLLECTION_SPEC.loader.exec_module(COLLECTION)


class BackendBundleBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = builder.BUILD_ROOT / "test-temp"
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def test_collection_selects_only_approved_resource_files(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temporary:
            root = Path(temporary)
            files = (
                "config.json",
                "build-info.json",
                "README.md",
                "core/mock/assistant.json",
                "core/mock/telemetry.json",
                "docs/retrieval/guide.md",
            )
            for name in files:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            (root / "config.local.json").write_text("{}\n", encoding="utf-8")
            (root / "apex_memory.db").write_bytes(b"operator data")
            (root / "docs" / "notes.txt").write_text("not retrieval markdown", encoding="utf-8")

            selected = COLLECTION.bundle_datas(root)

            selected_paths = {Path(source).relative_to(root).as_posix() for source, _ in selected}
            self.assertEqual(selected_paths, set(files))
            self.assertNotIn("config.local.json", selected_paths)
            self.assertNotIn("apex_memory.db", selected_paths)
            self.assertNotIn("docs/notes.txt", selected_paths)

    def test_onnxruntime_collection_excludes_only_example_dataset_subtree(self) -> None:
        self.assertTrue(
            COLLECTION.is_onnxruntime_example_data_path(
                "_internal/onnxruntime/datasets/logreg_iris.onnx"
            )
        )
        self.assertTrue(
            COLLECTION.is_onnxruntime_example_data_path(
                r"onnxruntime\datasets\__init__.py"
            )
        )
        self.assertFalse(
            COLLECTION.is_onnxruntime_example_data_path(
                "_internal/onnxruntime/capi/onnxruntime_providers_shared.dll"
            )
        )
        self.assertFalse(
            COLLECTION.is_onnxruntime_example_data_path(
                "_internal/espeakng_loader/espeak-ng-data/phondata"
            )
        )
        self.assertTrue(COLLECTION.include_onnxruntime_submodule("onnxruntime.capi"))
        self.assertFalse(
            COLLECTION.include_onnxruntime_submodule("onnxruntime.datasets")
        )
        self.assertFalse(
            COLLECTION.include_onnxruntime_submodule("onnxruntime.datasets.example")
        )

    def test_package_collection_excludes_hooks_and_compiler_only_modules(self) -> None:
        self.assertEqual(
            COLLECTION.bundle_analysis_excludes(),
            ["numpy.f2py", "numpy._pyinstaller", "pygame.__pyinstaller", "setuptools"],
        )
        self.assertFalse(
            COLLECTION.include_runtime_submodule("numpy._pyinstaller.hook-numpy")
        )
        self.assertFalse(
            COLLECTION.include_runtime_submodule("pygame.__pyinstaller.hook-pygame")
        )
        self.assertFalse(COLLECTION.include_runtime_submodule("numpy.f2py.f2py2e"))
        self.assertFalse(COLLECTION.include_runtime_submodule("numpy._pytesttester"))
        self.assertTrue(COLLECTION.include_runtime_submodule("numpy.linalg"))
        self.assertTrue(
            COLLECTION.is_bundle_excluded_data_path("numpy/_pyinstaller/hook-numpy.py")
        )
        self.assertTrue(
            COLLECTION.is_bundle_excluded_data_path("numpy/f2py/f2py2e.py")
        )
        self.assertTrue(
            COLLECTION.is_bundle_excluded_data_path(
                "pygame/__pyinstaller/hook-pygame.py"
            )
        )
        self.assertFalse(
            COLLECTION.is_bundle_excluded_data_path(
                "espeakng_loader/espeak-ng-data/phondata"
            )
        )

    def test_package_collection_keeps_lazy_domain_exports_in_frozen_builds(self) -> None:
        hidden_imports = set(COLLECTION.bundle_hidden_imports())
        self.assertTrue({
            "core.conversations.service", "core.conversations.store",
            "core.runs.coordinator", "core.runs.models", "core.runs.service", "core.runs.store",
            "core.briefings.service", "core.briefings.store",
            "core.knowledge.service", "core.knowledge.store",
            "core.retrieval.models", "core.retrieval.service", "core.retrieval.store",
            "core.actions.models", "core.actions.runtime", "core.actions.service", "core.actions.store",
            "core.activity.models", "core.activity.service", "core.activity.store",
        }.issubset(hidden_imports))

    def test_build_info_is_deterministic_and_contains_no_machine_path(self) -> None:
        toolchain = builder._load_toolchain()
        lock_digest = "a" * 64
        first = builder.make_build_info(toolchain, "abcdef0123456789", lock_digest)
        second = builder.make_build_info(toolchain, "abcdef0123456789", lock_digest)

        self.assertEqual(first, second)
        self.assertLessEqual(len(first["build_id"]), 256)
        self.assertNotIn("/", first["build_id"])
        self.assertNotIn("\\", first["build_id"])
        serialized = json.dumps(first)
        self.assertNotIn(str(ROOT), serialized)
        self.assertEqual(first["lock_sha256"], lock_digest)
        self.assertEqual(first["extras"], ["tracing", "tts-google", "tts-kokoro"])
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(first["app_version"], project["version"])

    def test_manifest_hashes_sorted_files_and_omits_itself(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temporary:
            root = Path(temporary)
            (root / "z.txt").write_bytes(b"z")
            (root / "a.txt").write_bytes(b"a")

            manifest = builder.write_manifest(root, "build-id")

            self.assertEqual([item["path"] for item in manifest["files"]], ["a.txt", "z.txt"])
            self.assertEqual(len(manifest["files"]), 2)
            self.assertEqual(json.loads((root / "bundle-manifest.json").read_text())["build_id"], "build-id")

    def test_reproducibility_mismatch_summary_reports_bounded_relative_file_deltas(self) -> None:
        first = {
            "build_id": "first-build-id",
            "files": [
                {"path": "changed.bin", "sha256": "a", "size": 1},
                {"path": "removed.bin", "sha256": "b", "size": 1},
            ],
            "schema_version": 1,
        }
        second = {
            "build_id": "second-build-id",
            "files": [
                {"path": "added.bin", "sha256": "c", "size": 1},
                {"path": "changed.bin", "sha256": "d", "size": 2},
            ],
            "schema_version": 1,
        }

        summary = builder._manifest_difference_summary(first, second, sample_limit=1)

        self.assertIn("added files (1): added.bin", summary)
        self.assertIn("removed files (1): removed.bin", summary)
        self.assertIn("changed files (1): changed.bin", summary)
        self.assertIn("metadata fields differ: build_id", summary)
        self.assertNotIn("first-build-id", summary)
        self.assertNotIn("second-build-id", summary)

    def test_reproducibility_mismatch_summary_caps_path_samples(self) -> None:
        first = {"files": []}
        second = {
            "files": [
                {"path": f"changed/{index:02d}.bin", "sha256": str(index), "size": index}
                for index in range(12)
            ]
        }

        summary = builder._manifest_difference_summary(first, second, sample_limit=2)

        self.assertIn("added files (12): changed/00.bin, changed/01.bin, ... (+10)", summary)
        self.assertNotIn("changed/02.bin", summary)

    def test_reproducibility_helper_accepts_exit_one_and_projects_safe_schema(self) -> None:
        report = {
            "schema_version": 1,
            "equal": False,
            "summary": {"sha256": ["a" * 64, "b" * 64], "size_bytes": [10, 11]},
            "pe": {
                "changed_fields": ["TimeDateStamp"],
                "section_count": [3, 3],
                "changed_section_count": 1,
                "changed_sections": [".rsrc"],
            },
            "carchive": {
                "order_equal": True,
                "entry_count": [2, 2],
                "only_left_count": 0,
                "only_right_count": 0,
                "changed_payload_count": 0,
                "changed_entry_metadata_count": 0,
                "changed_script_count": 1,
                "serialization_only_script_count": 0,
                "only_left": [],
                "only_right": [],
                "changed_payloads": [],
                "changed_entry_metadata": [],
                "changed_scripts": ["apex_entry"],
                "changed_script_code_fields": ["co_consts"],
                "pyz": [],
                "base_library_zip": None,
            },
        }
        completed = mock.Mock(returncode=1, stdout=json.dumps(report), stderr="private diagnostic path")

        with mock.patch.object(builder.subprocess, "run", return_value=completed) as run:
            result = builder._executable_reproducibility_diagnostics(
                Path("isolated-python.exe"), Path("first.exe"), Path("second.exe")
            )

        self.assertIsNotNone(result)
        self.assertIn('"equal":false', result)
        self.assertIn('"changed_fields":["TimeDateStamp"]', result)
        self.assertIn('"changed_sections":[".rsrc"]', result)
        self.assertIn('"changed_script_code_fields":["co_consts"]', result)
        self.assertNotIn("private diagnostic path", result)
        self.assertEqual(run.call_args.args[0][0], "isolated-python.exe")

        report["carchive"]["changed_scripts"] = ["C:/Users/runner/private.py"]
        completed.stdout = json.dumps(report)
        with mock.patch.object(builder.subprocess, "run", return_value=completed):
            unsafe_result = builder._executable_reproducibility_diagnostics(
                Path("isolated-python.exe"), Path("first.exe"), Path("second.exe")
            )
        self.assertIsNone(unsafe_result)

    def test_forensic_helper_failure_does_not_hide_reproducibility_failure(self) -> None:
        first = {
            "build_id": "build-id",
            "files": [{"path": "apex-backend.exe", "sha256": "a", "size": 1}],
            "schema_version": 1,
        }
        second = {
            "build_id": "build-id",
            "files": [{"path": "apex-backend.exe", "sha256": "b", "size": 1}],
            "schema_version": 1,
        }
        timeout = subprocess.TimeoutExpired("forensic-helper", 180)

        with mock.patch.object(builder.subprocess, "run", side_effect=timeout):
            with self.assertRaises(builder.BundleBuildError) as raised:
                builder._raise_reproducibility_mismatch(
                    first, second, Path("isolated-python.exe"), Path("first.exe"), Path("second.exe")
                )

        self.assertIn("Controlled PyInstaller builds produced different file hashes", str(raised.exception))
        self.assertIn("changed files (1): apex-backend.exe", str(raised.exception))
        self.assertIn("executable diagnostics unavailable", str(raised.exception))

    def test_forensic_helper_rejects_unapproved_or_malformed_report_fields(self) -> None:
        invalid_results = (
            mock.Mock(returncode=2, stdout=json.dumps({"schema_version": 1, "error": "FileNotFoundError"}), stderr=""),
            mock.Mock(
                returncode=1,
                stdout=json.dumps({
                    "schema_version": 1,
                    "equal": False,
                    "local_path": "C:/Users/runner/private.exe",
                }),
                stderr="",
            ),
        )
        for completed in invalid_results:
            with mock.patch.object(builder.subprocess, "run", return_value=completed):
                result = builder._executable_reproducibility_diagnostics(
                    Path("isolated-python.exe"), Path("first.exe"), Path("second.exe")
                )

            self.assertIsNone(result)

    def test_backend_and_cli_entrypoints_expose_the_existing_commands(self) -> None:
        backend = subprocess.run(
            [sys.executable, str(ROOT / "packaging" / "windows" / "backend_entry.py"), "--help"],
            cwd=self.temp_root,
            capture_output=True,
            text=True,
            check=False,
        )
        cli = subprocess.run(
            [sys.executable, str(ROOT / "packaging" / "windows" / "cli_entry.py"), "--help"],
            cwd=self.temp_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(backend.returncode, 0, backend.stderr)
        self.assertIn("serve", backend.stdout)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertIn("Use the running local APEX backend", cli.stdout)


if __name__ == "__main__":
    unittest.main()
