"""Remove the retired run stop reason from an existing SQLite constraint."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.runtime_paths import get_runtime_paths, initialize_environment

initialize_environment()

_CURRENT_STOP_REASONS = frozenset(
    {
        "end_turn",
        "operator_cancelled",
        "max_elapsed_seconds",
        "max_retries",
        "max_model_turns",
        "max_tool_calls",
        "provider_error",
        "tool_error",
        "runtime_error",
        "resource_exhaustion",
        "interrupted_by_restart",
        "internal_error",
    }
)
_REQUIRED_COLUMNS = frozenset(
    {
        "id", "conversation_id", "partition", "user_message_id", "agent_message_id",
        "requested_model", "resolved_model", "provider", "runtime", "status", "stop_reason",
        "created_at", "started_at", "completed_at", "updated_at", "limit_snapshot_json",
        "turns_count", "tool_calls_count", "retries_count", "total_tokens", "elapsed_seconds",
        "usage_quality", "runtime_measurements_json", "final_message_status", "answer_persisted",
        "tool_outcome_counts_json", "action_ids_json", "trace_id", "error_code",
    }
)
_OPTIONAL_BETA6_COLUMNS = frozenset({"final_message_id", "error_message"})
_STOP_CHECK = re.compile(
    r"stop_reason\s+TEXT\s+CHECK\s*\(\s*stop_reason\s+IS\s+NULL\s+OR\s*"
    r"stop_reason\s+IN\s*\((?P<values>[^)]*)\)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_STOP_VALUE = re.compile(r"\s*'((?:''|[^'])*)'\s*")


class ConstraintCleanupError(RuntimeError):
    """The database does not match the narrow supported cleanup shape."""


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)


def _table_definition(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='cortex_runs'"
    ).fetchone()
    if row is None or not isinstance(row[0], str):
        raise ConstraintCleanupError("cortex_runs table is missing or has no SQL definition")
    return row[0]


def _inspect(conn: sqlite3.Connection) -> tuple[str, bool, int]:
    from core.persistence_schema import validate_versioned_schema

    try:
        validate_versioned_schema(
            conn,
            domain="cortex_runs",
            version=2,
            tables={
                "cortex_runs": tuple(sorted(_REQUIRED_COLUMNS)),
            },
            error_type=ConstraintCleanupError,
        )
    except ConstraintCleanupError:
        raise
    except Exception as exc:
        raise ConstraintCleanupError("cortex_runs version marker is malformed") from exc
    sql = _table_definition(conn)
    column_info = {
        row[1]: row for row in conn.execute("PRAGMA table_info(cortex_runs)")
    }
    columns = set(column_info)
    optional_columns = columns - _REQUIRED_COLUMNS
    if (
        not _REQUIRED_COLUMNS.issubset(columns)
        or not optional_columns.issubset(_OPTIONAL_BETA6_COLUMNS)
    ):
        raise ConstraintCleanupError("cortex_runs has an unsupported column shape")
    for name in optional_columns:
        column = column_info[name]
        if str(column[2]).upper() != "TEXT" or column[3] or column[4] is not None:
            raise ConstraintCleanupError("cortex_runs has an unsupported optional column shape")

    checks = list(_STOP_CHECK.finditer(sql))
    if len(checks) != 1:
        raise ConstraintCleanupError("cortex_runs stop_reason constraint is unrecognized")
    values: list[str] = []
    for member in checks[0].group("values").split(","):
        match = _STOP_VALUE.fullmatch(member)
        if match is None:
            raise ConstraintCleanupError("cortex_runs stop_reason constraint is unrecognized")
        values.append(match.group(1).replace("''", "'"))
    member_set = set(values)
    has_retired_reason = "max_total_tokens" in member_set
    if member_set != _CURRENT_STOP_REASONS | ({"max_total_tokens"} if has_retired_reason else set()):
        raise ConstraintCleanupError("cortex_runs stop_reason values are unsupported")
    if len(values) != len(member_set):
        raise ConstraintCleanupError("cortex_runs stop_reason constraint has duplicate values")

    retired_rows = 0
    if has_retired_reason:
        retired_rows = conn.execute(
            "SELECT count(*) FROM cortex_runs WHERE stop_reason = 'max_total_tokens'"
        ).fetchone()[0]
    return sql, has_retired_reason, int(retired_rows)


def _capture_objects(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return [
        (row[0], row[1], row[2])
        for row in conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'cortex_runs' AND type IN ('index', 'trigger') "
            "AND sql IS NOT NULL ORDER BY type, name"
        )
    ]


def _capture_rows(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    return [tuple(row) for row in conn.execute("SELECT * FROM cortex_runs ORDER BY rowid")]


def _backup_database(source_path: Path, backup_path: Path) -> None:
    with closing(_connect_readonly(source_path)) as source, closing(
        sqlite3.connect(backup_path)
    ) as destination:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise ConstraintCleanupError("SQLite backup failed integrity validation")


def _create_backup(source_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for _ in range(10):
        backup_path = source_path.with_name(
            f"{source_path.name}.constraint-cleanup-{stamp}-{uuid.uuid4().hex[:8]}.bak"
        )
        try:
            descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        else:
            os.close(descriptor)
            try:
                _backup_database(source_path, backup_path)
            except Exception:
                backup_path.unlink(missing_ok=True)
                raise
            return backup_path
    raise ConstraintCleanupError("could not allocate a unique adjacent backup name")


def _replacement_sql(sql: str) -> str:
    match = _STOP_CHECK.search(sql)
    if match is None:
        raise ConstraintCleanupError("cortex_runs stop_reason constraint is unrecognized")
    values = match.group("values")
    replaced_values, count = re.subn(
        r"\s*,\s*'max_total_tokens'(?=\s*(?:,|$))", "", values,
        flags=re.IGNORECASE,
    )
    if count != 1:
        raise ConstraintCleanupError("cortex_runs stop_reason member could not be removed safely")
    replaced_check = sql[: match.start("values")] + replaced_values + sql[match.end("values"):]
    renamed, count = re.subn(
        r"(?i)^(\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)cortex_runs\b",
        r"\1cortex_runs__constraint_cleanup",
        replaced_check,
        count=1,
    )
    if count != 1:
        raise ConstraintCleanupError("cortex_runs table declaration is unrecognized")
    return renamed


def _validate_integrity(conn: sqlite3.Connection) -> None:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise ConstraintCleanupError("database integrity validation failed")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise ConstraintCleanupError("database contains foreign key violations")


def _validate_preservation(conn: sqlite3.Connection, backup_path: Path) -> None:
    conn.execute("ATTACH DATABASE ? AS cleanup_baseline", (str(backup_path),))
    baseline_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM cleanup_baseline.sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    current_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if current_tables != baseline_tables:
        raise ConstraintCleanupError("database table set changed during cleanup")
    for table in sorted(current_tables):
        escaped = table.replace('"', '""')
        columns = [
            row[1]
            for row in conn.execute(f'PRAGMA main.table_info("{escaped}")')
        ]
        if not columns:
            raise ConstraintCleanupError("a database table has an unsupported shape")
        column_sql = ", ".join(
            f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns
        )
        grouped_live = f"SELECT {column_sql}, count(*) FROM main.\"{escaped}\" GROUP BY {column_sql}"
        grouped_baseline = (
            f"SELECT {column_sql}, count(*) FROM cleanup_baseline.\"{escaped}\" "
            f"GROUP BY {column_sql}"
        )
        live_count = conn.execute(f'SELECT count(*) FROM main."{escaped}"').fetchone()[0]
        baseline_count = conn.execute(
            f'SELECT count(*) FROM cleanup_baseline."{escaped}"'
        ).fetchone()[0]
        if live_count != baseline_count:
            raise ConstraintCleanupError(f"rows changed in table {table}")
        if conn.execute(f"{grouped_live} EXCEPT {grouped_baseline}").fetchone() is not None:
            raise ConstraintCleanupError(f"rows changed in table {table}")
        if conn.execute(f"{grouped_baseline} EXCEPT {grouped_live}").fetchone() is not None:
            raise ConstraintCleanupError(f"rows changed in table {table}")

    current_objects = [
        tuple(row)
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM main.sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    ]
    baseline_objects = [
        tuple(row)
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM cleanup_baseline.sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    ]
    expected = []
    for kind, name, table, sql in baseline_objects:
        if kind == "table" and name == "cortex_runs":
            sql = _replacement_sql(sql).replace(
                "cortex_runs__constraint_cleanup", "cortex_runs", 1
            )
        expected.append((kind, name, table, sql))
    normalize = lambda sql: re.sub(r'(?i)"cortex_runs"', "cortex_runs", sql) if sql else None
    normalized_current = [
        (kind, name, table, normalize(sql))
        for kind, name, table, sql in current_objects
    ]
    normalized_expected = [
        (kind, name, table, normalize(sql))
        for kind, name, table, sql in expected
    ]
    if normalized_current != normalized_expected:
        raise ConstraintCleanupError("database schema objects changed during cleanup")


def normalize_database(
    database: Path,
    *,
    apply: bool = False,
) -> str:
    database = database.resolve()
    if not database.is_file():
        raise ConstraintCleanupError("database file does not exist")
    readonly = _connect_readonly(database)
    try:
        _sql, has_retired_reason, retired_rows = _inspect(readonly)
    finally:
        readonly.close()

    if not has_retired_reason:
        return "already normalized"
    if retired_rows:
        raise ConstraintCleanupError(
            f"refusing cleanup: {retired_rows} run(s) use max_total_tokens as stop_reason"
        )
    if not apply:
        return "normalization available; database unchanged"

    conn = sqlite3.connect(database, timeout=30, isolation_level=None)
    backup_path: Path | None = None
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA legacy_alter_table=ON")
        conn.execute("BEGIN IMMEDIATE")
        old_sql, has_retired_reason, retired_rows = _inspect(conn)
        if not has_retired_reason:
            conn.execute("COMMIT")
            return "already normalized"
        if retired_rows:
            raise ConstraintCleanupError(
                f"refusing cleanup: {retired_rows} run(s) use max_total_tokens as stop_reason"
            )

        rows_before = _capture_rows(conn)
        objects_before = _capture_objects(conn)
        backup_path = _create_backup(database)

        conn.execute(_replacement_sql(old_sql))
        columns = [row[1] for row in conn.execute("PRAGMA table_info(cortex_runs)")]
        column_sql = ", ".join(f'"{column}"' for column in columns)
        conn.execute(
            f"INSERT INTO cortex_runs__constraint_cleanup ({column_sql}) "
            f"SELECT {column_sql} FROM cortex_runs"
        )
        conn.execute("DROP TABLE cortex_runs")
        conn.execute(
            "ALTER TABLE cortex_runs__constraint_cleanup RENAME TO cortex_runs"
        )
        for _kind, _name, object_sql in objects_before:
            conn.execute(object_sql)

        new_sql, has_retired_reason, retired_rows = _inspect(conn)
        if has_retired_reason or retired_rows:
            raise ConstraintCleanupError("retired stop_reason remains after table rebuild")
        expected_sql = _replacement_sql(old_sql).replace(
            "cortex_runs__constraint_cleanup", "cortex_runs", 1
        )
        if re.sub(r'(?i)"cortex_runs"', "cortex_runs", new_sql) != expected_sql:
            raise ConstraintCleanupError("rebuilt cortex_runs definition does not match the expected shape")
        if _capture_rows(conn) != rows_before:
            raise ConstraintCleanupError("cortex_runs rows changed during table rebuild")
        if _capture_objects(conn) != objects_before:
            raise ConstraintCleanupError("cortex_runs indexes or triggers changed during table rebuild")
        assert backup_path is not None
        _validate_preservation(conn, backup_path)
        _validate_integrity(conn)
        conn.execute("COMMIT")
        return f"normalized; backup: {backup_path}"
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument(
        "--apply", action="store_true",
        help="rebuild the supported cortex_runs constraint after stopping APEX",
    )
    args = parser.parse_args(argv)
    try:
        database = args.database or get_runtime_paths().database_path
        print(normalize_database(database, apply=args.apply))
    except (ConstraintCleanupError, OSError, sqlite3.Error) as exc:
        print(f"run constraint cleanup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
