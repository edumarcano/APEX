# APEX Frontend

The React/TypeScript interface runs through Vite during development and from the repository's compiled `dist/` directory in launcher sessions. This guide covers local development, state ownership, and presentation loading. Use [Architecture](../docs/architecture.md) for backend boundaries and the [Design System](../docs/design-system.md) for visual and interaction rules.

## Local development

Complete the dependency and environment setup in [Getting Started](../docs/getting-started.md) first. The Vite server serves the interface; FastAPI must run separately for application requests.

Start the API from the repository root:

```powershell
uv run python -m uvicorn core.api:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal, run these from `frontend/`:

```powershell
npm ci
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`. The API accepts the standard localhost and loopback origins on port 5173. If that port is occupied, free it before starting Vite so the frontend stays on an allowed origin.

`npm ci` installs the locked dependency graph. Use `npm install` when intentionally changing dependencies and updating the lockfile. Vite reloads frontend edits; backend development reload is handled by the API process.

## Validation and production build

Run these from `frontend/`:

```powershell
npm test
npm run lint
npm run build
npm run check:loading
```

| Command | Purpose |
|---|---|
| `npm test` | Run Vitest and the loading-check script's tests once |
| `npm run lint` | Run ESLint's TypeScript and React rules |
| `npm run build` | Check TypeScript and write the production build to `../dist/` |
| `npm run check:loading` | Verify the built import graph and report JavaScript sizes |

The loading check requires a completed build. For repeated frontend tests during development, use `npm run test:watch`. The [manual server instructions](../docs/getting-started.md#run-the-servers-manually) explain how to serve the compiled build, and the launcher serves it on port 5500.

## Windows desktop shell

The Windows Tauri shell uses the same React interface and the locally supervised FastAPI backend. Its development toolchain adds native prerequisites beyond the Python and Node setup in [Getting Started](../docs/getting-started.md):

- Install Rust stable with the `x86_64-pc-windows-msvc` target.
- Install Visual Studio 2022 Build Tools with the **Desktop development with C++** workload and a Windows SDK.
- Use Node.js 24 and npm for the frontend build.
- Build and smoke-check the frozen backend bundle using the canonical [Windows backend bundle build steps](../docs/backend-bundle.md#build). The desktop shell requires this verified bundle; it does not build the Python backend itself.

After building the verified backend bundle, run these commands from `frontend/` to stage it and start the Tauri development window:

```powershell
npm ci
npm run desktop:dev
```

`desktop:prepare` checks the bundle manifest, build identity, and file hashes before staging it under `src-tauri/resources/backend-bundle`. `desktop:dev` runs that preparation step and starts Tauri. Tauri starts Vite on `127.0.0.1:5173` with a strict port so its native origin stays predictable. `npm run dev` remains the ordinary browser workflow and still mounts the interface immediately; the browser does not load the native adapter.

To build from a different verified backend bundle, pass its absolute path to both commands so preparation and assembly use the same source:

```powershell
npm run desktop:prepare -- --bundle "C:\path\to\backend-bundle"
npm run desktop:build -- --bundle "C:\path\to\backend-bundle"
```

`desktop:build` re-verifies and stages the bundle, then invokes the locked Tauri CLI; its build hook compiles the production frontend. The command assembles a runnable folder at `build/desktop-shell/APEX/` containing `APEX.exe` and `backend-bundle/`. It does not create an installer. Installed Windows behavior still needs validation in the packaged-shell workflow.

In the native window, APEX waits for the owned backend and checks the fixed local runtime identity endpoint before mounting workspace API hooks. Startup, port/profile conflict, origin rejection, identity mismatch, and backend failure states provide retry or quit actions. Retrying asks first because restarting closes the current workspace and discards unsent text; drafts are not persisted.

In the packaged app, closing the window hides it to the tray while its backend remains available to the CLI. Tray **Show** restores the window and **Quit** shuts down the owned backend. A second app launch activates the existing window, and the shell restores saved geometry. Runtime Settings includes opt-in Windows startup and completion notifications. Startup launches hidden; OS integration failures are surfaced separately from the saved preferences. Completion notifications contain only generic text and are limited to successful committed runs while the app is hidden or minimized. Validate these installed Windows integrations with the packaged-app gate in [Backend Bundle](../docs/backend-bundle.md#build); browser development does not exercise OS tray, startup, or notification behavior.

Device location has a separate opt-in in Runtime Settings > Desktop and an explicit foreground permission check in each native app session. Its commands and event subscriptions stay behind `src/platform`; coordinate-free status reads use the loopback API. Weather labels distinguish device from configured results, including retained stale data. See [Device location configuration](../docs/configuration.md#device-location-for-weather) and the focused [Windows location smoke harness](../scripts/smoke_device_location.py) for validation against the actual OS state.

## Source organization

`App.tsx` composes the workspaces and coordinates shared flows. Components own presentation, hooks own focused state and API workflows, and `lib/` holds API endpoints and parsing or presentation helpers. Shared contracts live in `types/`; `test/` supplies test setup and fixtures. `index.css` defines tokens, materials, layout, and motion, while `main.tsx` starts the application.

## State ownership

Keep state with the owner that manages its lifecycle. `App.tsx` coordinates those owners without duplicating their state machines. `useApexData` handles boot configuration and reminders; it should not grow into a general application store.

| Area | Owners and responsibilities |
|---|---|
| Telemetry | `useTelemetryCollectionState` tracks whether collection has started in the app session. `useTelemetrySnapshot` owns snapshots and refresh requests; usable data is separate from the collection latch. `useMarketData` reloads cached Market data when a collection revision changes. |
| Conversations | `ApexAssistantRuntime` owns thread history, drafts, submission, streaming, tool traces, and outputs. It renders live and saved activity. `useCortexRuns` owns the recent run list, selection, polling, and cancellation. |
| Models and tools | `useCortex` owns Agent status, the model catalog, cloud verification, and local-model lifecycle requests. `useToolCatalog` owns tool selection and profile application; `useToolPreflight` estimates the next request's token use. |
| Briefings | `useBriefingSessions` owns profiles, generation, session selection, evidence, and presentation state. `useBriefingSpeech` owns preparation, playback, and stop requests. `useBriefingPresentation` acknowledges an artifact after it becomes visible. |
| Context and actions | `useContextInspector` owns record inspection and review workflows. `useActions` owns action lists, audit detail, polling, and versioned controls. `useContextVault` owns vault settings, preview, status, refresh, and copy removal. |
| Reports | `useActivityReports` owns report lists and details, filters, dispositions, context proposals, and linked-review refresh. |

Supporting hooks handle preflight dialogs, host diagnostics, and MCP status. `useWorkspaceView` resolves the Overview or Briefing presentation and owns the selected briefing profile; shared layout hooks handle presentation breakpoints.

App-level owners survive workspace navigation. Hooks mounted inside a workspace retain that workspace's mount lifecycle; deferring its code does not move its state into the shared runtime.

## Presentation loading

Launch and Overview load with the app shell. Settings loads on its first open; Cortex, Reports, and Briefing load when selected. These boundaries defer presentation code while `ApexAssistantRuntime` and app-level state owners stay mounted. Navigating between workspaces or returning to Launch preserves conversation drafts, history, and active work.

Loading and failure states stay within the requested presentation, leaving workspace navigation available. Settings supplies a focus-trapped dialog while its code loads and restores focus on close. Retry starts a fresh loading attempt without resetting the shared runtime. If an asset remains unavailable, explicit page reload is available; it discards unsent text.

The runtime's default assistant-message Markdown renderer loads separately. Its loading and failure fallback shows escaped plain text so the answer, composer, and activity remain usable. Cortex, Briefing, and Reports retain their own rendering rules inside their deferred presentations.

The production build writes a Vite manifest and a sanitized module report under the repository's `dist/.vite/`. `npm run check:loading` follows static imports and HTML module preloads, verifies that deferred presentations and Markdown dependencies stay outside the initial graph, confirms native admission and Tauri API code stay out of browser startup imports, and reports entry, initial, deferred, and total JavaScript sizes. Gzip totals sum the compressed sizes of individual assets.

Its optional `--baseline` argument accepts an absolute directory containing an earlier build and manifest:

```powershell
npm run check:loading -- --baseline "C:\path\to\previous\dist"
```

Compare builds made with the same lockfile and options. Byte reductions alone do not measure browser startup time or first-use latency.

## API boundary

`src/lib/api.ts` centralizes the FastAPI base URL at `http://127.0.0.1:8000`. The frontend receives configuration and runtime state through HTTP; it does not read `.env`, `config.json`, or `config.local.json` directly.

The browser owns presentation state such as the active workspace. `ApexAssistantRuntime` manages conversation interaction, while FastAPI and SQLite own durable history and other application records. Connectors, settings, telemetry collection, model execution, tools, context, actions, and speech run on the backend. Audio plays on the APEX host. See [API](../docs/api.md) for request behavior.

## Frontend rules

- Preserve Launch, explicit collection, development mode, and demo mode behavior.
- Keep independent flows usable when another path is degraded.
- Parse external JSON defensively before storing it in typed state.
- Preserve keyboard access, focus handling, semantic labels, and reduced-motion behavior.
- Use existing tokens and state semantics before adding colors or material treatments.
- Add focused Vitest coverage when state transitions, request handling, or user interactions change.

Follow the [frontend engineering guidance](../docs/agent-guidance/frontend.md) for implementation and testing, and the [Design System](../docs/design-system.md) for visual changes.
