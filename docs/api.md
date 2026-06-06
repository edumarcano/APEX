# APEX API Reference

The APEX API runs on FastAPI at `http://127.0.0.1:8000`. All endpoints are local-only by default. CORS origins are controlled by the `APEX_ALLOWED_ORIGINS` environment variable (see [Environment Variables](#environment-variables-affecting-api-behavior)).

There is no authentication. The API is designed for single-machine local use.

---

## Endpoints

### `GET /`

Health check. Returns a minimal payload for launcher readiness polling.

**Response `200`**
```json
{ "status": "online", "system": "APEX Nexus" }
```

---

### `POST /api/v1/trigger`

Runs the full pipeline: gate → collection → synthesis → delivery. Blocking — returns after all four stages complete and TTS audio has started on a background thread.

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
  "metadata": {
    "dev_mode_active": false,
    "demo_mode_active": false,
    "synthesis_strategy": "llm",
    "tts_strategy": "google"
  }
}
```

**`metadata` field descriptions:**

| Field | Type | Description |
|---|---|---|
| `dev_mode_active` | boolean | `true` when `DEV_MODE=true` was active for the run |
| `demo_mode_active` | boolean | `true` when `DEMO_MODE=true` was active for the run |
| `synthesis_strategy` | string | Active synthesis backend: `"llm"` in production; `"raw"`, `"slm"`, or `"llm"` in dev mode; `"slm"` in demo mode |
| `tts_strategy` | string | Active TTS engine: `"google"` or `"pyttsx3"` in production; reflects `DEV_TTS_PLAYBACK` or `DEMO_TTS` otherwise |

**Demo path:** When the demo path is active, the response always returns `demo_mode_active: true` and `dev_mode_active: true` regardless of the `DEV_MODE` flag value.

**Note:** the trigger response is returned while TTS audio is still playing on a background thread. Use `GET /api/v1/status` to track `is_speaking` state after the trigger resolves.

**Response `403`** — scanner gate failed (wrong network, no AC power, or inside the 1-hour cooldown)
```json
{ "detail": "System gate failed: scanner.should_run() is False." }
```

---

### `GET /api/v1/status`

Diagnostic snapshot of the active pipeline run. Readable only while a trigger is running or TTS audio is playing.

**Response `200`** — `PipelineStatusSnapshot`
```json
{
  "step": 2,
  "label": "COLLECTION",
  "timestamp": "2026-06-06T12:34:56.789012+00:00",
  "is_speaking": false
}
```

| Field | Type | Description |
|---|---|---|
| `step` | integer | Pipeline step 1–4: Gate, Collection, Synthesis, Delivery |
| `label` | string | Short stage label: `GATE`, `COLLECTION`, `SYNTHESIS`, `DELIVERY` |
| `timestamp` | string | UTC ISO-8601 timestamp of the last stage update |
| `is_speaking` | boolean | `true` when `_SPEAK_LOCK` is held or `pygame.mixer.music.get_busy()` is active |

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

---

## Pydantic Models

### `BriefingResponse`

```python
class BriefingResponse(BaseModel):
    status: str                   # Run outcome label ("success")
    briefing: str                 # Synthesized briefing text
    telemetry: TelemetryPayload   # Per-module raw telemetry
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

Each field contains the raw string produced by the corresponding connector, or an empty string when the connector is disabled.

### `RuntimeMetadata`

```python
class RuntimeMetadata(BaseModel):
    dev_mode_active: bool
    demo_mode_active: bool
    synthesis_strategy: str   # "raw" | "slm" | "llm"
    tts_strategy: str         # "pyttsx3" | "google" | "elevenlabs"
```

### `PipelineStatusSnapshot`

```python
class PipelineStatusSnapshot(BaseModel):
    step: int
    label: str
    timestamp: str    # UTC ISO-8601
    is_speaking: bool
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
| `DEV_MODE` | `false` | Bypasses scanner gate and run logging; Gmail/Calendar connectors still make live requests with content masked to `[HIDDEN]`; Gemini bypass depends on `DEV_AI_SYNTHESIS` |
| `DEMO_MODE` | `false` | Intercepts trigger; serves static mock telemetry |
| `ENABLE_STARTUP_GATE` | `true` | When `false`, skips Wi-Fi/power/cooldown while keeping live APIs |
| `DEV_AI_SYNTHESIS` | `raw` | Synthesis path when `DEV_MODE=true`: `raw`, `slm` (placeholder), `llm` |
| `DEV_TTS_PLAYBACK` | `pyttsx3` | TTS engine when `DEV_MODE=true`: `pyttsx3`, `google`, `elevenlabs` (placeholder) |
| `DEMO_TTS` | `pyttsx3` | TTS engine when `DEMO_MODE=true`: `pyttsx3`, `google` |
| `APEX_ALLOWED_ORIGINS` | _(see below)_ | Comma-separated CORS origins; replaces defaults entirely when set |

**Default CORS origins** (when `APEX_ALLOWED_ORIGINS` is unset):
```
http://127.0.0.1:8000
http://localhost:8000
http://127.0.0.1:5500
http://localhost:5500
```

A custom value replaces these defaults rather than extending them. If you serve the HUD from a different port, set `APEX_ALLOWED_ORIGINS` to include all required origins.
