"""Small read-only checks for the supported SQLite persistence schemas."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence


def _object_type(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ?", (name,)
    ).fetchone()
    return str(row[0]) if row is not None else None


def validate_table_columns(
    conn: sqlite3.Connection,
    *,
    table: str,
    columns: Sequence[str],
    error_type: type[Exception] = RuntimeError,
) -> None:
    """Validate expected columns when a table exists; never creates or alters it."""
    object_type = _object_type(conn, table)
    if object_type is None:
        return
    if object_type != "table":
        raise error_type(f"Persistence table {table!r} has an invalid schema.")
    try:
        identifier = table.replace('"', '""')
        actual = {
            str(row[1]) for row in conn.execute(f'PRAGMA table_info("{identifier}")')
        }
    except sqlite3.Error as exc:
        raise error_type(f"Persistence table {table!r} has an invalid schema.") from exc
    missing = set(columns) - actual
    if missing:
        raise error_type(
            f"Persistence table {table!r} is missing required columns: "
            f"{', '.join(sorted(missing))}."
        )


def validate_versioned_schema(
    conn: sqlite3.Connection,
    *,
    domain: str,
    version: int,
    tables: Mapping[str, Sequence[str]],
    optional_tables: Mapping[str, Sequence[str]] | None = None,
    error_type: type[Exception] = RuntimeError,
) -> None:
    """Check a version marker and canonical table columns without writing."""
    optional_tables = optional_tables or {}
    owned_tables = {**tables, **optional_tables}
    present: set[str] = set()
    for name in owned_tables:
        object_type = _object_type(conn, name)
        if object_type is None:
            continue
        if object_type != "table":
            raise error_type(f"Persistence table {name!r} has an invalid schema.")
        present.add(name)

    marker_object = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'schema_versions'"
    ).fetchone()
    if marker_object is not None and marker_object[0] != "table":
        raise error_type("Persistence version table has an invalid schema.")
    marker_table_exists = marker_object is not None
    marker: int | None = None
    if marker_table_exists:
        try:
            marker_column_names = [
                str(row[1]) for row in conn.execute('PRAGMA table_info("schema_versions")')
            ]
            marker_columns = set(marker_column_names)
            if (
                len(marker_column_names) != len(marker_columns)
                or marker_column_names.count("domain") != 1
                or marker_column_names.count("version") != 1
            ):
                raise error_type("Persistence version table has an invalid schema.")
            rows = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = ?", (domain,)
            ).fetchall()
            if len(rows) > 1:
                raise error_type(
                    f"Persistence version table has duplicate markers for {domain!r}."
                )
            row = rows[0] if rows else None
        except error_type:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise error_type("Persistence version table is malformed.") from exc
        if row is not None:
            try:
                if not isinstance(row[0], int):
                    raise TypeError("schema version must be a SQLite integer")
                marker = row[0]
            except (TypeError, ValueError, IndexError) as exc:
                raise error_type(f"Persistence version for {domain!r} is malformed.") from exc

    if marker is None and not present:
        return
    if marker != version:
        raise error_type(
            f"Unsupported {domain} persistence schema: expected version {version}, "
            f"found {marker if marker is not None else 'no version marker'}."
        )

    missing_tables = set(tables) - present
    if missing_tables:
        raise error_type(
            f"Unsupported {domain} persistence schema: missing required tables "
            f"{', '.join(sorted(missing_tables))}."
        )
    for table, columns in owned_tables.items():
        validate_table_columns(
            conn, table=table, columns=columns, error_type=error_type
        )
