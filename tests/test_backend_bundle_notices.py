from __future__ import annotations

import csv
import importlib.util
import tarfile
import tempfile
import unittest
from pathlib import Path

from importlib.metadata import PathDistribution

_NOTICES_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "notices.py"
_SPEC = importlib.util.spec_from_file_location("apex_bundle_notices", _NOTICES_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_NOTICES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_NOTICES)
_copy_license_files = _NOTICES._copy_license_files
_has_non_metadata_payload = _NOTICES._has_non_metadata_payload
_locked_runtime_names = _NOTICES._locked_runtime_names


class BackendBundleNoticeTests(unittest.TestCase):
    def _distribution(self, root: Path, *, with_license: bool = True) -> PathDistribution:
        dist_info = root / "fixture_runtime-1.2.3.dist-info"
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: fixture-runtime\nVersion: 1.2.3\n",
            encoding="utf-8",
        )
        record_paths = ["fixture_runtime-1.2.3.dist-info/METADATA"]
        if with_license:
            license_file = dist_info / "licenses" / "COPYING.txt"
            license_file.parent.mkdir()
            license_file.write_text("Original upstream license text.\n", encoding="utf-8")
            record_paths.append("fixture_runtime-1.2.3.dist-info/licenses/COPYING.txt")
            notice_file = dist_info / "ThirdPartyNotices.txt"
            notice_file.write_text("Original upstream third-party notice.\n", encoding="utf-8")
            record_paths.append("fixture_runtime-1.2.3.dist-info/ThirdPartyNotices.txt")
        with (dist_info / "RECORD").open("w", encoding="utf-8", newline="") as record:
            csv.writer(record).writerows((path, "", "") for path in record_paths)
        return PathDistribution(dist_info)

    def test_copies_actual_distribution_license_and_returns_relative_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            distribution = self._distribution(root / "site-packages")
            output = root / "bundle"

            inventory = _copy_license_files(distribution, output, "fixture-runtime", "1.2.3")

            self.assertEqual(len(inventory), 2)
            entry = inventory[0]
            self.assertEqual(entry["package"], "fixture-runtime")
            self.assertEqual(entry["version"], "1.2.3")
            self.assertFalse(str(root) in entry["path"])
            self.assertEqual(
                (output / entry["path"]).read_text(encoding="utf-8"),
                "Original upstream license text.\n" if "COPYING" in entry["path"] else "Original upstream third-party notice.\n",
            )

    def test_stages_hash_pinned_gpl_corresponding_sources(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "bundle"
            loader_source_archive = (
                repository_root
                / "packaging"
                / "windows"
                / "source-material"
                / "espeakng-loader-0.2.4-source.tar.gz"
            )
            with tarfile.open(loader_source_archive, "r:gz") as source_tar:
                source_member = next(
                    member
                    for member in source_tar.getmembers()
                    if member.isfile() and member.name.endswith("/espeakng_loader/__init__.py")
                )
                wrapper_bytes = source_tar.extractfile(source_member).read()
            dist_info = root / "site-packages" / "espeakng_loader-0.2.4.dist-info"
            dist_info.mkdir(parents=True)
            package_file = dist_info.parent / "espeakng_loader" / "__init__.py"
            package_file.parent.mkdir(parents=True)
            package_file.write_bytes(wrapper_bytes.replace(b"\n", b"\r\n"))
            (dist_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: espeakng-loader\nVersion: 0.2.4\n",
                encoding="utf-8",
            )
            (dist_info / "RECORD").write_text(
                "espeakng_loader/__init__.py,,\n",
                encoding="utf-8",
            )
            distribution = PathDistribution(dist_info)

            inventory = _NOTICES._stage_corresponding_sources(
                repository_root,
                output,
                {"phonemizer-fork", "espeakng-loader"},
                {"espeakng-loader": distribution},
            )

            packages = {entry["package"] for entry in inventory}
            self.assertIn("phonemizer-fork source", packages)
            self.assertIn("eSpeak NG source", packages)
            self.assertIn("espeakng-loader", packages)
            for entry in inventory:
                self.assertTrue((output / entry["path"]).is_file())
            license_entry = next(entry for entry in inventory if entry["package"] == "espeakng-loader")
            license_text = (output / license_entry["path"]).read_text(encoding="utf-8")
            self.assertIn("MIT License", license_text)
            self.assertIn("Copyright (c) 2025 thewh1teagle", license_text)

    def test_rejects_loader_wrapper_that_does_not_match_licensed_source(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist_info = root / "site-packages" / "espeakng_loader-0.2.4.dist-info"
            dist_info.mkdir(parents=True)
            package_file = dist_info.parent / "espeakng_loader" / "__init__.py"
            package_file.parent.mkdir(parents=True)
            package_file.write_text("# unrelated source\n", encoding="utf-8")
            (dist_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: espeakng-loader\nVersion: 0.2.4\n",
                encoding="utf-8",
            )
            (dist_info / "RECORD").write_text("espeakng_loader/__init__.py,,\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "differs from the source"):
                _NOTICES._stage_corresponding_sources(
                    repository_root,
                    root / "bundle",
                    {"espeakng-loader"},
                    {"espeakng-loader": PathDistribution(dist_info)},
                )

    def test_fails_when_distribution_has_no_license_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            distribution = self._distribution(root / "site-packages", with_license=False)

            with self.assertRaisesRegex(RuntimeError, "no installed LICENSE"):
                _copy_license_files(distribution, root / "bundle", "fixture-runtime", "1.2.3")

    def test_missing_record_inventory_fails_closed_instead_of_classifying_package_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dist_info = Path(temporary) / "fixture_runtime-1.2.3.dist-info"
            dist_info.mkdir()
            (dist_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: fixture-runtime\nVersion: 1.2.3\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "no installed RECORD inventory"):
                _has_non_metadata_payload(PathDistribution(dist_info))

    def test_extracts_original_pygame_licenses_from_locked_source_distribution(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist_info = root / "site-packages" / "pygame_ce-2.5.7.dist-info"
            dist_info.mkdir(parents=True)
            (dist_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: pygame-ce\nVersion: 2.5.7\n",
                encoding="utf-8",
            )
            (dist_info / "RECORD").write_text("", encoding="utf-8")

            inventory = _NOTICES._stage_locked_sdist_licenses(
                repository_root, root / "bundle", PathDistribution(dist_info)
            )

            contents = [(root / "bundle" / entry["path"]).read_text(encoding="utf-8") for entry in inventory]
            self.assertTrue(any("GNU LESSER GENERAL PUBLIC LICENSE" in text for text in contents))
            self.assertTrue(any("Simple DirectMedia Layer" in text for text in contents))
            self.assertTrue(any("FreeType" in text for text in contents))

    def test_stages_native_library_licenses_only_for_matching_wheel_versions(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site_packages = root / "site-packages"
            dist_info = site_packages / "pygame_ce-2.5.7.dist-info"
            dist_info.mkdir(parents=True)
            (dist_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: pygame-ce\nVersion: 2.5.7\n",
                encoding="utf-8",
            )
            (dist_info / "RECORD").write_text(
                "pygame/libxmp.dll,,\npygame/libwavpack-1.dll,,\n", encoding="utf-8"
            )
            pygame = site_packages / "pygame"
            pygame.mkdir()
            (pygame / "libxmp.dll").write_bytes(b"upstream libxmp 4.6.1")
            (pygame / "libwavpack-1.dll").write_bytes(b"upstream WavPack 5.6.0")

            inventory = _NOTICES._stage_pygame_native_licenses(
                repository_root, root / "bundle", PathDistribution(dist_info)
            )

            self.assertEqual(
                {(entry["package"], entry["version"]) for entry in inventory if entry["kind"] == "verified-native-license"},
                {("libxmp", "4.6.1"), ("WavPack", "5.6.0")},
            )

    def test_stages_exact_upstream_license_texts_for_wheels_that_omit_them(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                ("fastmcp_slim-3.4.4", "fastmcp-slim", "3.4.4", _NOTICES._stage_fastmcp_slim_license),
                ("flatbuffers-25.12.19", "flatbuffers", "25.12.19", _NOTICES._stage_flatbuffers_license),
                ("loguru-0.7.3", "loguru", "0.7.3", _NOTICES._stage_loguru_license),
            )
            for folder, name, version, stage in cases:
                with self.subTest(package=name):
                    dist_info = root / folder / f"{name}-{version}.dist-info"
                    dist_info.mkdir(parents=True)
                    (dist_info / "METADATA").write_text(
                        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
                        encoding="utf-8",
                    )
                    (dist_info / "RECORD").write_text("", encoding="utf-8")

                    inventory = stage(repository_root, root / "bundle", PathDistribution(dist_info))

                    self.assertEqual(len(inventory), 1)
                    self.assertTrue((root / "bundle" / inventory[0]["path"]).is_file())

    def test_locked_runtime_closure_includes_all_project_extras_and_omits_dev_group(self) -> None:
        lock_path = Path(__file__).resolve().parents[1] / "uv.lock"

        names = _locked_runtime_names(lock_path)

        self.assertIn("google-cloud-texttospeech", names)
        self.assertIn("opentelemetry-sdk", names)
        self.assertIn("espeakng-loader", names)
        self.assertNotIn("httpx2", names)


if __name__ == "__main__":
    unittest.main()
