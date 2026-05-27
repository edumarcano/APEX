# APEX Changelog

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
