# Capability routing model selection

Measured on this machine on 2026-08-06.

## Hardware and runtime

| Field | Value |
|---|---|
| OS | Windows 11 (10.0.26200) |
| CPU | Intel64 Family 6 Model 189 |
| RAM | 15.54 GiB |
| Python | 3.14.3 |
| ONNX Runtime | 1.27.0 |
| tokenizers | 0.23.1 |
| APEX commit | `4a8ef02` (pre-benchmark); branch `feature/smart-tool-routing` |

## Dataset

- Cases: 320 (`cases.jsonl`)
- Split: dev 256 / test 64 (hash-based assignment)
- Threshold tuning: development split only

## Candidate artifacts

### all-minilm-l6-v2

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

Local path: `%LOCALAPPDATA%\APEX\models\tool-routing\bge-small-en-v1.5\07e27b8edc19a66f020db6906126054f190f7284\`

## Test-split quality (locked thresholds)

Thresholds tuned on dev: `minimum_top_score=0.28`, `minimum_none_margin=0.05`.

| Router | Micro recall | Complete coverage | No-tool accuracy | Avg schema tokens |
|---|---:|---:|---:|---:|
| expose-all | 1.000 | 1.000 | 0.000 | 1340 |
| lexical-baseline | 0.020 | 0.322 | 1.000 | 0 |
| **minilm-onnx** | **0.673** | **0.729** | **1.000** | 149 |
| bge-small-onnx | 0.408 | 0.508 | 0.889 | 149 |

## Runtime (warm encode, 200 iterations)

| Model | Cold load | First encode | Warm p95 | Peak RSS delta |
|---|---:|---:|---:|---:|
| all-minilm-l6-v2 | 0.02 ms | 255.67 ms | **3.94 ms** | **39.7 MiB** |
| bge-small-en-v1.5 | 0.00 ms | 370.58 ms | 9.42 ms | 59.47 MiB |

## Acceptance gates

| Gate | Required | MiniLM | BGE |
|---|---:|---:|---:|
| Micro recall | >= 0.97 | **0.673** | 0.408 |
| Complete coverage | >= 0.95 | **0.729** | 0.508 |
| No-tool accuracy | >= 0.93 | 1.000 | 0.889 |
| Warm p95 latency | <= 50 ms | 3.94 ms | 9.42 ms |
| Peak RSS delta | <= 150 MiB | 39.7 MiB | 59.47 MiB |

## Decision

**No candidate passed all quality gates on the held-out test split.**

Production integration remains **`shadow` mode** (`config.json` → `ask_apex.tool_routing_mode`). The ONNX runtime is pinned to **all-minilm-l6-v2** for observation only; enforcement must not be enabled until recall and coverage gates pass.

Likely next experiments:

- Improve benchmark dataset realism (reduce synthetic padding cases).
- Evaluate hybrid semantic + lexical boosts.
- Refine family prototypes and aggregation on dev only.
- Revisit BGE query-prefix handling for short prompts.
