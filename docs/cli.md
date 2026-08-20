# APEX CLI

The APEX CLI is a small terminal client for a backend that is already running on `http://127.0.0.1:8000`. Run it from the repository with `uv run apex`. It does not start, configure, or expose the backend, and it never talks to a remote URL.

Use the HUD when a visual workspace is more useful. Use the CLI for a quick check, one-off Agent request, briefing, or action review from a terminal.

## Commands

```powershell
uv run apex status
uv run apex agents
uv run apex ask "What needs my attention?"
uv run apex ask "Review my plan" --agent panthera --effort focused --profile daily_planning
uv run apex briefing
uv run apex briefing --mode structured
uv run apex actions list
uv run apex actions show <action-id>
uv run apex actions approve <action-id>
uv run apex actions reject <action-id>
uv run apex actions verify <action-id>
```

`status` checks backend readiness, including configuration and database access, and shows the effective saved Agent and runtime that an `ask` command will use when `--agent` is omitted. `agents` lists the visible Agents and their current availability. Each `ask` invocation creates one persisted CLI conversation and submits one turn; it does not attach the current HUD snapshot. When `--profile` is omitted, the backend chooses the saved default profile for the selected Agent.

`context status` shows local retrieval mode, indexing counts, and pending indexed items,
and any safe degraded category. `context prepare` explicitly prepares the local
FastEmbed model and backfills semantic vectors; it may take a while and is the
only CLI command that can download model files. Both commands talk only to the
loopback API and support `--json`.

`briefing` uses the normal full refresh-and-generate route. Omitting `--mode` uses the saved Flash default; supported overrides are `flash`, `focused`, and `structured`. These are breaking identifiers: the former Agent-named values are rejected.

## Actions

The CLI shows the same durable action records as Cortex. `show` includes frozen proposal arguments and audit events. Before `approve`, `reject`, or `verify`, the CLI reads the current action version and submits that version with the request. If another client changed the action first, APEX returns a conflict and the CLI does not retry.

Running `approve` is explicit operator approval, including for destructive actions. A successful command can still report an uncertain or failed action outcome; inspect the returned action ID and the action history before deciding what to do next. The CLI never replays an action automatically.

## JSON and exit codes

Pass `--json` before or after a command to print the complete successful API response as JSON:

```powershell
uv run apex actions list --json
```

CLI and HTTP failures print a small JSON error object in this mode. Exit code `0` means the requested operation completed successfully, `1` means a backend, runtime, or action outcome failed, and `2` means command-line usage was invalid.

See [API](api.md) for the route contracts and [Privacy](privacy.md) for the local trust boundary.
