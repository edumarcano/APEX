"""Benchmark comparing DeepSeek V4 Flash 0731 and GLM 5.3 Flash on OpenRouter.

Executes 3 scenarios per model, once each (no loops/averages):
- Scenario 1: Simple Cortex Query (no tools)
- Scenario 2: Realistic Tool Query (triggers 1-2 tool calls)
- Scenario 3: Daily Briefing (end-to-end synthesis via APEX briefing pipeline)

Outputs results in a Markdown table:
| Model | Scenario | TTFT | Total | Tokens | Cost |
|---|---|---:|---:|---:|---:|
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import patch
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from core.agent.model_catalog import get_model_profile
from core.agent.pricing import estimate_inference_cost
from core.agent.providers.openrouter import OpenRouterProvider
from core.agent.types import AgentQueryRequest, TokenUsage
from core.api.cortex import query_agent
from core.briefings.daily import generate_briefing_generation
from core.briefings.models import BriefingGenerationRequest
from core.briefings.runtime import resolve_briefing_configuration


MODELS = [
    "deepseek/deepseek-v4-flash-0731",
    "z-ai/glm-5.3-flash",
]


@dataclass
class ScenarioResult:
    model: str
    scenario: str
    ttft_ms: float
    total_seconds: float
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost: float
    provider: str = "OpenRouter"
    generation_ids: list[str] = field(default_factory=list)


class _TrackingStream:
    """Wraps OpenAI stream to capture TTFT, token counts, and actual billed costs."""

    def __init__(self, stream: Any, tracker: dict[str, Any], request_start: float) -> None:
        self._stream = stream
        self._tracker = tracker
        self._request_start = request_start
        self._first_token_seen = False

    def __iter__(self) -> Iterator[Any]:
        for chunk in self._stream:
            gen_id = getattr(chunk, "id", None)
            if gen_id is None and isinstance(chunk, dict):
                gen_id = chunk.get("id")
            if gen_id and gen_id not in self._tracker["generation_ids"]:
                self._tracker["generation_ids"].append(gen_id)

            if not self._first_token_seen:
                choices = getattr(chunk, "choices", None)
                if choices and len(choices) > 0:
                    delta = getattr(choices[0], "delta", None)
                    content = getattr(delta, "content", None) if delta else None
                    tool_calls = getattr(delta, "tool_calls", None) if delta else None
                    if content or tool_calls:
                        self._first_token_seen = True
                        if self._tracker["ttft_ms"] is None:
                            self._tracker["ttft_ms"] = round(
                                (time.perf_counter() - self._request_start) * 1000, 2
                            )

            usage = getattr(chunk, "usage", None)
            if usage is None and isinstance(chunk, dict):
                usage = chunk.get("usage")

            if usage is not None:
                # Extract actual billed cost reported by OpenRouter
                cost = getattr(usage, "cost", None)
                if cost is None and isinstance(usage, dict):
                    cost = usage.get("cost")
                if cost is None:
                    cost_details = getattr(usage, "cost_details", None)
                    if isinstance(cost_details, dict):
                        cost = cost_details.get("upstream_inference_cost")
                    elif hasattr(cost_details, "upstream_inference_cost"):
                        cost = cost_details.upstream_inference_cost

                if cost is not None and isinstance(cost, (int, float)):
                    self._tracker["billed_cost"] += float(cost)
                    self._tracker["has_billed_cost"] = True

                prompt_tokens = getattr(usage, "prompt_tokens", None) or (
                    usage.get("prompt_tokens") if isinstance(usage, dict) else None
                )
                completion_tokens = getattr(usage, "completion_tokens", None) or (
                    usage.get("completion_tokens") if isinstance(usage, dict) else None
                )

                details = getattr(usage, "completion_tokens_details", None) or (
                    usage.get("completion_tokens_details") if isinstance(usage, dict) else None
                )
                reasoning_tokens = None
                if details:
                    reasoning_tokens = getattr(details, "reasoning_tokens", None) or (
                        details.get("reasoning_tokens") if isinstance(details, dict) else None
                    )

                if prompt_tokens:
                    self._tracker["input_tokens"] += int(prompt_tokens)
                if completion_tokens:
                    visible = int(completion_tokens)
                    if reasoning_tokens:
                        visible = max(visible - int(reasoning_tokens), 0)
                        self._tracker["reasoning_tokens"] += int(reasoning_tokens)
                    self._tracker["output_tokens"] += visible

            yield chunk

    def close(self) -> None:
        if hasattr(self._stream, "close"):
            self._stream.close()


@contextmanager
def capture_turn_metrics(model_id: str) -> Iterator[dict[str, Any]]:
    tracker: dict[str, Any] = {
        "ttft_ms": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "billed_cost": 0.0,
        "has_billed_cost": False,
        "turn_count": 0,
        "generation_ids": [],
    }

    orig_generate_turn = OpenRouterProvider.generate_turn

    def wrapped_generate_turn(self: OpenRouterProvider, messages: Any, tools: Any, profile: Any, *args: Any, **kwargs: Any) -> Any:
        orig_create = self.client.chat.completions.create

        def wrapped_create(*c_args: Any, **c_kwargs: Any) -> Any:
            req_start = time.perf_counter()
            stream = orig_create(*c_args, **c_kwargs)
            return _TrackingStream(stream, tracker, req_start)

        self.client.chat.completions.create = wrapped_create
        try:
            result = orig_generate_turn(self, messages, tools, profile, *args, **kwargs)
        finally:
            self.client.chat.completions.create = orig_create

        tracker["turn_count"] += 1
        if tracker["ttft_ms"] is None and result.runtime_measurements:
            if result.runtime_measurements.ttft_ms is not None:
                tracker["ttft_ms"] = result.runtime_measurements.ttft_ms

        if result.usage:
            if tracker["input_tokens"] == 0 and result.usage.input_tokens:
                tracker["input_tokens"] += result.usage.input_tokens
            if tracker["output_tokens"] == 0 and result.usage.output_tokens:
                tracker["output_tokens"] += result.usage.output_tokens
            if tracker["reasoning_tokens"] == 0 and result.usage.reasoning_tokens:
                tracker["reasoning_tokens"] += result.usage.reasoning_tokens

        return result

    with patch.object(OpenRouterProvider, "generate_turn", wrapped_generate_turn):
        yield tracker


class _BriefingControl:
    """Minimal control adapter fulfilling RunExecutionControl for briefing synthesis."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.handle = SimpleNamespace(
            get_record=lambda: SimpleNamespace(partition="production")
        )
        self.runtime_measurements = None

    def check_cancelled(self) -> None:
        pass

    def publish_activity(self, event: str, payload: dict[str, Any]) -> None:
        self.events.append((event, payload))

    def before_model_turn(self) -> None:
        pass

    def after_model_turn(self, _result: Any) -> None:
        pass

    def before_tool(self) -> None:
        pass

    def after_tool(self) -> None:
        pass

    def before_provider_attempt(self) -> None:
        pass

    def before_retry(self, _retry_number: int = 0) -> None:
        pass

    def remaining_seconds(self) -> float:
        return 600.0


