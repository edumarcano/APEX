# APEX Changelog

---

## v1.5.0 — HUD-Renaissance: The Control Deck

**Released:** May 31, 2026

This release adds a full reminder management system to the HUD, covering API persistence, interactive input, per-item dismissal, and optimistic UI state. The launcher was hardened with a backend readiness gate that eliminates startup race conditions, and the orchestrator gained browser lifecycle awareness so closing the HUD window cleanly shuts down the backend.

---

### What's New

#### Reminder Management System

Active reminders are now a first-class data surface in the HUD, with full lifecycle support from creation through dismissal.

- `GET /api/v1/reminders` was added to `core/api.py`. It returns all unread reminders from the database as a typed `RemindersResponse` containing a list of `ReminderItem` objects (each carrying `id`, `text`, and `created_at`).
- `POST /api/v1/reminders` was added. It accepts a `ReminderCreateRequest` payload, runs the text through `clean_for_tts()` to strip markdown and non-ASCII characters, persists the result via `database.save_reminder()`, and returns a `ReminderCreateResponse` with the new row ID.
- `POST /api/v1/reminders/read` was added. It marks a single reminder as read by ID and returns a `RemindersReadResponse` confirming the operation.
- Auto-mark-read behavior was removed from the `POST /api/v1/trigger` briefing endpoint. Reminders are now only dismissed on explicit user action.
- `database.save_reminder()` was updated to return the inserted row ID instead of `None`.
- `activeReminders` was added to `ApexDataState` and `TelemetryPayload` as a structured list, making reminder state available to all HUD consumers through the unified `useApexData()` hook.

#### Reminder Terminal Input Component

A persistent, fixed-position input field was added to the HUD bottom edge for submitting new reminders without leaving the dashboard.

- `ReminderTerminal.tsx` implements a `POST /api/v1/reminders` form. On successful submission the input clears, a brief emerald glow pulses on the container border, and a `refreshReminders` callback re-syncs the list.
- A global keyboard shortcut registers a `/` keydown listener. Pressing `/` from anywhere on the dashboard focuses the input unless the user is already inside an editable field.
- Submitting while a previous request is in flight is blocked by an `isSubmitting` guard.
- The component is mounted in `App.tsx` as a floating overlay with `z-50` stacking, centered horizontally at the bottom of the viewport.

#### Reminder List Row Component

Individual reminder entries are now interactive, with per-item dismissal directly from the HUD.

- `ReminderListRow.tsx` renders each `ReminderItem` with its text and a dismiss button.
- `markReminderAsRead` in `useApexData.ts` performs optimistic removal: the item is removed from local state immediately, a `POST /api/v1/reminders/read` call is issued in the background, and the original state is restored on API failure.
- `refreshReminders` was added to `useApexData.ts` as a best-effort sync callback, called after new reminder submissions to ensure the list reflects the latest persisted state.
- The reminders string was removed from the schedule panel in `App.tsx`. The calendar section now renders calendar entries only; reminder data surfaces exclusively through the new reminder list.

---

### Fixes

#### Launcher Backend Readiness Gate

The `launcher.py` orchestrator previously used a hardcoded three-second delay before opening the browser. This caused intermittent `Failed to fetch` errors when the API had not finished binding its port.

- The fixed delay was removed from `main()`.
- A polling loop was added that issues `GET http://127.0.0.1:8000/` every 500ms for up to 30 attempts (15 seconds maximum). The browser opens immediately after the first `200` response.
- If all 30 attempts time out, a warning is printed and the browser opens regardless, preserving the original fallback behavior.
- `urllib.request` and `urllib.error` were added as imports to support the polling loop without additional dependencies.

---

### Refactors

#### Browser Window Lifecycle Binding

The orchestrator now treats the browser window as the authoritative signal for APEX shutdown.

- `main()` in `launcher.py` was updated to call `browser_proc.wait()` after the kiosk window opens. When the user closes the browser window, the orchestrator prints a shutdown message, terminates the `uvicorn` process, and exits cleanly.
- This behavior applies only when the browser was launched via `subprocess.Popen` (i.e., Chrome or Edge with `--app=`). The `webbrowser` fallback path retains the previous `Ctrl+C` loop behavior since a `Popen` handle is not available in that case.
- The `digest.txt` working file was added to `.gitignore`.

---

### Files Changed

| Area | Files |
|---|---|
| Backend API | `core/api.py` |
| Backend Database | `core/database.py` |
| Launcher Orchestrator | `launcher.py` |
| Frontend Components | `frontend/src/components/ReminderTerminal.tsx`, `frontend/src/components/ReminderListRow.tsx` |
| Frontend Data Hook | `frontend/src/hooks/useApexData.ts` |
| Frontend Types | `frontend/src/types/telemetry.ts` |
| Frontend Layout | `frontend/src/App.tsx` |
| Repo Config | `.gitignore` |
| Docs | `README.md` |

---

### Summary Stats

- **4 commits** merged into `v1.5.0`
- **~680 lines added**, **~160 lines removed** across 10 files
- **3 new API endpoints** (`GET /api/v1/reminders`, `POST /api/v1/reminders`, `POST /api/v1/reminders/read`)
- **2 new UI components** (`ReminderTerminal`, `ReminderListRow`)
- **1 startup race condition eliminated** (hardcoded delay replaced with polling readiness gate)
- **1 browser lifecycle binding** added (uvicorn exits on HUD window close)

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

