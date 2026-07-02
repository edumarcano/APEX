# APEX Frontend

React/TypeScript HUD served by Vite. Communicates with the FastAPI backend at `http://127.0.0.1:8000`.

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

```
frontend/
├── src/
│   ├── hooks/
│   │   ├── useApexData.ts           # Central data hook: trigger, polling, telemetry, reminder state, boot config fetch
│   │   ├── useSystemDiagnostics.ts  # 1,000 ms diagnostics poller
│   │   └── useApexAssistant.ts      # Ask APEX / assistant drawer state: query submission, history, tool trace
│   ├── types/
│   │   └── telemetry.ts             # TelemetryPayload, ApexDataState, PipelineState, DigestPayload,
│   │                                #   SystemDiagnostics, AtmosphericTheme, WeatherConditionArchetype
│   ├── components/
│   │   ├── ApexLogo.tsx             # State-driven SVG reactor: segment activation by pipeline step
│   │   ├── CommandTrigger.tsx       # Status-driven synthesis trigger button (idle / loading states)
│   │   ├── BriefingDigest.tsx       # Insight bullets panel with history ledger modal
│   │   ├── BriefingPanel.tsx        # Briefing text with curtain-reveal and speaking border mask
│   │   ├── CelestialBackground.tsx  # Seeded starfield — 80 stars across three twinkling tiers
│   │   ├── TelemetryCard.tsx        # Shared card frame, VTE interpolation, F1 renderer, weather glow
│   │   ├── SystemDiagnostics.tsx    # Six-column status footer: internet, briefing state, sync health, hardware resources, system time
│   │   ├── VocalOrb.tsx             # SVG speaking-state indicator
│   │   ├── ReminderTerminal.tsx     # Reminder input dock (POST /api/v1/reminders)
│   │   ├── ReminderListRow.tsx      # Per-item reminder display with optimistic dismissal
│   │   ├── AskApexBar.tsx           # Inline Ask APEX query input, prompt chips, profile selector
│   │   ├── AssistantDrawer.tsx      # Slide-out assistant drawer: message history, tool trace, follow-up input
│   │   └── CloudProfileSelector.tsx # Comet/Nova/Pulsar profile dropdown
│   ├── App.tsx      # Root layout: three-column bento grid, nebula glow, demo badge
│   └── main.tsx     # Vite entry point
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── tsconfig.json
```

---

## API Base URL

The API base URL is hardcoded to `http://127.0.0.1:8000` in `src/hooks/useApexData.ts`. This matches the uvicorn bind address set in `core/api.py` and `launcher.py`. Change both if you serve the backend on a different port, and update `APEX_ALLOWED_ORIGINS` in `.env` accordingly.

---

## Key Hooks

### `useApexData`

The single data hook for the entire HUD. Starts in `idle` state on mount and fetches `GET /api/v1/reminders` to populate the standby reminder list. The trigger is not fired automatically. When `triggerSynthesis()` is called, it fires `POST /api/v1/trigger`, polls `GET /api/v1/status` at 500 ms intervals until the pipeline completes, then parses and stores telemetry and digest fields. Exposes the full `ApexDataState` plus `triggerSynthesis`, `refreshReminders`, and `markReminderAsRead`.

### `useSystemDiagnostics`

Polls `GET /api/v1/diagnostics` every 1,000 ms. Returns `{ diagnostics, status }`. Independent of pipeline state.

### `useApexAssistant`

State for the Ask APEX bar and assistant drawer. `queryAssistant(prompt, profile)` posts to `POST /api/v1/agent/query` with the prompt, selected profile, and the full accumulated `assistantHistory` array, then appends the resulting user/model message pair to local state on success. There is no server-side session — this hook is the sole owner of conversation history for the tab's lifetime. Exposes `assistantHistory`, `isAssistantQuerying`, `isAssistantOpen`, `assistantLatestTrace` (the most recent turn's tool executions), `assistantError`, `queryAssistant`, `resetAssistantSession` (clears history and closes the drawer), and `setAssistantOpen`.

---

## Environment Notes

- The HUD does not read `.env` directly. All configuration reaches the frontend through the API response (`metadata`, `digest` fields), a dedicated `GET /api/v1/config` fetch made once on boot (populates `askApexEnabled` and `defaultProfile`), or through the CORS policy set on the backend.
- `DEMO_MODE=true` on the backend causes the trigger response to include `metadata.demo_mode_active: true`, which `App.tsx` uses to render the amber "DEMO MODE ACTIVE" header badge. The same flag also switches `POST /api/v1/agent/query` to a deterministic keyword-matched response with no live Gemini call.