def run_scenario_1(model_id: str) -> ScenarioResult:
    """Scenario 1: Simple Cortex Query (no tools)."""
    scenario_name = "Simple Cortex Query"
    prompt = "Explain the difference between synchronous and asynchronous execution in software engineering in two concise sentences."
    request = AgentQueryRequest(
        prompt=prompt,
        agent="apex",
        model_id=model_id,
        selected_tool_names=[],
    )

    start_time = time.perf_counter()
    with capture_turn_metrics(model_id) as tracker:
        response = query_agent(request)
    total_seconds = time.perf_counter() - start_time

    # Cost fallback to APEX pricing estimator if actual billed cost was not returned
    cost = tracker["billed_cost"]
    if not tracker["has_billed_cost"]:
        est = estimate_inference_cost(
            model=model_id,
            usage=TokenUsage(
                input_tokens=tracker["input_tokens"],
                output_tokens=tracker["output_tokens"],
                reasoning_tokens=tracker["reasoning_tokens"],
            ),
            provider="openrouter",
        )
        cost = est.total_cost or 0.0

    ttft = tracker["ttft_ms"] or (
        response.timing.provider_ms if response.timing and response.timing.provider_ms else 0.0
    )

    return ScenarioResult(
        model=model_id,
        scenario=scenario_name,
        ttft_ms=ttft,
        total_seconds=total_seconds,
        input_tokens=tracker["input_tokens"],
        output_tokens=tracker["output_tokens"],
        reasoning_tokens=tracker["reasoning_tokens"],
        cost=cost,
        generation_ids=list(tracker["generation_ids"]),
    )


