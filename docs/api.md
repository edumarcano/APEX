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
| GET | `/api/v1/cortex/tool-catalog` | Agent-specific native and MCP tool catalog |
| POST | `/api/v1/cortex/tool-preflight` | Estimated next-request token breakdown |
| GET | `/api/v1/cortex/tool-profiles` | Built-in and saved tool profiles |
| POST | `/api/v1/cortex/tool-profiles` | Create a saved tool profile |
| PATCH | `/api/v1/cortex/tool-profiles/{profile_id}` | Edit a saved tool profile |
| DELETE | `/api/v1/cortex/tool-profiles/{profile_id}` | Delete a saved tool profile |
| POST | `/api/v1/cortex/tool-profiles/default` | Assign an Agent default profile |
| GET | `/api/v1/agents` | Backend-owned Agent catalog and availability |
| POST | `/api/v1/agents/{agent_key}/verify` | Explicit non-generative cloud access check |
| POST | `/api/v1/cortex/local-model/load` | Pre-warm a selected local model |
| POST | `/api/v1/cortex/local-model/unload` | Unload the active local model |
| POST | `/api/v1/cortex/query` | Run one Cortex Engine turn |
| GET | `/api/v1/market` | Independent EOD market data |
| GET | `/api/v1/mcp/status` | Sanitized MCP runtime status |
| GET | `/api/v1/llama-cpp/status` | Sanitized llama.cpp server ownership status |
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

- `200` — required local state is ready.
- `503` — settings or database readiness failed.

Optional external services are deliberately excluded.

### GET `/api/v1/config`

Returns boot-time HUD values such as Ask APEX enablement, the effective Agent and effort selection, briefing and voice defaults, market enablement, message limits, runtime modes, and initial synthesis hints. `agent_initial_selection` is the effective selection; in development mode it can be Acinonyx without changing saved production preferences.

### GET `/api/v1/settings`

Returns the resolved settings envelope. The current contract version is `10`.

```json
{
  "schema_version": 10,
  "settings": {
    "user_designation": "",
    "features": { "weather": true, "sports": true, "news": true, "email": false, "calendar": false, "market": false },
    "modules": { "football": false, "f1": true },
    "football": { "teams": [] },
    "market": { "symbols": [] },
    "ask_apex": { "enabled": true, "runtime": "cloud", "cloud_agent": "panthera", "effort": "focused", "local_agent": "mus", "neofelis_google_search_enabled": true, "neofelis_google_maps_enabled": true, "delphinus_x_search_enabled": true, "orcinus_x_search_enabled": true, "apodemus_context_window": 8192 },
    "briefing": { "default_mode": "panthera" },
    "voice": { "engine": "google", "gender": "female", "mode": "automatic" },
    "mcp": { "enabled": false, "servers": { "github": { "enabled": false }, "brave": { "enabled": false }, "alphavantage": { "enabled": false } } },
    "llama_cpp": { "enabled": false, "managed": false, "host": "http://127.0.0.1:8080", "executable_path": "", "preset_path": "" }
  },
  "local_file_present": false,
  "local_override_active": false,
  "load_warning": null,
  "dev_mode_active": false,
  "demo_mode_active": false
}
```

`football.teams` and `market.symbols` are returned in the resolved settings snapshot and are patchable through Runtime Settings. OpenAPI contains the complete shape.

`settings.briefing.default_mode` remains a persisted compatibility field. The Home command rail is the visible control for changing it and writes the selected mode immediately; the value is returned by `/api/v1/config` on the next startup.

### PATCH `/api/v1/settings`

Accepts a strict partial patch for the optional user designation, connectors, sports modules, followed football teams, market symbols, Ask APEX, briefing, voice, llama.cpp enablement, loopback host, optional managed-server paths, and tracked MCP enablement. Unknown fields return `422`. An empty object returns the current envelope without writing.

```json
{
  "user_designation": "Chief",
  "briefing": { "default_mode": "structured_digest" },
  "voice": { "mode": "manual" },
  "mcp": { "servers": { "github": { "enabled": true } } }
}
```

The store validates and transactionally replaces `config.local.json` before publishing the new snapshot. A permanent write failure returns `500` and leaves active settings unchanged. MCP changes reconcile only after persistence succeeds. llama.cpp managed-server transitions run after persistence; changes while a managed server is starting return `409`.

Environment modes, prompt text, credentials, endpoints, commands, allowlists, and tool risks are not patchable. The optional `user_designation` is the only personalization field and is persisted to the gitignored local settings overlay. Machine-local llama.cpp `executable_path` and `preset_path` also persist only to `config.local.json`.

## Runtime status

### GET `/api/v1/llama-cpp/status`

