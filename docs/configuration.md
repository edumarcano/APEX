# Configuration

APEX keeps portable defaults in `config.json`, editable non-secret Runtime Settings in `config.local.json`, and credentials, environment-only switches, and the Context vault destination path in `.env`. Do not commit secrets or GGUF paths.

## Runtime Settings

Runtime Settings persist the editable parts of the resolved configuration. Schema version `23` includes Context vault selections and `ask_apex` model routing. `ask_apex` has one native identity plus model-based routing:

```json
{
  "enabled": true,
  "selected_model": "deepseek/deepseek-v4-flash-0731",
  "sandbox_mode": false,
  "cloud": { "last_model": "deepseek/deepseek-v4-flash-0731", "effort": "low" },
  "local": { "last_model": "gemma-4-E2B-Q4_K_M.gguf", "context_window": 16384, "reasoning_mode": "none" }
}
```

Current default model mapping is `apex` -> `deepseek/deepseek-v4-flash-0731`; `selected_model` is authoritative. Selecting a cloud or local model remembers that choice and its controls in the matching runtime section. Cloud and local personal-context preferences are independent. Cloud tool profiles default to All APEX Tools; local profiles default to No APEX Tools.

Optional `user_designation` and `agent_display_name` are machine-local personalization fields stored only in `config.local.json`. An empty `agent_display_name` keeps the default visible name Apex Agent.

Home and Cortex share this model selection. Home applies per-turn overrides: the lowest supported cloud effort, or a 16K local context with reasoning disabled. Those overrides never change saved Cortex preferences.

## Context vault selection

For setup, sharing, refresh, and cleanup steps, see the [Context vault guide](context-vault.md).

The Context vault selection is disabled by default and starts with no scopes or selected records. Use Cortex → Context → Vault to create and edit scopes, choose entities and records, preview eligible exports, and save or enable a selection. The global `enabled` flag and scope list are also available through `PATCH /api/v1/settings`. Each scope has a stable ID, name, enable flag, selected entity IDs, explicit record IDs, excluded record IDs, and an `include_sensitive` opt-in. Selected entities match canonical records where the entity is the subject or object. Merged entity IDs remain selected but produce a reselection issue instead of silently selecting the merge target. Record exclusions continue through known replacement and conflict-resolution lineage.

Set `APEX_CONTEXT_VAULT_PATH` in `.env` to an absolute machine-specific directory for local Markdown publication. The setting is optional. The callable publisher creates `index.md` and stable `scopes/<scope-id>/` folders. Each scope has its own index, entity notes, and record notes named with immutable IDs. Links inside a scope stay within that scope, so its folder can be copied by itself.

The publisher includes only active production records without a pending challenge; sensitive records require that scope's opt-in. Record notes include the canonical claim, relationship fields, timestamps, source IDs and source kind/origin/derivation. They omit original source evidence and source locators. APEX stores ownership hashes, pending file paths, and export status in local SQLite state outside the vault. It regenerates edited files at owned paths and removes obsolete owned notes, while leaving other files, including handwritten notes and `.obsidian/`, untouched. It refuses an unowned file at a generated path and does not recursively delete the destination.

When exports are enabled, one worker in the main API process reconciles them at startup and after committed production knowledge or selection changes. Filesystem work runs off the async request loop; manual refreshes share the same serialized publisher. A revision change during a refresh leaves the export dirty and starts another reconciliation. Failures keep dirty state and retry a bounded number of times, then wait for another change or manual refresh. Status reports local publication only; it does not claim that Drive copied the files or that Obsidian or Gemini indexed them.

Use `GET /api/v1/cortex/vault` and `POST /api/v1/cortex/vault/preview` to inspect the current selection. The older `/api/v1/cortex/context-vault` read routes remain available. `POST /api/v1/cortex/vault/refresh` refreshes now. Disable exports before `DELETE /api/v1/cortex/vault/copies`; the route returns `409 Conflict` while exports are enabled, then removes only files tracked as APEX-owned. Disabling exports retains the existing files. Deselecting records while enabled removes their managed copies on refresh. Changing `APEX_CONTEXT_VAULT_PATH` on restart leaves copies at the previous root and reports that destination for deliberate cleanup, even while exports are disabled. Demo and development sandbox sessions cannot publish to the production vault.