def run_scenario_2(model_id: str) -> ScenarioResult:
    """Scenario 2: Realistic Tool Query (triggers 1-2 tool calls)."""
    scenario_name = "Realistic Tool Query"
    prompt = "Please check my active reminders using the get_active_reminders tool."
    request = AgentQueryRequest(
        prompt=prompt,
        agent="apex",
        model_id=model_id,
        selected_tool_names=["get_active_reminders"],
    )

    start_time = time.perf_counter()
    with capture_turn_metrics(model_id) as tracker:
        response = query_agent(request)
    total_seconds = time.perf_counter() - start_time

    cost = tracker["billed_cost"]
    if not tracker["has_billed_cost"]:
        est = estimate_inference_cost(
            model=model_id,
            usage=TokenUsage(
                input_tokens=tracker["input_tokens"],
                output_tokens=tracker["output_tokens"],
                reasoning_tokens=tracker["reasoning_tokens"],
            ),
            provider="openrouter",
        )
        cost = est.total_cost or 0.0

    ttft = tracker["ttft_ms"] or (
        response.timing.provider_ms if response.timing and response.timing.provider_ms else 0.0
    )

    return ScenarioResult(
        model=model_id,
        scenario=scenario_name,
        ttft_ms=ttft,
        total_seconds=total_seconds,
        input_tokens=tracker["input_tokens"],
        output_tokens=tracker["output_tokens"],
        reasoning_tokens=tracker["reasoning_tokens"],
        cost=cost,
        generation_ids=list(tracker["generation_ids"]),
    )


def run_scenario_3(model_id: str) -> ScenarioResult:
    """Scenario 3: Daily Briefing (end-to-end synthesis via APEX briefing pipeline)."""
    scenario_name = "Daily Briefing"
    profile = get_model_profile(model_id)
    default_reasoning = profile.default_reasoning if profile else None

    req = BriefingGenerationRequest(
        idempotency_key=uuid4(),
        profile_id="daily",
        model_id=model_id,
        reasoning=default_reasoning,
    )
    configuration = resolve_briefing_configuration(req)
    control = _BriefingControl()

    start_time = time.perf_counter()
    with capture_turn_metrics(model_id) as tracker:
        with patch(
            "core.briefings.daily.ContextPolicy.from_settings",
            return_value=SimpleNamespace(permits_retrieval=False),
        ):
            _output = generate_briefing_generation(
                uuid4(), req, configuration, control  # type: ignore[arg-type]
            )
    total_seconds = time.perf_counter() - start_time

    cost = tracker["billed_cost"]
    if not tracker["has_billed_cost"]:
        est = estimate_inference_cost(
            model=model_id,
            usage=TokenUsage(
                input_tokens=tracker["input_tokens"],
                output_tokens=tracker["output_tokens"],
                reasoning_tokens=tracker["reasoning_tokens"],
            ),
            provider="openrouter",
        )
        cost = est.total_cost or 0.0

    ttft = tracker["ttft_ms"] or 0.0

    return ScenarioResult(
        model=model_id,
        scenario=scenario_name,
        ttft_ms=ttft,
        total_seconds=total_seconds,
        input_tokens=tracker["input_tokens"],
        output_tokens=tracker["output_tokens"],
        reasoning_tokens=tracker["reasoning_tokens"],
        cost=cost,
        generation_ids=list(tracker["generation_ids"]),
    )


