from __future__ import annotations

import json
import unittest

from core.activity.agent_reads import (
    AGENT_REPORT_MAX_OUTPUT_CHARS,
    AgentReportReadInputError,
    get_activity_report,
    search_activity_reports,
)
from core.activity.models import ActivityReportContent
from core.activity.service import ActivityService
from core.activity.store import ActivityNotFoundError, ActivityStore


class ActivityAgentReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ActivityStore(None)
        self.store.initialize()
        self.service = ActivityService(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def submit(
        self, *, key: str, title: str, outcome: str = "Completed",
        partition: str = "production", client_id: str = "codex",
        **content_fields: object,
    ):
        fields = {"task_status": "completed", **content_fields}
        return self.service.submit(
            client_id=client_id, principal="test", partition=partition,
            content=ActivityReportContent(
                submission_key=key, title=title, outcome=outcome, **fields,
            ),
        ).report

    def test_search_filters_fields_and_excludes_dismissed_by_default(self) -> None:
        subject = self.submit(key="subject", title="One", subjects=["Café planning"])
        project = self.submit(key="project", title="Two", projects=["Project A"])
        markdown_only = self.submit(key="markdown", title="Three", markdown_body="needle only in markdown")
        dismissed = self.submit(key="dismissed", title="Needle dismissed")
        self.service.set_disposition(dismissed.id, partition="production", disposition="dismissed")

        result = search_activity_reports(self.service, partition="production", query="café")
        self.assertEqual([row["report_id"] for row in result["results"]], [str(subject.id)])
        self.assertTrue(result["results"][0]["content_is_untrusted"])
        self.assertTrue(result["results"][0]["source_label_is_caller_declared"])
        self.assertEqual(
            [row["report_id"] for row in search_activity_reports(
                self.service, partition="production", query="project a",
            )["results"]],
            [str(project.id)],
        )
        self.assertEqual(search_activity_reports(
            self.service, partition="production", query="needle",
        )["results"], [])
        self.assertEqual(
            [row["report_id"] for row in search_activity_reports(
                self.service, partition="production", query="needle", disposition="dismissed",
            )["results"]],
            [str(dismissed.id)],
        )
        self.assertEqual(search_activity_reports(
            self.service, partition="production", query="needle only in markdown",
        )["results"], [])
        # A wildcard character is literal rather than a SQL LIKE pattern.
        self.submit(key="wildcard", title="100% done")
        self.assertEqual(len(search_activity_reports(
            self.service, partition="production", query="100%",
        )["results"]), 1)

    def test_filters_and_tied_receipt_times_paginate_without_skipping(self) -> None:
        reports = [self.submit(key=f"page-{i}", title=f"Report {i}") for i in range(7)]
        with self.store._connection() as conn, conn:
            conn.execute("UPDATE activity_reports SET received_at='2026-01-01T00:00:00Z'")

        first = search_activity_reports(self.service, partition="production", limit=3)
        second = search_activity_reports(
            self.service, partition="production", limit=3, cursor=first["next_cursor"],
        )
        third = search_activity_reports(
            self.service, partition="production", limit=3, cursor=second["next_cursor"],
        )
        actual = [item["report_id"] for page in (first, second, third) for item in page["results"]]
        self.assertEqual(actual, [str(report.id) for report in reversed(reports)])
        self.assertIsNone(third["next_cursor"])
        self.assertLessEqual(len(json.dumps(first, default=str)), AGENT_REPORT_MAX_OUTPUT_CHARS)

        another_source = self.submit(key="other-source", title="Other", client_id="other")
        filtered = search_activity_reports(
            self.service, partition="production", client_id="other", limit=1,
        )
        self.assertEqual([item["report_id"] for item in filtered["results"]], [str(another_source.id)])

    def test_search_rejects_invalid_arguments_and_filter_mismatched_cursor(self) -> None:
        for kwargs in (
            {"query": 3}, {"client_id": "Bad ID"}, {"client_id": "éclair"},
            {"disposition": "unknown"}, {"disposition": []},
            {"limit": 0}, {"limit": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(AgentReportReadInputError):
                search_activity_reports(self.service, partition="production", **kwargs)
        self.submit(key="cursor", title="Cursor")
        self.submit(key="cursor-2", title="Cursor two")
        page = search_activity_reports(self.service, partition="production", limit=1)
        self.assertIsNotNone(page["next_cursor"])
        with self.assertRaises(AgentReportReadInputError):
            search_activity_reports(
                self.service, partition="sandbox", limit=1, cursor=page["next_cursor"],
            )

    def test_maximum_unicode_query_cursor_round_trips(self) -> None:
        query = "🙂" * 256
        self.submit(key="unicode-query-1", title=query)
        self.submit(key="unicode-query-2", title=query + " next")
        page = search_activity_reports(
            self.service, partition="production", query=query, limit=1,
        )
        self.assertIsNotNone(page["next_cursor"])
        self.assertLessEqual(len(page["next_cursor"]), 2_048)
        next_page = search_activity_reports(
            self.service, partition="production", query=query, limit=1,
            cursor=page["next_cursor"],
        )
        self.assertEqual(len(next_page["results"]), 1)

    def test_reads_are_partition_scoped_and_invalid_ids_fail_as_input(self) -> None:
        production = self.submit(key="same", title="Private", partition="production")
        sandbox = self.submit(key="same", title="Sandbox", partition="sandbox")
        self.assertEqual(search_activity_reports(self.service, partition="sandbox")["results"][0]["title"], "Sandbox")
        with self.assertRaises(ActivityNotFoundError):
            get_activity_report(self.service, partition="sandbox", report_id=str(production.id))
        self.assertEqual(get_activity_report(
            self.service, partition="production", report_id=str(production.id),
        )["report"]["title"], "Private")
        with self.assertRaises(AgentReportReadInputError):
            get_activity_report(self.service, partition="production", report_id="../secret")
        with self.assertRaises(AgentReportReadInputError):
            get_activity_report(
                self.service, partition="production", report_id=str(sandbox.id), cursor="bad",
            )

    def test_detail_chunks_unicode_and_long_fields_without_loss_or_duplication(self) -> None:
        outcome = "Résultat 東京 🙂 " * 900
        finding = "Finding λ " * 900
        markdown = "# تقرير\n\n" + "body 🧪 " * 5_000
        report = self.submit(
            key="long", title="Long report", outcome=outcome,
            findings=[{"text": finding, "derivation": "model_interpretation"}],
            unresolved_questions=["Question? " * 350],
            suggested_follow_up="Follow up " * 300,
            subjects=["Café"], projects=["Project 東京"],
            evidence_links=["https://example.test/evidence"],
            artifact_references=["artifact://example"], markdown_body=markdown,
        )
        pages: list[dict[str, object]] = []
        cursor = None
        while True:
            page = get_activity_report(
                self.service, partition="production", report_id=str(report.id), cursor=cursor,
            )
            self.assertLessEqual(len(json.dumps(page, default=str)), AGENT_REPORT_MAX_OUTPUT_CHARS)
            pages.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                break

        stitched: dict[str, str] = {}
        for page in pages:
            for block in page["content"]:
                reference = block["reference"]
                stitched[reference] = stitched.get(reference, "") + block["text"]
        self.assertEqual(stitched["/outcome"], outcome.strip())
        self.assertEqual(stitched["/findings/0"], finding.strip())
        self.assertEqual(stitched["/markdown_body"], markdown)
        self.assertEqual(stitched["/unresolved_questions/0"], ("Question? " * 350).strip())
        finding_block = next(block for page in pages for block in page["content"] if block["kind"] == "finding")
        self.assertEqual(finding_block["derivation"], "model_interpretation")
        self.assertTrue(pages[0]["report"]["content_is_untrusted"])
        self.assertTrue(pages[0]["report"]["source_label_is_caller_declared"])

    def test_worst_case_unicode_metadata_and_finding_titles_are_complete_and_bounded(self) -> None:
        title = "🙂" * 512
        status = "🧪" * 512
        finding_title = "東京" * 256
        report = self.submit(
            key="unicode-metadata", title=title, outcome="done",
            findings=[{"title": finding_title, "text": "Finding text", "derivation": "unknown"}],
            task_status=status,
        )
        detail = get_activity_report(self.service, partition="production", report_id=str(report.id))
        stitched: dict[str, str] = {}
        while True:
            self.assertLessEqual(len(json.dumps(detail, default=str)), AGENT_REPORT_MAX_OUTPUT_CHARS)
            for block in detail["content"]:
                stitched[block["reference"]] = stitched.get(block["reference"], "") + block["text"]
            cursor = detail["next_cursor"]
            if cursor is None:
                break
            detail = get_activity_report(
                self.service, partition="production", report_id=str(report.id), cursor=cursor,
            )
        self.assertEqual(stitched["/title"], title)
        self.assertEqual(stitched["/task_status"], status)
        self.assertEqual(stitched["/findings/0/title"], finding_title)

    def test_alternating_small_and_large_blocks_continue_at_first_unemitted_block(self) -> None:
        findings = [
            {"title": f"Finding {i}", "text": "tiny" if i % 2 == 0 else "large 🧪 " * 1_500}
            for i in range(12)
        ]
        report = self.submit(key="alternating", title="Alternating", outcome="Outcome", findings=findings)
        cursor = None
        reconstructed: dict[str, str] = {}
        while True:
            page = get_activity_report(
                self.service, partition="production", report_id=str(report.id), cursor=cursor,
            )
            self.assertLessEqual(len(json.dumps(page, default=str)), AGENT_REPORT_MAX_OUTPUT_CHARS)
            for block in page["content"]:
                reconstructed[block["reference"]] = reconstructed.get(block["reference"], "") + block["text"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        for index, finding in enumerate(findings):
            self.assertEqual(reconstructed[f"/findings/{index}"], finding["text"].strip())
            self.assertEqual(reconstructed[f"/findings/{index}/title"], finding["title"])

    def test_detail_rejects_malformed_or_mismatched_continuation(self) -> None:
        report = self.submit(key="cursor-detail", title="Report", outcome="Long " * 2_000)
        first = get_activity_report(self.service, partition="production", report_id=str(report.id))
        self.assertIsNotNone(first["next_cursor"])
        with self.assertRaises(AgentReportReadInputError):
            get_activity_report(
                self.service, partition="sandbox", report_id=str(report.id), cursor=first["next_cursor"],
            )
        with self.assertRaises(AgentReportReadInputError):
            get_activity_report(self.service, partition="production", report_id=str(report.id), cursor="not-a-cursor")


if __name__ == "__main__":
    unittest.main()