## v1.2.0 — HUD-Renaissance: Pipeline State Visibility

**Released:** May 18, 2026

This release upgrades the APEX dashboard by transforming static loading screens into a real-time, interactive telemetry experience. The system now actively communicates its internal execution state, drastically improving user experience and perceived latency without triggering layout shifts.

### New Features

* **Live Progress Tracking:** Introduced a new `DiagnosticProgress` HUD component that polls the backend every 500ms during an active fetch.
  * Visualizes the 4 core pipeline phases (Gate → Collection → Synthesis → Delivery) via a dynamically lit horizontal step indicator.
* **Staggered Reactive Layouts:** * The dashboard layout now reacts to the live pipeline steps. Secondary modules (like Weather and Schedule) dim to 25% opacity when data is stale, and smoothly transition back to 100% visibility the exact moment their specific backend processing finishes.
* **Thread-Safe Telemetry Backend:** * Added a dedicated `PipelineState` class utilizing a `threading.Lock()` to ensure high-frequency frontend status polls do not interfere with the long-running worker loops.
  * Exposed a new `GET /api/v1/status` endpoint to serve secure, microsecond-latency state snapshots.

### Documentation

* Updated the project `README.md` to reflect the v1.2.0 architecture.
* Integrated a comprehensive Mermaid sequence diagram mapping the asynchronous polling flow, thread-locking, and automated 404 teardown sequences.

---

## v1.1.1 — AI Workforce Calibration Patch

**Released:** May 17, 2026

## What's Changed
- **Rule Configurations Updated:** Revised the operational profiles for the `analyst`, `auditor`, `builder`, `communicator`, and `mechanic` rules.
- **New Scopes Added:** Created directory-bound rules for the `frontend`, `backend`, and `devops` scopes.
- **Documentation Updated:** Modified `README.md` to map and display the new rules along with their targeted directory scopes.

---

## v1.1.0 — The Foundation (React/TypeScript Migration)

**Released:** May 17, 2026

This release replaces the original web interface with a modern dashboard built using React, TypeScript, Vite, and Tailwind CSS.

### Key Enhancements

* **Responsive Layout:** Built a grid interface that automatically adjusts to look great on different screen sizes.
* **Centralized Data Fetching:** Added a single data hook (`useApexData`) to handle all backend requests and manage the loading state in one place instead of using multiple loading places.
* **Text Streaming Panel:** Created a component that displays incoming text updates from the server with a smooth character-by-character text animation.
* **Project Cleanup:** Removed all old web files and renamed the development folder to keep the repository structure organized.
* **Configuration Sync:** Updated paths across configuration files, development rules, and `.gitignore` to match the new directory layout.

### Tech Stack Summary
* **Tools:** React, TypeScript, Vite, Tailwind CSS
* **Structure:** Source code is located in `/frontend` and builds production output to `/dist`

---

## v1.0.0 — The Core Foundation

**Released:** May 15, 2026

APEX is a Python-based personal HUD and automated briefing system — a real-world 
analog to sci-fi AI assistants. It evaluates its environment, pulls live telemetry 
from multiple sources, synthesizes everything through Gemini 2.5 Flash, and 
delivers a spoken audio briefing through a local web dashboard on demand.

### Core Capabilities

**AI-Synthesized Briefings:** Raw telemetry is synthesized into a concise, 
persona-driven audio briefing. The voice, tone, and identity are fully 
configurable via `config.json` without touching core logic.

**Context-Aware Gating:** Before anything runs, the system checks home Wi-Fi 
by SSID, AC power connection, and a 1-hour cooldown to protect API quotas.

**Live Data Connectors:** Modular extractors pull real-time data from OpenWeatherMap 
(local conditions), F1 schedules via Ergast/Jolpica, FC Barcelona fixtures via 
football-data.org, GNews for AI and Global Events headlines, Google Workspace 
(unread Primary Gmail and a 48-hour Calendar window via OAuth2), and a local 
SQLite database for persistent reminders.

**Resilient Audio Engine:** TTS runs a fallback chain — Google Cloud TTS → 
Inworld AI → pyttsx3 offline. Audio is played directly from memory via pygame, 
no temp files written to disk.

### Architecture

**FastAPI Backend:** All gating, extraction, and synthesis logic runs as an 
isolated REST API on `127.0.0.1:8000`.

**Web HUD:** A plain HTML/CSS/JS frontend with no framework or build step, 
using CSS Grid for a responsive bento-grid dashboard.

**Launcher Orchestrator:** `launcher.py` starts the backend and static file 
server as parallel child processes and opens the HUD in a kiosk browser window 
automatically. `launch_apex.bat` wraps this for one-click Windows startup.

### Configuration

`config.json` controls feature flags, TTS settings, and the persona prompt. 
`.env` holds secrets, kept strictly separate from preferences. Each data 
connector can be toggled independently, and safe defaults apply if `config.json` 
is missing or malformed.

### Environment Modes

| Mode | Wi-Fi + Power | Cooldown | Gemini | Gmail + Calendar |
|------|--------------|----------|--------|-----------------|
| Production | ✅ | ✅ | ✅ | ✅ |
| `TEST_MODE` | ✅ | ⬜ | ⬜ | ⬜ |
| `SHOWCASE_MODE` | ⬜ | ⬜ | ✅ | ⬜ |

---

## Pre-v1.0.0

- Check commit history between April 27 and May 15, 2026 for more detailed alpha development information.