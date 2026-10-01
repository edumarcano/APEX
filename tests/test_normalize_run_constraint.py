"""Data-preservation tests for the explicit Cortex run constraint command."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock
from uuid import uuid4

from core.briefings.store import BriefingSessionStore
from core.connectors.models import utc_now_iso
from core.conversations.store import ConversationStore
from core.runs.models import RunLimitSnapshot
from core.runs.store import RunStore
from scripts import normalize_run_constraint


class NormalizeRunConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="apex-run-constraint-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "apex_memory.db"
        self.conversations = ConversationStore(self.database)
        self.conversations.initialize()
        self.runs = RunStore(self.database)
        self.runs.initialize()
        self.briefings = BriefingSessionStore(self.database)
        self.briefings.initialize()
        self.conversation_id = uuid4()
        self.user_message_id = uuid4()
        self.agent_message_id = uuid4()
        self.run_id = uuid4()
        self.session_id = uuid4()
        self.conversations.create(
            conversation_id=self.conversation_id,
            title="Cleanup fixture",
            partition="production",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )
        now = utc_now_iso()
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executemany(
                "INSERT INTO conversation_messages "
                "(id, conversation_id, role, content, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(self.user_message_id), str(self.conversation_id), "user", "Prompt", "completed", now, now),
                    (str(self.agent_message_id), str(self.conversation_id), "agent", "", "pending", now, now),
                ],
            )
            conn.execute(
                "CREATE TABLE cleanup_sentinel(id INTEGER PRIMARY KEY, payload BLOB NOT NULL)"
            )
            conn.execute(
                "INSERT INTO cleanup_sentinel VALUES (1, ?)", (sqlite3.Binary(b"\x00sentinel"),)
            )
            conn.execute(
                "CREATE TABLE cleanup_trigger_log(value TEXT NOT NULL)"
            )

        # Recreate only the old stop_reason CHECK shape before inserting any
        # rows, while retaining the canonical marker and parent tables.
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            old_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='cortex_runs'"
            ).fetchone()[0]
            old_sql = old_sql.replace(
                "'max_elapsed_seconds',\n                    'max_retries'",
                "'max_elapsed_seconds', 'max_total_tokens',\n                    'max_retries'",
            )
            conn.execute("DROP TABLE cortex_runs")
            conn.execute(old_sql)
            conn.execute("ALTER TABLE cortex_runs ADD COLUMN final_message_id TEXT")
            conn.execute("ALTER TABLE cortex_runs ADD COLUMN error_message TEXT")
            for name, sql in (
                ("idx_cortex_runs_partition_created", "ON cortex_runs(partition, created_at DESC)"),
                ("idx_cortex_runs_partition_status", "ON cortex_runs(partition, status)"),
                ("idx_cortex_runs_conversation", "ON cortex_runs(conversation_id, created_at DESC)"),
                ("idx_cortex_runs_cleanup_test", "ON cortex_runs(status, updated_at)"),
            ):
                conn.execute(f"CREATE INDEX {name} {sql}")
            conn.execute(
                "CREATE TRIGGER cleanup_run_update AFTER UPDATE ON cortex_runs "
                "BEGIN INSERT INTO cleanup_trigger_log VALUES (NEW.id); END"
            )
            conn.execute(
                "CREATE VIEW cleanup_run_view AS "
                "SELECT id, stop_reason FROM cortex_runs"
            )

        self.runs.create_run(
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            partition="production",
            user_message_id=self.user_message_id,
            agent_message_id=self.agent_message_id,
            requested_model="fixture-model",
            limit_snapshot=RunLimitSnapshot(
                max_elapsed_seconds=600,
                max_retries=4,
                max_model_turns=6,
                max_tool_calls=10,
            ),
        )
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                "UPDATE cortex_runs SET limit_snapshot_json = ?, final_message_id=?, "
                "error_message=? WHERE id = ?",
                (
                    '{ "max_total_tokens" : 128000, "max_elapsed_seconds":600, "max_retries":4, "max_model_turns":6, "max_tool_calls":10 }',
                    "historical-final-message",
                    "historical error detail",
                    str(self.run_id),
                ),
            )
            conn.execute(
                "INSERT INTO briefing_sessions "
                "(id, partition, idempotency_key, conversation_id, opening_message_id, run_id, "
                "profile_id, created_at, request_json, configuration_json) "
                "VALUES (?, 'production', 'cleanup-fixture', ?, ?, ?, 'daily', ?, '{}', '{}')",
                (str(self.session_id), str(self.conversation_id), str(self.agent_message_id), str(self.run_id), now),
            )
            conn.execute(
                "INSERT INTO briefing_speech "
                "(session_id, partition, artifact_sha256, status, updated_at) "
                "VALUES (?, 'production', ?, 'ready', ?)",
                (str(self.session_id), "a" * 64, now),
            )
            conn.execute(
                "INSERT INTO briefing_speech_audio_chunks "
                "(session_id, ordinal, content_type, engine, duration_seconds, audio_blob) "
                "VALUES (?, 0, 'audio/wav', 'pyttsx3', 1.0, ?)",
                (str(self.session_id), sqlite3.Binary(b"cached-audio")),
            )

    def tearDown(self) -> None:
        self.runs.close()
        self.conversations.close()
        self.briefings.close()

    def _command(
        self,
        *args: str,
        database: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts" / "normalize_run_constraint.py"),
                "--database",
                str(database or self.database),
                *args,
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

    def _schema_sql(self) -> str:
        with closing(sqlite3.connect(self.database)) as conn, conn:
            return conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='cortex_runs'"
            ).fetchone()[0]

    def test_check_only_is_read_only_and_apply_preserves_linked_data(self) -> None:
        before = self.database.read_bytes()
        checked = self._command()
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("database unchanged", checked.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(list(self.database.parent.glob("*.bak")), [])

        applied = self._command("--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("backup:", applied.stdout)
        self.assertNotIn("max_total_tokens", self._schema_sql())
        for _ in range(2):
            self.conversations.initialize()
            self.runs.initialize()
            self.briefings.initialize()
        self.assertEqual(self.runs.get_run(self.run_id, "production").limit_snapshot.max_total_tokens, 128000)
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            self.assertEqual(conn.execute("SELECT count(*) FROM briefing_sessions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT audio_blob FROM briefing_speech_audio_chunks").fetchone()[0], b"cached-audio")
            self.assertEqual(conn.execute("SELECT payload FROM cleanup_sentinel").fetchone()[0], b"\x00sentinel")
            self.assertEqual(conn.execute("SELECT count(*) FROM cleanup_run_view").fetchone()[0], 1)
            self.assertEqual(
                conn.execute(
                    "SELECT final_message_id, error_message FROM cortex_runs WHERE id=?",
                    (str(self.run_id),),
                ).fetchone(),
                ("historical-final-message", "historical error detail"),
            )
            index_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='idx_cortex_runs_cleanup_test'"
            ).fetchone()[0]
            self.assertEqual(
                index_sql,
                "CREATE INDEX idx_cortex_runs_cleanup_test ON cortex_runs(status, updated_at)",
            )
            conn.execute("DELETE FROM cleanup_trigger_log")
            conn.execute(
                "UPDATE cortex_runs SET updated_at=? WHERE id=?",
                (utc_now_iso(), str(self.run_id)),
            )
            self.assertEqual(
                conn.execute("SELECT value FROM cleanup_trigger_log").fetchone()[0],
                str(self.run_id),
            )
            conn.execute("DELETE FROM cortex_runs WHERE id = ?", (str(self.run_id),))
            self.assertEqual(conn.execute("SELECT count(*) FROM briefing_sessions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM briefing_speech").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM briefing_speech_audio_chunks").fetchone()[0], 0)

    def test_reapply_is_noop_and_rebuilt_schema_rejects_retired_reason(self) -> None:
        first = self._command("--apply")
        self.assertEqual(first.returncode, 0, first.stderr)
        backup_count = len(list(self.database.parent.glob("*.bak")))
        second = self._command("--apply")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already normalized", second.stdout)
        self.assertEqual(len(list(self.database.parent.glob("*.bak"))), backup_count)
        with closing(sqlite3.connect(self.database)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE cortex_runs SET stop_reason = 'max_total_tokens' WHERE id = ?",
                    (str(self.run_id),),
                )

    def test_fresh_run_store_schema_rejects_retired_reason(self) -> None:
        fresh_database = Path(self.temp_dir.name) / "fresh.db"
        fresh_store = RunStore(fresh_database)
        fresh_store.initialize()
        fresh_store.close()

        with closing(sqlite3.connect(fresh_database)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO cortex_runs "
                    "(id, conversation_id, partition, user_message_id, agent_message_id, "
                    "requested_model, status, stop_reason, created_at, updated_at, "
                    "limit_snapshot_json, usage_quality) "
                    "VALUES ('run', 'conversation', 'production', 'user', 'agent', "
                    "'model', 'queued', 'max_total_tokens', ?, ?, '{}', 'unavailable')",
                    (utc_now_iso(), utc_now_iso()),
                )

    def test_unsupported_version_and_retired_rows_are_refused_without_changes(self) -> None:
        original = self._schema_sql()
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                "UPDATE schema_versions SET version=1 WHERE domain='cortex_runs'"
            )
        unsupported_before = self.database.read_bytes()
        unsupported = self._command("--apply")
        self.assertNotEqual(unsupported.returncode, 0)
        self.assertEqual(self.database.read_bytes(), unsupported_before)
        self.assertEqual(list(self.database.parent.glob("*.bak")), [])

        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                "UPDATE schema_versions SET version=99 WHERE domain='cortex_runs'"
            )
        newer_before = self.database.read_bytes()
        newer = self._command("--apply")
        self.assertNotEqual(newer.returncode, 0)
        self.assertEqual(self.database.read_bytes(), newer_before)
        self.assertEqual(list(self.database.parent.glob("*.bak")), [])

        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                "UPDATE schema_versions SET version=2 WHERE domain='cortex_runs'"
            )
            conn.execute(
                "UPDATE cortex_runs SET stop_reason='max_total_tokens' WHERE id=?",
                (str(self.run_id),),
            )
        retired_before = self.database.read_bytes()
        retired = self._command("--apply")
        self.assertNotEqual(retired.returncode, 0)
        self.assertEqual(self.database.read_bytes(), retired_before)
        self.assertEqual(self._schema_sql(), original)
        self.assertEqual(list(self.database.parent.glob("*.bak")), [])

    def test_backup_failure_and_post_rebuild_failure_leave_source_unchanged(self) -> None:
        before = self.database.read_bytes()
        with closing(sqlite3.connect(self.database)) as conn:
            historical_json = conn.execute(
                "SELECT limit_snapshot_json FROM cortex_runs WHERE id=?",
                (str(self.run_id),),
            ).fetchone()[0]
        with mock.patch.object(
            normalize_run_constraint,
            "_create_backup",
            side_effect=OSError("backup failed"),
        ):
            with self.assertRaises(OSError):
                normalize_run_constraint.normalize_database(self.database, apply=True)
        self.assertEqual(self.database.read_bytes(), before)

        with mock.patch.object(
            normalize_run_constraint,
            "_validate_integrity",
            side_effect=normalize_run_constraint.ConstraintCleanupError("injected integrity failure"),
        ):
            with self.assertRaisesRegex(normalize_run_constraint.ConstraintCleanupError, "injected"):
                normalize_run_constraint.normalize_database(self.database, apply=True)
        self.assertIn("max_total_tokens", self._schema_sql())
        with closing(sqlite3.connect(self.database)) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT limit_snapshot_json, final_message_id, error_message "
                    "FROM cortex_runs WHERE id=?",
                    (str(self.run_id),),
                ).fetchone(),
                (historical_json, "historical-final-message", "historical error detail"),
            )
            self.assertEqual(conn.execute("SELECT count(*) FROM briefing_sessions").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT audio_blob FROM briefing_speech_audio_chunks").fetchone()[0],
                b"cached-audio",
            )
        self.assertEqual(len(list(self.database.parent.glob("*.bak"))), 1)

    def test_missing_database_is_not_created(self) -> None:
        missing = Path(self.temp_dir.name) / "missing.db"
        failed = self._command("--apply", database=missing)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(missing.exists())

    def test_unrecognized_schema_fails_without_mutation(self) -> None:
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                "UPDATE schema_versions SET version=2 WHERE domain='cortex_runs'"
            )
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='cortex_runs'"
            ).fetchone()[0]
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute(
                "UPDATE sqlite_master SET sql=? WHERE type='table' AND name='cortex_runs'",
                (sql.replace("'max_total_tokens'", "'unrecognized_reason'"),),
            )
            conn.execute("PRAGMA writable_schema=OFF")
        before = self.database.read_bytes()
        failed = self._command("--apply")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
