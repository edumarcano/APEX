"""Focused contract coverage for the apex runs command-line subsystem."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

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
        self.trust_env = False

    def request(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append({"method": method, "url": url, **kwargs})
        next_response = next(self._responses)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    def close(self) -> None:
        self.closed = True


class CliRunsTests(unittest.TestCase):
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

    def test_runs_list(self) -> None:
        runs_response = _Response(200, [
            {
                "id": "run-1",
                "status": "completed",
                "resolved_model": "deepseek/deepseek-v4-flash-0731",
                "runtime": "cloud",
                "total_tokens": 512,
                "elapsed_seconds": 1.25,
            },
            {
                "id": "run-2",
                "status": "running",
                "requested_model": "gemma-4-E2B-Q4_K_M.gguf",
                "runtime": "local",
                "total_tokens": 128,
                "elapsed_seconds": 0.4,
            },
        ])
        code, output, _, session = self._run(
            ["runs", "list", "--status", "completed", "--limit", "10"],
            [runs_response],
        )
        self.assertEqual(code, 0)
        self.assertIn("run-1", output)
        self.assertIn("completed", output)
        self.assertIn("512 tok", output)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/runs?status=completed&limit=10")

    def test_runs_list_json(self) -> None:
        runs_data = [
            {
                "id": "run-1",
                "status": "completed",
                "total_tokens": 512,
            }
        ]
        runs_response = _Response(200, runs_data)
        code, output, _, _ = self._run(
            ["runs", "list", "--json"],
            [runs_response],
        )
        self.assertEqual(code, 0)
        parsed = json.loads(output)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "run-1")

    def test_runs_show(self) -> None:
        run_detail = _Response(200, {
            "id": "run-abc",
            "status": "completed",
            "stop_reason": "end_turn",
            "conversation_id": "conv-xyz",
            "resolved_model": "deepseek/deepseek-v4-flash-0731",
            "runtime": "cloud",
            "provider": "openrouter",
            "total_tokens": 1024,
            "usage_quality": "reported",
            "elapsed_seconds": 2.1,
            "turns_count": 2,
            "tool_calls_count": 1,
            "retries_count": 0,
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "evidence": {
                "answer_persisted": True,
                "tool_outcome_counts": {"weather_forecast": 1},
                "action_ids": [],
            },
        })
        code, output, _, session = self._run(
            ["runs", "show", "run-abc"],
            [run_detail],
        )
        self.assertEqual(code, 0)
        self.assertIn("Run ID: run-abc", output)
        self.assertIn("Status: completed", output)
        self.assertIn("Stop Reason: end_turn", output)
        self.assertIn("Model: deepseek/deepseek-v4-flash-0731 (cloud / openrouter)", output)
        self.assertIn("Tokens: 1024 (reported)", output)
        self.assertIn("Trace ID: 4bf92f3577b34da6a3ce929d0e0e4736", output)
        self.assertIn("Answer Persisted: True", output)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/runs/run-abc")

    def test_runs_show_json(self) -> None:
        run_detail = {
            "id": "run-abc",
            "status": "completed",
            "total_tokens": 1024,
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        }
        resp = _Response(200, run_detail)
        code, output, _, _ = self._run(
            ["runs", "show", "run-abc", "--json"],
            [resp],
        )
        self.assertEqual(code, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["id"], "run-abc")
        self.assertEqual(parsed["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")

    def test_runs_show_not_found(self) -> None:
        resp = _Response(404, {"detail": "Run was not found."})
        code, _, errors, _ = self._run(
            ["runs", "show", "run-nonexistent"],
            [resp],
        )
        self.assertEqual(code, 1)
        self.assertIn("Run was not found", errors)

    def test_runs_cancel(self) -> None:
        cancel_response = _Response(200, {
            "id": "run-abc",
            "status": "cancelled",
            "stop_reason": "operator_cancelled",
        })
        code, output, _, session = self._run(
            ["runs", "cancel", "run-abc"],
            [cancel_response],
        )
        self.assertEqual(code, 0)
        self.assertIn("Run ID: run-abc", output)
        self.assertIn("Status: cancelled", output)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/runs/run-abc/cancel")
        self.assertEqual(session.calls[0]["method"], "POST")

    def test_runs_cancel_json(self) -> None:
        cancel_response = {
            "id": "run-abc",
            "status": "cancelled",
            "stop_reason": "operator_cancelled",
        }
        resp = _Response(200, cancel_response)
        code, output, _, _ = self._run(
            ["runs", "cancel", "run-abc", "--json"],
            [resp],
        )
        self.assertEqual(code, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["status"], "cancelled")

    def test_runs_invalid_run_id(self) -> None:
        code, _, errors, _ = self._run(
            ["runs", "show", "   "],
            [],
        )
        self.assertEqual(code, 1)
        self.assertIn("Run ID must contain non-whitespace text", errors)


if __name__ == "__main__":
    unittest.main()
