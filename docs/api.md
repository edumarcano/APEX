# APEX API Reference

The APEX API runs on FastAPI at `http://127.0.0.1:8000`. `launcher.py` and the module entrypoint bind it to loopback. CORS origins are controlled by the `APEX_ALLOWED_ORIGINS` environment variable (see [Environment Variables](#environment-variables-affecting-api-behavior)).

There is no authentication. The API is designed only for APEX running on its local machine; LAN and public access are intentionally unsupported. Supporting remote access would require authentication, authorization, and transport-security work. CORS restricts browser origins; it does not authenticate clients or protect a remotely bound API.

---

## Endpoints

### `GET /`

Compatibility health check. Returns a minimal payload. Prefer `/api/v1/health/live` and `/api/v1/health/ready` for new probes.

**Response `200`**
```json
{ "status": "online", "system": "APEX" }
```

---

### `GET /api/v1/health/live`

Process liveness probe. Does not check configuration or database dependencies.

**Response `200`**
```json
{ "status": "live" }
```

---

### `GET /api/v1/health/ready`

Readiness probe. Verifies that the runtime settings store can be loaded and that SQLite answers a lightweight `SELECT 1`. Does not call optional external providers (connectors, OAuth, or Ollama).

**Response `200`**
```json
{ "status": "ready", "config": "ok", "database": "ok" }
```

**Response `503`**
```json
{ "detail": "Configuration unavailable." }
```
or
```json
{ "detail": "Database unavailable." }
```

---

### `GET /api/v1/config`

Exposes global system configuration to the frontend HUD on boot. Called once alongside `GET /api/v1/reminders` while the HUD is idle.

Editable fields (`default_profile`, `ask_apex_enabled`, `market_enabled`) are sourced from the process-wide runtime settings store (`config.json` overlaid by `config.local.json`), not from import-time frozen constants. Non-editable fields (`max_session_messages`, synthesis boot hints, DEV/DEMO flags) continue to come from `config.json` / environment as before.

**Response `200`**
```json
{
  "default_profile": "comet",
  "ask_apex_enabled": true,
  "market_enabled": true,
  "max_session_messages": 6,
  "dev_mode_active": false,
  "demo_mode_active": false,
  "synthesis_strategy": "cloud",
  "synthesis_profile": "comet"
}
```

| Field | Type | Description |
|---|---|---|
| `default_profile` | string | Default APEX assistant profile identity (`"comet"`, `"nova"`, `"pulsar"`, `"lynx"`, `"acinonyx"`, or `"neofelis"`) from the runtime settings store (`ask_apex.default_profile`, with legacy `default_cloud_profile` fallback at load time) |
| `ask_apex_enabled` | boolean | Whether the assistant bar and assistant drawer are enabled, from the runtime settings store |
| `market_enabled` | boolean | Whether the HUD market connector polls and displays live data, from the runtime settings store |
| `max_session_messages` | integer | Client-side chat history cap, from `config.json` `ask_apex.max_session_messages` |
| `synthesis_strategy` | string | Initial HUD route: `cloud`, `local`, `raw`, or `demo` |
| `synthesis_profile` | string \| null | Nominal initial profile (`comet` or `lynx`) when applicable |

---

### `GET /api/v1/settings`

Returns the resolved editable settings snapshot plus read-only runtime metadata. Safe to call without the HUD.

**Response `200`** — `SettingsResponse`
```json
{
  "schema_version": 2,
  "settings": {
    "features": {
      "weather": true,
      "sports": true,
      "news": false,
      "email": false,
      "calendar": true,
      "market": true
    },
    "modules": {
      "football": false,
      "f1": true
    },
    "assistant": {
      "enabled": true,
      "default_profile": "comet"
    },
    "voice": {
      "engine": "google",
      "gender": "female"
    }
  },
  "local_file_present": false,
  "local_override_active": false,
  "load_warning": null,
  "dev_mode_active": false,
  "demo_mode_active": false
}
```

| Field | Type | Description |
|---|---|---|
| `schema_version` | integer | Settings contract version (currently `2`) |
| `settings` | object | Resolved editable snapshot (`features`, `modules`, `assistant`, `voice`) |
| `local_file_present` | boolean | Whether `config.local.json` exists on disk |
| `local_override_active` | boolean | Whether a valid local overlay is active |
| `load_warning` | string \| null | Diagnostic from the last load when local overlay was discarded |
| `dev_mode_active` | boolean | Read-only `DEV_MODE` env state |
| `demo_mode_active` | boolean | Read-only `DEMO_MODE` env state |

---

### `PATCH /api/v1/settings`

Merges dirty nested fields into the runtime settings store, validates, persists transactionally to `config.local.json`, and publishes only after a successful write. Omit unchanged sections and fields. Unknown fields are rejected.

**Request body** — `SettingsPatch` (all sections optional; nested fields optional)
```json
{
  "features": { "news": true },
  "voice": { "gender": "male" }
}
```

| Section | Fields |
|---|---|
| `features` | `weather`, `sports`, `news`, `email`, `calendar`, `market` (booleans) |
| `modules` | `football`, `f1` (booleans) |
| `assistant` | `enabled` (boolean), `default_profile` (one of the six profile identities) |
| `voice` | `engine` (`google` \| `pyttsx3` \| `kokoro`), `gender` (`male` \| `female`) |

**Response `200`** — same `SettingsResponse` envelope as GET after the patch applies.

**Response `422`** — invalid or unknown fields (FastAPI/Pydantic validation).

**Response `500`** — permanent persistence failure; active settings are not changed.
```json
{ "detail": "Failed to persist settings to config.local.json. Active settings were not changed. (...)" }
```

Empty patches (`{}`) return the current envelope without writing.

`DEV_MODE` and `DEMO_MODE` are not patchable through this endpoint.

**Effective timing:** briefing connector and module flags are captured at briefing start; `features.market` immediately starts or stops HUD polling; assistant enablement is checked when a query begins (in-flight queries finish); voice engine/gender are bound when delivery/`speak` begins.

---

### `POST /api/v1/trigger`

Runs the full pipeline: preflight stage label → collection → synthesis → delivery. Blocking — returns after all four stages complete and TTS audio has started on a background thread. Collection reuses the process-local telemetry snapshot service (`core/telemetry`) and still returns legacy per-module display strings on the response.

Startup Wi-Fi, battery, and cooldown checks are **not** hard blockers on this endpoint. Call `POST /api/v1/preflight` for advisory warnings before interactive activation. Calling this endpoint directly skips advisory acknowledgement; existing hard blockers (locks, credentials, resource gates) still apply where they are enforced.

When `DEMO_MODE=true`, this endpoint bypasses all connectors and serves a staged simulation using static mock telemetry from `core/mock/telemetry.json`. Stage delays of 1.5 seconds are inserted between each step so the frontend polling loop can observe them.

**Request body:** empty JSON object `{}` or no body.

**Response `200`** — `BriefingResponse`
```json
{
  "status": "success",
  "briefing": "...",
  "telemetry": {
    "weather": "...",
    "sports": "...",
    "news": "...",
    "email": "...",
    "calendar": "...",
    "reminders": "..."
  },
  "digest": {
    "weather_archetype": "clear_day",
    "unread_emails_count": 2,
    "upcoming_events_count": 1,
    "f1_sprint_active": false,
    "reminders_pending_count": 0,
    "sync_health_score": 95.0,
    "connector_health": [
      {
        "name": "weather",
        "status": "healthy",
        "freshness": "live",
        "reason_code": "ok",
        "observed_at": "2026-07-13T16:00:00+00:00"
      }
    ],
    "confidence_score": 95.0,
    "failed_connectors": [],
    "insights": ["..."]
  },
  "metadata": {
    "dev_mode_active": false,
    "demo_mode_active": false,
    "synthesis_strategy": "cloud",
    "synthesis_provider": "gemini",
    "synthesis_profile": "comet",
    "synthesis_fallback_reason": null,
    "synthesis_warmup_ms": null,
    "synthesis_generation_ms": 1240,
    "tts_strategy": "google",
    "active_tts_engine": "google",
    "system_load_throttled": false
  }
}
```

**`metadata` field descriptions:**

| Field | Type | Description |
|---|---|---|
| `dev_mode_active` | boolean | `true` when `DEV_MODE=true` was active for the run |
| `demo_mode_active` | boolean | `true` when `DEMO_MODE=true` was active for the run |
| `synthesis_strategy` | string | Configured route: `"cloud"` in production; `"raw"`, `"local"`, or `"cloud"` in dev mode; `"demo"` in demo mode |
| `synthesis_provider` | string \| null | Resolved briefing provider: `gemini`, `ollama`, `raw`, or `demo` |
| `synthesis_profile` | string \| null | Resolved profile: `comet`, `lynx`, `acinonyx`, or `neofelis` |
| `synthesis_fallback_reason` | string \| null | Machine-readable reason when routing changed or raw fallback was used |
| `synthesis_warmup_ms` | integer \| null | Local warmup duration when applicable |
| `synthesis_generation_ms` | integer \| null | Resolved provider generation duration when applicable |
| `tts_strategy` | string | Configured TTS strategy: `"google"`, `"kokoro"`, or `"pyttsx3"` in production; reflects `DEV_TTS_PLAYBACK` or `DEMO_TTS` otherwise |
| `active_tts_engine` | string | Resolved active TTS engine used for playback (e.g., `"google"`, `"kokoro"`, or `"pyttsx3"`); may differ from `tts_strategy` if system resource throttling triggers local fallback |
| `system_load_throttled` | boolean | `true` when hardware resource utilization exceeds throttle limits and triggers local fallback |

**`digest` field descriptions:**

| Field | Type | Description |
|---|---|---|
| `weather_archetype` | string \| null | Normalized weather condition label: `"clear_day"`, `"clear_night"`, `"clouds"`, `"rain"`, `"thunderstorm"`, or `null` |
| `unread_emails_count` | integer | Count of unread primary inbox messages collected during the run |
| `upcoming_events_count` | integer | Count of calendar events within the 48-hour briefing window |
| `f1_sprint_active` | boolean | `true` when an F1 sprint session is scheduled this week |
| `reminders_pending_count` | integer | Count of unread reminders included in the briefing |
| `sync_health_score` | float | Equal-weight typed connector sync health (0–100) |
| `connector_health` | object[] | Per-connector rows: `name`, `status`, `freshness`, `reason_code`, `observed_at` |
| `confidence_score` | float | Compatibility alias of `sync_health_score` for legacy consumers |
| `failed_connectors` | string[] | Legacy unavailable-connector labels: `"weather"`, `"news"`, `"email"`, `"calendar"`, `"sports"` (F1/football map to `"sports"`) |
| `insights` | string[] | Cross-correlated action-oriented bullet strings produced by the synthesis `===INSIGHTS===` output section |

**Demo path:** When the demo path is active, the response always returns `demo_mode_active: true` and `dev_mode_active: true` regardless of the `DEV_MODE` flag value. The `digest` object is loaded from `core/mock/telemetry.json`.

**Note:** the trigger response is returned while TTS audio is still playing on a background thread. Use `GET /api/v1/status` to track `is_speaking` state after the trigger resolves.

**Response `409`** — another pipeline run already holds the trigger lock
```json
{ "detail": "Pipeline run already active." }
```

---

### `GET /api/v1/telemetry/latest`

Returns the current in-memory telemetry snapshot for this API process. Raw snapshots are not persisted to SQLite.

**Response `200`** — `TelemetrySnapshot`
```json
{
  "snapshot_id": "9f3c2a1e-4b5d-6789-abcd-ef0123456789",
  "collected_at": "2026-07-21T16:00:00+00:00",
  "modules": {
    "weather": {
      "name": "weather",
      "status": "healthy",
      "freshness": "live",
      "reason_code": "ok",
      "observed_at": "2026-07-21T16:00:00+00:00",
      "display_text": "Current temperature is 72 degrees with clear sky.",
      "data": { "temp_f": 72, "condition": "clear sky" }
    }
  },
  "sync_health_score": 100.0,
  "connector_health": [],
  "failed_connectors": []
}
```

Module `status` values: `healthy`, `degraded`, `unavailable`, `disabled`. Disabled connectors are excluded from the Sync Health denominator.

**Response `404`** — no snapshot has been collected yet
```json
{ "detail": "No telemetry snapshot is available." }
```

---

### `POST /api/v1/telemetry/refresh`

Refresh one or more connectors and return the resulting complete snapshot.

**Request body**
```json
{
  "connectors": ["weather", "news"],
  "force": false
}
```

| Field | Type | Description |
|---|---|---|
| `connectors` | string[] \| null | Optional connector names. Omitted or empty refreshes all enabled connectors. |
| `force` | boolean | When `false`, returns the current snapshot only when every requested enabled connector was observed within five minutes and disabled states still match runtime settings. When `true`, always collects; a forced external connector call records a timestamp for rapid-refresh preflight warnings. |

Partial refresh merges into the prior snapshot. When a refreshed module returns `unavailable`, the previous healthy/degraded module content is retained as `stale`. Competing refreshes are not queued.

**Response `200`** — `TelemetrySnapshot` (same shape as latest)

**Response `409`** — refresh lock held
```json
{ "detail": "Telemetry refresh already in progress." }
```

**Response `400`** — unknown connector names

Market data remains on `GET /api/v1/market` and is independent of this refresh path.

---

### `POST /api/v1/preflight`

Advisory operational risk evaluation for a planned HUD or API operation. Returns stable warning codes plus non-overridable blockers. Session acknowledgements are request-scoped and not persisted.

**Request body**
```json
{
  "operation": "activate",
  "connectors": null,
  "synthesis_profile": "comet",
  "force": false,
  "involves_cloud": true,
  "acknowledged_warnings": [],
  "cloud_disclosure_acknowledged": false
}
```

**Advisory warning codes:** `outside_configured_network`, `network_trust_unknown`, `running_on_battery`, `rapid_connector_refresh`, `cloud_data_disclosure`, `high_resource_local_profile`.

SSID comparison is configured-network policy, not proof of network security. Missing/unreadable SSID yields `network_trust_unknown`. Battery warnings and RAM/CPU gates apply only before a cold local-model load; a matching resident model skips them. Rapid-refresh warnings apply only to forced enabled external connectors, not reminders-only reads. `DEMO_MODE` returns an empty advisory result.

**Hard blocker codes (cannot be overridden by acknowledgement):** `missing_credentials`, `model_unreachable`, `model_not_installed`, `concurrent_local_execution`, `insufficient_ram`, `cpu_overloaded`, `database_failure`, `configuration_failure`, `invalid_input`, `model_load_failure`. Credential evaluation covers Gemini plus enabled requested weather, news, football, Gmail, and Calendar connectors.

**Response `200`** — `PreflightResponse`
```json
{
  "warnings": [
    {
      "code": "cloud_data_disclosure",
      "message": "This operation may send sanitized operational context to a cloud provider."
    }
  ],
  "blockers": [],
  "can_proceed": true
}
```

---

### `GET /api/v1/status`

Diagnostic snapshot of the active pipeline run. Readable only while a trigger is running or TTS audio is playing.

**Response `200`** — `PipelineStatusSnapshot`
```json
{
  "run_id": "9f3c2a1e-4b5d-6789-abcd-ef0123456789",
  "step": 2,
  "label": "COLLECTION",
  "timestamp": "2026-06-06T12:34:56.789012+00:00",
  "is_speaking": false,
  "active_tts_engine": "google",
  "system_load_throttled": false,
  "synthesis": {
    "phase": "idle",
    "provider": null,
    "profile": null,
    "loading": false,
    "fallback_reason": null
  }
}
```

| Field | Type | Description |
|---|---|---|
| `run_id` | string \| null | Correlation ID for the active briefing pipeline run |
| `step` | integer | Pipeline step 1–4: Gate, Collection, Synthesis, Delivery |
| `label` | string | Short stage label: `GATE`, `COLLECTION`, `SYNTHESIS`, `DELIVERY` |
| `timestamp` | string | UTC ISO-8601 timestamp of the last stage update |
| `is_speaking` | boolean | `true` when `_SPEAK_LOCK` is held or `pygame.mixer.music.get_busy()` is active |
| `active_tts_engine` | string | Resolved active TTS engine used for playback (e.g., `"google"`, `"kokoro"`, or `"pyttsx3"`) |
| `system_load_throttled` | boolean | `true` when hardware resource utilization exceeds throttle limits and triggers local fallback |
| `synthesis` | object \| null | Live synthesis routing state for the active run |
| `synthesis.phase` | string | `idle`, `loading`, `ready`, `generating`, `fallback`, or `complete` |
| `synthesis.provider` | string \| null | Resolved provider while routing: `gemini`, `ollama`, `raw`, or `demo` |
| `synthesis.profile` | string \| null | Resolved profile when applicable (`comet`, `lynx`, `acinonyx`, `neofelis`) |
| `synthesis.loading` | boolean | `true` while local model warmup is in progress (`phase == "loading"`) |
| `synthesis.fallback_reason` | string \| null | Machine-readable reason when routing changed or raw fallback was used |

**Response `404`** — no active run. The frontend treats this as the idle signal, clears the polling interval, and marks `isSpeaking` as `false`.

---

### `GET /api/v1/diagnostics`

Real-time hardware utilization snapshot. Available at any time, independent of pipeline state.

**Response `200`**
```json
{
  "cpu": 12.5,
  "cpu_freq": 2.4,
  "ram": 58.3,
  "ram_used": 9.3,
  "ram_total": 16.0,
  "disk": 44.1,
  "disk_used": 220.5,
  "disk_total": 500.0
}
```

Each psutil query is isolated in a `try/except`; a single hardware read failure returns `0.0` for that field without crashing the response. `cpu_freq` is in GHz. `ram_used`, `ram_total`, `disk_used`, and `disk_total` are in GB. The `SystemDiagnostics` HUD component polls this endpoint at 1,000 ms intervals.

---

### `GET /api/v1/market`

Cache-first end-of-day market snapshot for a configured ticker symbol set. Independent of the briefing pipeline and of `DEV_MODE`; polled by the frontend's `useMarketData` hook every 30 seconds only while `features.market` is enabled. The endpoint remains available when HUD polling is disabled.

**Response `200`** — `MarketResponse`
```json
{
  "status": "live",
  "cooldown_active": false,
  "cooldown_remaining_seconds": 0,
  "tickers": [
    {
      "symbol": "SPY",
      "price": 521.34,
      "change": 1.12,
      "change_percent": 0.22,
      "status": "live",
      "last_updated": "2026-07-08T21:00:00+00:00",
      "sparkline": [521.34, 520.22, 519.87, 518.90, 519.50, 520.10, 520.75]
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `status` | string | Aggregate feed state: `"live"`, `"partial"`, `"stale"`, `"unavailable"`, `"not_configured"`, or `"provider_unavailable"` |
| `cooldown_active` | boolean | `true` when outgoing Alpha Vantage requests are globally paused after a prior provider error |
| `cooldown_remaining_seconds` | integer | Seconds remaining in the active cooldown window (0 when inactive) |
| `tickers` | `MarketTickerItem[]` | Ordered snapshots, one per configured symbol |

**`MarketTickerItem` fields:**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Configured ticker symbol |
| `price` | float \| null | Latest available daily close price |
| `change` | float \| null | Absolute close-to-close change versus the prior trading day |
| `change_percent` | float \| null | Percent close-to-close change, without a trailing `%` sign |
| `status` | string | Per-symbol freshness: `"live"`, `"stale"`, or `"unavailable"` |
| `last_updated` | string \| null | UTC ISO-8601 timestamp of the last successful fetch for this symbol |
| `sparkline` | float[] | Up to 7 recent daily closes, newest first |

**Symbol configuration:** `MARKET_SYMBOLS` (`.env`) is a comma-separated ticker list. When unset, `status` is `"not_configured"` and `tickers` is empty.

**Simulation fallback:** When `DEMO_MODE=true` or `ALPHA_VANTAGE_API_KEY` is unset, the endpoint returns a deterministic simulated feed (fixed symbol set `SPY`, `AAPL`, `MSFT`) with `status: "live"` rather than an error or empty response, so the HUD ticker always has data to render.

**Cache and cooldown behavior:** Each symbol is cached to a local file with a 12-hour TTL. A failed or rate-limited Alpha Vantage request sets a 15-minute cooldown during which no further outbound requests are made for any configured symbol; cached data (marked `"stale"`) is served instead. `cooldown_active` and `cooldown_remaining_seconds` reflect this window.

**Response `503`** — snapshot retrieval raised an unhandled exception
```json
{ "detail": "Market snapshot unavailable." }
```

---

### `GET /api/v1/reminders`

Returns all unread reminders.

**Response `200`** — list of `ReminderRecord`
```json
[
  { "id": 1, "note": "Call the bank before 3pm." },
  { "id": 2, "note": "Pick up package from front desk." }
]
```

Returns an empty list `[]` when there are no unread reminders.

**Demo path:** When `DEMO_MODE=true`, returns two static `ReminderRecord` items (`id: 991`, `id: 992`) without querying the database.

---

### `POST /api/v1/reminders`

Persists a new reminder. Input is sanitized before storage.

**Request body** — `CreateReminderRequest`
```json
{ "text": "Your reminder text here." }
```

`text` must be 1–4,096 characters. Before persistence, the text is passed through `clean_for_tts()`, which strips markdown constructs (headers, bold, italic, strikethrough, code blocks, links, images, blockquotes, list markers) and non-ASCII characters, then collapses whitespace.

**Response `201`** — `CreateReminderResponse`
```json
{ "id": 3 }
```

**Response `422`** — the text is empty after sanitization (e.g., input contained only emoji or markdown).
```json
{ "detail": "Reminder text is empty after TTS sanitization." }
```

**Demo path:** When `DEMO_MODE=true`, sanitization still runs but the record is not written to the database. Returns a static `{ "id": 999 }` response.

---

### `POST /api/v1/reminders/read`

Marks one or more reminders as read by row ID. The HUD calls this on explicit user dismissal and removes the item from local state optimistically, restoring it if this call fails.

**Request body** — `MarkReadRequest`
```json
{ "ids": [1, 2] }
```

`ids` must contain at least one integer ≥ 1.

**Response `200`** — `MarkReadResponse`
```json
{ "status": "success" }
```

**Demo path:** When `DEMO_MODE=true`, returns `{ "status": "success" }` without writing to the database.

---

### `GET /api/v1/briefings/history`

Returns up to 50 recent briefing ledger entries ordered by timestamp descending.

**Response `200`** — list of `BriefingHistoryRecord`
```json
[
  {
    "id": 3,
    "timestamp": "2026-06-08T08:15:00+00:00",
    "briefing": "Greetings Chief...",
    "digest": {
      "weather_archetype": "clear_day",
      "unread_emails_count": 2,
      "upcoming_events_count": 1,
      "f1_sprint_active": false,
      "reminders_pending_count": 2,
      "sync_health_score": 100.0,
      "confidence_score": 100.0,
      "failed_connectors": [],
      "insights": []
    },
    "metadata": {
      "run_id": "9f3c2a1e-4b5d-6789-abcd-ef0123456789",
      "dev_mode_active": false,
      "demo_mode_active": false,
      "synthesis_strategy": "cloud",
      "tts_strategy": "google",
      "active_tts_engine": "google",
      "system_load_throttled": false
    },
    "digest_status": "valid"
  }
]
```

| Field | Type | Description |
|---|---|---|
| `digest_status` | string | History quality: `valid`, `legacy`, `malformed`, or `zero_health` |

Returns an empty list `[]` when no briefings have been stored. Malformed rows still return a safe digest fallback for HUD compatibility, but `digest_status` distinguishes them from genuine zero-health scores. History fetch failures return `503` with `"Briefing history unavailable."`

**Demo path:** When `DEMO_MODE=true`, returns a static set of three mock `BriefingHistoryRecord` entries without querying the database.

---

### `POST /api/v1/agent/query`

Executes one turn of the APEX conversational assistant, including any tool calls the model requests. The route is synchronous so FastAPI runs blocking Gemini or Ollama provider I/O on its worker-thread boundary. Internally, Cortex drives the reasoning/tool-calling loop.

The endpoint is stateless on the server. The full conversation history is supplied by the client on every call and echoed back into the next request — there is no server-side session store.

**Request body** — `AgentQueryRequest`
```json
{
  "prompt": "What is the current weather?",
  "profile": "comet",
  "session_id": null,
  "history": []
}
```

| Field | Type | Description |
|---|---|---|
| `prompt` | string | The user's query for this turn. |
| `profile` | string | Cloud (`"comet"`, `"nova"`, `"pulsar"`) or local (`"lynx"`, `"acinonyx"`, `"neofelis"`) profile. Defaults to `"comet"`. |
| `session_id` | string \| null | Optional client-generated grouping identifier; passed through unchanged. |
| `history` | `AgentMessage[]` | Prior turns for this session, including `tool_calls`/`tool_results`. Empty on the first turn. |
| `snapshot_id` | string \| null | Optional telemetry snapshot ID. When present and matching the current in-memory snapshot, module display text is injected as HUD context. Absent or mismatched IDs inject no snapshot context. |
| `briefing_id` | integer \| null | Optional briefing history row ID. When present, that briefing's prose and insights are injected as HUD context. Absent or unknown IDs inject no briefing context. |

`profile` accepts three cloud values (`"comet"`, `"nova"`, `"pulsar"`, routed to Gemini) and three local values (`"lynx"`, `"acinonyx"`, `"neofelis"`, routed to Ollama). See [Local Agent Profiles](architecture.md#local-agent-profiles) for the local profile table.

**Response `200`** — `AgentQueryResponse`
```json
{
  "answer": "Current conditions are 78°F with clear skies.",
  "profile_used": { "display_name": "Apex Nova", "api_model": "gemini-3-flash-preview", "...": "..." },
  "tool_trace": [
    { "name": "get_weather_forecast", "status": "ok", "duration_ms": 412.3 }
  ],
  "tool_outputs": [],
  "session_id": null,
  "error": null
}
```

| Field | Type | Description |
|---|---|---|
| `answer` | string | Final synthesized text response. |
| `profile_used` | object | Full cloud or local model profile dump for the profile that served this request. |
| `tool_trace` | object[] | One entry per tool executed this turn: `name`, `status` (`"ok"` or `"error"`), `duration_ms`. |
| `tool_outputs` | object[] | One entry per tool executed this turn with its full structured output: `name`, `status`, `duration_ms`, `output`. Only tools in the output whitelist (see below) return their real `output`; all others return `{"error": "Tool output is not whitelisted for client display."}`. A dispatcher exception returns the stable public payload `{"error": "Tool execution failed."}` rather than the exception text. |
| `session_id` | string \| null | Echo of the request's `session_id`. |
| `error` | string \| null | Populated when a bounded-loop limit was reached or an exception occurred; `answer` still contains a usable fallback message in that case. |

**Tool output whitelist:** `tool_outputs` exists so the HUD can render structured result cards (forecast tables, standings, calendar entries) without re-deriving them from `answer` text. Only tools in `ALLOWED_TOOL_OUTPUT_REGISTRY` (`core/agent/loop.py`) return their real output in this field: `get_weather_forecast`, `get_f1_driver_standings`, `get_f1_season_calendar`, `get_upcoming_calendar_events`, `get_active_reminders`, `get_briefing_history`.

**Response `403`** — Assistant interface disabled via runtime settings (`assistant.enabled` / `ask_apex.enabled`)
```json
{ "detail": "APEX is currently disabled in system settings." }
```

**Response `400`** — unknown `profile` value not present in the registered Gemini or Ollama profile maps.

**Missing API key:** When `GEMINI_API_KEY` is not set, the endpoint returns `200` with a static unavailability message in `answer` and `error` set to `"GEMINI_API_KEY is missing from environment variables."` rather than raising an HTTP error.

**HUD context injection:** The handler does **not** implicitly inject the latest persisted briefing. Optional `briefing_id` and/or `snapshot_id` on the request select explicit HUD context. Absent identifiers mean no HUD briefing/telemetry context is appended to the system instruction. Selected context is sanitized, bounded to 2,000 characters, wrapped in `<untrusted_hud_context>` markers, and accompanied by an instruction to treat it as data rather than commands.

**Bounded tool-calling loop:** Execution is capped by the active profile's `max_tool_turns` and `max_tool_calls` (see [Cloud Agent Profiles](architecture.md#cloud-agent-profiles) in the architecture reference). Reaching either limit ends the loop and returns the last model text with `error` populated, rather than looping indefinitely or failing the request.

**Demo path:** When `DEMO_MODE=true`, returns a deterministic canned response selected by keyword-matching the prompt against entries in `core/mock/assistant.json` (weather/forecast, F1/standings/calendar, reminders/tasks, or a generic fallback). Each entry supplies its own `answer`, `tool_trace`, and `tool_outputs`. No live Gemini or Ollama call is made.

**Local (Ollama) profile behavior:** Requests targeting a local profile (`lynx`, `acinonyx`, `neofelis`) pass through additional admission checks before the agent loop runs:

1. **Execution slot** — only one local generation runs at a time. A concurrent request while another is in flight returns `429`.
2. **Resource gate** — if the target model is not already loaded in Ollama, current host RAM/CPU utilization is checked against the profile's configured limits (`config.json` `ollama.resource_gates.*`). A model that is already loaded skips this check, since re-selecting it does not add to host resource usage.
3. **Model switch** — if the target model differs from whatever is currently loaded, the previous model is unloaded and the new one is loaded before the turn runs. A load failure returns `503`.

**Response `429`** — a local generation is already in progress
```json
{ "detail": "A local model generation is already in progress. Wait for it to finish and try again." }
```

**Response `503`** — local profile blocked by the resource gate, or the model failed to load
```json
{ "detail": "Local profile blocked: Current memory pressure exceeds threshold." }
```
```json
{ "detail": "Local model qwen3:8b failed to load. Ensure Ollama is reachable and configured." }
```

**Response `503`** — Ollama local inference disabled in `config.json` (`ollama.enabled: false`)
```json
{ "detail": "Local Ollama inference is disabled in system settings." }
```

---

### `GET /api/v1/agent/profiles`

Returns availability status for all six assistant profiles (three cloud, three local) so the HUD can gate profile selection before a query is sent.

Ollama reachability, installed model tags, and host vitals are read from a shared cache refreshed at most once every 10 seconds, so frequent polling never floods the Ollama daemon.

**Response `200`** — list of `AgentProfileStatus`
```json
[
  {
    "key": "lynx",
    "display_name": "Apex Lynx",
    "provider": "ollama",
    "tier": "lightweight",
    "stability": "stable",
    "thinking_level": null,
    "status": "model_not_installed",
    "active": false,
    "loading": false,
    "reason": "Model tag is not installed locally",
    "idle_unload_remaining_seconds": null,
    "loaded_model": null
  },
  {
    "key": "comet",
    "display_name": "Apex Comet",
    "provider": "gemini",
    "tier": "fast",
    "stability": "stable",
    "status": "available",
    "active": false,
    "loading": false,
    "reason": null,
    "idle_unload_remaining_seconds": null,
    "loaded_model": null
  }
]
```

| Field | Type | Description |
|---|---|---|
| `key` | string | Profile identifier: `"comet"`, `"nova"`, `"pulsar"`, `"lynx"`, `"acinonyx"`, `"neofelis"` |
| `display_name` | string | Human-readable label (e.g., `"Apex Lynx"`) |
| `provider` | string | `"ollama"` or `"gemini"` |
| `tier` | string | Performance tier label (e.g., `"lightweight"`, `"fast"`, `"advanced"`) |
| `stability` | string | `"stable"` or `"preview"` |
| `thinking_level` | string \| null | Gemini profile effort (`minimal`, `low`, `medium`, `high`); null for Ollama |
| `status` | string | See `ProfileAvailabilityStatus` values below |
| `active` | boolean | `true` when this profile's local model is currently loaded in Ollama memory (always `false` for cloud profiles) |
| `loading` | boolean | `true` while this profile's local model is being warmed up (loaded into Ollama but not yet ready to serve); always `false` for cloud profiles. Distinct from `active`: a model is `loading` before it is `active`. |
| `reason` | string \| null | Human-readable explanation when `status` is not `"available"` |
| `idle_unload_remaining_seconds` | integer \| null | Seconds until this local model auto-unloads; populated only for the currently active local profile |
| `loaded_model` | object \| null | Runtime details reported by Ollama (`name`, `model`, `size_bytes`, `size_vram_bytes`, `processor`, `context`, `expires_at`) when this profile's model is loaded |

**`ProfileAvailabilityStatus` values:**

| Value | Meaning |
|---|---|
| `available` | Profile can be selected and queried now |
| `busy` | Local execution slot is held (briefing synthesis or another local generation); local profiles only. Reason: `"Briefing synthesis is using local inference."` Cloud profiles remain independently evaluated. |
| `disabled` | Profile disabled in system settings (`ollama.enabled: false`, or missing `GEMINI_API_KEY` for cloud profiles) |
| `ollama_unreachable` | Ollama daemon did not respond to the status probe |
| `model_not_installed` | The profile's model tag is not present in Ollama's installed tags |
| `insufficient_ram` | Host RAM utilization meets or exceeds the profile's `ram_limit` |
| `cpu_overloaded` | Host CPU utilization meets or exceeds the profile's `cpu_limit` |

---

### `POST /api/v1/voice/speak`

Speaks sanitized text using the configured TTS engine and the universal speech lock. Runs synchronously on FastAPI's worker-thread boundary. Voice mode settings (`off` / `manual` / `automatic`) are a later milestone; this endpoint always attempts delivery when called.

**Request body** — `VoiceSpeakRequest`
```json
{
  "text": "APEX online. Ready for operations."
}
```

| Field | Type | Description |
|---|---|---|
| `text` | string | Non-empty text (1–4000 chars). Sanitized through the existing TTS cleaner before playback. |

**Response `200`** — `VoiceSpeakResponse`
```json
{ "status": "spoken" }
```

**Response `400`** — empty after sanitization
```json
{ "detail": "Speech text is empty after sanitization." }
```

**Response `409`** — speech lock already held
```json
{ "detail": "Speech delivery is already in progress." }
```

---

### `POST /api/v1/local-model/unload`

Provider-neutral manual unload for the active APEX local model. The legacy `POST /api/v1/agent/local/unload` route remains as a compatibility alias.

Manually unloads the currently active local Ollama model from memory, ahead of the automatic idle-unload timer.

**Request body:** empty JSON object `{}` or no body.

**Response `200`** — `LocalUnloadResponse`
```json
{ "status": "success" }
```

Returns success when no local model is currently active or the unload completes cleanly.

**Response `403`** — manual unload disabled via `config.json` `ollama.manual_unload_enabled`
```json
{ "detail": "Manual local model unload is disabled in system settings." }
```

**Response `409`** — a local generation is currently in progress
```json
{ "detail": "A local model generation is in progress. Wait for it to finish before unloading." }
```

**Response `503`** — the unload request to Ollama failed
```json
{ "detail": "Active local model failed to unload from Ollama." }
```

---

## Pydantic Models

### `BriefingResponse`

```python
class BriefingResponse(BaseModel):
    status: str                   # Run outcome label ("success")
    briefing: str                 # Synthesized briefing text
    telemetry: TelemetryPayload   # Per-module display telemetry
    digest: DigestPayload         # Structured summaries and Sync Health
    metadata: RuntimeMetadata     # Runtime routing metadata
```

### `TelemetryPayload`

```python
class TelemetryPayload(BaseModel):
    weather: str
    sports: str
    news: str
    email: str
    calendar: str
    reminders: str
```

Each field contains the display string produced for the HUD, or an empty string when the connector is disabled. These strings remain part of the response compatibility contract but are not forwarded to briefing models; synthesis uses the separate typed, sanitized `SynthesisInput` boundary.

### `RuntimeMetadata`

```python
class RuntimeMetadata(BaseModel):
    run_id: str | None
    dev_mode_active: bool
    demo_mode_active: bool
    synthesis_strategy: str   # "raw" | "local" | "cloud" | "demo"
    synthesis_provider: str | None   # "gemini" | "ollama" | "raw" | "demo"
    synthesis_profile: str | None    # "comet" | "lynx" | "acinonyx" | "neofelis"
    synthesis_fallback_reason: str | None
    synthesis_warmup_ms: int | None
    synthesis_generation_ms: int | None
    tts_strategy: str         # "pyttsx3" | "google" | "kokoro"
    active_tts_engine: str    # "pyttsx3" | "google" | "kokoro"
    system_load_throttled: bool
```

### `PipelineStatusSnapshot`

```python
class PipelineStatusSnapshot(BaseModel):
    run_id: str | None
    step: int
    label: str
    timestamp: str    # UTC ISO-8601
    is_speaking: bool
    active_tts_engine: str    # "pyttsx3" | "google" | "kokoro"
    system_load_throttled: bool
    synthesis: PipelineSynthesisState | None
```

### `ReminderRecord`

```python
class ReminderRecord(BaseModel):
    id: int     # SQLite row ID (≥ 1)
    note: str   # Sanitized reminder text
```

### `CreateReminderRequest`

```python
class CreateReminderRequest(BaseModel):
    text: str   # 1–4,096 characters; sanitized before persistence
```

### `CreateReminderResponse`

```python
class CreateReminderResponse(BaseModel):
    id: int   # SQLite row ID of the new reminder (≥ 1)
```

### `MarkReadRequest`

```python
class MarkReadRequest(BaseModel):
    ids: list[int]   # One or more row IDs (≥ 1 each)
```

### `MarkReadResponse`

```python
class MarkReadResponse(BaseModel):
    status: str = "success"
```

### `DigestPayload`

```python
class DigestPayload(BaseModel):
    weather_archetype: str | None = None
    unread_emails_count: int = 0
    upcoming_events_count: int = 0
    f1_sprint_active: bool = False
    reminders_pending_count: int = 0
    sync_health_score: float | None = None
    connector_health: list[ConnectorHealthEntry] = []
    confidence_score: float                # Alias of sync_health_score
    failed_connectors: list[str] = []      # Legacy unavailable labels; F1/football -> "sports"
    insights: list[str] = []
```

`sync_health_score` averages equal weights across enabled modules (`weather`, `news`, `email`, `calendar`, `f1`, `football`, `reminders`) using typed statuses: healthy `1.0`, degraded `0.5`, unavailable `0.0`. Fresh validated cache is healthy; stale fallback is degraded. Regex prose inference and the former F1 10% penalty are not used.

### `BriefingHistoryRecord`

```python
class BriefingHistoryRecord(BaseModel):
    id: int              # SQLite row ID
    timestamp: str       # New rows use timezone-aware UTC ISO-8601
    briefing: str        # Synthesized briefing text delivered to TTS
    digest: DigestPayload
    metadata: RuntimeMetadata | None = None
    digest_status: Literal["valid", "legacy", "malformed", "zero_health"]
```

Legacy rows can contain timezone-naive local timestamps and no metadata. They remain readable without a schema rewrite. `digest_status` distinguishes a current valid digest, a compatible legacy shape, malformed stored JSON, and a genuine zero-health run.

### `ToolCall`

```python
class ToolCall(BaseModel):
    id: str                          # Unique call identifier from the model
    name: str                        # Registered tool name to execute
    arguments: dict[str, Any]        # Arguments validated against the tool signature
    thought_signature: str | None = None  # Base64-encoded Gemini 3 reasoning token
```

`thought_signature` is an opaque token Gemini attaches to function calls under its native "thinking" mode. It is round-tripped verbatim (base64-decoded to bytes on the outbound request, re-encoded on the inbound response) so multi-turn tool-calling loop state stays valid across turns; APEX never inspects its contents.

### `ToolResult`

```python
class ToolResult(BaseModel):
    id: str          # Matches the originating ToolCall.id
    name: str        # Tool name that was executed
    output: Any      # Serializable raw output from the Python handler
```

### `AgentMessage`

```python
class AgentMessage(BaseModel):
    role: Literal["user", "model", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None
```

### `AgentQueryRequest`

```python
class AgentQueryRequest(BaseModel):
    prompt: str
    profile: Literal["comet", "nova", "pulsar", "lynx", "acinonyx", "neofelis"] = "comet"
    session_id: str | None = None
    history: list[AgentMessage] = []
```

### `AgentQueryResponse`

```python
class AgentQueryResponse(BaseModel):
    answer: str
    profile_used: dict[str, Any]
    tool_trace: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []
    session_id: str | None = None
    error: str | None = None
```

`tool_outputs` carries the full structured result for whitelisted tools (see [POST /api/v1/agent/query](#post-apiv1agentquery) above for the whitelist).

### `AgentProfileStatus`

```python
class AgentProfileStatus(BaseModel):
    key: str
    display_name: str
    provider: Literal["ollama", "gemini"]
    tier: str
    stability: Literal["stable", "preview"]
    status: ProfileAvailabilityStatus
    active: bool
    loading: bool = False
    reason: str | None = None
    idle_unload_remaining_seconds: int | None = None
    loaded_model: LocalLoadedModelStatus | None = None
```

Returned as a list by `GET /api/v1/agent/profiles`. See that endpoint's documentation above for the `ProfileAvailabilityStatus` value table.

### `LocalLoadedModelStatus`

```python
class LocalLoadedModelStatus(BaseModel):
    name: str
    model: str
    size_bytes: int | None = None
    size_vram_bytes: int | None = None
    processor: str | None = None
    context: str | None = None
    expires_at: str | None = None
```

Runtime details reported by Ollama's `/api/ps` endpoint for a loaded model. All fields except `name` and `model` are `None` when Ollama does not report that field.

### `LocalUnloadResponse`

```python
class LocalUnloadResponse(BaseModel):
    status: str = "success"
```

---

## Text Sanitization (`clean_for_tts`)

`clean_for_tts(text)` is applied to reminder input before database persistence. It strips the following markdown constructs in order:

1. Fenced code blocks (` ``` ... ``` `)
2. Image syntax (`![alt](url)` → alt text)
3. Link syntax (`[text](url)` → text)
4. Inline code (`` `code` `` → code)
5. ATX headers (`## heading` → heading)
6. Blockquotes (`> text` → text)
7. Horizontal rules
8. Unordered list markers (`- `, `* `, `+ `)
9. Ordered list markers (`1. `)
10. Bold (`**text**` / `__text__` → text)
11. Italic (`*text*` / `_text_` → text)
12. Strikethrough (`~~text~~` → text)
13. Non-ASCII characters → replaced with space
14. Whitespace collapsed to single spaces and stripped

A reminder that is entirely emoji or markdown returns an empty string, which triggers `HTTP 422`.

---

## Environment Variables Affecting API Behavior

| Variable | Default | Description |
|---|---|---|
| `DEV_MODE` | `false` | Suppresses configured-network preflight warnings and production run logging; Gmail/Calendar connectors still make live requests with content masked to `[HIDDEN]`; Gemini bypass depends on `DEV_AI_SYNTHESIS` |
| `DEMO_MODE` | `false` | Intercepts trigger; serves static mock telemetry |
| `ENABLE_STARTUP_GATE` | `true` | Legacy compatibility setting for `scanner.should_run()`; it does not gate API trigger or telemetry routes |
| `DEV_AI_SYNTHESIS` | `raw` | Synthesis path when `DEV_MODE=true`: `raw`, `local` (local → raw), `cloud` (Gemini → local → raw) |
| `DEV_TTS_PLAYBACK` | `pyttsx3` | TTS engine when `DEV_MODE=true`: `pyttsx3`, `google`, `kokoro` |
| `DEMO_TTS` | `pyttsx3` | TTS engine when `DEMO_MODE=true`: `pyttsx3`, `google`, `kokoro` |
| `APEX_ALLOWED_ORIGINS` | _(see below)_ | Comma-separated CORS origins; replaces defaults entirely when set |
| `ALPHA_VANTAGE_API_KEY` | _(unset)_ | Alpha Vantage API key for `GET /api/v1/market`; when unset, the endpoint serves a simulated ticker feed instead of live data |
| `MARKET_SYMBOLS` | _(unset)_ | Comma-separated ticker symbols for `GET /api/v1/market`; when unset, the endpoint returns `status: "not_configured"` with an empty ticker list |

**Default CORS origins** (when `APEX_ALLOWED_ORIGINS` is unset):
```
http://127.0.0.1:8000
http://localhost:8000
http://127.0.0.1:5500
http://localhost:5500
http://127.0.0.1:5173
http://localhost:5173
```

The `5173` pair covers the Vite dev server (`npm run dev`).

A custom value replaces these defaults rather than extending them. If you serve the HUD from a different port, set `APEX_ALLOWED_ORIGINS` to include all required origins.

Changing CORS origins does not change the server bind address and does not add authentication. The supported launcher path remains loopback-only.
