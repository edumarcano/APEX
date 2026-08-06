# Capability routing model selection

Measured on this machine on 2026-08-06 (benchmark-quality and error-analysis pass).

## Hardware and runtime

| Field | Value |
|---|---|
| OS | Windows 11 (10.0.26200) |
| CPU | Intel64 Family 6 Model 189 |
| RAM | 15.54 GiB |
| Python | 3.14.3 |
| ONNX Runtime | 1.27.0 |
| tokenizers | 0.23.1 |

## Dataset

- Cases: 320 (`cases.jsonl`)
- Split: dev 256 / test 64 (hash-based assignment)
- Threshold and calibration tuning: development split only
- Label corrections: `label_corrections.json` (1 dev false-friend case)

## Shadow-mode candidate artifacts

### all-minilm-l6-v2 (shadow-mode candidate)

| Artifact | Repository revision | SHA-256 |
|---|---|---|
| `onnx/model_qint8_avx512_vnni.onnx` | `sentence-transformers/all-MiniLM-L6-v2@d83dd3760b5bfe921f2fe125446b17bf0b7eda8c` | `4278337fd0ff3c68bfb6291042cad8ab363e1d9fbc43dcb499fe91c871902474` |
| `tokenizer.json` | same | `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037` |
| `config.json` | same | `953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41` |

Local path: `%LOCALAPPDATA%\APEX\models\tool-routing\all-minilm-l6-v2\d83dd3760b5bfe921f2fe125446b17bf0b7eda8c\`

### bge-small-en-v1.5

| Artifact | Repository revision | SHA-256 |
|---|---|---|
| `onnx/model_qint8_avx512_vnni.onnx` | `BAAI/bge-small-en-v1.5@07e27b8edc19a66f020db6906126054f190f7284` | `c7663636f9d9d2660b1e5eb5ac3432109fa27a70d89a548dae8beae7b661890b` |
| `tokenizer.json` | same | `d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66` |
| `config.json` | same | `094f8e891b932f2000c92cfc663bac4c62069f5d8af5b5278c4306aef3084750` |

Local path: `%LOCALAPPDATA%\APEX\models\tool-routing\bge-small-en-v1.5\07e27b8edc19a66f020db6906126054f190f7284\`

## Held-out test quality (locked dev thresholds + calibration)

| Router | Micro recall | Complete coverage | No-tool accuracy | Top-1 / Top-2 / Top-3 recall |
|---|---:|---:|---:|---|
| expose-all | 1.000 | 1.000 | 0.000 | 0.265 / 0.306 / 0.367 |
| lexical-baseline + rules | 0.837 | 0.864 | 1.000 | 0.449 / — / — |
| minilm-onnx | 0.673 | 0.729 | 1.000 | 0.673 / 0.694 / 0.959 |
| bge-small-onnx | 0.551 | 0.627 | 1.000 | 0.551 / — / — |
| hybrid-minilm-onnx | 0.673 | 0.729 | 1.000 | 0.673 / 0.694 / 0.959 |

### Prototype embedding modes (dev split, MiniLM)

| Mode | Micro recall | Complete coverage | Top-1 recall |
|---|---:|---:|---:|
| description only | 0.551 | 0.627 | 0.604 |
| exemplars only | 0.673 | 0.729 | 0.696 |
| combined (description + exemplars) | 0.673 | 0.729 | 0.700 |

Exemplar and combined prototypes tie on coverage; description-only underperforms.

### `max_selected_families` (hybrid-minilm, test)

| Cap | Micro recall | Complete coverage | Notes |
|---|---:|---:|---|
| 2 | 0.673 | 0.729 | Current default |
| 3 | 0.673 | 0.729 | No change; second families fail score/margin gates, not cap |

### Handwritten vs synthetic (hybrid-minilm, test)

| Origin | Micro recall | Exact-set accuracy | Cases |
|---|---:|---:|---:|
| handwritten | 0.556 | 0.500 | 16 |
| synthetic | 0.742 | 0.814 | 43 |

## Acceptance gates

| Gate | Required | hybrid-minilm |
|---|---:|---:|
| Micro recall | >= 0.97 | **0.673** |
| Complete coverage | >= 0.95 | **0.729** |
| No-tool accuracy | >= 0.93 | 1.000 |
| Warm p95 latency | <= 50 ms | 3.94 ms (prior run) |
| Peak RSS delta | <= 150 MiB | 39.7 MiB (prior run) |

## Decision

**No configuration passed all enforcement gates on the held-out test split.**

`ask_apex.tool_routing_mode` remains **`shadow`**. The ONNX shadow-mode candidate is **all-minilm-l6-v2** for observation only.

### Tool-search recovery evaluation

The `benchmark_recovery.py` harness measures an **oracle upper-bound catalog-recovery** scenario:

- It uses the original user prompt as the search query.
- It uses expected family labels to decide whether recovery should help.
- It does **not** model agent-initiated search decisions, query quality, or end-to-end task completion.

Report both raw-case metrics (for reproducibility) and unique-prompt metrics (deduplicated logical prompts). Repeated `multi-todo-sched-*` variants count once in unique-prompt handwritten reporting. `search-auto-*` cases remain synthetic stress cases.

Optional real-provider evaluation lives in `evaluate_recovery_e2e.py` and is not run in CI.

Enforcement remains disabled because held-out routing quality gates are still unmet and agent-initiated recovery has not passed end-to-end safety and usefulness gates.

### Quality progression (test split, hybrid-minilm)

| Stage | Micro recall | Complete coverage | No-tool accuracy |
|---|---:|---:|---:|
| Semantic-only baseline (prior pass) | 0.673 | 0.729 | 1.000 |
| + deterministic rules + calibration | 0.673 | 0.729 | 1.000 |
| Lexical + rules (no ONNX) | 0.837 | 0.864 | 1.000 |

Rules and calibration preserve semantic quality while improving lexical routing and reducing held-out failures from 46 to 16.

### Narrowest next experiment

Improve multi-family selection for co-occurring `schedule` + `todo` prompts: relax `additional_family_minimum_score` / margin only when a second high-confidence rule match is present, then re-evaluate on dev before touching test.
