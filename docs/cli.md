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
uv run apex activity submit --client codex --submission-key report-001 --title "Review branch" --task-status completed --outcome "Ready for review" --finding "Tests passed"
uv run apex activity import .\report.json --client codex
uv run apex activity import .\report.md --client codex --submission-key report-002 --title "Investigation" --task-status completed --outcome "No reproduction"
uv run apex activity list --client codex --disposition new
uv run apex activity show <report-id>
uv run apex activity propose-context <report-id> --finding-reference /findings/0 "Tests passed" --kind fact
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

## External activity

`activity` submits and reads untrusted reports through the local backend. The configured client ID is source attribution declared by the local operator; it does not authenticate installed software. The registration must be enabled, permit `operator`, allow submissions, and match the backend's current production or sandbox partition.

`activity submit` builds a version-one report from `--submission-key`, `--title`, `--task-status`, and `--outcome`. Add repeatable findings, evidence links, artifact references, unresolved questions, subjects, or projects when they help inspection. `--markdown-file` stores a Markdown body as report content. Artifact references remain references; APEX does not fetch them.

`activity import` accepts a JSON report object with the same version-one fields, or a `.md`/`.markdown` body with required metadata options. Imports work offline once the local backend is running. `list` filters the current partition by client and inbox disposition, and `show` prints the immutable receipt and report content.

`activity propose-context` selects `/findings/<index>`, or `/outcome` or `/markdown_body` when the report has no structured findings, and creates a pending context review. Its text and structured fields describe the proposed claim; the stored finding remains the immutable source evidence. Pass `--correct-record <record-id>` to propose a correction through the same review lifecycle. Use `context review` commands to accept, reject, or refresh it.

Reports do not automatically enter personal context, retrieval, prompts, briefings, or attention. Reading, reviewing, dismissing, or reopening a report does not approve a context change.

### First client trial: Grok Bot local terminal

This trial uses the generic local importer. The actual Grok Bot local-terminal integration has not been verified; the steps below describe APEX's side and require a local Bot setup that can produce a JSON file and run a command.

Merge this registration into `config.json`. If the file already has `external_activity.clients`, add the entry to that array and keep the other clients. The ID is source attribution, not a credential. Use `production` when `DEV_MODE` is off and `sandbox` when `DEV_MODE=true`; `DEMO_MODE` rejects submissions.

```json
{
  "external_activity": {
    "clients": [
      {
        "id": "grok-bot",
        "display_name": "Grok Bot",
        "enabled": true,
        "allowed_principals": ["operator"],
        "permissions": ["activity:submit"],
        "partition": "production"
      }
    ]
  }
}
```

Start the APEX backend with `uv run python launcher.py` from the repository root, or confirm that it is already running at `http://127.0.0.1:8000`. Ask Grok Bot for a concise completed-task report and have the approved local terminal action save one version-one report object as `grok-bot-trial.json` in the repository root. For example:

```json
{
  "version": "1",
  "submission_key": "grok-bot-trial-unique-01",
  "title": "Local activity import trial",
  "task_status": "completed",
  "outcome": "The report was written for the APEX Inbox trial.",
  "findings": [
    {
      "title": "Trial finding",
      "text": "The JSON report contains a concise finding.",
      "derivation": "model_interpretation"
    }
  ]
}
```

Use a fresh `submission_key` for each new report. Retrying an unchanged file with the same key returns the original receipt; changing the report while reusing that key is rejected. Inspect the saved JSON, then approve and run this exact command in the Bot's local terminal from the repository root:

```powershell
uv run apex activity import .\grok-bot-trial.json --client grok-bot
```

A successful first import prints `Received: <report-id>` and a receipt time. Confirm the report is in the local Inbox by running `uv run apex activity list --client grok-bot --disposition new`, then `uv run apex activity show <report-id>` with the receipt ID. In the HUD, open **Inbox**, select the report, and inspect its source, new disposition, outcome, finding, and any references before changing its disposition.

If the import fails, check that the backend is running with `uv run apex status`, the JSON has one report object with all required fields, `grok-bot` is enabled with `activity:submit`, and its partition matches the current mode. An unavailable or disabled registration is denied; a repeated identical report should print `Duplicate receipt`. Do not retry changed content under an existing key.

Local command execution can read and change files or start programs with the permissions of the OS account running the Bot. Approve that access only if the granted scope is clear and acceptable; if it is too broad, use the JSON handoff and run the import yourself, which checks APEX's importer but does not verify Bot integration. This procedure uses the local CLI and does not require exposing the backend or gateway to a network.

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