Returns sanitized llama.cpp server ownership for Runtime Settings: `enabled`, `managed`, `ownership` (`none` | `external` | `apex`), `state` (`disabled` | `external_connected` | `managed_running` | `starting` | `managed_stopped` | `startup_failed`), and an optional sanitized `last_error`. Never includes executable paths, preset paths, PIDs, or raw process output.

### GET `/api/v1/status`

Returns the active full-run compatibility pipeline snapshot: `run_id`, step, label, UTC timestamp, speech state, active TTS engine, load-throttling state, and optional synthesis phase/provider/Agent.

Returns `404` when no full trigger or delivery is active. Independent telemetry refresh, Cortex queries, and snapshot-based briefing generation expose their state through their own responses and frontend owners.

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

- `200` — complete snapshot, including partial/stale connector outcomes.
- `400` — unknown or invalid connector selection.
- `409` — another refresh owns collection.

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

- `200` — transcript, compatibility telemetry strings, typed digest, and runtime metadata.
- `409` — another full trigger owns execution.
- `503` — a required operation-specific dependency cannot run and no applicable fallback completes the request.

Runtime metadata includes `run_id`, requested mode, resolved synthesis provider/Agent/model, ordered fallback steps, token usage, provider timing, estimated provider cost, TTS resolution, `snapshot_id`, and whether automatic speech started.

### POST `/api/v1/briefings/generate`

Generates from the current telemetry snapshot without calling connectors.

```json
{ "snapshot_id": "current-snapshot-uuid", "mode": "structured_digest" }
```

- `200` — the same `BriefingResponse` envelope used by the full trigger.
- `409` — the snapshot is missing, stale, or no longer process-current.

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

### GET `/api/v1/cortex/tool-catalog`

Returns the current catalog for one Agent (`?agent=panthera`). Individual entries
include the stable capability name, model-facing label and description, native or
MCP origin, source/server, risk, availability reason, Agent-policy result, and
estimated schema tokens. Groups contain curated APEX families or MCP servers with
tool counts and schema-token subtotals. The response also includes built-in and
saved profiles, the Agent's default profile, and known local context capacity.

The selector is a prompt-level exposure layer. It does not enable an MCP server,
connect or authenticate it, change a persistent allowlist, or bypass Acinonyx's
policy.

### POST `/api/v1/cortex/tool-preflight`

Accepts an Agent, selected stable names, optional profile, prompt, bounded
history, and explicit snapshot/briefing attachment IDs. It returns estimates for
system instructions, conversation history, HUD context, selected schemas,
prompt, total, configured context, reserved response capacity, and remaining
capacity. Every value is marked as an estimate by the response contract.
Rejected selections remain in the response as structured diagnostics with
`can_proceed=false`; the endpoint does not turn those diagnostics into a
generic HTTP error. A conservative local context boundary can still report
`can_proceed=false` so the query route can block a known overflow without
silently truncating selected schemas.

### GET `/api/v1/cortex/tool-profiles`

Returns built-in and persisted custom profiles. Built-in profiles are `No Tools`, `All Allowed`, `Personal Ops`, `Daily
Planning`, `Research`, and `Markets`. `All Allowed` resolves dynamically against
current Agent policy and runtime availability; other profiles retain explicit
stable names. Custom profile references are preserved when a tool later becomes
unavailable. Profile writes persist non-secret settings in `config.local.json`
and never modify MCP runtime configuration.

### POST `/api/v1/cortex/tool-profiles`

Creates a custom profile from explicit stable capability names.

### PATCH `/api/v1/cortex/tool-profiles/{profile_id}`

Edits a saved custom profile. Its missing or unavailable tool references remain
in the profile.

### DELETE `/api/v1/cortex/tool-profiles/{profile_id}`

Deletes a saved custom profile and clears Agent defaults that pointed to it.

### POST `/api/v1/cortex/tool-profiles/default`

Assigns an existing built-in or custom profile as the default for one Agent.

### GET `/api/v1/agents`

Returns visible Apex Agents in stable product order. Each entry supplies its full display name, description, provider and configured model, version, runtime, tier, stability, supported effort levels, ordered capability tags, effective provider-grounding state, versioned pricing metadata, and availability/lifecycle diagnostics. Acinonyx appears first only in development mode.

The Agent catalog currently includes Acinonyx (`gemini-3.5-flash-lite`, development-only), Panthera (`gpt-5.6-luna`), Neofelis (`gemini-3.6-flash`), Delphinus (`grok-4.3`), Orcinus (`grok-4.5`), Sorex (`qwen3:1.7b`), Mus (`qwen3:4b-instruct`), and Apodemus (`gemma-4-E2B-Q4_K_M.gguf` through llama.cpp).

