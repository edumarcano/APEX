"""Safety and fidelity tests for copy-import of an APEX data profile."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from io import BytesIO
from contextlib import closing
from pathlib import Path
from unittest import mock
from uuid import uuid4

from core.activity.store import ActivityStore
from core.briefings.store import BriefingSessionStore
from core.conversations.store import ConversationStore
from core.data_import.engine import ImportEngine, ImportOperationError
from core.knowledge.store import KnowledgeStore
from core.retrieval.store import RetrievalStore
from core.runs.store import RunStore
from core.runtime_paths import RuntimePaths


class DataImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="apex-import-")
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.destination = self.base / "destination"
        self.source.mkdir()
        self.paths = RuntimePaths(resource_root=self.destination, data_root=self.destination)
        self.database = self.source / "apex_memory.db"
        self._initialize_source()
        self.engine = ImportEngine(self.paths)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _initialize_source(self) -> None:
        from core import database

        with closing(sqlite3.connect(self.database)) as connection:
            database.initialize_db(connection=connection)
        stores = (
            ConversationStore(self.database), RunStore(self.database),
            BriefingSessionStore(self.database), KnowledgeStore(self.database),
            ActivityStore(self.database), RetrievalStore(self.database),
        )
        try:
            for store in stores:
                store.initialize()
        finally:
            for store in stores:
                store.close()

    def test_import_preserves_database_and_source_bytes(self) -> None:
        conversations = ConversationStore(self.database)
        conversation_id = uuid4()
        conversations.create(
            conversation_id=conversation_id, title="Historical conversation",
            partition="production", origin="hud", agent="apex",
            selected_tool_names=None, tool_profile_id=None,
        )
        conversations.close()
        (self.source / "config.json").write_text('{"theme":"dark"}\n', encoding="utf-8")
        (self.source / ".env").write_text(
            "OPENAI_API_KEY=placeholder\nMICROSOFT_TODO_TOKEN_CACHE_PATH=C:\\old\\cache.bin\n",
            encoding="utf-8",
        )
        weight_dir = self.source / "weights" / "fastembed"
        weight_dir.mkdir(parents=True)
        (weight_dir / "model.bin").write_bytes(b"managed-weight")
        before = {
            path.relative_to(self.source).as_posix(): path.read_bytes()
            for path in self.source.rglob("*") if path.is_file()
        }
        self.assertFalse((self.source / ".apex-host.lock").exists())

        preview = self.engine.preview(str(self.source))
        self.assertTrue(preview["can_import"], preview["blockers"])
        result = self.engine.import_data(str(self.source), str(preview["preview_id"]))

        self.assertEqual(result["phase"], "ready")
        with closing(sqlite3.connect(self.destination / "apex_memory.db")) as connection:
            copied_title = connection.execute(
                "SELECT title FROM conversations WHERE id=?", (str(conversation_id),)
            ).fetchone()
        self.assertEqual(copied_title, ("Historical conversation",))
        self.assertEqual((self.destination / "weights/fastembed/model.bin").read_bytes(), b"managed-weight")
        self.assertEqual((self.destination / ".env").read_bytes(), (self.source / ".env").read_bytes())
        self.assertIn("microsoft_cache_path_needs_review", preview["warnings"])
        after = {
            path.relative_to(self.source).as_posix(): path.read_bytes()
            for path in self.source.rglob("*") if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertFalse((self.source / ".apex-host.lock").exists())
        self.assertFalse((self.destination / ".apex-import-journal.json").exists())

    def test_relative_google_credential_is_copied_and_rewritten_without_interpolation(self) -> None:
        (self.source / "credentials.json").write_text('{"private_key":"never-log"}', encoding="utf-8")
        (self.source / ".env").write_text(
            "GOOGLE_APPLICATION_CREDENTIALS=credentials.json\n"
            "MICROSOFT_TODO_TOKEN_CACHE_PATH=private/msal.bin\n"
            f"APEX_CONTEXT_VAULT_PATH={self.base / 'vault'}\n"
            "UNRELATED_SETTING=${HOME}\n",
            encoding="utf-8",
        )
        preview = self.engine.preview(str(self.source))
        self.assertTrue(preview["can_import"], preview["blockers"])
        self.assertIn("microsoft_cache_path_needs_review", preview["warnings"])
        self.assertTrue(any(item["path"] == "Microsoft authentication cache" for item in preview["items"]))
        self.assertTrue(any(item["path"] == "Context Vault" for item in preview["items"]))

        progress: list[tuple[str, int, int]] = []
        self.engine.progress = lambda stage, completed, total: progress.append((stage, completed, total))
        self.engine.import_data(str(self.source), str(preview["preview_id"]))

        from dotenv import dotenv_values

        values = dotenv_values(self.destination / ".env", interpolate=False)
        self.assertEqual(values["GOOGLE_APPLICATION_CREDENTIALS"], str(self.destination / "credentials.json"))
        self.assertEqual(values["MICROSOFT_TODO_TOKEN_CACHE_PATH"], str(self.source / "private/msal.bin"))
        self.assertEqual(values["UNRELATED_SETTING"], "${HOME}")
        self.assertEqual((self.source / ".env").read_text(encoding="utf-8").splitlines()[0], "GOOGLE_APPLICATION_CREDENTIALS=credentials.json")
        self.assertTrue(progress)
        self.assertTrue(all(completed <= total for _stage, completed, total in progress))
        self.assertIn("database_transport", {stage for stage, _completed, _total in progress})
        self.assertIn("database_backup", {stage for stage, _completed, _total in progress})

    def test_known_config_paths_are_previewed_without_traversal_or_rewrite(self) -> None:
        config = {
            "llama_cpp": {
                "executable_path": str(self.base / "private" / "llama-server.exe"),
                "preset_path": str(self.base / "private" / "model.json"),
            },
            "activity_report_folder": {"folder_path": str(self.base / "reports")},
        }
        raw_config = json.dumps(config, separators=(",", ":"))
        (self.source / "config.local.json").write_text(raw_config, encoding="utf-8")

        preview = self.engine.preview(str(self.source))

        self.assertIn("external_path_needs_review", preview["warnings"])
        labels = {item["path"] for item in preview["items"] if item["disposition"] == "retain_external"}
        self.assertTrue({"Local model executable", "Local model preset", "Activity report folder"}.issubset(labels))
        self.engine.import_data(str(self.source), str(preview["preview_id"]))
        self.assertEqual((self.destination / "config.local.json").read_text(encoding="utf-8"), raw_config)

    def test_interpolated_relative_credential_is_preserved_as_correction_warning(self) -> None:
        expression = "${HOME}/private/credentials.json"
        (self.source / ".env").write_text(
            f"GOOGLE_APPLICATION_CREDENTIALS={expression}\n", encoding="utf-8"
        )
        preview = self.engine.preview(str(self.source))
        self.assertIn("relative_credential_path_needs_review", preview["warnings"])
        self.engine.import_data(str(self.source), str(preview["preview_id"]))
        from dotenv import dotenv_values

        values = dotenv_values(self.destination / ".env", interpolate=False)
        self.assertEqual(values["GOOGLE_APPLICATION_CREDENTIALS"], expression)

    def test_reference_rewrite_rejects_env_bytes_that_differ_from_inventory(self) -> None:
        (self.source / ".env").write_text(
            "GOOGLE_APPLICATION_CREDENTIALS=credentials.json\n", encoding="utf-8"
        )
        preview = self.engine.preview(str(self.source))
        original_read = __import__("core.data_import.engine", fromlist=["_read_guarded"])._read_guarded

        def altered_read(path: Path) -> bytes:
            raw = original_read(path)
            if path == self.source / ".env":
                return raw.replace(b"credentials.json", b"other.json")
            return raw

        with mock.patch("core.data_import.engine._read_guarded", side_effect=altered_read):
            with self.assertRaisesRegex(ImportOperationError, "source_changed"):
                self.engine.import_data(str(self.source), str(preview["preview_id"]))
        self.assertFalse((self.destination / "apex_memory.db").exists())

    def test_preview_warns_for_unsupported_retrieval_but_allows_canonical_import(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE schema_versions SET version=999 WHERE domain='retrieval'")
            connection.commit()

        preview = self.engine.preview(str(self.source))

        self.assertTrue(preview["can_import"])
        self.assertIn("retrieval_schema_unsupported", preview["warnings"])
        self.assertNotIn("source_database_incompatible", preview["blockers"])

    def test_hot_journal_is_recovered_in_scratch_without_changing_source_bytes(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("CREATE TABLE import_probe (value TEXT)")
            connection.execute("INSERT INTO import_probe VALUES ('before')")
            connection.commit()
        crash_code = (
            "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute(\"UPDATE import_probe SET value='uncommitted'\"); os._exit(0)"
        )
        subprocess.run([sys.executable, "-B", "-c", crash_code, str(self.database)], check=True)
        journal = Path(str(self.database) + "-journal")
        self.assertTrue(journal.exists())
        before = {path.name: path.read_bytes() for path in (self.database, journal)}

        preview = self.engine.preview(str(self.source))
        self.assertTrue(preview["can_import"], preview["blockers"])
        self.engine.import_data(str(self.source), str(preview["preview_id"]))

        with closing(sqlite3.connect(self.destination / "apex_memory.db")) as connection:
            value = connection.execute("SELECT value FROM import_probe").fetchone()
        self.assertEqual(value, ("before",))
        self.assertEqual({path.name: path.read_bytes() for path in (self.database, journal)}, before)

    def test_wal_database_is_backed_up_without_modifying_source_sidecars(self) -> None:
        wal_root = self.base / "wal-bundle"
        wal_root.mkdir()
        wal_database = wal_root / "apex_memory.db"
        with closing(sqlite3.connect(self.database)) as source_connection:
            wal_connection = sqlite3.connect(wal_database)
            source_connection.backup(wal_connection)
        try:
            wal_connection.execute("PRAGMA journal_mode=WAL")
            wal_connection.execute("PRAGMA wal_autocheckpoint=0")
            wal_connection.execute("CREATE TABLE wal_probe (value TEXT)")
            wal_connection.commit()
            wal_connection.execute("INSERT INTO wal_probe VALUES ('committed-in-wal')")
            wal_connection.commit()
            wal = Path(str(wal_database) + "-wal")
            self.assertTrue(wal.exists())
            (self.source / "apex_memory.db").write_bytes(wal_database.read_bytes())
            (self.source / "apex_memory.db-wal").write_bytes(wal.read_bytes())
        finally:
            wal_connection.close()
        wal = self.source / "apex_memory.db-wal"
        before = {path.name: path.read_bytes() for path in (self.database, wal)}

        preview = self.engine.preview(str(self.source))
        self.assertTrue(preview["can_import"], preview["blockers"])
        self.engine.import_data(str(self.source), str(preview["preview_id"]))

        with closing(sqlite3.connect(self.destination / "apex_memory.db")) as connection:
            value = connection.execute("SELECT value FROM wal_probe").fetchone()
        self.assertEqual(value, ("committed-in-wal",))
        self.assertEqual({path.name: path.read_bytes() for path in (self.database, wal)}, before)

    def test_preview_blocks_existing_destination_database_and_path_collision(self) -> None:
        self.destination.mkdir()
        (self.source / "config.json").write_text("source config", encoding="utf-8")
        (self.destination / "config.json").write_text("operator data", encoding="utf-8")
        preview = self.engine.preview(str(self.source))
        self.assertIn("destination_path_exists", preview["blockers"])

        (self.destination / "apex_memory.db").touch()
        preview = self.engine.preview(str(self.source))
        self.assertIn("destination_database_exists", preview["blockers"])

    def test_dangling_database_link_counts_as_destination_collision(self) -> None:
        self.destination.mkdir()
        try:
            os.symlink("missing-target.db", self.destination / "apex_memory.db")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")
        preview = self.engine.preview(str(self.source))
        self.assertIn("destination_database_exists", preview["blockers"])

    def test_import_rejects_stale_preview(self) -> None:
        preview = self.engine.preview(str(self.source))
        (self.source / "config.json").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ImportOperationError, "preview_stale"):
            self.engine.import_data(str(self.source), str(preview["preview_id"]))
        self.assertFalse((self.destination / "apex_memory.db").exists())

    def test_active_source_lease_is_refused_without_creating_a_lock_file(self) -> None:
        from core.host.profile_lock import ProfileLock

        lease = ProfileLock(self.source).acquire()
        try:
            preview = self.engine.preview(str(self.source))
        finally:
            lease.release()
        self.assertFalse(preview["can_import"])
        self.assertIn("source_active", preview["blockers"])

    @unittest.skipUnless(os.name == "nt", "Native Windows picker returns verbatim paths")
    def test_verbatim_source_blocks_legacy_host_without_creating_a_lock(self) -> None:
        source = "\\\\?\\" + str(self.source.resolve())
        for location in ("environment", "cwd"):
            with self.subTest(location=location):
                process = mock.Mock()
                process.pid = os.getpid() + 1
                process.info = {
                    "name": "python.exe", "cmdline": ["python", "-m", "core.backend_host"],
                    "cwd": str(self.source if location == "cwd" else self.base),
                }
                process.environ.return_value = (
                    {"APEX_DATA_DIR": str(self.source)} if location == "environment" else {}
                )
                with mock.patch("psutil.process_iter", return_value=[process]):
                    preview = self.engine.preview(source)
                self.assertFalse(preview["can_import"])
                self.assertIn("source_active", preview["blockers"])
                self.assertFalse((self.source / ".apex-host.lock").exists())

    @unittest.skipUnless(os.name == "nt", "Native Windows picker returns verbatim paths")
    def test_verbatim_source_rejects_destination_and_installation_overlap(self) -> None:
        source = "\\\\?\\" + str(self.source.resolve())
        roots = (
            (self.source, None),
            (self.source / "nested-destination", None),
            (self.base, None),
            (self.destination, self.base),
        )
        for destination, installation in roots:
            with self.subTest(destination=destination, installation=installation):
                paths = RuntimePaths(
                    resource_root=self.destination, data_root=destination,
                    installation_root=installation,
                )
                with self.assertRaisesRegex(ImportOperationError, "source_invalid"):
                    ImportEngine(paths).preview(source)
                self.assertFalse((self.source / ".apex-host.lock").exists())

    @unittest.skipUnless(os.name == "nt", "Windows deny-write handles provide this guard")
    def test_open_legacy_sqlite_writer_is_refused_by_deny_write_guard(self) -> None:
        writer = sqlite3.connect(self.database)
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE schema_versions SET version=version WHERE domain='core'")
            preview = self.engine.preview(str(self.source))
        finally:
            writer.rollback()
            writer.close()
        self.assertFalse(preview["can_import"])
        self.assertIn("source_busy_or_unreadable", preview["blockers"])

    def test_recovery_removes_only_unchanged_importer_owned_outputs(self) -> None:
        (self.source / "config.json").write_text("source config", encoding="utf-8")
        preview = self.engine.preview(str(self.source))
        original_link = os.link
        def interrupt_after_one(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            if Path(target).name == "apex_memory.db":
                raise RuntimeError("simulated interruption")
            original_link(source, target)

        with mock.patch("core.data_import.engine.os.link", side_effect=interrupt_after_one):
            with self.assertRaises(RuntimeError):
                self.engine.import_data(str(self.source), str(preview["preview_id"]))
        copied = self.destination / "config.json"
        self.assertTrue(copied.exists())
        self.assertEqual(self.engine.status()["phase"], "recovery_required")

        result = self.engine.recover()

        self.assertEqual(result["phase"], "choice_required")
        self.assertFalse(copied.exists())
        self.assertFalse((self.destination / "apex_memory.db").exists())

    def test_incomplete_stage_owner_before_journal_leaves_profile_selectable(self) -> None:
        (self.source / "config.json").write_bytes(b"source config")
        self.destination.mkdir()
        sentinel = self.destination / "operator.txt"
        sentinel.write_bytes(b"operator data")
        source_before = {
            path.relative_to(self.source).as_posix(): path.read_bytes()
            for path in self.source.rglob("*") if path.is_file()
        }
        preview = self.engine.preview(str(self.source))
        original_write_text = Path.write_text

        def fail_owner_write(path: Path, *args: object, **kwargs: object) -> int:
            if path.name == ".owner":
                raise OSError("simulated interruption before ownership proof")
            return original_write_text(path, *args, **kwargs)

        with mock.patch.object(Path, "write_text", fail_owner_write):
            with self.assertRaisesRegex(OSError, "ownership proof"):
                self.engine.import_data(str(self.source), str(preview["preview_id"]))

        self.assertFalse((self.destination / ".apex-import-journal.json").exists())
        self.assertEqual(self.engine.status()["phase"], "choice_required")
        self.assertEqual(sentinel.read_bytes(), b"operator data")
        self.assertEqual(
            {path.relative_to(self.source).as_posix(): path.read_bytes()
             for path in self.source.rglob("*") if path.is_file()},
            source_before,
        )
        self.assertFalse((self.destination / "config.json").exists())

    def test_rollback_clears_journal_before_best_effort_stage_cleanup(self) -> None:
        (self.source / "config.json").write_text("source config", encoding="utf-8")
        preview = self.engine.preview(str(self.source))
        original_link = os.link
        def interrupt_after_one(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            if Path(target).name == "apex_memory.db":
                raise RuntimeError("simulated interruption")
            original_link(source, target)

        with mock.patch("core.data_import.engine.os.link", side_effect=interrupt_after_one):
            with self.assertRaises(RuntimeError):
                self.engine.import_data(str(self.source), str(preview["preview_id"]))
        journal = json.loads((self.destination / ".apex-import-journal.json").read_text())
        stage = self.destination / journal["stage"]

        with mock.patch("core.data_import.engine.shutil.rmtree"):
            result = self.engine.recover()

        self.assertEqual(result["phase"], "choice_required")
        self.assertFalse((self.destination / ".apex-import-journal.json").exists())
        self.assertTrue(stage.exists())
        self.assertEqual(self.engine.recover()["phase"], "choice_required")

    def test_recovery_keeps_modified_output_and_pending_journal(self) -> None:
        (self.source / "config.json").write_text("source config", encoding="utf-8")
        preview = self.engine.preview(str(self.source))
        original_link = os.link
        def interrupt_after_one(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            if Path(target).name == "apex_memory.db":
                raise RuntimeError("simulated interruption")
            original_link(source, target)

        with mock.patch("core.data_import.engine.os.link", side_effect=interrupt_after_one):
            with self.assertRaises(RuntimeError):
                self.engine.import_data(str(self.source), str(preview["preview_id"]))
        copied = self.destination / "config.json"
        copied.write_text("operator changed file", encoding="utf-8")

        result = self.engine.recover()

        self.assertEqual(result["phase"], "recovery_required")
        self.assertEqual(copied.read_text(encoding="utf-8"), "operator changed file")
        self.assertTrue((self.destination / ".apex-import-journal.json").exists())

    def test_committed_recovery_verifies_final_outputs_when_stage_is_absent(self) -> None:
        preview = self.engine.preview(str(self.source))
        original_replace = self.engine._write_json_replace

        def interrupt_after_commit(path: Path, value: object) -> None:
            original_replace(path, value)
            if isinstance(value, dict) and value.get("phase") == "committed":
                raise RuntimeError("simulated crash after commit record")

        with mock.patch.object(self.engine, "_write_json_replace", side_effect=interrupt_after_commit):
            with self.assertRaises(RuntimeError):
                self.engine.import_data(str(self.source), str(preview["preview_id"]))
        journal = json.loads((self.destination / ".apex-import-journal.json").read_text())
        stage = self.destination / journal["stage"]
        self.assertTrue(stage.resolve().is_relative_to(self.destination.resolve()))
        shutil.rmtree(stage)
        before = {path.name: path.read_bytes() for path in self.destination.iterdir() if path.is_file()}

        result = self.engine.recover()

        self.assertEqual(result["phase"], "ready")
        self.assertFalse((self.destination / ".apex-import-journal.json").exists())
        for name in ("apex_memory.db", ".apex-setup.json"):
            self.assertEqual((self.destination / name).read_bytes(), before[name])
        self.assertEqual(self.engine.status()["phase"], "ready")

    def test_committed_recovery_keeps_changed_database_and_pending_journal(self) -> None:
        preview = self.engine.preview(str(self.source))
        original_replace = self.engine._write_json_replace

        def interrupt_after_commit(path: Path, value: object) -> None:
            original_replace(path, value)
            if isinstance(value, dict) and value.get("phase") == "committed":
                raise RuntimeError("simulated crash after commit record")

        with mock.patch.object(self.engine, "_write_json_replace", side_effect=interrupt_after_commit):
            with self.assertRaises(RuntimeError):
                self.engine.import_data(str(self.source), str(preview["preview_id"]))
        journal = json.loads((self.destination / ".apex-import-journal.json").read_text())
        stage = self.destination / journal["stage"]
        self.assertTrue(stage.resolve().is_relative_to(self.destination.resolve()))
        shutil.rmtree(stage)
        destination_db = self.destination / "apex_memory.db"
        with closing(sqlite3.connect(destination_db)) as connection:
            connection.execute("CREATE TABLE operator_change (value TEXT)")
            connection.commit()

        result = self.engine.recover()

        self.assertEqual(result["phase"], "recovery_required")
        self.assertTrue(destination_db.exists())
        self.assertTrue((self.destination / ".apex-import-journal.json").exists())

    def test_malformed_journal_stage_path_is_rejected_without_path_access(self) -> None:
        self.destination.mkdir()
        (self.destination / ".apex-import-journal.json").write_text(json.dumps({
            "version": 1, "id": "../../escape", "phase": "staging",
            "source_fingerprint": "0" * 64, "stage": "../../escape", "outputs": [],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ImportOperationError, "import_journal_invalid"):
            self.engine._read_journal()
        with self.assertRaisesRegex(ImportOperationError, "import_journal_invalid"):
            self.engine.recover()

    def test_direct_asgi_import_refuses_pending_journal_before_profile_writes(self) -> None:
        self.destination.mkdir()
        (self.destination / ".apex-import-journal.json").write_text("{}", encoding="utf-8")
        environment = os.environ.copy()
        environment["APEX_DATA_DIR"] = str(self.destination)
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import core.api.app"],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            text=True, capture_output=True, timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImportRecoveryRequired", result.stderr)
        self.assertFalse((self.destination / "config.json").exists())
        self.assertFalse((self.destination / "apex_memory.db").exists())

    def test_dangling_import_journal_link_still_blocks_startup(self) -> None:
        self.destination.mkdir()
        try:
            os.symlink("missing-journal", self.destination / ".apex-import-journal.json")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")
        from core.data_import.guard import ImportRecoveryRequired, refuse_pending_import

        with self.assertRaises(ImportRecoveryRequired):
            refuse_pending_import(self.destination)

    def test_setup_preview_does_not_load_profile_env_or_runtime_engines(self) -> None:
        self.destination.mkdir()
        (self.destination / ".env").write_text("APEX_SETUP_SENTINEL=secret-value\n", encoding="utf-8")
        request = json.dumps({
            "version": 1, "request_id": "setup-check", "operation": "preview",
            "source_dir": str(self.source),
        }) + "\n"
        environment = os.environ.copy()
        environment["APEX_DATA_DIR"] = str(self.destination)
        environment.pop("APEX_SETUP_SENTINEL", None)
        command = (
            "import os,sys; from core.backend_host import main; code=main(['setup']); "
            "assert 'APEX_SETUP_SENTINEL' not in os.environ; "
            "assert 'core.api.app' not in sys.modules; "
            "assert 'core.agent.local_runtime.registry' not in sys.modules; "
            "assert 'fastembed' not in sys.modules; "
            "assert 'clients.microsoft_auth' not in sys.modules; raise SystemExit(code)"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", command], input=request,
            cwd=Path(__file__).resolve().parents[1], env=environment,
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        frames = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(frames[-1]["type"], "result")
        self.assertTrue(frames[-1]["payload"]["can_import"])

    def test_fresh_start_marks_profile_without_deleting_operator_files(self) -> None:
        self.destination.mkdir()
        sentinel = self.destination / "operator.txt"
        sentinel.write_text("keep", encoding="utf-8")

        result = self.engine.fresh_start()

        self.assertEqual(result["phase"], "ready")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.destination / "apex_memory.db").exists())
        self.assertEqual(json.loads((self.destination / ".apex-setup.json").read_text()), {"version": 1, "choice": "fresh_start"})

    def test_fresh_start_marker_publication_failure_leaves_no_partial_marker(self) -> None:
        self.destination.mkdir()
        sentinel = self.destination / "operator.txt"
        sentinel.write_bytes(b"preserve")
        with mock.patch("core.data_import.engine.os.link", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                self.engine.fresh_start()

        self.assertEqual(sentinel.read_bytes(), b"preserve")
        self.assertFalse((self.destination / ".apex-setup.json").exists())
        self.assertFalse(list(self.destination.glob(".apex-setup.json.tmp-*")))
        self.assertEqual(self.engine.status()["phase"], "choice_required")

    def test_source_destination_overlap_is_rejected(self) -> None:
        nested_source = self.destination / "nested-source"
        nested_source.mkdir(parents=True)
        with self.assertRaisesRegex(ImportOperationError, "source_invalid"):
            self.engine.preview(str(nested_source))

    def test_setup_request_requires_integer_version_exact_bounded_line(self) -> None:
        from core.data_import import cli

        valid = json.dumps({"version": 1, "request_id": "x", "operation": "status"}).encode() + b"\n"
        with mock.patch.object(cli.sys, "stdin", mock.Mock(buffer=BytesIO(valid))):
            self.assertEqual(cli._read_request()["operation"], "status")
        boolean_version = json.dumps({"version": True, "request_id": "x", "operation": "status"}).encode() + b"\n"
        with mock.patch.object(cli.sys, "stdin", mock.Mock(buffer=BytesIO(boolean_version))):
            with self.assertRaisesRegex(ImportOperationError, "request_invalid"):
                cli._read_request()
        oversized = b'{"version":1,"request_id":"x","operation":"status","extra":"' + b"x" * 65530 + b'"}\n'
        with mock.patch.object(cli.sys, "stdin", mock.Mock(buffer=BytesIO(oversized))):
            with self.assertRaisesRegex(ImportOperationError, "request_invalid"):
                cli._read_request()


if __name__ == "__main__":
    unittest.main()
