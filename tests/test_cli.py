"""Focused contract coverage for the loopback APEX command-line client."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import requests

from apex import cli


class _Response:
    def __init__(self, status_code: int, payload: object | Exception) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, responses: list[object]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append({"method": method, "url": url, **kwargs})
        next_response = next(self._responses)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    def close(self) -> None:
        self.closed = True


class CliTests(unittest.TestCase):
    def _run(
        self,
        argv: list[str],
        responses: list[object],
    ) -> tuple[int, str, str, _Session]:
        session = _Session(responses)
        output = io.StringIO()
        errors = io.StringIO()
        with (
            redirect_stdout(output),
            redirect_stderr(errors),
            mock.patch("apex.cli.ApiClient", return_value=cli.ApiClient(session)),
        ):
            code = cli.main(argv)
        return code, output.getvalue(), errors.getvalue(), session

    def test_status_and_models_use_current_read_routes(self) -> None:
        status_code, status_output, _, status_session = self._run(
            ["status"],
            [
                _Response(200, {"status": "ready", "config": "ok", "database": "ok"}),
                _Response(
                    200,
                    {
                        "cortex_initial_selection": {
                            "runtime": "local",
                            "agent": "apex",
                            "model_id": "gemma-4-E2B-Q4_K_M.gguf",
                            "effort": None,
                        },
                    },
                ),
            ],
        )
        self.assertEqual(status_code, 0)
        self.assertIn("ready", status_output.lower())
        self.assertIn("apex", status_output.lower())
        self.assertIn("gemma-4-e2b", status_output.lower())
        self.assertEqual(status_session.calls[0]["method"], "GET")
        self.assertEqual(status_session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/health/ready")
        self.assertEqual(status_session.calls[1]["url"], f"{cli.API_ROOT}/api/v1/config")
        self.assertFalse(status_session.calls[0]["allow_redirects"])
        self.assertFalse(status_session.trust_env)
        self.assertTrue(status_session.closed)

        agent_code, agent_output, _, agent_session = self._run(
            ["models"],
            [_Response(200, {"key": "apex", "model_catalog": [{
                "model_id": "deepseek/deepseek-v4-flash-0731", "display_name": "DeepSeek V4 Flash",
                "runtime": "cloud", "provider": "openrouter", "status": "available",
            }]})],
        )
        self.assertEqual(agent_code, 0)
        self.assertIn("DeepSeek", agent_output)
        self.assertEqual(agent_session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/agent")

    def test_ask_preserves_backend_defaults_and_sends_explicit_options(self) -> None:
        conversation = _Response(201, {"id": "conversation-1"})
        response = _Response(200, {"answer": "Ready.", "tool_outputs": []})
        code, _, _, session = self._run(["ask", "  Hello  "], [conversation, response])
        self.assertEqual(code, 0)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/conversations")
        self.assertEqual(session.calls[0]["json"], {"origin": "cli", "title": "CLI: Hello"})
        self.assertEqual(session.calls[1]["url"], f"{cli.API_ROOT}/api/v1/cortex/conversations/conversation-1/turns")
        self.assertEqual(session.calls[1]["json"]["prompt"], "Hello")

        code, _, _, session = self._run(
            ["ask", "Plan", "--model", "deepseek/deepseek-v4-flash-0731", "--effort", "high", "--profile", "daily_planning"],
            [_Response(201, {"id": "conversation-2"}), response],
        )
        self.assertEqual(code, 0)
        self.assertEqual({key: value for key, value in session.calls[1]["json"].items() if key not in {"user_message_id", "agent_message_id"}}, {
            "prompt": "Plan", "model_id": "deepseek/deepseek-v4-flash-0731", "effort": "high",
            "tool_profile_id": "daily_planning",
        })
        self.assertEqual(session.calls[1]["timeout"], (3.0, 600.0))

    def test_briefing_and_action_reads_map_to_their_existing_routes(self) -> None:
        briefing_code, briefing_output, _, briefing_session = self._run(
            ["briefing", "--mode", "structured"],
            [_Response(200, {"status": "ok", "briefing": "All clear."})],
        )
        self.assertEqual(briefing_code, 0)
        self.assertIn("All clear.", briefing_output)
        self.assertEqual(briefing_session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/trigger")
        self.assertEqual(briefing_session.calls[0]["json"], {"mode": "structured"})

        listed_code, _, _, listed_session = self._run(
            ["actions", "list"],
            [_Response(200, [{"action_id": "action-1", "status": "proposed", "proposal": {"risk": "write", "summary": "Approve"}}])],
        )
        self.assertEqual(listed_code, 0)
        self.assertEqual(listed_session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/actions")

        shown_code, shown_output, _, shown_session = self._run(
            ["actions", "show", "action/a"],
            [_Response(200, {"action_id": "action/a", "status": "proposed", "proposal": {"risk": "write", "capability_name": "create", "summary": "Approve", "arguments": {}}, "events": []})],
        )
        self.assertEqual(shown_code, 0)
        self.assertIn("action/a", shown_output)
        self.assertEqual(shown_session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/actions/action%2Fa")

    def test_context_status_and_prepare_use_explicit_retrieval_routes(self) -> None:
        code, output, _, session = self._run(
            ["context", "status"],
            [_Response(200, {"enabled": True, "mode": "fts_only", "state": "unprepared", "indexed_items": 2, "embedding_items": 0, "pending_items": 1})],
        )
        self.assertEqual(code, 0)
        self.assertIn("fts_only", output)
        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/retrieval/status")

        code, _, _, session = self._run(
            ["context", "prepare"],
            [_Response(200, {"enabled": True, "mode": "semantic", "state": "ready", "indexed_items": 2, "embedding_items": 2, "pending_items": 0})],
        )
        self.assertEqual(code, 0)
        self.assertEqual(session.calls[0]["method"], "POST")
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/retrieval/prepare")
        self.assertEqual(session.calls[0]["timeout"], (3.0, 600.0))

    def test_context_list_encodes_repeated_filters_and_query(self) -> None:
        code, output, _, session = self._run(
            [
                "context",
                "list",
                "--status",
                "active",
                "--status",
                "conflicting",
                "--kind",
                "preference",
                "--query",
                "plan/review now",
                "--limit",
                "7",
            ],
            [_Response(200, [{"id": "record-1", "kind": "preference", "status": "active", "text": "Plan."}])],
        )
        self.assertEqual(code, 0)
        self.assertIn("record-1", output)
        self.assertEqual(
            session.calls[0]["url"],
            f"{cli.API_ROOT}/api/v1/cortex/context?status=active&status=conflicting&kind=preference&q=plan%2Freview%20now&limit=7",
        )

    def test_context_show_renders_sources_history_and_related_ids(self) -> None:
        detail = {
            "id": "record/1",
            "kind": "preference",
            "status": "active",
            "text": "I prefer short plans.",
            "subject": {"id": "entity-1", "name": "Operator", "aliases": []},
            "predicate": "prefers",
            "object_value": "short plans",
            "created_at": "2026-09-11T10:00:00Z",
            "updated_at": "2026-09-11T10:00:00Z",
            "sources": [{
                "id": "source-1",
                "kind": "conversation_message",
                "origin": "operator_input",
                "derivation": "direct",
                "locator": "conversation/1/message/2",
                "occurred_at": None,
                "captured_at": "2026-09-11T10:00:01Z",
                "linked_at": "2026-09-11T10:00:02Z",
                "original_text": "I prefer short plans.",
            }],
            "history": [{
                "id": "history-1",
                "operation": "created",
                "reason_code": "direct_save",
                "actor": "operator",
                "created_at": "2026-09-11T10:00:00Z",
                "source_id": "source-1",
            }],
            "related_records": [{"id": "record-2"}],
            "pending_review_ids": ["review-1"],
            "predecessors": [],
            "superseded_by": [],
        }
        code, output, _, session = self._run(
            ["context", "show", "record/1"], [_Response(200, detail)]
        )
        self.assertEqual(code, 0)
        self.assertIn("conversation_message", output)
        self.assertIn("operator_input", output)
        self.assertIn("direct", output)
        self.assertIn("Locator: conversation/1/message/2", output)
        self.assertIn("Occurred At: Not recorded", output)
        self.assertIn("Captured At: 2026-09-11T10:00:01Z", output)
        self.assertIn("Linked At: 2026-09-11T10:00:02Z", output)
        self.assertIn("Original: I prefer short plans.", output)
        self.assertIn("direct_save", output)
        self.assertIn("Related record IDs: record-2", output)
        self.assertIn("Pending review IDs: review-1", output)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/context/record%2F1")

    def test_context_add_sends_save_fields_and_reports_saved(self) -> None:
        code, output, _, session = self._run(
            [
                "context",
                "add",
                "I prefer short plans.",
                "--kind",
                "preference",
                "--subject",
                "Operator",
                "--predicate",
                "prefers",
                "--object-value",
                "short plans",
                "--effective-at",
                "2026-09-11",
                "--sensitive",
                "--idempotency-key",
                "save-1",
            ],
            [_Response(200, {"outcome": "saved", "record_id": "record-1", "review_id": None})],
        )
        self.assertEqual(code, 0)
        self.assertIn("Saved", output)
        self.assertEqual(session.calls[0]["method"], "POST")
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/context/saves")
        self.assertEqual(
            session.calls[0]["json"],
            {
                "text": "I prefer short plans.",
                "kind": "preference",
                "subject": "Operator",
                "predicate": "prefers",
                "object_value": "short plans",
                "effective_at": "2026-09-11",
                "sensitive": True,
                "idempotency_key": "save-1",
            },
        )

    def test_context_add_reports_review_required_without_failure(self) -> None:
        code, output, _, _ = self._run(
            ["context", "add", "Possible conflict.", "--kind", "note"],
            [_Response(200, {"outcome": "review_required", "review_id": "review-1"})],
        )
        self.assertEqual(code, 0)
        self.assertIn("Needs review: review-1", output)

    def test_context_correct_reads_updated_at_before_save(self) -> None:
        code, _, _, session = self._run(
            ["context", "correct", "record/1", "Corrected text.", "--kind", "fact", "--idempotency-key", "correct-1"],
            [
                _Response(200, {"id": "record/1", "updated_at": "2026-09-11T10:00:00Z"}),
                _Response(200, {"outcome": "saved", "record_id": "record-2"}),
            ],
        )
        self.assertEqual(code, 0)
        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/context/record%2F1")
        self.assertEqual(session.calls[1]["method"], "POST")
        self.assertEqual(
            session.calls[1]["json"],
            {
                "text": "Corrected text.",
                "kind": "fact",
                "sensitive": False,
                "idempotency_key": "correct-1",
                "correction_record_id": "record/1",
                "expected_updated_at": "2026-09-11T10:00:00Z",
            },
        )

    def test_context_retract_reports_action_and_review_ids(self) -> None:
        code, output, _, session = self._run(
            ["context", "retract", "record-1"],
            [_Response(200, {
                "action_id": "action-1",
                "status": "proposed",
                "proposal": {"arguments": {"review_id": "review-1"}},
            })],
        )
        self.assertEqual(code, 0)
        self.assertIn("Action ID: action-1", output)
        self.assertIn("Review ID: review-1", output)
        self.assertEqual(session.calls[0]["json"], {"operation": "retract", "record_id": "record-1"})

    def test_context_review_list_and_show_use_review_routes(self) -> None:
        code, output, _, session = self._run(
            ["context", "review", "list", "--decision", "pending", "--decision", "stale", "--limit", "4"],
            [_Response(200, [{"id": "review-1", "decision": "pending", "operation": "capture", "reason_codes": ["sensitive"]}])],
        )
        self.assertEqual(code, 0)
        self.assertIn("review-1", output)
        self.assertEqual(
            session.calls[0]["url"],
            f"{cli.API_ROOT}/api/v1/cortex/context/reviews?decision=pending&decision=stale&limit=4",
        )

        code, output, _, session = self._run(
            ["context", "review", "show", "review/1"],
            [_Response(200, {
                "id": "review/1",
                "decision": "pending",
                "operation": "capture",
                "partition": "production",
                "reason_codes": ["sensitive"],
                "expected_revisions": {"record-1": "revision-1"},
                "proposal": {"text": "Secret preference"},
                "evidence": {"original_text": "Secret preference"},
            })],
        )
        self.assertEqual(code, 0)
        self.assertIn("Expected revisions", output)
        self.assertIn("record-1: revision-1", output)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/context/reviews/review%2F1")

    def test_context_review_decisions_read_revisions_and_reject_succeeds(self) -> None:
        for operation, decision in (("accept", "accepted"), ("reject", "rejected")):
            with self.subTest(operation=operation):
                code, output, _, session = self._run(
                    ["context", "review", operation, "review-1"],
                    [
                        _Response(200, {"id": "review-1", "expected_revisions": {"record-1": "revision-1"}}),
                        _Response(200, {"id": "review-1", "decision": decision, "action_id": "action-1"}),
                    ],
                )
                self.assertEqual(code, 0)
                self.assertIn(f"Decision: {decision}", output)
                self.assertEqual(session.calls[0]["method"], "GET")
                self.assertEqual(session.calls[1]["method"], "POST")
                self.assertEqual(session.calls[1]["json"], {"expected_revisions": {"record-1": "revision-1"}})

    def test_context_review_stale_conflict_reports_server_message_without_retry(self) -> None:
        code, _, errors, session = self._run(
            ["context", "review", "accept", "review-1"],
            [
                _Response(200, {"id": "review-1", "expected_revisions": {"record-1": "revision-1"}}),
                _Response(409, {"detail": "Context changed; refresh the review and decide again."}),
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("refresh the review", errors)
        self.assertEqual(len(session.calls), 2)

    def test_context_json_returns_complete_success_payload(self) -> None:
        response = {"outcome": "review_required", "record_id": None, "review_id": "review-1"}
        code, output, errors, _ = self._run(
            ["context", "add", "Needs review.", "--kind", "note", "--json"],
            [_Response(200, response)],
        )
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(json.loads(output), response)

    def test_action_mutations_fetch_current_version_once_then_submit_it(self) -> None:
        for operation, expected_status in (("approve", "verified"), ("reject", "rejected"), ("verify", "verified")):
            with self.subTest(operation=operation):
                code, _, _, session = self._run(
                    ["actions", operation, "action-1"],
                    [
                        _Response(200, {"action_id": "action-1", "version": 7}),
                        _Response(200, {"action_id": "action-1", "status": expected_status}),
                    ],
                )
                self.assertEqual(code, 0)
                self.assertEqual(len(session.calls), 2)
                self.assertEqual(session.calls[0]["method"], "GET")
                self.assertEqual(session.calls[1]["method"], "POST")
                self.assertEqual(session.calls[1]["url"], f"{cli.API_ROOT}/api/v1/actions/action-1/{operation}")
                self.assertEqual(session.calls[1]["json"], {"expected_version": 7})

    def test_action_conflicts_and_unknown_outcomes_do_not_retry(self) -> None:
        code, _, errors, session = self._run(
            ["actions", "approve", "action-1"],
            [
                _Response(200, {"action_id": "action-1", "version": 2}),
                _Response(409, {"detail": "Action is no longer in the requested state."}),
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("no longer", errors)
        self.assertEqual(len(session.calls), 2)

        code, output, _, session = self._run(
            ["actions", "approve", "action-1"],
            [
                _Response(200, {"action_id": "action-1", "version": 2}),
                _Response(200, {"action_id": "action-1", "status": "outcome_unknown"}),
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("outcome_unknown", output)
        self.assertEqual(len(session.calls), 2)

    def test_json_output_and_safe_transport_errors(self) -> None:
        code, output, _, _ = self._run(
            ["status", "--json"],
            [
                _Response(200, {"status": "ready", "config": "ok", "database": "ok"}),
                _Response(
                    200,
                    {
                        "cortex_initial_selection": {
                            "runtime": "cloud",
                            "agent": "apex",
                            "model_id": "deepseek/deepseek-v4-flash-0731",
                            "effort": "high",
                        },
                    },
                ),
            ],
        )
        self.assertEqual(code, 0)
        status_payload = json.loads(output)
        self.assertEqual(status_payload["status"], "ready")
        self.assertEqual(status_payload["agent"]["key"], "apex")

        code, output, errors, _ = self._run(
            ["--json", "status"],
            [requests.Timeout("private")],
        )
        self.assertEqual(code, 1)
        self.assertEqual(errors, "")
        error = json.loads(output)["error"]
        self.assertEqual(error["kind"], "backend_unavailable")
        self.assertNotIn("private", output)

        code, output, errors, session = self._run(
            ["status"],
            [_Response(302, ValueError("redirect body"))],
        )
        self.assertEqual(code, 1)
        self.assertIn("HTTP 302", errors)
        self.assertEqual(len(session.calls), 1)

    def test_invalid_json_and_agent_errors_are_nonzero(self) -> None:
        code, _, errors, _ = self._run(
            ["status"], [_Response(200, ValueError("not json"))]
        )
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", errors)

        code, _, errors, _ = self._run(
            ["status"], [_Response(200, ["not a readiness object"])]
        )
        self.assertEqual(code, 1)
        self.assertIn("invalid readiness", errors)

        code, output, errors, _ = self._run(
            ["ask", "Hello"], [_Response(201, {"id": "conversation-1"}), _Response(200, {"answer": "Partial.", "error": "Agent stopped."})]
        )
        self.assertEqual(code, 1)
        self.assertIn("Partial.", output)
        self.assertIn("Agent stopped.", errors)

        code, output, errors, _ = self._run(
            ["--json", "ask", "Hello"],
            [_Response(201, {"id": "conversation-1"}), _Response(200, {"answer": "Partial.", "error": "Agent stopped."})],
        )
        self.assertEqual(code, 1)
        self.assertEqual(errors, "")
        self.assertEqual(json.loads(output)["error"]["kind"], "agent_error")

    def test_invalid_usage_keeps_argparse_exit_code_two(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "2"):
                cli.main(["ask"])


if __name__ == "__main__":
    unittest.main()
