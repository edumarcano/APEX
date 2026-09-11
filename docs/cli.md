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
uv run apex context list
uv run apex context list --status active --status conflicting --kind preference --query "short plans" --limit 20
uv run apex context show <record-id>
uv run apex context add "I prefer short plans." --kind preference
uv run apex context correct <record-id> "I prefer concise plans." --kind preference
uv run apex context retract <record-id>
uv run apex context review list
uv run apex context review list --decision pending --decision stale --limit 20
uv run apex context review show <review-id>
uv run apex context review accept <review-id>
uv run apex context review reject <review-id>
uv run apex actions list
uv run apex actions show <action-id>
uv run apex actions approve <action-id>
uv run apex actions reject <action-id>
uv run apex actions verify <action-id>
uv run apex runs list
uv run apex runs list --status running
uv run apex runs show <run-id>
uv run apex runs cancel <run-id>
```

`status` checks backend readiness, including configuration and database access, and shows Apex Agent, its selected model, runtime, and saved cloud reasoning preference. `models` lists the unified model catalog and model-specific availability. Each `ask` invocation creates one persisted CLI conversation and submits one turn; it does not attach the current HUD snapshot. `--model` is optional; omitting it uses the persisted selected model. When `--profile` is omitted, the backend chooses the saved default profile for the selected model runtime.

`context status` shows local retrieval mode, indexing counts, and pending indexed items,
and any safe degraded category. `context prepare` explicitly prepares the local
FastEmbed model and backfills semantic vectors; it may take a while and is the
only CLI command that can download model files. Both commands talk only to the
loopback API and support `--json`.

`context list` filters current personal-context records by repeated `--status`,
`--kind`, and `--query` values, bounded by `--limit`. `context show` displays a
record's current fields together with source kind, locator, occurrence, capture,
and link times, source origin and derivation, original evidence, concise
knowledge-history entries, related record IDs, and pending review IDs. The
detail response is the place to inspect original evidence and recorded changes.

`context add` sends direct operator input to the save route. Use `--subject`,
`--predicate`, and exactly one of `--object-entity` or `--object-value` for a
structured claim; `--effective-at` accepts an ISO-8601 date or timestamp. Use
`--sensitive` for an explicitly sensitive entry and `--idempotency-key` for a
retry-safe submission. A clear save reports `Saved`; a sensitive or conflicting
entry reports `Needs review` with its review ID. `context correct` reads the
record first, then submits its returned revision with the replacement fields.
`context retract` creates the existing approval-gated reconciliation proposal
and prints both its action and review IDs. These commands do not prompt for
confirmation.

`context review list` accepts repeated `--decision` filters (`pending`,
`accepted`, `rejected`, or `stale`) and a `--limit`. `context review show`
displays the frozen proposal, evidence, reasons, and expected record revisions.
Before `accept` or `reject`, the CLI reads the review detail and submits those
expected revisions. A stale `409` is reported as an error and requires a new
command invocation; the CLI does not refresh or retry it. Rejecting a review
successfully exits with code `0`.

`briefing` uses the normal full refresh-and-generate route. Omitting `--mode` uses the saved Flash default; supported overrides are `flash`, `focused`, and `structured`. These are breaking identifiers: the former Agent-named values are rejected.

## Actions

The CLI shows the same durable action records as Cortex. `show` includes frozen proposal arguments and audit events. Before `approve`, `reject`, or `verify`, the CLI reads the current action version and submits that version with the request. If another client changed the action first, APEX returns a conflict and the CLI does not retry.

Running `approve` is explicit operator approval, including for destructive actions. A successful command can still report an uncertain or failed action outcome; inspect the returned action ID and the action history before deciding what to do next. The CLI never replays an action automatically.

## Runs

`runs` commands inspect and control bounded Cortex execution:

- `list` returns recent runs in the active partition, newest first. Filter by `--status` (`queued`, `running`, `cancelling`, `completed`, `failed`, `cancelled`, `interrupted`) or limit results with `--limit` (default 25, maximum 100).
- `show` displays run details, cumulative token consumption, timing, turn/tool counts, completion evidence, trace ID, and error information.
- `cancel` explicitly cancels a queued or running run.

## JSON and exit codes

Pass `--json` before or after a command to print the complete successful API response as JSON:

```powershell
uv run apex actions list --json
```

CLI and HTTP failures print a small JSON error object in this mode. Exit code `0` means the requested operation completed successfully, `1` means a backend, runtime, or action outcome failed, and `2` means command-line usage was invalid.

See [API](api.md) for the route contracts and [Privacy](privacy.md) for the local trust boundary.
