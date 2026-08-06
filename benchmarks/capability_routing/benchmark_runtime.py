#!/usr/bin/env python3
"""Runtime benchmark for capability routing encoders."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import onnxruntime
import psutil
import tokenizers

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"


def _child_main(model_key: str, iterations: int, out_path: Path) -> int:
    from core.agent.routing.context import build_routing_document
    from core.agent.routing.model_manifest import CANDIDATE_MODEL_SPECS
    from core.agent.routing.onnx_encoder import clear_encoder_cache, get_onnx_encoder

    clear_encoder_cache()
    spec = CANDIDATE_MODEL_SPECS[model_key]

    def rss_mb() -> float:
        return psutil.Process().memory_info().rss / (1024 * 1024)

    baseline = rss_mb()
    started = time.perf_counter()
    encoder = get_onnx_encoder(spec)
    load_ms = round((time.perf_counter() - started) * 1000, 2)
    after_load = rss_mb()
    document = build_routing_document("What is on my calendar tomorrow?", [])
    first_started = time.perf_counter()
    encoder.encode_queries([document])
    first_encode_ms = round((time.perf_counter() - first_started) * 1000, 2)
    latencies: list[float] = []
    for _ in range(iterations):
        tick = time.perf_counter()
        encoder.encode_queries([document])
        latencies.append((time.perf_counter() - tick) * 1000)
    latencies.sort()
    peak = rss_mb()
    payload = {
        "model_key": model_key,
        "repository": spec.repository,
        "revision": spec.revision,
        "artifact_bytes": spec.total_bytes,
        "import_rss_mb": round(baseline, 2),
        "cold_load_ms": load_ms,
        "first_encode_ms": first_encode_ms,
        "warm_p50_ms": round(latencies[int(len(latencies) * 0.5)], 2),
        "warm_p95_ms": round(latencies[int(len(latencies) * 0.95)], 2),
        "warm_p99_ms": round(latencies[int(len(latencies) * 0.99)], 2),
        "idle_rss_delta_mb": round(after_load - baseline, 2),
        "peak_rss_delta_mb": round(peak - baseline, 2),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["all-minilm-l6-v2", "bge-small-en-v1.5"])
    parser.add_argument("--all-candidates", action="store_true")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--child", nargs=2, metavar=("MODEL", "OUT"))
    args = parser.parse_args()
    if args.child:
        return _child_main(args.child[0], args.iterations, Path(args.child[1]))
    models = ["all-minilm-l6-v2", "bge-small-en-v1.5"] if args.all_candidates else [args.model or "all-minilm-l6-v2"]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "python": sys.version.split()[0],
        "onnxruntime": onnxruntime.__version__,
        "tokenizers": tokenizers.__version__,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "models": {},
    }
    for model_key in models:
        out_path = RESULTS_DIR / f"runtime-{model_key}.json"
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__)),
                "--iterations",
                str(args.iterations),
                "--child",
                model_key,
                str(out_path),
            ],
            check=True,
        )
        report["models"][model_key] = json.loads(out_path.read_text(encoding="utf-8"))
    summary = RESULTS_DIR / "runtime-summary.json"
    summary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
