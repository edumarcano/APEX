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
│   │   ├── useApexData.ts           # Central data hook: trigger, polling, telemetry, reminder state
│   │   └── useSystemDiagnostics.ts  # 1,000 ms diagnostics poller
│   ├── types/
│   │   └── telemetry.ts             # TelemetryPayload, ApexDataState, PipelineState, DigestPayload,
│   │                                #   SystemDiagnostics, AtmosphericTheme, WeatherConditionArchetype
│   ├── context/
│   │   └── AtmosphericThemeContext.tsx  # React context weather theme provider
│   ├── components/
│   │   ├── ApexLogo.tsx             # State-driven SVG reactor: segment activation by pipeline step
│   │   ├── BriefingDigest.tsx       # Insight bullets panel with history ledger modal
│   │   ├── BriefingPanel.tsx        # Briefing text with curtain-reveal and speaking border mask
│   │   ├── CelestialBackground.tsx  # Seeded starfield — 80 stars across three twinkling tiers
│   │   ├── ConfidenceBadge.tsx      # Header confidence score badge with connector tooltip
│   │   ├── TelemetryCard.tsx        # Shared card frame, VTE interpolation, F1 renderer, weather glow
│   │   ├── SystemDiagnostics.tsx    # Three-gauge CPU/RAM/disk grid with severity glow
│   │   ├── RingGauge.tsx            # Stateless SVG circular gauge with arc and N/A fallback
│   │   ├── VocalOrb.tsx             # SVG speaking-state indicator
│   │   ├── ReminderTerminal.tsx     # Reminder input dock (POST /api/v1/reminders)
│   │   └── ReminderListRow.tsx      # Per-item reminder display with optimistic dismissal
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

The single data hook for the entire HUD. Fires `POST /api/v1/trigger` on mount, polls `GET /api/v1/status` at 500 ms intervals, and fetches `GET /api/v1/reminders` after trigger resolution. Exposes the full `ApexDataState` plus `refreshReminders` and `markReminderAsRead`.

### `useSystemDiagnostics`

Polls `GET /api/v1/diagnostics` every 1,000 ms. Returns `{ diagnostics, status }`. Independent of pipeline state.

---

## Environment Notes

- The HUD does not read `.env` directly. All configuration reaches the frontend through the API response (`metadata`, `digest` fields) or through the CORS policy set on the backend.
- `DEMO_MODE=true` on the backend causes the trigger response to include `metadata.demo_mode_active: true`, which `App.tsx` uses to render the amber "DEMO MODE ACTIVE" header badge.