The `apex context vault` CLI exposes status, preview, configuration, refresh, and managed-copy removal. Local publication completion does not indicate that another application or cloud sync service has copied or indexed the files.

## Google Calendar selection

When Calendar is enabled, Runtime Settings lists readable primary, secondary, subscribed, and hidden Google calendars. APEX reads only the selected IDs; a fresh configuration selects `primary`, but it may be unchecked and an empty selection remains empty. Calendar labels are shown with events by default in Home, briefings, and Agent tool results. Turning off `calendar.show_calendar_names` suppresses those event labels without changing the picker.

Calendar IDs and this display preference are local runtime settings:

```json
{
  "calendar": {
    "selected_calendar_ids": ["primary"],
    "show_calendar_names": true
  }
}
```

APEX keeps unavailable saved IDs so they can be removed deliberately. It reads selected calendars independently: events from calendars that succeed remain available when another selected calendar fails, and Sync Health reports the partial failure. It does not create events, alter Google Calendar visibility, or use webhooks or a remote cache.

## External activity intake

Local activity intake accepts caller-declared source IDs. Use a nonempty lowercase ID matching `^[a-z][a-z0-9_-]{0,63}$`, such as `codex` or `grok-bot`. The ID is stored as source attribution; it does not identify or authenticate the software that submitted the report. The server assigns the local `operator` principal and the current production or development sandbox partition.

### Optional local-folder mailbox

The main APEX backend can poll one operator-selected folder for completed report files. The mailbox is disabled by default. Its enabled flag and absolute folder path are machine-local Runtime Settings stored in the gitignored `config.local.json`; keep credentials in `.env`. A legacy `activity_mailbox.client_id` value is ignored at startup and removed on the next settings save.

```json
{
  "activity_mailbox": {
    "enabled": true,
    "folder_path": "/absolute/path/to/activity-mailbox"
  }
}
```

On Windows, use an absolute path such as `C:\\Users\\<you>\\AppData\\Local\\APEX\\activity-mailbox`. Create the folder in a private local or synced location and grant access only to the operator and the sync tool. APEX scans it at startup and about every 60 seconds; Inbox **Refresh** requests an immediate scan. A missing folder remains configured and is retried. Runtime setting changes take effect without restarting APEX.

Place only completed, top-level `.json` files in the folder; the extension is case-insensitive, and the filename does not need to match the report's `submission_key`. Each file must contain a version-one submission envelope and be at most 256 KiB. For example:

```json
{
  "client_id": "grok-bot",
  "report": {
    "version": "1",
    "submission_key": "run-2026-09-23",
    "title": "Completed review",
    "task_status": "completed",
    "outcome": "The requested checks passed."
  }
}
```

