# APEX CLI

The APEX CLI is a small terminal client for a backend that is already running on `http://127.0.0.1:8000`. Run it from the repository with `uv run apex`. It does not start, configure, or expose the backend, and it never talks to a remote URL.

Use the CLI for readiness checks, one-off Agent requests, briefings, context management, and action review. The backend owns validation, persistence, and execution; commands use the same routes as the interface. See [Getting Started](getting-started.md) to start it.

To run the packaged Windows CLI independently of the source checkout, see [Windows backend bundle](backend-bundle.md).

List commands and options with `uv run apex --help`, or add `--help` to a command such as `uv run apex context add --help`. Replace placeholders such as `<record-id>` with an ID returned by APEX.

## Status and models

```powershell
uv run apex status
uv run apex models
```

`status` checks backend readiness, including configuration and database access, and shows the APEX Agent display name (or Lynx when unset), its selected model, runtime, and saved cloud reasoning preference. `models` lists the unified model catalog under that same display name and model-specific availability.

## Agent requests

```powershell
uv run apex ask "What needs my attention?"
uv run apex ask "Review my plan" --model z-ai/glm-5.3-flash --effort high --profile daily_planning
```

Each `ask` invocation creates one persisted CLI conversation and submits one turn; it does not attach the current telemetry snapshot. `--model` is optional; omitting it uses the persisted selected model. When `--profile` is omitted, the backend chooses the saved default profile for the selected model runtime.

## Briefings

```powershell
uv run apex briefing
uv run apex briefing --profile catch-up
uv run apex briefing --profile deep --model gemini-3.7-flash
```

`briefing` creates a `cli`-origin session through `POST /api/v1/briefing-sessions`, then polls that session detail until it completes, fails, is cancelled, or is interrupted. It does not refresh connectors separately, mark the artifact as presented, or prepare or play speech. The default profile is `daily`; `--profile` accepts `daily`, `catch-up`, or `deep`. If `--model` is omitted, the CLI reads `ask_apex.selected_model` from saved Runtime Settings. Use `--json` for the complete terminal session detail; human output shows profile, model, status, canonical sections, and limitations.

Polling stops after ten minutes. Interrupting the command or reaching that timeout leaves backend work running. Use `runs list` to find the run and `runs cancel <run-id>` to request cancellation.

## Personal context

```powershell
uv run apex context list
uv run apex context list --status active --status conflicting --kind preference --query "short plans" --limit 20
uv run apex context show <record-id>
```

`context list` filters current personal-context records with repeatable `--status` filters, one `--kind`, and one `--query`. `--limit` defaults to 100 and accepts 1–100. `context show` displays a record's current fields together with source kind, locator, occurrence, capture, and link times, source origin and derivation, original evidence, concise knowledge-history entries, related record IDs, and pending review IDs. The detail response is the place to inspect original evidence and recorded changes.

### Save and reconcile context

```powershell
uv run apex context add "I prefer short plans." --kind preference
uv run apex context correct <record-id> "I prefer concise plans." --kind preference
uv run apex context retract <record-id>
```

`context add` sends direct operator input to the save route. Use `--subject`, `--predicate`, and exactly one of `--object-entity` or `--object-value` for a structured claim; `--effective-at` accepts an ISO-8601 date or timestamp. Use `--sensitive` for an explicitly sensitive entry and `--idempotency-key` for a retry-safe submission. A clear save reports `Saved`; a sensitive or conflicting entry reports `Needs review` with its review ID. `context correct` reads the record first, then submits its returned revision with the replacement fields. `context retract` creates the existing approval-gated reconciliation proposal and prints both its action and review IDs. These commands do not prompt for confirmation.

### Review proposals

```powershell
uv run apex context review list
uv run apex context review list --decision pending --decision stale --limit 20
uv run apex context review show <review-id>
uv run apex context review accept <review-id>
uv run apex context review reject <review-id>
```

`context review list` accepts repeated `--decision` filters (`pending`, `accepted`, `rejected`, or `stale`) and a `--limit`. `context review show` displays the frozen proposal, evidence, reasons, and expected record revisions. Before `accept` or `reject`, the CLI reads the review detail and submits those expected revisions. A stale `409` is reported as an error; repeating the same CLI decision does not refresh the review. Refresh it in Cortex Review or through the API, then decide the newly returned review. Rejecting a review successfully exits with code `0`.

### Retrieval readiness

```powershell
uv run apex context status
uv run apex context prepare
```

`context status` shows local retrieval mode, indexing counts, and pending indexed items, and any safe degraded category. `context prepare` explicitly prepares the local FastEmbed model and backfills semantic vectors; it may take a while and is the only CLI command that can download model files. Both commands talk only to the loopback API and support `--json`.

## Context vault

```powershell
uv run apex context vault status --json
uv run apex context vault preview <scope-id>
uv run apex context vault configure --enabled --scopes-file .\vault-scopes.json
uv run apex context vault configure --disabled
uv run apex context vault refresh
uv run apex context vault remove
```

