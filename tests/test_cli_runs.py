"""Focused contract coverage for the apex runs command-line subsystem."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from typing import Any
from unittest import mock

import requests

from apex import cli


class _Response:
    def __init__(self, status_code: int, payload: object | Exception, lines: list[Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self._lines = lines or []
        self.closed = False

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_lines(self, decode_unicode: bool = True) -> Any:
        for line in self._lines:
            if isinstance(line, Exception):
                raise line
            yield line

    def close(self) -> None:
        self.closed = True


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

    def get(self, url: str, **kwargs: object) -> object:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> object:
        return self.request("POST", url, **kwargs)

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

    def test_runs_start_detached(self) -> None:
        conversation = _Response(201, {"id": "conv-101"})
        run_record = _Response(202, {
            "id": "run-202",
            "status": "queued",
            "requested_model": "deepseek/deepseek-v4-flash-0731",
            "conversation_id": "conv-101",
        })
        code, output, errors, session = self._run(
            ["runs", "start", "What is the plan?", "--detach", "--model", "deepseek/deepseek-v4-flash-0731"],
            [conversation, run_record],
        )
        self.assertEqual(code, 0)
        self.assertIn("run-202", output)
        self.assertIn("queued", output)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/conversations")
        self.assertEqual(session.calls[1]["url"], f"{cli.API_ROOT}/api/v1/cortex/conversations/conv-101/runs")
        self.assertEqual(session.calls[1]["json"]["prompt"], "What is the plan?")
        self.assertEqual(session.calls[1]["json"]["model_id"], "deepseek/deepseek-v4-flash-0731")

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

    def test_runs_follow_channel_separation(self) -> None:
        lines = [
            "id: 1",
            "event: model.started",
            'data: {"turn": 1}',
            "",
            "id: 2",
            "event: response.delta",
            'data: {"delta": "Hello, "}',
            "",
            "id: 3",
            "event: tool.started",
            'data: {"name": "weather_forecast"}',
            "",
            "id: 4",
            "event: tool.completed",
            'data: {"name": "weather_forecast", "status": "ok", "duration_ms": 120.4}',
            "",
            "id: 5",
            "event: response.delta",
            'data: {"delta": "world!"}',
            "",
            "id: 6",
            "event: run.completed",
            'data: {"record": {"id": "run-xyz", "status": "completed", "total_tokens": 120, "elapsed_seconds": 0.8, "resolved_model": "deepseek"}}',
            "",
        ]
        sse_response = _Response(200, {}, lines=lines)
        code, stdout, stderr, session = self._run(
            ["runs", "follow", "run-xyz"],
            [sse_response],
        )
        self.assertEqual(code, 0)
        # Verify text deltas routed to stdout
        self.assertEqual(stdout.strip(), "Hello, world!")

        # Verify activity and summary footer routed to stderr
        self.assertIn("[Model started: turn 1]", stderr)
        self.assertIn("[Tool started: weather_forecast]", stderr)
        self.assertIn("[Tool completed: weather_forecast (ok, 120ms)]", stderr)
        self.assertIn("[Run completed: 0.8s | 120 tokens | deepseek]", stderr)
        self.assertEqual(session.calls[0]["url"], f"{cli.API_ROOT}/api/v1/cortex/runs/run-xyz/events")

    def test_runs_follow_json_emits_ndjson(self) -> None:
        lines = [
            "id: 1",
            "event: response.delta",
            'data: {"delta": "test"}',
            "",
            "id: 2",
            "event: run.completed",
            'data: {"record": {"status": "completed"}}',
            "",
        ]
        sse_response = _Response(200, {}, lines=lines)
        code, stdout, stderr, _ = self._run(
            ["runs", "follow", "run-xyz", "--json"],
            [sse_response],
        )
        self.assertEqual(code, 0)
        ndjson_lines = [line for line in stdout.strip().split("\n") if line]
        self.assertEqual(len(ndjson_lines), 2)
        parsed_1 = json.loads(ndjson_lines[0])
        parsed_2 = json.loads(ndjson_lines[1])
        self.assertEqual(parsed_1.get("delta"), "test")
        self.assertEqual(parsed_2.get("record", {}).get("status"), "completed")

    def test_runs_follow_ctrl_c_detaches_cleanly(self) -> None:
        class _InterruptingSession(_Session):
            def get(self, url: str, **kwargs: object) -> object:
                raise KeyboardInterrupt()

        output = io.StringIO()
        errors = io.StringIO()
        with (
            redirect_stdout(output),
            redirect_stderr(errors),
            mock.patch("apex.cli.ApiClient", return_value=cli.ApiClient(_InterruptingSession([]))),
        ):
            code = cli.main(["runs", "follow", "run-int"])

        self.assertEqual(code, 0)
        self.assertIn("Detached from run run-int", errors.getvalue())
        self.assertIn("Run continues in background", errors.getvalue())

    def test_runs_follow_reconnects_with_last_event_id(self) -> None:
        # First connection drops after event 1; second connection continues with event 2 and 3
        lines_1 = [
            "id: 1",
            "event: response.delta",
            'data: {"delta": "Part 1. "}',
            "",
        ]
        lines_2 = [
            "id: 2",
            "event: response.delta",
            'data: {"delta": "Part 2."}',
            "",
            "id: 3",
            "event: run.completed",
            'data: {"record": {"status": "completed"}}',
            "",
        ]
        resp_1 = _Response(200, {}, lines=lines_1)
        resp_2 = _Response(200, {}, lines=lines_2)
        code, stdout, _, session = self._run(
            ["runs", "follow", "run-stream"],
            [resp_1, resp_2],
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), "Part 1. Part 2.")
        self.assertEqual(len(session.calls), 2)
        # Check that second request passed Last-Event-ID: 1
        self.assertEqual(session.calls[1]["headers"].get("Last-Event-ID"), "1")
        self.assertTrue(resp_1.closed)
        self.assertTrue(resp_2.closed)

    def test_runs_follow_reconnects_on_midstream_network_drop(self) -> None:
        lines_1 = [
            "id: 1",
            "event: response.delta",
            'data: {"delta": "Hello "}',
            "",
            requests.RequestException("connection dropped mid-stream"),
        ]
        lines_2 = [
            "id: 2",
            "event: response.delta",
            'data: {"delta": "world!"}',
            "",
            "id: 3",
            "event: run.completed",
            'data: {"record": {"status": "completed"}}',
            "",
        ]
        resp_1 = _Response(200, {}, lines=lines_1)
        resp_2 = _Response(200, {}, lines=lines_2)
        code, stdout, _, session = self._run(
            ["runs", "follow", "run-drop"],
            [resp_1, resp_2],
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), "Hello world!")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[1]["headers"].get("Last-Event-ID"), "1")
        self.assertTrue(resp_1.closed)
        self.assertTrue(resp_2.closed)

    def test_runs_follow_terminal_snapshot_does_not_retry(self) -> None:
        lines = [
            "id: 0",
            "event: run.snapshot",
            'data: {"run": {"id": "run-old", "status": "completed", "total_tokens": 256, "elapsed_seconds": 1.5, "resolved_model": "deepseek"}, "answer": "Done."}',
            "",
        ]
        resp = _Response(200, {}, lines=lines)
        code, stdout, stderr, session = self._run(
            ["runs", "follow", "run-old"],
            [resp],
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), "Done.")
        self.assertIn("[Run completed: 1.5s | 256 tokens | deepseek]", stderr)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(resp.closed)


if __name__ == "__main__":
    unittest.main()
