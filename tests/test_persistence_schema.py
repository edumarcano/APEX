from __future__ import annotations

import sqlite3
import unittest

from core.persistence_schema import validate_table_columns, validate_versioned_schema


class PersistenceSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)

    def create_version_table(self, *, unique_domain: bool = True) -> None:
        domain_constraint = "PRIMARY KEY" if unique_domain else ""
        self.conn.execute(
            f"CREATE TABLE schema_versions(domain TEXT {domain_constraint}, version INTEGER)"
        )

    def validate(self, *, optional_tables=None) -> None:
        validate_versioned_schema(
            self.conn,
            domain="sample",
            version=3,
            tables={"canonical": ("id", "value")},
            optional_tables=optional_tables,
            error_type=ValueError,
        )

    def test_absent_domain_is_fresh_even_when_shared_marker_table_exists(self) -> None:
        self.create_version_table()
        self.validate()

    def test_existing_schema_requires_marker_and_canonical_columns(self) -> None:
        self.conn.execute("CREATE TABLE canonical(id TEXT, value TEXT)")
        with self.assertRaisesRegex(ValueError, "no version marker"):
            self.validate()

        self.create_version_table()
        self.conn.execute("INSERT INTO schema_versions VALUES ('sample', 3)")
        self.validate()

    def test_wrong_or_malformed_version_is_rejected(self) -> None:
        self.create_version_table()
        self.conn.execute("INSERT INTO schema_versions VALUES ('sample', 2.5)")
        with self.assertRaisesRegex(ValueError, "malformed"):
            self.validate()

        self.conn.execute("DROP TABLE schema_versions")
        self.create_version_table(unique_domain=False)
        self.conn.executemany(
            "INSERT INTO schema_versions VALUES ('sample', ?)", ((3,), (3,))
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.validate()

    def test_existing_version_requires_all_current_tables_and_columns(self) -> None:
        self.create_version_table()
        self.conn.execute("INSERT INTO schema_versions VALUES ('sample', 3)")
        with self.assertRaisesRegex(ValueError, "missing required tables"):
            self.validate()

        self.conn.execute("CREATE TABLE canonical(id TEXT)")
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            self.validate()

    def test_optional_table_is_repairable_when_absent_but_validated_when_present(self) -> None:
        self.create_version_table()
        self.conn.execute("INSERT INTO schema_versions VALUES ('sample', 3)")
        self.conn.execute("CREATE TABLE canonical(id TEXT, value TEXT)")
        self.validate(optional_tables={"derived": ("id", "payload")})
        self.conn.execute("CREATE TABLE derived(id TEXT)")
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            self.validate(optional_tables={"derived": ("id", "payload")})

    def test_malformed_shared_version_table_uses_requested_error_type(self) -> None:
        self.conn.execute("CREATE TABLE schema_versions(domain TEXT)")
        with self.assertRaises(ValueError):
            self.validate()

    def test_current_version_without_singleton_domain_key_is_rejected_without_writes(self) -> None:
        self.create_version_table(unique_domain=False)
        self.conn.execute("INSERT INTO schema_versions VALUES ('sample', 3)")
        self.conn.execute("CREATE TABLE canonical(id TEXT, value TEXT)")
        self.conn.execute("INSERT INTO canonical VALUES ('existing', 'keep')")

        with self.assertRaisesRegex(ValueError, "unique domain key"):
            self.validate()

        self.assertEqual(
            self.conn.execute("SELECT domain, version FROM schema_versions").fetchall(),
            [("sample", 3)],
        )
        self.assertEqual(
            self.conn.execute("SELECT id, value FROM canonical").fetchall(),
            [("existing", "keep")],
        )

    def test_composite_domain_unique_key_does_not_satisfy_upsert_contract(self) -> None:
        self.conn.execute(
            "CREATE TABLE schema_versions(domain TEXT, version INTEGER, UNIQUE(domain, version))"
        )
        with self.assertRaisesRegex(ValueError, "unique domain key"):
            self.validate()

    def test_partial_single_column_unique_index_does_not_satisfy_upsert_contract(self) -> None:
        self.conn.execute("CREATE TABLE schema_versions(domain TEXT, version INTEGER)")
        self.conn.execute(
            "CREATE UNIQUE INDEX uq_schema_domain ON schema_versions(domain) WHERE domain IS NOT NULL"
        )
        with self.assertRaisesRegex(ValueError, "unique domain key"):
            self.validate()

    def test_single_column_unique_index_satisfies_upsert_contract(self) -> None:
        self.conn.execute("CREATE TABLE schema_versions(domain TEXT, version INTEGER)")
        self.conn.execute("CREATE UNIQUE INDEX uq_schema_domain ON schema_versions(domain)")
        self.validate()

    def test_owned_view_is_rejected_instead_of_treated_as_fresh(self) -> None:
        self.conn.execute("CREATE VIEW canonical AS SELECT 'existing' AS id, 'keep' AS value")
        with self.assertRaisesRegex(ValueError, "canonical.*invalid schema"):
            self.validate()
        self.assertEqual(
            self.conn.execute("SELECT id, value FROM canonical").fetchone(),
            ("existing", "keep"),
        )

    def test_table_column_check_skips_absent_optional_table(self) -> None:
        validate_table_columns(
            self.conn, table="not_created", columns=("id",), error_type=ValueError
        )


if __name__ == "__main__":
    unittest.main()
