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
npm run check:loading
```

- `npm ci` installs the exact `package-lock.json` graph.
- `npm run dev` starts the Vite hot-reload server.
- `npm test` runs Vitest and the production loading-check tests once.
- `npm run lint` runs ESLint with TypeScript-aware rules.
- `npm run build` runs the TypeScript build and writes the production HUD to `../dist/`.
- `npm run check:loading` checks that build's initial import graph and reports JavaScript byte totals. Run it after the build.

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

| Owner | Owns |
|---|---|
| `useApexData` | Boot settings and reminder data and actions |
| `useTelemetryCollectionState` | The `collectionStarted` app-session latch and its `startCollection`/`resetCollection` transitions, kept separate from whether usable telemetry data exists. |
| `usePreflight` | Preflight requests and warning or blocker dialog flow |
| `useTelemetrySnapshot` | Current telemetry snapshot, refresh state, and refresh actions |
| `useBriefingSessions` | Briefing profiles, generation, session status, selected session and evidence, and presentation state |
| `useBriefingSpeech` | Speech status and explicit preparation, playback, and stop actions for the selected completed session |
| `useWorkspaceView` | Resolving the selected Overview or Briefing presentation and owning the selected briefing profile |
| `useBriefingPresentation` | Marking a completed briefing as presented after it becomes visible |
| `useCompactLayout` | Shared compact-layout breakpoint |
| `useCortex` | APEX Agent status and catalog, cloud-model verification, and local-model lifecycle |
| `ApexAssistantRuntime` | Conversation and thread history, one-turn submission, streaming, tool traces, and outputs |
| `useCortexRuns` | Recent Cortex runs, active-run polling, selection, activity detail inspection, and cooperative cancellation |
| `useActions` | Cortex-visible action list, expanded audit detail, bounded polling, and versioned action controls |
| `useToolCatalog` | Agent catalog, selected-tool state, and profile application |
| `useToolPreflight` | Debounced estimated token breakdown for the next request |
| `useMarketData` | Cache-backed Market reads, reloaded when telemetry publishes a Market collection revision |
| `useSystemDiagnostics` | Independent host diagnostics polling |
| `useContextInspector` | Personal-context records and detail, retrieval status, entity lookup, direct saves, reconciliation proposals, and durable review decisions |
| `useContextVault` | Vault settings, selection preview, export status, refresh, and managed-copy removal |
| `useActivityReports` | Bounded external report list/detail, filters, dispositions, context proposals, and linked-review refresh |

`App.tsx` coordinates these owners but should not duplicate their internal state machines.

## Presentation loading

Launch and Overview load with the app shell. Settings loads on its first open; Cortex, Reports, and Briefing load when selected. These boundaries defer presentation code while `ApexAssistantRuntime` and the app-level state owners stay mounted. Navigating between workspaces or returning to Launch preserves conversation drafts, history, and active work. Existing workspace-local hooks keep their current mount lifecycle.

Loading and failure states stay within the requested presentation, leaving workspace navigation available. Settings supplies a focus-trapped dialog while its code loads and restores focus on close. Retry starts a fresh loading attempt without resetting the shared runtime. If an asset remains unavailable, explicit page reload is available; it discards unsent text.

The runtime's default assistant-message Markdown renderer loads separately. Its loading and failure fallback shows escaped plain text so the answer, composer, and activity remain usable. Cortex, Briefing, and Reports retain their own rendering rules inside their deferred presentations.

The production build writes a Vite manifest and a sanitized module report under `dist/.vite/`. `npm run check:loading` follows static imports and HTML module preloads, checks the deferred presentations and Markdown dependencies, and reports entry, initial, deferred, and total JavaScript sizes with per-asset gzip totals. Its optional `--baseline` argument accepts an absolute directory containing an earlier build and manifest. Compare builds made with the same lockfile and options; byte reductions alone do not measure browser startup time or first-use latency.

## API boundary

`src/lib/api.ts` centralizes the FastAPI base URL at `http://127.0.0.1:8000`. The HUD does not read `.env`, `config.json`, or `config.local.json` directly. Configuration and runtime state arrive through HTTP responses.

The browser owns presentation state such as the active view. `ApexAssistantRuntime` owns conversation and thread interaction, including submission and streaming, while FastAPI and SQLite provide the durable conversation history and other persisted application records. FastAPI also owns connectors, settings, telemetry collection, models, tools, context and action services, and speech. See the [API guide](../docs/api.md) for behavioral contracts.

## Frontend rules

- Preserve the Launch screen, explicit collection flow, development mode, and demo mode behavior.
- Keep independent flows usable when another path is degraded.
- Parse external JSON defensively before storing it in typed state.
- Preserve keyboard access, focus handling, semantic labels, and reduced-motion behavior.
- Use existing tokens and state semantics before adding new colors or material treatments.
- Add focused Vitest coverage for changed state transitions, request handling, or user interaction.

Visual changes must follow the [APEX Design System](../docs/design-system.md) and the repository's [frontend engineering guidance](../docs/agent-guidance/frontend.md).