def format_tokens(r: ScenarioResult) -> str:
    if r.reasoning_tokens > 0:
        return f"{r.input_tokens} in / {r.output_tokens} out ({r.reasoning_tokens} rsn)"
    return f"{r.input_tokens} in / {r.output_tokens} out"


def resolve_routed_providers(results: list[ScenarioResult], api_key: str) -> None:
    """Fetch routed upstream providers for each scenario from OpenRouter generation metadata."""
    all_gen_ids = {gid for r in results for gid in r.generation_ids}
    if not all_gen_ids:
        return

    provider_map: dict[str, str] = {}
    print("\nResolving routed upstream providers from OpenRouter...", flush=True)

    for attempt in range(8):
        unresolved = [gid for gid in all_gen_ids if gid not in provider_map]
        if not unresolved:
            break
        for gid in unresolved:
            try:
                resp = requests.get(
                    f"https://openrouter.ai/api/v1/generation?id={gid}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    pname = data.get("provider_name")
                    if pname:
                        provider_map[gid] = str(pname)
            except Exception:
                pass
        remaining = [gid for gid in all_gen_ids if gid not in provider_map]
        if remaining and attempt < 7:
            time.sleep(2.0 + attempt * 0.5)

    for r in results:
        names = []
        for gid in r.generation_ids:
            if gid in provider_map:
                names.append(provider_map[gid])
        seen = set()
        distinct = [n for n in names if not (n in seen or seen.add(n))]
        if distinct:
            r.provider = ", ".join(distinct)


def format_results_markdown(results: list[ScenarioResult]) -> str:
    lines = [
        "| Model | Provider | Scenario | TTFT | Total | Tokens | Cost |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for r in results:
        tokens_str = format_tokens(r)
        ttft_str = f"{r.ttft_ms:.1f}ms"
        total_str = f"{r.total_seconds:.2f}s"
        cost_str = f"${r.cost:.6f}"
        lines.append(
            f"| {r.model} | {r.provider} | {r.scenario} | {ttft_str} | {total_str} | {tokens_str} | {cost_str} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark OpenRouter Flash models on APEX.")
    parser.add_argument(
        "--models",
        nargs="+",
        default=MODELS,
        help="Model IDs to benchmark.",
    )
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)

    all_results: list[ScenarioResult] = []

    for model_id in args.models:
        print(f"\n--- Running benchmark for: {model_id} ---", flush=True)

        print("  Running Scenario 1: Simple Cortex Query...", flush=True)
        r1 = run_scenario_1(model_id)
        print(f"    Done: TTFT={r1.ttft_ms:.1f}ms, Total={r1.total_seconds:.2f}s, Tokens={format_tokens(r1)}, Cost=${r1.cost:.6f}", flush=True)
        all_results.append(r1)

        print("  Running Scenario 2: Realistic Tool Query...", flush=True)
        r2 = run_scenario_2(model_id)
        print(f"    Done: TTFT={r2.ttft_ms:.1f}ms, Total={r2.total_seconds:.2f}s, Tokens={format_tokens(r2)}, Cost=${r2.cost:.6f}", flush=True)
        all_results.append(r2)

        print("  Running Scenario 3: Daily Briefing...", flush=True)
        r3 = run_scenario_3(model_id)
        print(f"    Done: TTFT={r3.ttft_ms:.1f}ms, Total={r3.total_seconds:.2f}s, Tokens={format_tokens(r3)}, Cost=${r3.cost:.6f}", flush=True)
        all_results.append(r3)

    resolve_routed_providers(all_results, api_key)

    print("\nBenchmark Results:\n")
    table = format_results_markdown(all_results)
    print(table)


if __name__ == "__main__":
    main()
