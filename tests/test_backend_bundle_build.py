from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

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
