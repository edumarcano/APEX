"""Focused persistence, service, API, and CLI coverage for external activity."""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from core.activity import (
    ActivityClientDisabledError,
    ActivityClientRegistration,
    ActivityConflictError,
    ActivityPermissionError,
    ActivityReportContent,
    ActivityService,
    ActivityStore,
    ActivityStoreError,
)
from core.api.app import app
from core.api.routers import activity as activity_router
from core import config as core_config
from core.settings.store import RuntimeSettingsStore
from src.apex import cli

def _registration(
    *,
    enabled: bool = True,
    permissions: tuple[str, ...] = ("activity:submit",),
    partition: str = "production",
) -> ActivityClientRegistration:
    return ActivityClientRegistration(
        id="codex", display_name="Codex", enabled=enabled,
        allowed_principals=["operator"], permissions=permissions, partition=partition,
    )


def _report(*, key: str = "report-1", outcome: str = "Done") -> ActivityReportContent:
    return ActivityReportContent(
        submission_key=key, title="Review branch", task_status="completed", outcome=outcome,
        findings=[{"text": "All focused checks passed."}],
    )


class ActivityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ActivityStore(None)
        self.store.initialize()
        self.service = ActivityService(self.store, (_registration(),))

    def tearDown(self) -> None:
        self.store.close()

    def test_submission_is_idempotent_and_conflicting_reuse_is_rejected(self) -> None:
        first = self.service.submit(client_id="codex", principal="operator", partition="production", content=_report())
        retry = self.service.submit(client_id="codex", principal="operator", partition="production", content=_report())

        self.assertFalse(first.duplicate)
        self.assertTrue(retry.duplicate)
        self.assertEqual(first.report.id, retry.report.id)
        self.assertEqual(len(self.service.list(partition="production")), 1)
        with self.assertRaises(ActivityConflictError):
            self.service.submit(client_id="codex", principal="operator", partition="production", content=_report(outcome="Changed"))

    def test_concurrent_duplicate_submissions_create_one_receipt(self) -> None:
        def submit():
            return self.service.submit(client_id="codex", principal="operator", partition="production", content=_report(key="concurrent"))

        with ThreadPoolExecutor(max_workers=6) as executor:
            receipts = list(executor.map(lambda _: submit(), range(6)))
        self.assertEqual({receipt.report.id for receipt in receipts}, {receipts[0].report.id})
        self.assertEqual(sum(not receipt.duplicate for receipt in receipts), 1)
        self.assertEqual(len(self.service.list(partition="production")), 1)

    def test_separate_store_connections_share_the_duplicate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.db"
            first = ActivityStore(path)
            second = ActivityStore(path)
            first.initialize()
            second.initialize()
            first_service = ActivityService(first, (_registration(),))
            second_service = ActivityService(second, (_registration(),))

            with ThreadPoolExecutor(max_workers=2) as executor:
                receipts = list(executor.map(
                    lambda service: service.submit(client_id="codex", principal="operator", partition="production", content=_report(key="cross-connection")),
                    (first_service, second_service),
                ))
            self.assertEqual({receipt.report.id for receipt in receipts}, {receipts[0].report.id})
            self.assertEqual(sum(not receipt.duplicate for receipt in receipts), 1)
            first.close()
            second.close()

    def test_restart_retains_immutable_report_and_receipt_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.db"
            first_store = ActivityStore(path)
            first_store.initialize()
            first_service = ActivityService(first_store, (_registration(),))
            receipt = first_service.submit(client_id="codex", principal="operator", partition="production", content=_report())
            first_store.close()

            reopened_store = ActivityStore(path)
            reopened_store.initialize()
            report = reopened_store.get(receipt.report.id, partition="production")
            self.assertEqual(report.content.outcome, "Done")
            self.assertEqual(report.client_display_name, "Codex")
            self.assertEqual(report.disposition, "new")
            reopened_store.close()

    def test_registration_and_partition_checks_write_nothing(self) -> None:
        disabled = ActivityService(self.store, (_registration(enabled=False),))
        with self.assertRaises(ActivityClientDisabledError):
            disabled.submit(client_id="codex", principal="operator", partition="production", content=_report())
        with self.assertRaises(ActivityPermissionError):
            self.service.submit(client_id="codex", principal="operator", partition="sandbox", content=_report())
        no_submit_permission = ActivityService(self.store, (_registration(permissions=()),))
        with self.assertRaises(ActivityPermissionError):
            no_submit_permission.submit(client_id="codex", principal="operator", partition="production", content=_report())
        self.assertEqual(self.service.list(partition="production"), [])

    def test_retained_reports_remain_listable_when_registration_changes(self) -> None:
        receipt = self.service.submit(
            client_id="codex", principal="operator", partition="production", content=_report(),
        )
        for registrations in ((), (_registration(enabled=False),)):
            recreated = ActivityService(self.store, registrations)
            self.assertEqual([report.id for report in recreated.list(partition="production")], [receipt.report.id])

    def test_oversized_serialized_report_is_rejected_before_storage(self) -> None:
        large = ActivityReportContent(
            submission_key="large", title="Large", task_status="completed", outcome="Done",
            artifact_references=["a" * 2048 for _ in range(100)], markdown_body="m" * 200_000,
        )
        with self.assertRaisesRegex(ActivityStoreError, "report_too_large"):
            self.service.submit(client_id="codex", principal="operator", partition="production", content=large)
        self.assertEqual(self.service.list(partition="production"), [])

    def test_finding_references_resolve_only_immutable_report_locations(self) -> None:
        receipt = self.service.submit(client_id="codex", principal="operator", partition="production", content=_report())
        self.assertEqual(
            self.service.resolve_finding_reference(receipt.report.id, partition="production", reference="/findings/0"),
            "All focused checks passed.",
        )
        with self.assertRaisesRegex(ValueError, "finding_reference_invalid"):
            self.service.resolve_finding_reference(receipt.report.id, partition="production", reference="/outcome")

        markdown_body = "\n# Notes\n\n"
        fallback = ActivityReportContent(
            submission_key="fallback", title="Fallback", task_status="completed",
            outcome="No findings", markdown_body=markdown_body,
        )
        fallback_receipt = self.service.submit(
            client_id="codex", principal="operator", partition="production", content=fallback,
        )
        self.assertEqual(
            self.service.resolve_finding_reference(
                fallback_receipt.report.id, partition="production", reference="/outcome",
            ),
            "No findings",
        )
        self.assertEqual(
            self.service.resolve_finding_reference(
                fallback_receipt.report.id, partition="production", reference="/markdown_body",
            ),
            markdown_body,
        )

    def test_static_client_registration_fails_closed_for_duplicates_and_invalid_permissions(self) -> None:
        valid = {
            "id": "codex", "display_name": "Codex", "enabled": True,
            "allowed_principals": ["operator"], "permissions": ["activity:submit"],
            "partition": "production",
        }
        disabled_duplicate = {**valid, "enabled": False}
        malformed_permissions = {**valid, "id": "invalid", "permissions": ["activity:review"]}
        missing_enabled = {**valid, "id": "missing-enabled"}
        del missing_enabled["enabled"]
        config_data = {
            "external_activity": {
                "clients": [valid, disabled_duplicate, malformed_permissions, missing_enabled],
            },
        }
        with mock.patch.object(core_config, "_CONFIG_DATA", config_data), self.assertLogs("core.config", "WARNING"):
            registrations = core_config.load_activity_client_registrations()
        self.assertEqual(registrations, ())

    def test_static_registrations_do_not_become_runtime_setting_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text(json.dumps({"external_activity": {"clients": []}}), encoding="utf-8")
            settings = RuntimeSettingsStore(config_path=root / "config.json", local_config_path=root / "config.local.json")
            self.assertIsNone(settings.load_warning)


class ActivityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=True)
        self.store = ActivityStore(None)
        self.store.initialize()
        self.service = ActivityService(self.store, (_registration(),))

    def tearDown(self) -> None:
        self.store.close()

    def test_local_submission_list_and_detail_stay_in_current_partition(self) -> None:
        conversation = SimpleNamespace(partition=lambda: "production")
        payload = {"client_id": "codex", "report": _report().model_dump(mode="json")}
        with mock.patch.object(activity_router, "DEMO_MODE", False), mock.patch.object(activity_router, "get_activity_service", return_value=self.service), mock.patch.object(activity_router, "get_conversation_service", return_value=conversation):
            created = self.client.post("/api/v1/activity/reports", json=payload)
            listed = self.client.get("/api/v1/activity/reports?disposition=new")
            detail = self.client.get(f"/api/v1/activity/reports/{created.json()['id']}")

        self.assertEqual(created.status_code, 201)
        self.assertFalse(created.json()["duplicate"])
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(detail.json()["report"]["findings"][0]["text"], "All focused checks passed.")

    def test_demo_submission_is_rejected_without_reaching_store(self) -> None:
        with mock.patch.object(activity_router, "DEMO_MODE", True):
            response = self.client.post("/api/v1/activity/reports", json={"client_id": "codex", "report": _report().model_dump(mode="json")})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.service.list(partition="production"), [])


class _CliClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request(self, method: str, path: str, *, payload=None, long_running: bool = False):
        self.calls.append((method, path, payload))
        if method == "POST":
            return {"id": "report-1", "received_at": "2026-09-21T00:00:00Z", "duplicate": False}
        return []


class ActivityCliTests(unittest.TestCase):
    def test_submit_and_json_import_use_the_local_report_contract(self) -> None:
        parser = cli.build_parser()
        client = _CliClient()
        args = parser.parse_args([
            "activity", "submit", "--client", "codex", "--submission-key", "key-1",
            "--title", "Report", "--task-status", "completed", "--outcome", "Done", "--finding", "Check passed",
        ])
        self.assertEqual(args.handler(args, client, True), 0)
        self.assertEqual(client.calls[0][1], "/api/v1/activity/reports")
        self.assertEqual(client.calls[0][2]["report"]["findings"], [{"text": "Check passed"}])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(_report(key="key-2").model_dump(mode="json")), encoding="utf-8")
            imported = parser.parse_args(["activity", "import", str(path), "--client", "codex"])
            self.assertEqual(imported.handler(imported, client, True), 0)
        self.assertEqual(client.calls[1][2]["report"]["submission_key"], "key-2")
