# APEX Changelog

---

## v1.4.0 — Developer Experience & Local Sandbox Recalibration

**Released:** May 28, 2026

This release consolidates the developer-mode control surface, hardens the speech pipeline, removes the Inworld AI TTS integration, and adds typed API response models. Three commits were merged, touching the configuration layer, the speaker subsystem, both data clients, and the API contract.

---

### What's New

#### Unified Developer Mode (`DEV_MODE`)

The previous `TEST_MODE` and `SHOWCASE_MODE` environment flags were removed and replaced with a single `DEV_MODE` flag.

- `core/config.py` gained `_parse_env_bool()`, which normalizes `"true"/"1"/"yes"` and `"false"/"0"/"no"` strings with bounded retry logic and a logged fallback for unrecognized values.
- `is_dev_mode()` was added as the canonical helper; all inline `os.getenv("TEST_MODE")` and `os.getenv("SHOWCASE_MODE")` reads across `api.py`, `brain.py`, and `scanner.py` were replaced with calls to it.
- A new `ENABLE_STARTUP_GATE` constant was added to `config.py`, defaulting to `True` when absent. Hardware and cooldown enforcement in `scanner.py` was extracted into `_enforce_production_gate()`. `should_run()` now branches on `DEV_MODE` first, then on `ENABLE_STARTUP_GATE`, before calling the gate.
- `database.mark_reminders_read()` in `api.py` is guarded behind `not dev_mode`; a diagnostic log line is emitted when the write is skipped.
- `.env.example` and `README.md` were updated to document `DEV_MODE` and `ENABLE_STARTUP_GATE`, including a revised environment modes table with a new `Marks Reminders Read` column.

#### Dev-Mode Routing Flags (`DEV_AI_SYNTHESIS`, `DEV_TTS_PLAYBACK`)

Two new environment flags give fine-grained control over the AI synthesis and TTS paths when `DEV_MODE` is active.

- `DEV_AI_SYNTHESIS` accepts `raw`, `slm`, or `llm`. `core/brain.py` branches on this value when `DEV_MODE` is active; `slm` and `llm` fall through or log accordingly. `raw` bypasses the model entirely.
- `DEV_TTS_PLAYBACK` controls which TTS path runs in dev mode. The Inworld AI branch in `core/speaker.py` was replaced with a `DEV_TTS_PLAYBACK`-keyed routing block.
- Both flags are validated against typed allowsets in `config.py` with normalization and logged fallbacks.

#### PII Masking in Data Clients

Gmail and Calendar dev-mode bypasses were moved out of `core/api.py` and into their respective client modules.

- `clients/gmail_client.py` and `clients/calendar_client.py` now mask personally identifiable information with `[HIDDEN]` sentinels on success when `DEV_MODE` is active.
- Both clients return an offline sentinel string on exception in dev mode, preventing live credential use during local testing.

#### Typed API Response Models

The `/api/v1/trigger` response is now backed by Pydantic models.

- `TelemetryPayload`, `RuntimeMetadata`, and `BriefingResponse` were added to `core/api.py`.
- The `metadata` field was added to the trigger response, carrying `dev_mode_active`, `synthesis_strategy`, and `tts_strategy` at runtime.

---

### Refactors

#### Speaker Subsystem: Pre-Warmed Singletons and Thread Safety

The `core/speaker.py` module was restructured to eliminate per-call initialization overhead and prevent concurrent invocation races.

- `_warm_cloud_clients()` instantiates a `TextToSpeechClient` singleton at import time. When credentials are absent, it logs a skip message instead of raising.
- `_warm_system_subsystems()` initializes `pygame.mixer` once at import time and holds the channel open across all playback calls.
- Per-call `pygame.mixer.init()` and `pygame.mixer.quit()` were removed from `_play_audio_bytes()`; a `get_init()` guard was added in their place.
- `fetch_google_audio()` uses the pre-warmed singleton and raises `RuntimeError` when it is `None`.
- A module-level `threading.Lock` was added; the `speak()` body is wrapped to serialize concurrent invocations.
- `initialize_engine()` was merged into `_speak_pyttsx3_local()` with exception handling around the engine lifecycle.
- Inworld AI integration (`fetch_inworld_audio`, `_HTTP_SESSION`, `requests` imports) was removed entirely. `config.json` was updated to set `primary_tts` to `"google"` and `inworld_voice_id` was removed.

---

### Files Changed

| Area | Files |
|---|---|
| Backend Config | `core/config.py` |
| Backend Logic | `core/api.py`, `core/brain.py`, `core/scanner.py`, `core/speaker.py` |
| Data Clients | `clients/gmail_client.py`, `clients/calendar_client.py` |
| Config & Env | `config.json`, `.env.example` |
| Docs | `README.md` |

---

### Summary Stats

- **3 commits** merged into `v1.4.0`
- **~593 lines added**, **~336 lines removed** across 10 files
- **1 unified dev flag** replacing two legacy flags (`TEST_MODE`, `SHOWCASE_MODE`)
- **2 new routing flags** (`DEV_AI_SYNTHESIS`, `DEV_TTS_PLAYBACK`)
- **3 new Pydantic response models** (`TelemetryPayload`, `RuntimeMetadata`, `BriefingResponse`)
- **1 external TTS integration removed** (Inworld AI)

---

## v1.3.0 — HUD-Renaissance: DATA AS GEOMETRY

**Released:** May 27, 2026

