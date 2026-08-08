# Local model benchmark v0

This directory contains a lightweight developer utility for comparing local
APEX Agents on one Windows development machine. It is intentionally not a
benchmark service: results are local files, there is no frontend or database
history, and the case set is kept small enough for a manual model comparison.

## Run it

From the repository root:

```powershell
uv run python scripts/benchmark_local_models.py `
  --agents apodemus neotoma `
  --context 16384 `
  --reasoning none `
  --repetitions 3
```

To compare every registered llama.cpp context preset:

```powershell
uv run python scripts/benchmark_local_models.py `
  --agents apodemus `
  --all-contexts
```

The command also accepts registered Ollama Agents (`sorex` and `mus`). Ollama
uses its fixed configured context; `--context 4096` is accepted for clarity.
Repeat `--reasoning` to compare `none` and `focused` without reloading the same
runtime alias:

```powershell
uv run python scripts/benchmark_local_models.py `
  --agents neotoma `
  --context 16384 `
  --reasoning none `
  --reasoning focused
```

## One-off llama.cpp candidates

A candidate uses an existing machine-local llama.cpp preset alias and does not
become an APEX Agent:

```powershell
uv run python scripts/benchmark_local_models.py `
  --llama-candidate gemma-4-E4B-Q4_K_M.gguf `
  --runtime-alias benchmark-gemma-e4b-16k `
  --context 16384 `
  --reasoning none
```

The alias must already appear in the configured llama.cpp router's `/models`
list. The candidate is represented by an in-memory profile only; it is not
added to `AGENT_SPECS`, Cortex, settings, or the Agent naming taxonomy.

## Runtime and metrics

The utility uses APEX's existing provider-neutral local coordinator and
provider adapters. It claims the local execution slot, refuses to touch an
unknown externally loaded model, unloads known models before changing context
or provider, and verifies the runtime state after every unload. If unload or
residency cannot be verified, the command stops rather than moving to another
model. Reasoning changes reuse a resident alias because they do not change the
runtime model configuration.
The command refuses to run while `/api/v1/health/live` reports a running APEX
process, and a lock file prevents concurrent benchmark commands. After verified
unload it waits for host memory state to settle. When llama.cpp reports a
context window, the requested context must match; unavailable reporting emits
a warning. The lock is removed on normal exit; if the process is forcibly
terminated, remove `benchmarks/.benchmark.lock` manually before retrying.

Each configuration receives one warmup request that is excluded from measured
performance results. The performance prompts record latency, normalized token
counts, and effective token rates when the provider returns usage data. These
rates use total provider wall time and are not native generation throughput.
Resource
records use available physical RAM, Windows commit charge when available, and
provider-process working set/private memory when the process can be identified.
System memory deltas are the preferred cross-model comparison; process values
are supplementary.

The tool suite contains deterministic no-tool, single-tool, multi-tool, and
restraint/recovery cases. It sends the real APEX tool schemas through the
normal Agent loop, but its dispatcher returns only fixed fixtures and never
calls weather, calendar, F1, reminders, or other live connectors. Scores are
separate rates for task success, required tool selection, schema validity,
multi-tool completion, unnecessary tool calls, and failures. There is no
LLM-as-judge or weighted overall score.
The benchmark measures configured APEX Agents as shipped, including their
Agent-specific identity instructions; it is not a neutral underlying-model
test.

## Results

By default the command writes a timestamped JSON result and a Markdown summary
under `benchmarks/results/`. Those files are gitignored because measurements
are machine-specific and are not a committed leaderboard or benchmark history.
