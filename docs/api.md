# APEX API

This is the behavioral reference for APEX's loopback HTTP API at `http://127.0.0.1:8000`. It explains workflows, ownership, and meaningful errors. FastAPI's generated [`/docs`](http://127.0.0.1:8000/docs) and [`/openapi.json`](http://127.0.0.1:8000/openapi.json) are the canonical exhaustive request and response schemas.

The API has no authentication and is intentionally bound to loopback. `APEX_ALLOWED_ORIGINS` controls browser CORS policy; it does not authorize non-browser clients or make remote binding safe. See [Configuration](configuration.md) and [Privacy](privacy.md).

The included [`uv run apex`](cli.md) command is a thin loopback client for a focused subset of these routes. It does not add routes or bypass their validation, action version checks, or runtime-mode behavior.

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
| GET | `/api/v1/briefings/targets` | Briefing synthesis target metadata |
| GET | `/api/v1/reminders` | Active reminders |
| GET | `/api/v1/reminders/task` | Exact selected-list task detail (`id=todo:…`) |
| GET | `/api/v1/reminders/completed` | Live bounded completed reminders |
| POST | `/api/v1/reminders` | Create a reminder |
| POST | `/api/v1/reminders/complete` | Complete or dismiss one reminder |
| POST | `/api/v1/reminders/update` | Update one active Microsoft To Do task |
| POST | `/api/v1/reminders/delete` | Delete one confirmed Microsoft To Do task |
| POST | `/api/v1/reminders/reopen` | Reopen one completed Microsoft To Do task |
| POST | `/api/v1/reminders/sync` | Reviewed local reminder synchronization |
| POST | `/api/v1/reminders/dismiss` | Dismiss a reviewed uncertain local reminder |
| GET | `/api/v1/actions` | List durable action proposals |
| GET | `/api/v1/actions/{action_id}` | Inspect one proposal and its audit events |
| POST | `/api/v1/actions/{action_id}/approve` | Approve, execute, and verify one action |
| POST | `/api/v1/actions/{action_id}/reject` | Reject one pending action |
| POST | `/api/v1/actions/{action_id}/verify` | Retry verification without replaying execution |
| GET | `/api/v1/cortex/tool-catalog` | Agent-specific native and MCP tool catalog |
| POST | `/api/v1/cortex/tool-preflight` | Estimated next-request token breakdown |
| GET | `/api/v1/cortex/tool-profiles` | Built-in and saved tool profiles |
| POST | `/api/v1/cortex/tool-profiles` | Create a saved tool profile |
| PATCH | `/api/v1/cortex/tool-profiles/{profile_id}` | Edit a saved tool profile |
| DELETE | `/api/v1/cortex/tool-profiles/{profile_id}` | Delete a saved tool profile |
| POST | `/api/v1/cortex/tool-profiles/default` | Assign an Agent default profile |
| GET | `/api/v1/cortex/agent` | Apex Agent and unified model catalog |
| POST | `/api/v1/cortex/models/verify` | Explicit non-generative cloud model access check |
| POST | `/api/v1/cortex/local-model/load` | Pre-warm a selected local model |
| POST | `/api/v1/cortex/local-model/unload` | Unload the active local model |
| GET | `/api/v1/cortex/conversations` | List durable Cortex conversations |
| POST | `/api/v1/cortex/conversations` | Create a durable Cortex conversation |
| GET | `/api/v1/cortex/conversations/{conversation_id}` | Read one conversation |
| PATCH | `/api/v1/cortex/conversations/{conversation_id}` | Update one conversation |
| DELETE | `/api/v1/cortex/conversations/{conversation_id}` | Permanently delete one archived conversation |
| POST | `/api/v1/cortex/conversations/{conversation_id}/turns` | Run one durable Cortex turn |
| POST | `/api/v1/cortex/context/captures` | Propose a manual personal-context capture |
| GET | `/api/v1/cortex/context` | List local personal-context records in the current partition |
| GET | `/api/v1/cortex/context/{record_id}` | Inspect one record, its sources, history, and related records |
| GET | `/api/v1/cortex/context/entities` | Search unmerged local entities and exact aliases |
| POST | `/api/v1/cortex/context/actions` | Propose an approval-gated context reconciliation operation |
| GET | `/api/v1/cortex/retrieval/status` | Show local retrieval readiness and indexing state |
| POST | `/api/v1/cortex/retrieval/prepare` | Explicitly prepare the local embedding model and backfill vectors |
| GET | `/api/v1/market` | Independent EOD market data |
| GET | `/api/v1/mcp/status` | Sanitized MCP runtime status |
| GET | `/api/v1/llama-cpp/status` | Sanitized llama.cpp server ownership status |
| GET | `/api/v1/microsoft-todo/status` | Microsoft To Do authorization status |
| GET | `/api/v1/microsoft-todo/lists` | Bounded selected-list choices |
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

Returns boot-time HUD values such as Agent query enablement, the effective model selection, briefing and voice defaults, market enablement, message limits, runtime modes, and initial synthesis hints. `cortex_initial_selection` identifies Apex Agent and the saved model/runtime selection.

### GET `/api/v1/settings`

Returns the resolved settings envelope. The current contract version is `19`.

```json
{
  "schema_version": 19,
  "settings": {
    "user_designation": "",
    "features": { "weather": true, "sports": true, "news": true, "email": false, "calendar": false, "market": false },
    "modules": { "football": false, "f1": true },
    "football": { "teams": [] },
    "market": { "symbols": [] },
    "ask_apex": {
      "enabled": true,
      "selected_model": "deepseek/deepseek-v4-flash-0731",
      "sandbox_mode": false,
      "cloud": {
        "last_model": "deepseek/deepseek-v4-flash-0731",
        "effort": "low",
        "personal_context_enabled": false,
        "hosted_tools": { "google_search": true, "google_maps": true }
      },
      "local": {
        "last_model": "gemma-4-E2B-Q4_K_M.gguf",
        "context_window": 16384,
        "reasoning_mode": "none",
        "personal_context_enabled": false
      }
    },
    "tool_profiles": { "custom_profiles": [], "default_profile_by_runtime": {} },
    "briefing": { "default_mode": "flash" },
    "voice": { "engine": "google", "gender": "female", "mode": "automatic" },
    "mcp": { "enabled": false, "servers": { "github": { "enabled": false }, "brave": { "enabled": false }, "alphavantage": { "enabled": false } } },
    "llama_cpp": { "enabled": false, "managed": false, "host": "http://127.0.0.1:8080", "executable_path": "", "preset_path": "" },
    "microsoft_todo": { "reminder_list_id": "" }
  },
  "local_file_present": false,
  "local_override_active": false,
  "load_warning": null,
  "dev_mode_active": false,
  "demo_mode_active": false
}
```

`football.teams`, `market.symbols`, `tool_profiles`, and `microsoft_todo.reminder_list_id` are returned in the resolved settings snapshot. Apex Agent settings persist the selected model and independent cloud/local controls; the model catalog derives provider or local runtime. The selected provider/runtime remains in execution metadata and historical records. The optional list ID is opaque, bounded to 512 characters, and is never selected or cleared automatically. OpenAPI contains the complete shape. Tool profiles persist through the same settings store, but the dedicated `/api/v1/cortex/tool-profiles` routes are the canonical mutation workflow for built-in/custom profiles and per-runtime defaults.

`settings.briefing.default_mode` remains a persisted compatibility field. The Home command rail is the visible control for changing it and writes the selected mode immediately; the value is returned by `/api/v1/config` on the next startup.

### PATCH `/api/v1/settings`

Accepts a strict partial patch for the optional user designation, connectors, sports modules, followed football teams, market symbols, Agent query settings, tool profiles, briefing, voice, llama.cpp enablement, loopback host, optional managed-server paths, and tracked MCP enablement. Unknown fields return `422`. An empty object returns the current envelope without writing. Prefer the dedicated Cortex tool-profile routes for profile creation, editing, deletion, and default assignment.

```json
{
  "user_designation": "Chief",
  "briefing": { "default_mode": "structured" },
  "voice": { "mode": "manual" },
  "mcp": { "servers": { "github": { "enabled": true } } }
}
```

The store validates and transactionally replaces `config.local.json` before publishing the new snapshot. A permanent write failure returns `500` and leaves active settings unchanged. MCP changes reconcile only after persistence succeeds. llama.cpp managed-server transitions run after persistence; changes while a managed server is starting return `409`.

`ask_apex.local.reasoning_mode` accepts `none` or `focused` for llama.cpp models and only `none` for Ollama models. `focused` is request-level and does not trigger a local model unload/reload; unsupported model/mode combinations return `422`.

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
  "briefing_mode": "flash",
  "connectors": ["weather", "calendar"],
  "force": false,
  "acknowledged_warnings": []
}
```

Warnings can cover configured-network mismatch, battery use, rapid refresh, and elevated local resource use. Blockers are reserved for conditions that prevent the selected work, including missing required credentials, unavailable models, local inference contention, failed resource gates, invalid input, or broken local configuration/database state. The legacy `cloud_disclosure_acknowledged` input remains accepted but has no effect.

Calling an operation endpoint directly skips advisory acknowledgement; operation-specific hard failures still apply.

## Briefings

### POST `/api/v1/trigger`

Runs the full compatibility workflow: force-refresh telemetry, generate with an optional requested mode or configured default, persist normal-mode briefing history, and apply automatic voice-delivery rules.

```json
{ "mode": "flash" }
```

The body is optional. Valid modes are `focused`, `flash`, and `structured`. The `flash` briefing mode always uses the fixed `gemma-4-E2B-Q4_K_M.gguf` llama.cpp profile with no reasoning; interactive model settings do not affect it.

- `200` — transcript, compatibility telemetry strings, typed digest, and runtime metadata.
- `409` — another full trigger owns execution.
- `503` — a required operation-specific dependency cannot run and no applicable fallback completes the request.

Runtime metadata includes `run_id`, requested mode, resolved synthesis provider/Agent/model, ordered fallback steps, token usage, provider timing, estimated provider cost, TTS resolution, `snapshot_id`, and whether automatic speech started.

### POST `/api/v1/briefings/generate`

Generates from the current telemetry snapshot without calling connectors.

```json
{ "snapshot_id": "current-snapshot-uuid", "mode": "structured" }
```

- `200` — the same `BriefingResponse` envelope used by the full trigger.
- `409` — the snapshot is missing, stale, or no longer process-current.

Normal-mode generation persists the result. Demo mode uses static behavior and does not write normal-mode briefing history.

### GET `/api/v1/briefings/history`

Returns up to 50 newest briefing records with transcript, digest, runtime metadata, and digest-quality status. Malformed legacy records are classified rather than allowed to break the whole ledger response. Demo mode returns a static mock ledger.

### GET `/api/v1/briefings/targets`

Returns live availability and metadata for fixed briefing-generation targets in this order: `flash` (local Gemma), `focused` (OpenRouter DeepSeek V4 Flash), and `structured` (deterministic, no model). Removed Agent-named identifiers are rejected.

## Reminders

### GET `/api/v1/reminders`

Returns the unified reminder envelope. A configured selected list is authoritative: a successful read returns its newest 50 incomplete tasks as `live`; a failed read returns only that list's bounded cache as `stale`; no matching cache or no selected list is `unavailable`. Pending and uncertain local rows remain visible in every state.

```json
{
  "items": [{ "id": "todo:opaque", "note": "Review plan", "source": "todo", "sync_state": "synced" }],
  "source_state": "live",
  "cache_timestamp": null,
  "pending_sync_count": 0
}
```

### POST `/api/v1/reminders`

Accepts bounded text (maximum 500 characters). A connected selected list creates one immediately approved `create_microsoft_todo_task` action and returns `201` only after verification. Known offline/no-list requests return a local `pending` item with `201`. An ambiguous or verification-failed attempted write returns `202` with `outcome: "unknown"` and an action ID; a definitive attempted write returns `502` with its action ID and never creates a local fallback.

```json
{ "text": "Review the APEX documentation" }
```

Invalid or empty text returns `422`.

### POST `/api/v1/reminders/complete`

Accepts one opaque `{ "id": "todo:…" | "local:…" }`. Remote completion is an immediate verified action using cached stale-target evidence. An unavailable remote source returns `503`; a changed target returns `409`. Pending local rows are dismissed, while uncertain local rows require explicit review.

### Microsoft To Do task management

`GET /api/v1/reminders/task?id=todo:…` reads one exact task from the selected list for the edit and delete dialogs. It returns the opaque ID, title, due date/timezone, importance, completion metadata, and observed `last_modified_at`.

`GET /api/v1/reminders/completed` reads one bounded live collection and returns only completed Microsoft To Do tasks. It never reads SQLite cache or local outbox rows. When no selected list or live Microsoft connection is available, it returns an empty `unavailable` envelope.

`POST /api/v1/reminders/update`, `/delete`, and `/reopen` are explicit operator commands. They require the opaque `todo:` ID and the `last_modified_at` observed by the HUD; update accepts only title, due date/timezone, and importance. A verified mutation returns `200`; an ambiguous execution or failed verification returns `202` with an action ID and is never replayed automatically. Stale targets return `409`, known unavailability returns `503`, absence returns `404`, and definitive action failure returns `502` with its action ID.

### POST `/api/v1/reminders/sync`

Accepts one to 50 unique, explicitly selected pending `local:` IDs. Rows are processed sequentially with one action per item and return `synced`, `failed`, or `unknown` results. Concurrent batches return `409`; uncertain rows are never replayed automatically.

### POST `/api/v1/reminders/dismiss`

Archives one explicitly reviewed uncertain local row after the operator has inspected Microsoft To Do.

```json
{ "id": "local:12" }
```

## Apex Agents and local models

### GET `/api/v1/cortex/tool-catalog`

Returns the current catalog for one selected model (`?model_id=...`; omitted uses the saved selection). Individual entries
include the stable capability name, model-facing label and description, native or
MCP origin, source/server, risk, availability reason, Agent-policy result, and
estimated schema tokens. Groups contain curated APEX families or MCP servers with
tool counts and schema-token subtotals. The response also includes built-in and
saved profiles, the Agent's default profile, known local context capacity, and
the active provider-hosted grounding names. Provider-hosted grounding is
separate from APEX/MCP schema profiles.

The selector is a prompt-level exposure layer. It does not enable an MCP server,
connect or authenticate it, change a persistent allowlist, or bypass sandbox
policy when `DEV_MODE` and `ask_apex.sandbox_mode` are active.

### POST `/api/v1/cortex/tool-preflight`

Accepts an Agent, optional model override, optional context window, optional local reasoning mode, selected stable names, optional profile, prompt, optional conversation ID, and explicit snapshot/briefing attachment IDs. The backend reconstructs
the bounded active branch when a conversation ID is present. It returns estimates for
system instructions, conversation history, HUD context, reserved retrieved context, selected schemas,
prompt, total, configured context, reserved response capacity, and remaining
capacity. Every value is marked as an estimate by the response contract.
Rejected selections remain in the response as structured diagnostics with
`can_proceed=false`; the endpoint does not turn those diagnostics into a
generic HTTP error. Local context totals are generic UI warnings only. The
provider serializes the actual request, applies its template allowance and
safety margin, trims complete older interactions, and is authoritative for
whether the current interaction fits.

`model_id`, `context_window`, and `local_reasoning_mode` are all optional. When supplied, the estimate uses those values instead of the Agent's saved Cortex presets. The Home workspace uses these fields to estimate token use against the selected model and its ephemeral overrides without touching saved Cortex settings.

### GET `/api/v1/cortex/tool-profiles`

Returns built-in and persisted custom profiles. Built-in profiles are `No APEX
Tools`, `All APEX Tools`, `Personal Ops`, `Daily Planning`, `Research`, and
`Markets`. `All APEX Tools` resolves dynamically against
current Agent policy and runtime availability; other profiles retain explicit
stable names. Custom profile references are preserved when a tool later becomes
unavailable. Profile writes persist non-secret settings in `config.local.json`
and never modify MCP runtime configuration. Mutation responses include the
stable `affected_profile_id` when a profile was created, updated, deleted, or
assigned as a default.

### POST `/api/v1/cortex/tool-profiles`

Creates a custom profile from explicit stable capability names.

### PATCH `/api/v1/cortex/tool-profiles/{profile_id}`

Edits a saved custom profile. Its missing or unavailable tool references remain
in the profile.

### DELETE `/api/v1/cortex/tool-profiles/{profile_id}`

Deletes a saved custom profile and clears runtime defaults that pointed to it.

### POST `/api/v1/cortex/tool-profiles/default`

Assigns an existing built-in or custom profile as the default for one runtime (`cloud` or `local`).

### GET `/api/v1/cortex/agent`

Returns the single Apex Agent and its ordered model catalog. Each entry supplies model/provider/runtime, stability, supported reasoning and local controls, grounded-tool state, pricing, and availability/lifecycle diagnostics.

Development-only models appear in the `model_catalog` list only when `DEV_MODE` is active. They are not separate Apex Agents.

Cloud status starts as `configured` when a credential exists; it does not imply a provider has been reached. Explicit checks and completed inferences can report `verified`; sanitized errors can report unauthorized access, unavailable models, rate limits, quota or billing blocks, unreachable providers, or provider errors. Local availability distinguishes an unreachable runtime, missing model, loading model, busy execution slot, and provider-reported residency. Local catalog entries publish model-specific context and reasoning values, options, and defaults.

Registered cloud models include `deepseek/deepseek-v4-flash-0731`, `gpt-5.6-luna`, and development-only Gemini models. Registered local models include Gemma and Qwen GGUF profiles plus development-only Ollama profiles.

### POST `/api/v1/cortex/models/verify`

Runs one user-triggered, non-generative metadata check for a visible credential-backed cloud model:

```json
{ "model_id": "deepseek/deepseek-v4-flash-0731" }
```

Google uses the Gemini API model metadata endpoint and OpenAI uses the OpenAI API. OpenRouter uses authenticated `GET /api/v1/endpoints/zdr` and verifies that the selected model has a ZDR route. The five-second probe sends no prompt, context, or provider tool call. Results are sanitized and cached; polling never triggers a probe.

- `400` / `422` — the model is local or has no supported verification path.
- `403` — demo mode disallows provider contact.
- `404` — the model is not registered or visible.
- `409` — credentials are missing or that model already has a verification in progress.

### POST `/api/v1/cortex/local-model/load`

Pre-warms one installed local model before a request:

```json
{ "model_id": "gemma-4-E2B-Q4_K_M.gguf" }
```

`model_id` must be a registered local model. The route uses the same execution lock, resource gates, model-switch policy, and warmup options as a normal local turn. It returns success only after the local runtime confirms residency. Demo mode rejects pre-warming without contacting the local provider.

- `403` — demo mode disallows model calls.
- `409` — a local generation or lifecycle action is active.
- `503` — local inference is disabled, gated, unreachable, or could not be verified.

### POST `/api/v1/cortex/local-model/unload`

Canonical provider-neutral manual unload route. Returns success only when no APEX local model is resident or the active model's backend confirms it is absent after the request.

It also rejects a competing lifecycle action, and reports a failed post-action verification as unavailable.

- `403` — manual unload is disabled.
- `409` — local generation or lifecycle action is in progress.
- `503` — the unload request or post-action residency verification failed.

### GET `/api/v1/cortex/conversations`

Lists conversations in the current server-derived partition. Pass `archived=true` to list archived conversations instead of active ones.

### POST `/api/v1/cortex/conversations`

Creates a durable `hud` or `cli` conversation.

### GET `/api/v1/cortex/conversations/{conversation_id}`

Returns one conversation and every stored message node in stable creation order.

### PATCH `/api/v1/cortex/conversations/{conversation_id}`

Updates title, archive state, active branch, or saved Agent/tool-selection state.

### DELETE `/api/v1/cortex/conversations/{conversation_id}`

Permanently deletes an archived conversation and its stored message tree. The
conversation must belong to the current server-derived partition and must not
have a pending turn. Active conversations cannot be deleted; archive them first.

### Cortex turns

APEX owns Cortex conversation history in `apex_memory.db`. Conversations contain a tree of user and Agent messages, an active branch, Agent/tool selection state, timestamps, and archive state. HUD scratch threads remain browser-local until their first accepted turn; archived conversations can be permanently deleted through the archived-only DELETE route.

`GET /api/v1/cortex/conversations` lists the current server-derived partition. `POST /api/v1/cortex/conversations` creates a `hud` or `cli` conversation. `GET` and `PATCH /api/v1/cortex/conversations/{conversation_id}` read or update title, archive state, active branch, and saved Agent/tool state.

`POST /api/v1/cortex/conversations/{conversation_id}/turns` runs one Cortex Engine turn. Clients send generated user and Agent message UUIDs, an optional parent ID, and the current turn inputs.

```json
{
  "prompt": "What should I prioritize this afternoon?",
  "agent": "apex",
  "effort": "medium",
  "model_id": null,
  "context_window": null,
  "local_reasoning_mode": null,
  "user_message_id": "6dce6f5e-9f1e-4b2f-9930-0ca2668bd248",
  "agent_message_id": "d0b972df-2af6-42d3-9371-0433ccf9bd0a",
  "snapshot_id": "optional-current-snapshot-id",
  "briefing_id": 42,
  "selected_tool_names": [],
  "tool_profile_id": null
}
```

`model_id`, `context_window`, and `local_reasoning_mode` are optional per-turn overrides. When supplied, the turn uses those values instead of saved model preferences. The Home workspace sends these fields for every query: cloud models receive the lowest supported reasoning effort, and local models receive `context_window: 16384` with reasoning disabled. These overrides are ephemeral and never written back to settings.

`snapshot_id` and `briefing_id` are optional explicit context. When absent, APEX injects no HUD context. Unknown briefing IDs and stale snapshot IDs are omitted rather than replaced with the latest data. The server derives `sandbox` only when both `DEV_MODE` and the saved sandbox setting are active; clients cannot select or cross partitions. Sandbox turns reject saved `briefing_id` attachments and accept only the process-current masked development briefing identified by its matching `snapshot_id`.

The effective exposure is `selected tools ∩ Apex Agent policy ∩ runtime availability ∩ persistent MCP allowlists`. An explicit empty `selected_tool_names` list means `No APEX Tools`; omitted selection preserves runtime defaults of All APEX Tools for cloud and No APEX Tools for local. Invalid, unauthorized, disconnected, risk-rejected, or unavailable selected names are returned as structured per-tool failures. Cloud models can receive approved APEX capabilities and optional provider-hosted grounding where supported. `effort` is accepted only for models with reasoning levels. Responses contain Apex Agent and resolved model metadata, tool trace, usage, timing, and cost evidence.

- `400` — selected tools are invalid, outside policy, or unavailable.
- A provider-authoritative local context overflow is returned as an actionable
  stable response error after history trimming; the generic preflight estimate
  does not block the request.
- `403` — Agent queries are disabled.
- `429` — another local generation owns the execution slot.
- `503` — selected provider/model unavailable, cold-load gate failed, or model load failed.

Cortex Engine loops are bounded by the selected model profile. The final model turn is answer-only, leaving bounded tool-calling turns for workflows that need list resolution, task lookup, and approval-gated proposals.

### POST `/api/v1/cortex/context/captures`

Creates a `remember_personal_context` action proposal from direct operator input. It does not write a knowledge record until the normal action approval, execution, and verification flow completes. Structured captures require a subject, predicate, and exactly one entity or scalar value. Requests that resemble credentials or private keys are rejected before proposal creation.

When an Agent proposes the same capability from a durable Cortex turn, APEX stores the initiating user message as the source evidence. The model cannot select another conversation or source message.

### Context inspection and reconciliation

`GET /api/v1/cortex/context` lists up to 100 newest matching records in the
server-derived `production` or `sandbox` partition. It accepts repeated
`status` filters, an optional record kind, and a local text query over saved
text and structured entity fields. `GET /api/v1/cortex/context/{record_id}`
adds immutable source snapshots, supersession links, and nearby relationship
records. `GET /api/v1/cortex/context/entities` exposes only current entities
and their exact aliases for the local merge selector.

`POST /api/v1/cortex/context/actions` creates a normal durable action proposal
for `correct`, `retract`, `restore`, `set_current`, `add_alias`, or
`merge_entities`. It never changes knowledge directly. The server freezes the
selected record revision and current partition with the proposal, so a queued
operation fails safely when the underlying record changes. Retraction is a
destructive action; all other reconciliation operations are write actions.
Entity merges are explicit and one-way: record references and aliases move to
the selected target, while the source is retained only as a merged entity.

### Local retrieval foundation

`GET /api/v1/cortex/retrieval/status` reports whether local retrieval is disabled,
FTS-only, or semantic-ready, along with indexed, embedded, and pending item
counts. It reports stable error categories only. Conversation messages are
indexed locally in the shared unencrypted SQLite database and remain scoped to
the server-derived `production` or `sandbox` partition.

Repository documentation uses a separate shared `apex_docs` namespace. It
cannot return conversation records.

APEX attempts a no-download retrieval warm-up at startup when cached model
files are present. The explicit Prepare action remains available for
first-time setup and repair.

`POST /api/v1/cortex/retrieval/prepare` is the only operation that may download
the optional FastEmbed model into the ignored `weights/fastembed/` cache. It
repairs missing indexed items and backfills embeddings. Preparation is
explicit and synchronous; a concurrent request returns `409`. Missing or
invalid model files leave lexical FTS available and do not block startup or
Cortex turns.

`search_apex_docs` is a selected native read capability, not a public search
endpoint. It refreshes only `README.md` and `docs/**/*.md` immediately before
searching, then returns at most five excerpts with repository-relative source
locations. The excerpts are untrusted tool output. Agents should cite a used
excerpt as `path:Lstart-Lend`; it cannot alter system instructions or policy.

## Actions

Actions are loopback-only, durable proposals for supported native write capabilities. A Cortex turn validates and freezes the requested arguments, then returns a proposed action instead of performing the write. The API exposes the proposal, its ordered audit events, and the current lifecycle version.

Supported Microsoft To Do action capabilities are `create_microsoft_todo_task`, `update_microsoft_todo_task`, `complete_microsoft_todo_task`, `reopen_microsoft_todo_task`, and destructive `delete_microsoft_todo_task`. Every mutation requires an opaque list ID, task ID, and the task's observed `last_modified_at` from `list_microsoft_todo_tasks`; approval rereads that exact task and fails without writing when it changed. Updates can alter only title, due date, and importance; completion and reopening alter only status. Deletion verifies only through a confirmed exact-task `404`. A timeout or other ambiguous write outcome remains `outcome_unknown`; APEX never retries a write automatically, while explicit verification retry rereads only the frozen target.

`GET /api/v1/actions` returns newest-first records, accepts repeated `status` filters, and accepts `limit` from `1` through `50` (default `50`). The limit is applied after status filtering. `GET /api/v1/actions/{action_id}` also returns audit events. In demo mode the list is empty and detail is unavailable, so demo requests never read the real action ledger.

The approve, reject, and verify routes require `{"expected_version": 0}` with the version currently returned by the API. Approval runs synchronously: it approves a proposal, claims its execution once, and independently verifies the result. A later approval request may resume an already approved action, but restart recovery never replays an interrupted write. Verification retry is available only for `verification_failed` and `outcome_unknown` states and never re-executes the action. In demo mode, detail reads return `404` and mutations return `403`.

- `403` — an action mutation was made in demo mode.
- `404` — the action does not exist.
- `409` — the supplied version is stale or the requested lifecycle state is no longer valid.
- `503` — the local action service is unavailable.

## Markets and MCP

### GET `/api/v1/market`

Returns independently polled end-of-day ticker data, status, cooldown state, update time, and sparklines. Provider-error cooldown prevents repeated quota-consuming failures. Missing configuration returns a not-configured response with no tickers; demo mode returns simulated data.

### GET `/api/v1/mcp/status`

Returns sanitized global and per-provider MCP status, reasons, transport labels, and registered tool names. It never returns credentials, authorization headers, OAuth artifacts, endpoints, subprocess commands, allowlists, or local risk policy.

An enabled but unavailable provider remains enabled in settings while reporting a degraded or authorization-required state.

The status schema is unchanged while the runtime recovers transient provider failures automatically. A browser failure to retrieve this endpoint is a status-service failure, not evidence that every MCP provider is unavailable.

## Microsoft To Do authorization

### GET `/api/v1/microsoft-todo/status`

Returns whether the integration is configured, its authorization state, the fixed `Tasks.ReadWrite` permission, and a bounded authorization error when applicable. Existing read-only grants report authentication required until the user reconnects with the broader delegated permission.

### GET `/api/v1/microsoft-todo/lists`

Returns at most 50 sanitized `{ "id", "display_name" }` records for the Runtime Settings selected-list control. It returns `503` when the connected account cannot be read.

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

## Current route inventory

APEX API contract version 19.

| Method | Path | Purpose |
|---|---|---|
| DELETE | `/api/v1/cortex/conversations/{conversation_id}` | API route |
| DELETE | `/api/v1/cortex/tool-profiles/{profile_id}` | API route |
| DELETE | `/api/v1/microsoft-todo/auth` | API route |
| GET | `/` | API route |
| GET | `/api/v1/actions` | API route |
| GET | `/api/v1/actions/{action_id}` | API route |
| GET | `/api/v1/briefings/history` | API route |
| GET | `/api/v1/briefings/targets` | API route |
| GET | `/api/v1/config` | API route |
| GET | `/api/v1/cortex/agent` | API route |
| GET | `/api/v1/cortex/context` | API route |
| GET | `/api/v1/cortex/context/entities` | API route |
| GET | `/api/v1/cortex/context/{record_id}` | API route |
| GET | `/api/v1/cortex/conversations` | API route |
| GET | `/api/v1/cortex/conversations/{conversation_id}` | API route |
| GET | `/api/v1/cortex/retrieval/status` | API route |
| GET | `/api/v1/cortex/tool-catalog` | API route |
| GET | `/api/v1/cortex/tool-profiles` | API route |
| GET | `/api/v1/diagnostics` | API route |
| GET | `/api/v1/health/live` | API route |
| GET | `/api/v1/health/ready` | API route |
| GET | `/api/v1/llama-cpp/status` | API route |
| GET | `/api/v1/market` | API route |
| GET | `/api/v1/mcp/status` | API route |
| GET | `/api/v1/microsoft-todo/lists` | API route |
| GET | `/api/v1/microsoft-todo/status` | API route |
| GET | `/api/v1/reminders` | API route |
| GET | `/api/v1/reminders/completed` | API route |
| GET | `/api/v1/reminders/task` | API route |
| GET | `/api/v1/settings` | API route |
| GET | `/api/v1/status` | API route |
| GET | `/api/v1/telemetry/latest` | API route |
| PATCH | `/api/v1/cortex/conversations/{conversation_id}` | API route |
| PATCH | `/api/v1/cortex/tool-profiles/{profile_id}` | API route |
| PATCH | `/api/v1/settings` | API route |
| POST | `/api/v1/actions/{action_id}/approve` | API route |
| POST | `/api/v1/actions/{action_id}/reject` | API route |
| POST | `/api/v1/actions/{action_id}/verify` | API route |
| POST | `/api/v1/briefings/generate` | API route |
| POST | `/api/v1/cortex/context/actions` | API route |
| POST | `/api/v1/cortex/context/captures` | API route |
| POST | `/api/v1/cortex/conversations` | API route |
| POST | `/api/v1/cortex/conversations/{conversation_id}/turns` | API route |
| POST | `/api/v1/cortex/local-model/load` | API route |
| POST | `/api/v1/cortex/local-model/unload` | API route |
| POST | `/api/v1/cortex/models/verify` | API route |
| POST | `/api/v1/cortex/retrieval/prepare` | API route |
| POST | `/api/v1/cortex/tool-preflight` | API route |
| POST | `/api/v1/cortex/tool-profiles` | API route |
| POST | `/api/v1/cortex/tool-profiles/default` | API route |
| POST | `/api/v1/microsoft-todo/auth/start` | API route |
| POST | `/api/v1/preflight` | API route |
| POST | `/api/v1/reminders` | API route |
| POST | `/api/v1/reminders/complete` | API route |
| POST | `/api/v1/reminders/delete` | API route |
| POST | `/api/v1/reminders/dismiss` | API route |
| POST | `/api/v1/reminders/reopen` | API route |
| POST | `/api/v1/reminders/sync` | API route |
| POST | `/api/v1/reminders/update` | API route |
| POST | `/api/v1/telemetry/refresh` | API route |
| POST | `/api/v1/trigger` | API route |
| POST | `/api/v1/voice/speak` | API route |
