# APEX CLI

The APEX CLI is a small terminal client for a backend that is already running on `http://127.0.0.1:8000`. Run it from the repository with `uv run apex`. It does not start, configure, or expose the backend, and it never talks to a remote URL.

Use the HUD when a visual workspace is more useful. Use the CLI for a quick check, one-off Agent request, briefing, or action review from a terminal.

## Commands

```powershell
uv run apex status
uv run apex models
uv run apex ask "What needs my attention?"
uv run apex ask "Review my plan" --model deepseek/deepseek-v4-flash-0731 --effort high --profile daily_planning
uv run apex briefing
uv run apex briefing --mode structured
uv run apex context status
uv run apex context prepare
uv run apex actions list
uv run apex actions show <action-id>
uv run apex actions approve <action-id>
uv run apex actions reject <action-id>
uv run apex actions verify <action-id>
uv run apex runs start "What needs my attention?"
uv run apex runs start "Review my plan" --model deepseek/deepseek-v4-flash-0731 --detach
uv run apex runs list
uv run apex runs list --status running
uv run apex runs show <run-id>
uv run apex runs follow <run-id>
uv run apex runs cancel <run-id>
```

`status` checks backend readiness, including configuration and database access, and shows Apex Agent, its selected model, runtime, and saved cloud reasoning preference. `models` lists the unified model catalog and model-specific availability. Each `ask` invocation creates one persisted CLI conversation and submits one turn; it does not attach the current HUD snapshot. `--model` is optional; omitting it uses the persisted selected model. When `--profile` is omitted, the backend chooses the saved default profile for the selected model runtime.

`context status` shows local retrieval mode, indexing counts, and pending indexed items,
and any safe degraded category. `context prepare` explicitly prepares the local
FastEmbed model and backfills semantic vectors; it may take a while and is the
only CLI command that can download model files. Both commands talk only to the
loopback API and support `--json`.

`briefing` uses the normal full refresh-and-generate route. Omitting `--mode` uses the saved Flash default; supported overrides are `flash`, `focused`, and `structured`. These are breaking identifiers: the former Agent-named values are rejected.

## Actions

The CLI shows the same durable action records as Cortex. `show` includes frozen proposal arguments and audit events. Before `approve`, `reject`, or `verify`, the CLI reads the current action version and submits that version with the request. If another client changed the action first, APEX returns a conflict and the CLI does not retry.

Running `approve` is explicit operator approval, including for destructive actions. A successful command can still report an uncertain or failed action outcome; inspect the returned action ID and the action history before deciding what to do next. The CLI never replays an action automatically.

## Runs

`runs` commands inspect and control bounded Cortex execution:

- `start` creates a CLI conversation and submits a new run. By default, it immediately follows the live event stream until completion. Pass `--detach` to start the run in the background and output the run record immediately.
- `list` returns recent runs in the active partition, newest first. Filter by `--status` (`queued`, `running`, `cancelling`, `completed`, `failed`, `cancelled`, `interrupted`) or limit results with `--limit` (default 25, maximum 100).
- `show` displays run details, cumulative token consumption, timing, turn/tool counts, completion evidence, trace ID, and error information.
- `follow` consumes live server-sent events for an active or completed run. Response text deltas stream to `stdout`, while compact activity notifications (models, tools, action proposals) and the completion summary footer stream to `stderr`. If disconnected unexpectedly, it reconnects up to three times with `Last-Event-ID`. Pressing `Ctrl-C` detaches cleanly without cancelling the run.
- `cancel` explicitly cancels a queued or running run.

Passing `--json` to `follow` (or interactive `start`) outputs newline-delimited JSON (NDJSON) events to `stdout`.

## JSON and exit codes

Pass `--json` before or after a command to print the complete successful API response as JSON:

```powershell
uv run apex actions list --json
```

CLI and HTTP failures print a small JSON error object in this mode. Exit code `0` means the requested operation completed successfully, `1` means a backend, runtime, or action outcome failed, and `2` means command-line usage was invalid.

See [API](api.md) for the route contracts and [Privacy](privacy.md) for the local trust boundary.