This release completes the visual and data layer of the APEX HUD. Three parallel feature tracks were merged: a live system health monitor with custom SVG gauges, a weather-responsive theme and typographic engine, and a full Formula 1 race schedule pipeline with caching. The dashboard grid was restructured to accommodate all six telemetry card slots at responsive breakpoints.

---

### What's New

#### Formula 1 Race Schedule Pipeline

The APEX HUD now tracks the upcoming F1 race weekend in real time.

- The `sports_client.py` module was rewritten with a full data engine that fetches race schedule data from the Ergast API and normalizes it into a structured `F1_DATA:` JSON payload.
- A 24-hour file-backed cache (`clients/.f1_cache.json`) was added to prevent redundant API calls. On failure, the system falls back to the last known good data.
- UTC-to-Eastern datetime conversion and relative week label helpers were added to the data pipeline.
- `TelemetryCard.tsx` received a `rawScheduleText` prop and a built-in F1 schedule renderer. A balanced JSON extractor parses the `F1_DATA:` prefix out of the raw text stream without requiring a separate API response format.
- A `COUNTRY_FLAG_MAP` of ISO-2 country codes resolves host nation flags from the CDN. Unrecognized countries fall back to a checkered flag.
- Sprint race detection is included: when `sprintScheduled` is true, a labeled badge renders alongside the main race entry.
- `MODULE_F1` and `MODULE_FOOTBALL` feature flags were added to `config.json` and loaded via `core/config.py`.

#### Real-Time System Diagnostics

CPU, RAM, and disk usage are now visible in the HUD at a one-second polling interval.

- `core/scanner.py` gained a `sample_system_vitals()` function using `psutil`, with per-metric error fallback so a single hardware read failure does not crash the response.
- A `GET /api/v1/diagnostics` endpoint was registered in `core/api.py`.
- A `useSystemDiagnostics` React hook polls the diagnostics endpoint every 1,000ms and exposes typed state.
- A `RingGauge` SVG component renders a clamped arc for each metric. At 0% the arc is suppressed; above 100% it is clamped. An N/A fallback state renders when data is unavailable.
- A `SystemDiagnostics` component assembles the three-gauge grid (CPU / RAM / Disk) and is mounted in `App.tsx` inside a full-width `TelemetryCard` slot.
- `SystemDiagnostics` and `DEFAULT_SYSTEM_DIAGNOSTICS` types were added to `frontend/src/types/telemetry.ts`.

#### Responsive Weather Themes and Variable Typography Engine (VTE)

The HUD now responds visually to live weather conditions.

- `AtmosphericThemeContext.tsx` was extended to derive CSS custom properties (`--hud-bg`, `--hud-accent`, `--hud-border-color`, etc.) from the live weather report. Screen colors shift to match current atmospheric conditions.
- The **Variable Typography Engine** was introduced in `TelemetryCard.tsx`. The primary temperature readout's font weight is linearly interpolated between `font-weight: 300` (cold, 40°F) and `font-weight: 800` (hot, 90°F) using `resolveTemperatureFontWeight()`. Boundary clamping prevents out-of-range values.
- The `weatherDetail` field was separated from `weather` in the data layer (`useApexData.ts`, `telemetry.ts`) to prevent layout duplication when weather summary sentences were split into independent display fields.
- `AtmosphericThemeProvider` was moved from `main.tsx` into `App.tsx` and now receives `data.weather` as a direct prop, eliminating a duplicate `useApexData` call.

---

### Architecture Changes

#### HUD Layout Restructure

- The dashboard grid was updated from `md:grid-cols-2` to `md:grid-cols-2 xl:grid-cols-3` to support the six-card layout.
- `BriefingPanel` was refactored to accept `status`, `error`, and `isLoading` as explicit props, with isolated render branches for each system state (idle, loading, error, success).
- Pipeline polling state (`pipelineState`, `isPipelinePolling`) was lifted from `DiagnosticProgress` into `useApexData`, making it available to the full application.
- `DiagnosticProgress` was slimmed down and now receives its state as props from `App.tsx`.

#### Backend Stability

- A `CoInitialize` COM guard was added to `core/speaker.py` to prevent `pyttsx3` crashes on Windows when the speech engine is initialized outside the main thread.

---

### Files Changed

| Area | Files |
|---|---|
| Backend | `core/api.py`, `core/scanner.py`, `core/speaker.py`, `core/config.py`, `config.json` |
| Data Clients | `clients/sports_client.py` |
| Frontend Components | `TelemetryCard.tsx`, `BriefingPanel.tsx`, `DiagnosticProgress.tsx`, `RingGauge.tsx` (new), `SystemDiagnostics.tsx` (new) |
| Frontend Hooks | `useApexData.ts`, `useSystemDiagnostics.ts` (new) |
| Frontend Context | `AtmosphericThemeContext.tsx` |
| Frontend Types | `telemetry.ts` |
| App Shell | `App.tsx`, `main.tsx` |
| Config | `frontend/tsconfig.app.json`, `frontend/vite.config.ts` |
| Repo | `.gitignore`, `README.md` |

---

### Summary Stats

- **3 commits** merged into `v1.3.0`
- **+1,702 lines added**, **~233 lines removed** across 17 files
- **2 new React components** (`RingGauge`, `SystemDiagnostics`)
- **1 new React hook** (`useSystemDiagnostics`)
- **1 new API endpoint** (`GET /api/v1/diagnostics`)
- **1 new backend function** (`sample_system_vitals`)

---

## v1.2.0 and earlier

See git history for prior release notes.
