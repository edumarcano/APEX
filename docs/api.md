# APEX API

This is the behavioral reference for APEX's loopback HTTP API at `http://127.0.0.1:8000`. It explains workflows, ownership, and meaningful errors. FastAPI's generated [`/docs`](http://127.0.0.1:8000/docs) and [`/openapi.json`](http://127.0.0.1:8000/openapi.json) are the canonical exhaustive request and response schemas.

The API has no authentication and is intentionally bound to loopback. `APEX_ALLOWED_ORIGINS` controls browser CORS policy; it does not authorize non-browser clients or make remote binding safe. See [Configuration](configuration.md) and [Privacy](privacy.md).

## Route index

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Compatibility health response |
| GET | `/api/v1/health/live` | Process liveness |
| GET | `/api/v1/health/ready` | Local runtime readiness |
| GET | `/api/v1/config` | HUD boot configuration |
| GET | `/api/v1/settings` | Resolved runtime settings |
| PATCH | `/api/v1/settings` | Persist runtime-setting changes |
| GET | `/api/v1/status` | Active full-run pipeline state |
| GET | `/api/v1/diagnostics` | Host resource diagnostics |
| POST | `/api/v1/trigger` | Full refresh-and-briefing compatibility flow |
| POST | `/api/v1/briefings/generate` | Brief from the current snapshot |
| GET | `/api/v1/briefings/history` | Recent briefing ledger |
| GET | `/api/v1/reminders` | Active reminders |
| POST | `/api/v1/reminders` | Create a reminder |
| POST | `/api/v1/reminders/read` | Dismiss reminders |
| GET | `/api/v1/cortex/tool-scopes` | Local Agent tool scopes |
| GET | `/api/v1/agents` | Backend-owned Agent catalog and availability |
| POST | `/api/v1/agents/{agent_key}/verify` | Explicit non-generative cloud access check |
| POST | `/api/v1/cortex/local-model/load` | Pre-warm a selected local model |
| POST | `/api/v1/cortex/local-model/unload` | Unload the active local model |
| POST | `/api/v1/cortex/query` | Run one Cortex Engine turn |
| GET | `/api/v1/market` | Independent EOD market data |
| GET | `/api/v1/mcp/status` | Sanitized MCP runtime status |
| GET | `/api/v1/microsoft-todo/status` | Microsoft To Do authorization status |
| POST | `/api/v1/microsoft-todo/auth/start` | Begin device-code authorization |
| DELETE | `/api/v1/microsoft-todo/auth` | Disconnect Microsoft To Do |
| GET | `/api/v1/telemetry/latest` | Current process-local snapshot |
| POST | `/api/v1/telemetry/refresh` | Refresh all or selected connectors |
| POST | `/api/v1/preflight` | Evaluate an intended operation |
| POST | `/api/v1/voice/speak` | Speak an existing transcript |

## Service and configuration

### GET `/`

Compatibility health response. Use the dedicated health probes for orchestration.

### GET `/api/v1/health/live`

Returns success when the API process can answer. It does not inspect configuration, SQLite, connectors, models, or MCP providers.

### GET `/api/v1/health/ready`

Loads the runtime settings snapshot and executes a lightweight SQLite query. The launcher uses this route before opening the HUD.

- `200` â€” required local state is ready.
- `503` â€” settings or database readiness failed.

Optional external services are deliberately excluded.

### GET `/api/v1/config`

Returns boot-time HUD values such as Ask APEX enablement, the effective Agent and effort selection, briefing and voice defaults, market enablement, message limits, runtime modes, and initial synthesis hints. `agent_initial_selection` is the effective selection; in development mode it can be Acinonyx without changing saved production preferences.

### GET `/api/v1/settings`

Returns the resolved settings envelope. The current contract version is `7`.

```json
{
  "schema_version": 8,
  "settings": {
    "features": { "weather": true, "sports": true, "news": true, "email": false, "calendar": false, "market": true },
    "modules": { "football": false, "f1": true },
    "ask_apex": { "enabled": true, "runtime": "cloud", "cloud_agent": "panthera", "effort": "focused", "local_agent": "mus", "neofelis_google_search_enabled": true, "neofelis_google_maps_enabled": true, "delphinus_x_search_enabled": true, "orcinus_x_search_enabled": true },
    "briefing": { "default_mode": "panthera" },
    "voice": { "engine": "google", "gender": "female", "mode": "automatic" },
    "mcp": { "enabled": false, "servers": { "github": { "enabled": false }, "brave": { "enabled": false }, "alphavantage": { "enabled": false } } }
  },
  "local_file_present": false,
  "local_override_active": false,
  "load_warning": null,
  "dev_mode_active": false,
  "demo_mode_active": false
}
```

`football.teams` is also returned as read-only file configuration. OpenAPI contains the complete shape.

`settings.briefing.default_mode` remains a persisted compatibility field. The Overview command rail is the visible control for changing it and writes the selected mode immediately; the value is returned by `/api/v1/config` on the next startup.

### PATCH `/api/v1/settings`

Accepts a strict partial patch for connectors, sports modules, Ask APEX, briefing, voice, and tracked MCP enablement. Unknown fields return `422`. An empty object returns the current envelope without writing.

```json
{
  "briefing": { "default_mode": "structured_digest" },
  "voice": { "mode": "manual" },
  "mcp": { "servers": { "github": { "enabled": true } } }
}
```

The store validates and transactionally replaces `config.local.json` before publishing the new snapshot. A permanent write failure returns `500` and leaves active settings unchanged. MCP changes reconcile only after persistence succeeds.

Environment modes, credentials, prompts, endpoints, commands, allowlists, tool risks, and football teams are not patchable.

## Runtime status

### GET `/api/v1/status`

Returns the active full-run compatibility pipeline snapshot: `run_id`, step, label, UTC timestamp, speech state, active TTS engine, load-throttling state, and optional synthesis phase/provider/profile.

Returns `404` when no full trigger or delivery is active. Independent telemetry refresh, assistant queries, and snapshot-based briefing generation expose their state through their own responses and frontend owners.

### GET `/api/v1/diagnostics`

Returns current CPU, memory, disk, and network diagnostics for the HUD. This poll is independent of telemetry and briefing state.

## Telemetry and preflight

### GET `/api/v1/telemetry/latest`

Returns the current process-local `TelemetrySnapshot`. Each module reports typed status, freshness, reason, observation time, display text, and structured data.

Returns `404` before the first successful snapshot or after a process restart.

### POST `/api/v1/telemetry/refresh`

Refreshes all enabled connectors or a selected subset.

```json
{ "connectors": ["weather", "calendar"], "force": true }
```

Omit the body to perform a normal full refresh. A normal refresh may reuse a snapshot younger than five minutes; `force: true` bypasses that reuse.

- `200` â€” complete snapshot, including partial/stale connector outcomes.
- `400` â€” unknown or invalid connector selection.
- `409` â€” another refresh owns collection.

### POST `/api/v1/preflight`

Evaluates warnings and non-overridable blockers for one intended operation without executing it.

```json
{
  "operation": "activate_with_briefing",
  "briefing_mode": "panthera",
  "connectors": ["weather", "calendar"],
  "force": false,
  "acknowledged_warnings": []
}
```

Warnings can cover configured-network mismatch, battery use, rapid refresh, and elevated local resource use. Blockers are reserved for conditions that prevent the selected work, including missing required credentials, unavailable models, local inference contention, failed resource gates, invalid input, or broken local configuration/database state. The legacy `cloud_disclosure_acknowledged` input remains accepted but has no effect.

Calling an operation endpoint directly skips advisory acknowledgement; operation-specific hard failures still apply.

## Briefings

### POST `/api/v1/trigger`

Runs the full compatibility workflow: force-refresh telemetry, generate with an optional requested mode or configured default, persist production history, and apply automatic voice-delivery rules.

```json
{ "mode": "panthera" }
```

The body is optional. Valid modes are `panthera`, `mus`, `sorex`, and `structured_digest`.

- `200` â€” transcript, compatibility telemetry strings, typed digest, and runtime metadata.
- `409` â€” another full trigger owns execution.
- `503` â€” a required operation-specific dependency cannot run and no applicable fallback completes the request.

Runtime metadata includes `run_id`, requested mode, resolved synthesis provider/profile/model, ordered fallback steps, token usage, provider timing, estimated provider cost, TTS resolution, `snapshot_id`, and whether automatic speech started.

### POST `/api/v1/briefings/generate`

Generates from the current telemetry snapshot without calling connectors.

```json
{ "snapshot_id": "current-snapshot-uuid", "mode": "structured_digest" }
```

- `200` â€” the same `BriefingResponse` envelope used by the full trigger.
- `409` â€” the snapshot is missing, stale, or no longer process-current.

Production generation persists the result. Demo mode uses static behavior and does not write production history.

### GET `/api/v1/briefings/history`

Returns up to 50 newest briefing records with transcript, digest, runtime metadata, and digest-quality status. Malformed legacy records are classified rather than allowed to break the whole ledger response. Demo mode returns a static mock ledger.

## Reminders

### GET `/api/v1/reminders`

Returns active SQLite reminders. Demo mode returns static mock reminders without database access.

### POST `/api/v1/reminders`

Creates a local reminder from bounded text and returns its SQLite ID.

```json
{ "text": "Review the APEX documentation" }
```

Invalid or empty text returns `422`. Microsoft To Do remains a separate read-only source and is not synchronized.

### POST `/api/v1/reminders/read`

Dismisses one or more local reminders.

```json
{ "ids": [12, 13] }
```

The operation is explicit and is not changed by development mode.

## Apex Agents and local models

### GET `/api/v1/cortex/tool-scopes`

Returns local Agent tool scopes, including availability, reason, tool count, and estimated schema-token cost. Local Agents are tool-free unless one returned scope is selected for the next query.

### GET `/api/v1/agents`

Returns visible Apex Agents in stable product order. Each entry supplies its full display name, description, provider and configured model, version, runtime, tier, stability, supported effort levels, ordered capability tags, effective provider-grounding state, versioned pricing metadata, and availability/lifecycle diagnostics. Acinonyx appears first only in development mode.

The Agent catalog currently includes Acinonyx (`gemini-3.5-flash-lite`, development-only), Panthera (`gpt-5.6-luna`), Neofelis (`gemini-3.6-flash`), Delphinus (`grok-4.3`), Orcinus (`grok-4.5`), Sorex (`qwen3:1.7b`), and Mus (`qwen3:4b-instruct`).

Cloud status starts as `configured` when a credential exists; it does not imply a provider has been reached. Explicit checks and completed inferences can report `verified`; sanitized errors can report unauthorized access, unavailable models, rate limits, quota or billing blocks, unreachable providers, or provider errors. Provider account tier remains null unless a provider explicitly reports it. Local availability distinguishes an unreachable daemon, missing model tag, loading model, busy execution slot, and active model reported by Ollama. The `active` flag reflects daemon residency rather than APEX's in-process lifecycle tracker.

### POST `/api/v1/agents/{agent_key}/verify`

Runs one user-triggered, non-generative metadata check for a visible credential-backed cloud profile. Gemini uses its model metadata endpoint; OpenAI and xAI use `GET /v1/models/{model}`. The five-second probe sends no prompt, context, or provider tool call. Results are sanitized and cached; polling never triggers a probe.

- `400` â€” the profile is local or has no supported verification path.
- `403` â€” demo mode disallows provider contact.
- `404` â€” the profile is not visible.
- `409` â€” credentials are missing or that profile already has a verification in progress.

### POST `/api/v1/cortex/local-model/load`

Pre-warms one installed local profile before a request:

```json
{ "agent": "mus" }
```

The route uses the same execution lock, resource gates, model-switch policy, and warmup options as a normal local turn. It returns success only after Ollama confirms the selected model through its running-model status. Demo mode rejects pre-warming without contacting Ollama.

- `403` â€” demo mode disallows model calls.
- `409` â€” a local generation or lifecycle action is active.
- `503` â€” local inference is disabled, gated, unreachable, or could not be verified.

### POST `/api/v1/cortex/local-model/unload`

Canonical provider-neutral manual unload route. Returns success only when no APEX local model is resident or Ollama confirms the active model is absent after the request.

It also rejects a competing lifecycle action, and reports a failed post-action verification as unavailable.

- `403` â€” manual unload is disabled.
- `409` â€” local generation or lifecycle action is in progress.
- `503` â€” the unload request or post-action Ollama verification failed.

### POST `/api/v1/cortex/local-model/unload`

Compatibility alias with identical behavior to `POST /api/v1/cortex/local-model/unload`.

### POST `/api/v1/cortex/query`

Runs one assistant turn. The browser supplies history on every request; the server does not persist a session.

```json
{
  "prompt": "What should I prioritize this afternoon?",
  "agent": "panthera",
  "effort": "focused",
  "session_id": "browser-session-id",
  "history": [],
  "history_partition": "production",
  "snapshot_id": "optional-current-snapshot-id",
  "briefing_id": 42,
  "tool_scope": null
}
```

`snapshot_id` and `briefing_id` are optional explicit context. When absent, APEX injects no HUD context. Unknown briefing IDs and stale snapshot IDs are omitted rather than replaced with the latest data. `history_partition` is `production` or `acinonyx`; the backend discards history that crosses those partitions. Acinonyx rejects saved `briefing_id` attachments and accepts only the process-current masked development briefing identified by its matching `snapshot_id`.

Panthera, Neofelis, Delphinus, and Orcinus can receive the approved APEX capability registry, including Brave Search when connected. Acinonyx receives only weather, Formula 1, Brave Search, and Alpha Vantage capabilities. Local profiles receive no tools unless `tool_scope` selects one command bundle. Neofelis has optional Google Search and Maps grounding; Delphinus and Orcinus have optional X Search. OpenAI and xAI general native web search are never attached. `effort` is optional for every cloud profile, including Acinonyx, and rejected for local profiles. Responses contain synthesized text, resolved profile metadata, sanitized APEX/provider tool trace, citations, client-display-approved structured outputs, optional stable error, local context usage, normalized token usage, timing, and a versioned cost estimate. The provider-hosted-tool portion of a cost estimate is separate from token cost; MCP service fees are not estimated.

- `403` â€” assistant disabled.
- `429` â€” another local generation owns the execution slot.
- `503` â€” selected provider/model unavailable, cold-load gate failed, or model load failed.

Assistant loops are bounded. Panthera can use up to 6 model turns and 10 tool calls; the other cloud profiles can use up to 4 turns and 6 calls; Sorex and Mus use up to 2/3 and 3/4 turns/calls respectively. The last model turn is answer-only.

## Markets and MCP

### GET `/api/v1/market`

Returns independently polled end-of-day ticker data, status, cooldown state, update time, and sparklines. Provider-error cooldown prevents repeated quota-consuming failures. Missing configuration returns a not-configured response with no tickers; demo mode returns simulated data.

### GET `/api/v1/mcp/status`

Returns sanitized global and per-provider MCP status, reasons, transport labels, and registered tool names. It never returns credentials, authorization headers, OAuth artifacts, endpoints, subprocess commands, allowlists, or local risk policy.

An enabled but unavailable provider remains enabled in settings while reporting a degraded or authorization-required state.

## Microsoft To Do authorization

### GET `/api/v1/microsoft-todo/status`

Returns whether the integration is configured, its authorization state, the fixed `Tasks.Read` permission, and a bounded authorization error when applicable.

### POST `/api/v1/microsoft-todo/auth/start`

Begins device-code authorization and returns the Microsoft verification URI, user code, and expiry. APEX never uses a client secret for this public/native flow.

### DELETE `/api/v1/microsoft-todo/auth`

Clears the local authorization cache and returns the disconnected status. It does not alter Microsoft tasks or SQLite reminders.

## Voice

### POST `/api/v1/voice/speak`

Speaks an existing bounded transcript through the currently resolved engine.

```json
{ "text": "Your briefing is ready." }
```

- `200` â€” delivery was accepted and the resolved engine is reported.
- `409` â€” speech is already active.
- `503` â€” no configured fallback completed delivery.

The endpoint does not generate or persist a briefing. Voice mode determines whether the HUD offers manual delivery or starts it automatically after generation.

## Error and compatibility conventions

- `400` indicates invalid operation input not represented by schema validation.
- `403` indicates a locally disabled capability.
- `404` indicates absent process-local or active state.
- `409` indicates stale identity or resource ownership conflict.
- `422` indicates Pydantic request validation failure.
- `429` is reserved for non-blocking local-inference contention.
- `503` indicates a required local/provider dependency could not perform the selected operation.

Compatibility fields and aliases remain documented where clients can still use them. New integrations should prefer canonical routes and the generated OpenAPI contract.