`context vault status` reports local export revisions, dirty and refresh state, file counts, sanitized errors, and any old destinations that still contain copies. `preview` shows one scope's candidates and exclusions. `configure` updates global enablement and can replace all scope settings from a JSON array in `--scopes-file`; omitting the file preserves the current scopes. `refresh` waits for one serialized local publication and exits nonzero if the returned status is dirty or has a sanitized error. Disable exports before `remove`; while enabled, removal returns `409 Conflict`. The command then deletes only files tracked as APEX-owned at the currently configured destination. It leaves handwritten files and `.obsidian/` in place. Removal also exits nonzero if the returned status has a sanitized error. Disabling exports retains generated files. Commands accept `--json` for machine-readable output, including failure status.

`context vault preview <scope-id>` lists eligible and excluded records together with generated notes that would be added, updated, or removed under that scope, and changes to the shared root index, compared with the last successful local export. A new scope or a destination without a successful export is shown as additions. While export is disabled, preview still shows the projection that would be published if enabled. The comparison uses APEX's local ownership hashes; it does not confirm external sync or indexing. Use `--json` to print the complete response.

For setup and sharing, see the [Context vault guide](context-vault.md).

## External activity

```powershell
uv run apex activity submit --client codex --submission-key report-001 --title "Review branch" --task-status completed --outcome "Ready for review" --finding "Tests passed"
uv run apex activity import .\report.json --client codex
uv run apex activity import .\report.md --client codex --submission-key report-002 --title "Investigation" --task-status completed --outcome "No reproduction"
uv run apex activity list --client codex --disposition new
uv run apex activity show <report-id>
uv run apex activity propose-context <report-id> --finding-reference /findings/0 "Tests passed" --kind fact
```

`activity` submits and reads untrusted reports through the local backend. Supply `--client` on each submit or import command, or use it to filter `list`. It is a caller-declared source label, not software authentication, and must match `^[a-z][a-z0-9_-]{0,63}$`. The server assigns the local `operator` principal and its current production or sandbox partition.

`activity submit` builds a version-one report from `--submission-key`, `--title`, `--task-status`, and `--outcome`. Add repeatable findings, evidence links, artifact references, unresolved questions, subjects, or projects when they help inspection. `--markdown-file` stores a Markdown body as report content. Artifact references remain references; APEX does not fetch them.

`activity import` accepts a JSON report object with the same version-one fields, or a `.md`/`.markdown` body with required metadata options. Import requires the running local backend but no external service. `list` filters the current partition by client and report disposition, and `show` prints the immutable receipt and report content.

`activity propose-context` selects `/findings/<index>`, or `/outcome` or `/markdown_body` when the report has no structured findings. A new proposal creates a pending context review; repeating the same proposal returns its linked review with its current decision. Its text and structured fields describe the proposed claim; the stored finding remains the immutable source evidence. Pass `--correct-record <record-id>` to propose a correction through the same review lifecycle. Use `context review` commands to inspect, accept, or reject it. Refresh a stale review in Cortex Review or through the API before another decision.

Reports remain untrusted and are not indexed or automatically accepted as personal context. Outside DEV mode, a briefing may include relevant non-dismissed reports when personal context is enabled for its selected model runtime. Their inclusion preserves attribution and does not approve a context change. Reading or changing a report's disposition is separate from accepting a linked context review.

See [configuration](configuration.md#external-activity-intake) for source IDs and [the optional local report folder](configuration.md#optional-local-report-folder) for automatic intake setup.

## Actions

```powershell
uv run apex actions list
uv run apex actions show <action-id>
uv run apex actions approve <action-id>
uv run apex actions reject <action-id>
uv run apex actions verify <action-id>
```

The CLI shows the same durable action records as Cortex. `show` includes frozen proposal arguments and audit events. Before `approve`, `reject`, or `verify`, the CLI reads the current action version and submits that version with the request. If another client changed the action first, APEX returns a conflict and the CLI does not retry.

Running `approve` is explicit operator approval, including for destructive actions. An HTTP request can succeed while the action outcome is uncertain or failed; the CLI then exits with code `1`. Inspect the returned action ID and the action history before deciding what to do next. The CLI never replays an action automatically.

## Runs

```powershell
uv run apex runs list
uv run apex runs list --status running
uv run apex runs show <run-id>
uv run apex runs cancel <run-id>
```

`runs` commands inspect and control bounded Cortex execution:

- `list` returns recent runs in the active partition, newest first. Filter by `--status` (`queued`, `running`, `cancelling`, `completed`, `failed`, `cancelled`, `interrupted`) or limit results with `--limit` (default 25, maximum 100).
- `show` displays run details, cumulative token consumption, timing, turn/tool counts, completion evidence, trace ID, and error information.
- `cancel` requests cooperative cancellation and returns the current record without waiting for completion. A running provider or tool call may finish before the run becomes `cancelled`. Cancelling an already-cancelling or terminal run is idempotent.

## JSON and exit codes

Pass `--json` before or after a command to print the command result as JSON:

```powershell
uv run apex actions list --json
```

Handled command and HTTP failures print a small JSON error object in this mode. Invalid command-line usage prints ordinary argument-parser errors and help, even with `--json`. A completed briefing or action with a failed outcome prints its returned result and exits nonzero. Exit code `0` means the requested operation completed successfully, `1` means a backend, runtime, or action outcome failed, and `2` means command-line usage was invalid.

See [API](api.md) for the route contracts and [Privacy](privacy.md) for the local trust boundary.
