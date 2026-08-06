# Capability routing benchmark

Reproducible quality and runtime evaluation for APEX smart tool routing.

## Prerequisites

```bash
uv sync --locked
```

Install candidate ONNX encoders explicitly (no query-time download):

```bash
uv run python scripts/install_tool_router_model.py --model all-minilm-l6-v2
uv run python scripts/install_tool_router_model.py --model bge-small-en-v1.5
```

## Quality benchmark

Tune thresholds and calibration on the development split only:

```bash
uv run python benchmarks/capability_routing/benchmark_quality.py --split dev --all-candidates --compare-prototypes
```

Evaluate locked parameters on the held-out test split:

```bash
uv run python benchmarks/capability_routing/benchmark_quality.py \
  --split test \
  --all-candidates \
  --compare-max-families
```

Held-out failure analysis (machine-readable JSON + Markdown):

```bash
uv run python benchmarks/capability_routing/analyze_errors.py --split test --router hybrid-minilm-onnx
```

Tool-search recovery comparison (hybrid router vs relaxed second-family vs router+search):

```bash
uv run python benchmarks/capability_routing/benchmark_recovery.py --split test --runtime cloud
uv run python benchmarks/capability_routing/benchmark_recovery.py --split test --runtime local
```

## Runtime benchmark

```bash
uv run python benchmarks/capability_routing/benchmark_runtime.py --all-candidates
```

## Full workflow

```bash
uv run python benchmarks/capability_routing/benchmark_all.py
```

Generated JSON under `results/` is local-only unless curated into `model-selection.md`.
Label corrections are recorded in `label_corrections.json`.
