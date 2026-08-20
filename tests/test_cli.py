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

    def test_status_and_agents_use_existing_read_routes(self) -> None:
        status_code, status_output, _, status_session = self._run(
            ["status"],
            [
                _Response(200, {"status": "ready", "config": "ok", "database": "ok"}),
                _Response(
                    200,
                    {
                        "default_agent": "apodemus",
                        "agent_initial_selection": {
                            "runtime": "local",
                            "agent": "apodemus",
                            "effort": None,
                        },
                    },
                ),
            ],
        )
        self.assertEqual(status_code, 0)
        self.assertIn("ready", status_output.lower())
        self.assertIn("apodemus", status_output.lower())
        self.assertEqual(status_session.calls[0]["method"], "GET")
        self.assertEqual(status_session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/health/ready")
        self.assertEqual(status_session.calls[1]["url"], f"{cli.API_ROOT}/api/v1/config")
        self.assertFalse(status_session.calls[0]["allow_redirects"])
        self.assertFalse(status_session.trust_env)
        self.assertTrue(status_session.closed)

        agent_code, agent_output, _, agent_session = self._run(
            ["agents"],
            [_Response(200, [{
                "key": "panthera", "display_name": "Apex Panthera",
                "runtime": "cloud", "provider": "openai",
                "configured_model": "model", "status": "available",
            }])],
        )
        self.assertEqual(agent_code, 0)
        self.assertIn("Panthera", agent_output)
        self.assertEqual(agent_session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/agents")

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
            ["ask", "Plan", "--agent", "panthera", "--effort", "focused", "--profile", "daily_planning"],
            [_Response(201, {"id": "conversation-2"}), response],
        )
        self.assertEqual(code, 0)
        self.assertEqual({key: value for key, value in session.calls[1]["json"].items() if key not in {"user_message_id", "agent_message_id"}}, {
            "prompt": "Plan", "agent": "panthera", "effort": "focused",
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
                        "default_agent": "panthera",
                        "agent_initial_selection": {
                            "runtime": "cloud",
                            "agent": "panthera",
                            "effort": "focused",
                        },
                    },
                ),
            ],
        )
        self.assertEqual(code, 0)
        status_payload = json.loads(output)
        self.assertEqual(status_payload["status"], "ready")
        self.assertEqual(status_payload["agent"]["key"], "panthera")

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
