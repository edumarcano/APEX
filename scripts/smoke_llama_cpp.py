"""Optional live smoke checks against a local llama.cpp router.

Never run this script in normal CI. It contacts a real router when available and
prints a pass/fail table for manual validation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, ROOT)


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""


def _auth_headers() -> dict[str, str]:
    api_key = os.getenv("LLAMA_CPP_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        return {}
    return {"Authorization": f"Bearer {api_key.strip()}"}


def _chat(
    host: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 256,
        "reasoning_effort": "none",
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = True
    response = requests.post(
        f"{host.rstrip('/')}/v1/chat/completions",
        params={"autoload": "false"},
        json=payload,
        headers=_auth_headers(),
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("chat response was not a JSON object")
    return data


def _weather_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Get a short weather forecast for a city.",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
    }


def _crypto_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "fetch_crypto_price",
            "description": "Fetch a cryptocurrency spot price.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    }


def _assistant_message(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("missing choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("missing message")
    return message


def _run_checks(
    *,
    host: str,
    model: str,
    do_load: bool,
    do_unload: bool,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    try:
        response = requests.get(
            f"{host.rstrip('/')}/models",
            headers=_auth_headers(),
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
        results.append(CheckResult("Router reachable", "PASS"))
    except Exception as exc:
        results.append(
            CheckResult("Router reachable", "FAIL", type(exc).__name__)
        )
        return results

    installed: list[str] = []
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                installed.append(row["id"])
    if model in installed:
        results.append(CheckResult("Runtime alias configured", "PASS", model))
    else:
        results.append(
            CheckResult(
                "Runtime alias configured",
                "FAIL",
                f"{model} not listed by /models",
            )
        )

    if do_load:
        try:
            load = requests.post(
                f"{host.rstrip('/')}/models/load",
                json={"model": model},
                headers=_auth_headers(),
                timeout=60.0,
            )
            load.raise_for_status()
            results.append(CheckResult("Explicit load", "PASS"))
        except Exception as exc:
            results.append(CheckResult("Explicit load", "FAIL", type(exc).__name__))
            return results
    else:
        results.append(CheckResult("Explicit load", "SKIP", "--load not set"))

    try:
        data = _chat(
            host,
            model,
            [{"role": "user", "content": "Reply with exactly: smoke-ok"}],
        )
        content = _assistant_message(data).get("content")
        if isinstance(content, str) and content.strip():
            results.append(CheckResult("Basic final answer", "PASS"))
        else:
            results.append(CheckResult("Basic final answer", "FAIL", "empty content"))
    except Exception as exc:
        results.append(CheckResult("Basic final answer", "FAIL", type(exc).__name__))

    tool_message: dict[str, Any] | None = None
    try:
        data = _chat(
            host,
            model,
            [
                {
                    "role": "user",
                    "content": (
                        "Call get_weather_forecast for Boston. "
                        "Do not answer in plain text."
                    ),
                }
            ],
            tools=[_weather_tool()],
        )
        tool_message = _assistant_message(data)
        tool_calls = tool_message.get("tool_calls") or []
        if isinstance(tool_calls, list) and tool_calls:
            results.append(CheckResult("Single tool call", "PASS"))
        else:
            results.append(CheckResult("Single tool call", "FAIL", "no tool_calls"))
    except Exception as exc:
        results.append(CheckResult("Single tool call", "FAIL", type(exc).__name__))

    try:
        data = _chat(
            host,
            model,
            [
                {
                    "role": "user",
                    "content": (
                        "Call get_weather_forecast for Boston and "
                        "fetch_crypto_price for BTC in one response."
                    ),
                }
            ],
            tools=[_weather_tool(), _crypto_tool()],
        )
        calls = _assistant_message(data).get("tool_calls") or []
        names = {
            call.get("function", {}).get("name")
            for call in calls
            if isinstance(call, dict)
        }
        if {"get_weather_forecast", "fetch_crypto_price"} <= names:
            results.append(CheckResult("Parallel tool calls", "PASS"))
        else:
            results.append(
                CheckResult("Parallel tool calls", "FAIL", f"names={sorted(names)}")
            )
    except Exception as exc:
        results.append(CheckResult("Parallel tool calls", "FAIL", type(exc).__name__))

    try:
        if not tool_message or not (tool_message.get("tool_calls") or []):
            raise RuntimeError("missing prior tool call")
        prior_call = tool_message["tool_calls"][0]
        continuation = _chat(
            host,
            model,
            [
                {"role": "user", "content": "What is the weather in Boston?"},
                {
                    "role": "assistant",
                    "content": tool_message.get("content") or "",
                    "tool_calls": [prior_call],
                },
                {
                    "role": "tool",
                    "tool_call_id": prior_call.get("id") or "call_1",
                    "name": "get_weather_forecast",
                    "content": json.dumps({"summary": "clear", "temp_f": 68}),
                },
            ],
            tools=[_weather_tool()],
        )
        answer = _assistant_message(continuation).get("content")
        if isinstance(answer, str) and answer.strip():
            results.append(CheckResult("Tool-result continuation", "PASS"))
        else:
            results.append(
                CheckResult("Tool-result continuation", "FAIL", "empty answer")
            )
    except Exception as exc:
        results.append(
            CheckResult("Tool-result continuation", "FAIL", type(exc).__name__)
        )

    try:
        data = _chat(
            host,
            model,
            [{"role": "user", "content": "Say hello without hidden reasoning."}],
        )
        message = _assistant_message(data)
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content")
        think_open = "<" + "think" + ">"
        if reasoning or think_open in str(content):
            results.append(
                CheckResult("Reasoning absent from answer", "FAIL", "hidden content")
            )
        else:
            results.append(CheckResult("Reasoning absent from answer", "PASS"))
    except Exception as exc:
        results.append(
            CheckResult("Reasoning absent from answer", "FAIL", type(exc).__name__)
        )

    try:
        data = _chat(
            host,
            model,
            [{"role": "user", "content": "Reply with ok"}],
        )
        usage = data.get("usage")
        if isinstance(usage, dict) and (
            "prompt_tokens" in usage or "completion_tokens" in usage
        ):
            results.append(CheckResult("Usage fields", "PASS"))
        else:
            results.append(CheckResult("Usage fields", "SKIP", "not reported"))
        timings = data.get("timings")
        if isinstance(timings, dict) and timings:
            results.append(CheckResult("Timing fields", "PASS"))
        else:
            results.append(CheckResult("Timing fields", "SKIP", "not reported"))
    except Exception as exc:
        results.append(CheckResult("Usage fields", "FAIL", type(exc).__name__))
        results.append(CheckResult("Timing fields", "FAIL", type(exc).__name__))

    if do_unload:
        try:
            unload = requests.post(
                f"{host.rstrip('/')}/models/unload",
                json={"model": model},
                headers=_auth_headers(),
                timeout=30.0,
            )
            unload.raise_for_status()
            results.append(CheckResult("Explicit unload", "PASS"))
        except Exception as exc:
            results.append(CheckResult("Explicit unload", "FAIL", type(exc).__name__))
    else:
        results.append(CheckResult("Explicit unload", "SKIP", "--unload not set"))

    return results


def _print_table(results: list[CheckResult]) -> None:
    width = max(len(item.name) for item in results)
    print()
    print(f"{'Check'.ljust(width)}  Status  Detail")
    print(f"{'-' * width}  ------  ------")
    for item in results:
        detail = item.detail.replace("\n", " ")[:80]
        print(f"{item.name.ljust(width)}  {item.status:<6}  {detail}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Optional llama.cpp smoke checks for Apex local Agents."
    )
    parser.add_argument(
        "--host",
        default=os.getenv("LLAMA_CPP_HOST", "http://127.0.0.1:8080"),
        help="llama.cpp router base URL",
    )
    parser.add_argument(
        "--model",
        default="apodemus-16k",
        help="Runtime alias to exercise",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Explicitly POST /models/load before generation checks",
    )
    parser.add_argument(
        "--unload",
        action="store_true",
        help="Explicitly POST /models/unload after generation checks",
    )
    args = parser.parse_args(argv)

    print(f"[SMOKE] llama.cpp host={args.host} model={args.model}")
    results = _run_checks(
        host=args.host,
        model=args.model,
        do_load=args.load,
        do_unload=args.unload,
    )
    _print_table(results)
    failures = sum(1 for item in results if item.status == "FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
