# APEX Frontend

The frontend is the React/TypeScript HUD served by Vite during development and from the compiled root `dist/` directory in normal launcher sessions. This guide covers frontend-local work; use the [system architecture](../docs/architecture.md) and [design system](../docs/design-system.md) for the broader contracts.

## Commands

Run these from `frontend/`:

```powershell
npm ci
npm run dev
npm test
npm run lint
npm run build
```

- `npm ci` installs the exact `package-lock.json` graph.
- `npm run dev` starts the Vite hot-reload server.
- `npm test` runs Vitest once.
- `npm run lint` runs ESLint with TypeScript-aware rules.
- `npm run build` runs the TypeScript build and writes the production HUD to `../dist/`.

Use `npm install` only when intentionally changing dependencies and updating the lockfile.

## Source map

```text
frontend/src/
├── App.tsx          # Root composition and cross-flow coordination
├── components/      # HUD panels, controls, console, cards, and weather visuals
├── hooks/           # Focused state owners and API workflows
├── lib/             # API constants and pure parsing/presentation helpers
├── types/           # Settings and telemetry contracts
├── test/            # Shared test setup and fixtures
├── index.css        # Tokens, material system, layout, and motion
└── main.tsx         # Vite entry point
```

## State ownership

Do not expand `useApexData` into another global store. Use the focused owner for each runtime path:

| Hook | Owns |
|---|---|
| `useApexData` | Boot configuration, reminders, and compatibility trigger state |
| `useAppActivation` | Standby/activated browser session |
| `usePreflight` | Warning and blocker interaction |
| `useTelemetrySnapshot` | Process-current telemetry snapshot and refresh |
| `useBriefingPipeline` | Briefing generation, status polling, digest, and transcript |
| `useVoiceDelivery` | Manual and automatic speech requests |
| `useCortex` | Browser-held conversation, Agent/catalog status, explicit tool-selection diagnostics, tool traces and outputs |
| `useToolCatalog` | Agent-specific catalog, session-persistent selection, and profile application |
| `useToolPreflight` | Debounced estimated token breakdown for the next request |
| `useMarketData` | Independent market polling with stale fallback |
| `useSystemDiagnostics` | Independent host diagnostics polling |

`App.tsx` coordinates these owners but should not duplicate their internal state machines.

## API boundary

`src/lib/api.ts` centralizes the FastAPI base URL at `http://127.0.0.1:8000`. The HUD does not read `.env`, `config.json`, or `config.local.json` directly. Configuration and runtime state arrive through HTTP responses.

The browser owns ephemeral UI state and assistant conversation history. FastAPI owns connectors, settings persistence, telemetry collection, models, tools, speech, and SQLite. See the [API guide](../docs/api.md) for behavioral contracts.

## Frontend rules

- Preserve standby, development, and demo behavior.
- Keep independent flows usable when another path is degraded.
- Parse external JSON defensively before storing it in typed state.
- Preserve keyboard access, focus handling, semantic labels, and reduced-motion behavior.
- Use existing tokens and state semantics before adding new colors or material treatments.
- Add focused Vitest coverage for changed state transitions, request handling, or user interaction.

Visual changes must follow the [APEX Design System](../docs/design-system.md) and the repository's [frontend engineering guidance](../docs/agent-guidance/frontend.md).