The `report` object uses the same version-one fields described in [the API activity contract](api.md#external-activity-inbox); a bare report object is invalid here. Write to a temporary filename and rename it to a `.json` filename only after the file is complete. APEX leaves source files in place; identical reports reuse the original receipt, while changed content with the same source ID and key follows the normal conflict behavior.

The envelope's `client_id` is the source label claimed by the file producer; the `report` cannot choose a partition or principal. Mailbox reports enter the same untrusted Inbox as CLI, JSON/MCP gateway, and API submissions. The mailbox uses no provider API and adds no remote endpoint.

## External activity gateway

The submission gateway is separate from the normal APEX launcher. Start it only when another local program needs HTTP or MCP submission:

```powershell
uv run python -m core.activity.gateway
```

The gateway binds to `127.0.0.1:8001` unless `--host` and `--port` select another loopback address and port. Requests must use that selected host and port; the default also accepts the standard loopback aliases. It exposes `GET /healthz`, `POST /v1/activity/reports`, and Streamable HTTP MCP at `/mcp/`. The JSON route accepts `application/json`; MCP exposes only `submit_activity`. Both adapters accept caller-declared source IDs, use the local `operator` principal and current production or development sandbox partition, and share the `apex_memory.db` activity table used by the local API and CLI.

The gateway rejects non-loopback bindings, unexpected Host headers, cross-origin browser requests, request bodies above 256 KiB, and more than 30 combined JSON and MCP submission attempts per minute across the process. It does not start Cortex, connectors, the main API, or a second database. `DEMO_MODE` keeps its storage in memory and rejects submissions.

Keep this listener on loopback. Do not place it behind a tunnel, reverse proxy, or public endpoint; the gateway does not authenticate remote callers.

## Models and credentials

The fresh interactive default is OpenRouter DeepSeek V4 Flash with Low reasoning. Cloud models require their documented provider credential: `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`. Local models run through Ollama or llama.cpp and their availability is reported per model in Cortex.

Only one local generation may run at a time. APEX checks runtime reachability, installed models, resource gates, and residency before a cold load. The provider-neutral unload control releases the current local model.

## Briefing modes

Briefings are fixed routes, independent of the interactive model. Focused uses OpenRouter DeepSeek V4 Flash with High reasoning; Flash uses Gemma E2B through llama.cpp at 16K with reasoning disabled; Structured is deterministic. Fallback order is Focused, Flash, then Structured.

## External and managed router modes

Configure llama.cpp aliases with one preset per exposed context size. A tracked placeholder is [`docs/examples/llama-cpp-apex-local-models.preset.ini`](examples/llama-cpp-apex-local-models.preset.ini). Copy it to a machine-local path, replace GGUF placeholders, and keep that copy untracked. External launchers should use one preset at a time; managed mode uses the same aliases and resource gates.

## Bounded run limits

`config.json` sets execution ceilings for asynchronous Cortex runs:

```json
{
  "cortex_runs": {
    "max_concurrent_runs": 2,
    "max_elapsed_seconds": 600,
    "max_retries": 4,
    "max_model_turns": 6,
    "max_tool_calls": 10,
    "event_replay_limit": 512,
    "shutdown_drain_seconds": 30
  }
}
```

`max_concurrent_runs` limits active execution slots before the API returns `429`. `event_replay_limit` sets the in-memory event buffer size per run for Server-Sent Events reconnects. `shutdown_drain_seconds` bounds the full application shutdown window for cancelled run workers and application-owned startup tasks; if either remains active, APEX reports shutdown failure and leaves their dependencies open. The remaining fields define the immutable stop-limit snapshot applied to each run.

`total_tokens` remains cumulative usage accounting for every provider turn. It does not stop a run: multi-turn requests may resend conversation context, while the provider's context-window checks still protect each individual request. Previous `max_total_tokens` configuration values are ignored after beta.3, and old run records retain their recorded ceiling for history inspection.

## OpenTelemetry GenAI tracing

APEX can export distributed trace spans adhering to OpenTelemetry GenAI semantic conventions when an endpoint is configured in `.env`:

- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`: Destination URL for OTLP HTTP trace export (such as a local Arize Phoenix or OpenTelemetry collector).
- `OTEL_EXPORTER_OTLP_TRACES_HEADERS` or `OTEL_EXPORTER_OTLP_HEADERS`: Optional comma-separated `key=value` headers.
- `OTEL_SERVICE_NAME`: Service name attribute, defaulting to `apex`.

When `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is unset, tracing is disabled with zero runtime overhead. Trace spans include run identifiers, model names, token counts, and step durations; they never include prompt or answer text.

## Privacy and development modes

Personal context is off by default for both runtimes. Sandbox mode is available only in `DEV_MODE`, uses a restricted non-personal tool allowlist, and stores conversation history in the sandbox partition. `DEMO_MODE` takes precedence for demo paths and does not contact configured providers.

## Market data

Enable `features.market`, add one to eight `market.symbols`, and place `ALPHA_VANTAGE_API_KEY` in `.env`. Market reads daily closing data, and each symbol can contact Alpha Vantage at most once per UTC calendar day. A successful response remains fresh cached data for that UTC day even when the latest close came from an earlier trading day. Failed symbols retry on a later date with exponential backoff. An enabled connector without symbols or an API key reports unavailable in Sync Health but does not prevent APEX activation.
