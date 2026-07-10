# APEX Frontend

React/TypeScript HUD served by Vite. Communicates with the FastAPI backend at `http://127.0.0.1:8000`.

The header synthesis pill reports the engine used for the current briefing. A shared rust-orange control beneath the logo reports Ollama loading, residency, auto-unload countdown, and manual unload state for both briefing synthesis and assistant queries.

---

## Stack

| Layer | Technology |
|---|---|
| Framework | React 19 + TypeScript |
| Build | Vite |
| Styling | Tailwind CSS |
| Icons | lucide-react |
| Linting | ESLint with TypeScript-aware rules |

---

## Development

```bash
npm install
npm run dev       # starts Vite dev server (hot reload)
npm run build     # compiles to dist/ for production serving
npm run lint      # runs ESLint
```

The dev server is for local development only. The production path served by `launcher.py` uses the compiled `dist/` directory via `python -m http.server 5500`.

---

## Project Structure

```text
frontend/
|-- src/
|   |-- hooks/
|   |   |-- useApexData.ts           # Central data hook: trigger, polling, telemetry, reminder state, boot config fetch
|   |   |-- useSystemDiagnostics.ts  # 1,000 ms diagnostics poller
|   |   |-- useApexAssistant.ts      # Console assistant state: query submission, history, tool trace
|   |   `-- useMarketData.ts         # 30 s market poller with stale-fallback on fetch failure
|   |-- types/
|   |   `-- telemetry.ts             # TelemetryPayload, ApexDataState, PipelineState, DigestPayload, SystemDiagnostics
|   |-- lib/
|   |   |-- api.ts                   # Shared local API endpoint constants
|   |   |-- attentionTier.ts         # Pipeline-driven attention-tier reveal schedule and resolvers
|   |   `-- promptChips.ts           # Shared assistant prompt chip definitions
|   |-- components/
|   |   |-- ApexLogo.tsx             # State-driven SVG reactor: segment activation by pipeline step
|   |   |-- CommandTrigger.tsx       # Synthesis trigger button (hover/focus label states)
|   |   |-- BriefingDigest.tsx       # Insight bullets panel with history ledger modal
|   |   |-- CelestialBackground.tsx  # Seeded starfield across three twinkling tiers
|   |   |-- TelemetryCard.tsx        # Shared card frame, VTE interpolation, F1 renderer, weather icons, attention tier
|   |   |-- MarketTickerCard.tsx     # End-of-day market ticker card and compact row
|   |   |-- SystemDiagnostics.tsx    # Header diagnostics, sync health, hardware resources, system time
|   |   |-- VoiceSignalGlyph.tsx     # Centered pipeline status, thinking, and speech indicator
|   |   |-- ReminderListRow.tsx      # Per-item reminder display with optimistic dismissal
|   |   |-- AskApexBar.tsx           # Inline assistant query input and profile selector
|   |   |-- ConsoleTray.tsx          # Bottom/rail console with assistant and reminders tabs
|   |   |-- AssistantToolCards.tsx   # Structured per-tool result cards for whitelisted tool_outputs
|   |   |-- CloudProfileSelector.tsx # Cloud/local assistant profile dropdown with live availability gating
|   |   `-- weather/                 # Per-condition animated SVG icons (ClearDay, ClearNight, Clouds, Rain, Thunderstorm)
|   |-- App.tsx                      # Root layout: three-column HUD, nebula glow, console placement
|   `-- main.tsx                     # Vite entry point
|-- index.html
|-- package.json
|-- vite.config.ts
|-- tailwind.config.js
`-- tsconfig.json
```

---

## API Base URL

The API base URL is centralized in `src/lib/api.ts` as `http://127.0.0.1:8000`. This matches the uvicorn bind address set in `core/api.py` and `launcher.py`. Change both if you serve the backend on a different port, and update `APEX_ALLOWED_ORIGINS` in `.env` accordingly.

---

## Key Hooks

### `useApexData`

The single data hook for the entire HUD. Starts in `idle` state on mount and fetches `GET /api/v1/reminders` to populate the standby reminder list. The trigger is not fired automatically. When `triggerSynthesis()` is called, it fires `POST /api/v1/trigger`, polls `GET /api/v1/status` at 500 ms intervals until the pipeline completes, then parses and stores telemetry and digest fields. Exposes the full `ApexDataState` plus `triggerSynthesis`, `refreshReminders`, and `markReminderAsRead`.

### `useSystemDiagnostics`

Polls `GET /api/v1/diagnostics` every 1,000 ms. Returns `{ diagnostics, status }`. Independent of pipeline state.

### `useMarketData`

Polls `GET /api/v1/market` every 30,000 ms. Returns `{ data, isLoading }`. Independent of pipeline state. On a failed poll, a non-2xx response, or an unparseable body, the hook downgrades the previously held snapshot to a stale state (`toStaleFallback()`) instead of clearing it, so a transient failure degrades the ticker's freshness indicator rather than blanking it.

### `useApexAssistant`

State for the assistant console. `queryAssistant(prompt, profile)` posts to `POST /api/v1/agent/query` with the prompt, selected profile, and the full accumulated `assistantHistory` array, then appends the resulting user/model message pair to local state on success. There is no server-side session; this hook is the sole owner of conversation history for the tab's lifetime.

The hook also self-schedules a poll of `GET /api/v1/agent/profiles` every 4 seconds while the console is open or profile polling is otherwise enabled, dropping to a 1-second cadence while a query is in flight so the HUD can observe local-model loading transitions in near real time, and skipped while the tab is hidden. It keeps cloud/local profile availability, active-model, loading, and idle-unload-countdown state current. `unloadLocalModel()` posts to `POST /api/v1/agent/local/unload` and re-syncs profile status afterward.

Exposes `assistantHistory`, `isAssistantQuerying`, `isAssistantOpen`, `assistantLatestTrace` (the most recent turn's tool executions), `assistantError`, `profilesStatus` / `profilesStatusHydrated` (the polled profile availability matrix), `queryAssistant`, `unloadLocalModel`, `clearAssistantChat` (clears history and tool trace but leaves the console open), `resetAssistantSession` (clears history and closes the console), and `setAssistantOpen`.

---

## Environment Notes

- The HUD does not read `.env` or `config.json` directly. All configuration reaches the frontend through the API response (`metadata`, `digest` fields), a dedicated `GET /api/v1/config` fetch made once on boot (populates `askApexEnabled` and `defaultProfile`), the polled `GET /api/v1/agent/profiles` response (cloud/local profile availability, active local model, idle-unload countdown), the independently polled `GET /api/v1/market` response (`useMarketData`, 30 s cadence, no pipeline or config dependency), or through the CORS policy set on the backend.
- `DEMO_MODE=true` on the backend causes the trigger response to include `metadata.demo_mode_active: true`, which `App.tsx` uses to render the amber "DEMO MODE ACTIVE" header badge. The same flag also switches `POST /api/v1/agent/query` to a deterministic keyword-matched response with no live Gemini or Ollama call, and switches `GET /api/v1/market` to a simulated ticker feed.