Cloud status starts as `configured` when a credential exists; it does not imply a provider has been reached. Explicit checks and completed inferences can report `verified`; sanitized errors can report unauthorized access, unavailable models, rate limits, quota or billing blocks, unreachable providers, or provider errors. Provider account tier remains null unless a provider explicitly reports it. Local availability distinguishes an unreachable local runtime, missing model, loading model, busy execution slot, and active model reported by the local provider. Unreachable local backends use the generic provider-unreachable path with a sanitized reason. The `active` flag reflects provider residency rather than APEX's in-process lifecycle tracker. Loaded-model payloads may include provider, runtime alias, state, and selected or reported context when available.

### POST `/api/v1/agents/{agent_key}/verify`

Runs one user-triggered, non-generative metadata check for a visible credential-backed cloud Agent. Gemini uses its model metadata endpoint; OpenAI and xAI use `GET /v1/models/{model}`. The five-second probe sends no prompt, context, or provider tool call. Results are sanitized and cached; polling never triggers a probe.

- `400` — the Agent is local or has no supported verification path.
- `403` — demo mode disallows provider contact.
- `404` — the Agent is not visible.
- `409` — credentials are missing or that Agent already has a verification in progress.

### POST `/api/v1/cortex/local-model/load`

Pre-warms one installed local Agent before a request:

```json
{ "agent": "mus" }
```

`agent` may be `mus`, `sorex`, or `apodemus`. The route uses the same execution lock, resource gates, model-switch policy, and warmup options as a normal local turn. It returns success only after the local runtime confirms the selected model through residency verification. Demo mode rejects pre-warming without contacting the local provider.

- `403` — demo mode disallows model calls.
- `409` — a local generation or lifecycle action is active.
- `503` — local inference is disabled, gated, unreachable, or could not be verified.

### POST `/api/v1/cortex/local-model/unload`

Canonical provider-neutral manual unload route. Returns success only when no APEX local model is resident or the active model's backend confirms it is absent after the request.

It also rejects a competing lifecycle action, and reports a failed post-action verification as unavailable.

- `403` — manual unload is disabled.
- `409` — local generation or lifecycle action is in progress.
- `503` — the unload request or post-action residency verification failed.

### POST `/api/v1/cortex/query`

Runs one Cortex Engine turn. The browser supplies history on every request; the server does not persist a session.

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
  "selected_tool_names": [],
  "tool_profile_id": null
}
```

`snapshot_id` and `briefing_id` are optional explicit context. When absent, APEX injects no HUD context. Unknown briefing IDs and stale snapshot IDs are omitted rather than replaced with the latest data. `history_partition` is `production` or `acinonyx`; the backend discards history that crosses those partitions. Acinonyx rejects saved `briefing_id` attachments and accepts only the process-current masked development briefing identified by its matching `snapshot_id`.

The effective exposure is `selected tools ∩ Agent policy ∩ runtime availability ∩ persistent MCP allowlists`. An explicit empty `selected_tool_names` list means `No Tools`; omitted selection preserves the migration default of `All Allowed` for cloud Agents and `No Tools` for local Agents. Invalid, unauthorized, disconnected, risk-rejected, or unavailable selected names are returned as structured per-tool failures; they are never silently dropped. Panthera, Neofelis, Delphinus, and Orcinus can receive the approved APEX capability registry, including Brave Search when connected. Acinonyx receives only weather, Formula 1, Brave Search, and Alpha Vantage capabilities. Neofelis has optional Google Search and Maps grounding; Delphinus and Orcinus have optional X Search. OpenAI and xAI general native web search are never attached. `effort` is optional for every cloud Agent, including Acinonyx, and rejected for local Agents. Responses contain synthesized text, resolved Agent metadata, requested/offered/rejected tool names, selected schema-token estimate, active profile metadata, sanitized APEX/provider tool trace, citations, client-display-approved structured outputs, optional stable error, local context usage, normalized token usage, timing, and a versioned cost estimate. The provider-hosted-tool portion of a cost estimate is separate from token cost; MCP service fees are not estimated.

- `400` — selected tools are invalid, outside policy, unavailable, or the local estimated context is full.
- `403` — Ask APEX is disabled.
- `429` — another local generation owns the execution slot.
- `503` — selected provider/model unavailable, cold-load gate failed, or model load failed.

Cortex Engine Agent loops are bounded. Panthera can use up to 6 model turns and 10 tool calls; the other cloud Agents can use up to 4 turns and 6 calls; Sorex, Mus, and Apodemus use up to 2/3, 3/4, and 3/4 turns/calls respectively. The last model turn is answer-only.

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

Successful response after playback completes:

```json
{ "status": "spoken", "resolved_engine": "pyttsx3" }
```

- `200` — playback completed and the resolved engine is reported.
- `409` — speech is already active.
- `503` — no configured fallback completed delivery.

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
