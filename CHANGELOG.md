# APEX Changelog

---

## v1.13.0 — Cortex: Local Ollama Provider

**Released:** July 5, 2026

This release adds a local Ollama inference path to the APEX assistant, alongside the existing cloud Gemini profiles. Local Ollama profiles are introduced as experimental/preview functionality in this release: they are fully wired into the assistant, but runtime quality and latency are hardware-dependent, and model defaults may change as the local inference path is tuned. Three local model tiers (Lynx, Acinonyx, Neofelis) run fully on-device with automatic load/unload, a single-loaded-model policy, idle auto-unload, and per-profile RAM/CPU resource gating. The assistant profile selector and drawer now surface live availability across all six profiles, and the internal "Cortex" naming was formalized as the umbrella term for the assistant initiative.

---

### What's New

- Added an `OllamaProvider` implementing the `AgentProvider` protocol, translating APEX agent messages and tool schemas to and from Ollama's `/api/chat` REST contract, including tool-call argument parsing and `<think>` tag stripping from Qwen model output.
- Added three local model profiles — Lynx (`qwen3:1.7b`, lightweight), Acinonyx (`qwen3:4b-instruct`, balanced), and Neofelis (`qwen3:8b`, heavy) each with independent context window, token ceiling, thread count, timeout, and RAM/CPU resource gate settings.
- Added a local model lifecycle manager: single-loaded-model enforcement, coordinated model switching, idle auto-unload on a background poll loop, and a manual unload endpoint, backed by a shared HTTP session and status snapshot cache.
- Added a non-blocking execution slot for local generations so concurrent requests are rejected instead of queued, and a host resource gate that blocks a *cold* model load when RAM or CPU utilization exceeds the profile's configured threshold. Already-loaded models bypass the gate.
- Added a retry path for local tool-select turns that hit the token ceiling without producing a tool call: the turn regenerates once without tools under the final-answer budget instead of returning truncated prose.
- Added `GET /api/v1/agent/profiles`, returning live availability, active/loaded state, idle-unload countdown, and Ollama runtime details (size, VRAM, processor, context) for all six cloud and local profiles from a 10-second TTL snapshot.
- Added `POST /api/v1/agent/local/unload` for manually evicting the active local model ahead of the idle timer.
- Extended the assistant profile selector with a cloud/local section split, live per-profile availability gating with hover tooltips, and preview-stability badges.
- Added an active local model panel to the assistant drawer showing the loaded model, an idle-unload countdown, and a manual unload button.
- Replaced the hardcoded demo assistant keyword-matching logic with responses loaded from `core/mock/assistant.json`, so demo behavior can be edited without a code change.
- Renamed the FastAPI app title and health check payload from "APEX Nexus" to "APEX API"/"APEX", completing the internal Cortex/Nexus naming cleanup.

### Architecture Changes

- Extended `AgentProvider`, `run_agent_loop`, and the API layer's profile resolution to operate over a union of `GeminiModelProfile` and `OllamaModelProfile`, selecting provider, system prompt, and error messaging based on profile type.
- Added an `AgentModelProfile` union type shared across the agent loop, providers, and API layer in place of the Gemini-only profile type.
- Added `local_agent_system_prompt` as an independent config key from the existing cloud `agent_system_prompt`.
- Added `ollama` config section (`enabled`, `host`, `idle_unload_timeout_minutes`, `manual_unload_enabled`, per-profile `resource_gates`) with bounded parsing and logged fallbacks.
- Added a FastAPI lifespan handler that starts the idle-model background monitor on boot and cancels it cleanly on shutdown.
- Added session history trimming (`_trim_agent_history`) that bounds prompt evaluation cost per session and discards orphaned leading non-user messages after the cut.
- Withheld tool schemas on the final permitted local turn so a bounded local session is forced into a text answer instead of wasting the last turn on an unusable tool call.

### API Changes

- `POST /api/v1/agent/query` — `profile` now accepts three additional local values (`"lynx"`, `"acinonyx"`, `"neofelis"`) alongside the existing cloud values. Local profile requests pass through an admission sequence (execution slot, resource gate, model switch) and can return `429` (busy) or `503` (resource-gated, load failure, or Ollama disabled) in addition to the existing response shapes.
- Added `GET /api/v1/agent/profiles`, returning an `AgentProfileStatus` list with `key`, `display_name`, `provider`, `tier`, `stability`, `status`, `active`, `reason`, `idle_unload_remaining_seconds`, and `loaded_model`.
- Added `POST /api/v1/agent/local/unload`, returning `LocalUnloadResponse`; can return `403` (disabled), `409` (generation in progress), or `503` (unload failure).
- Added `AgentProfileStatus`, `LocalLoadedModelStatus`, and `LocalUnloadResponse` Pydantic models, and a `ProfileAvailabilityStatus` literal union (`available`, `disabled`, `ollama_unreachable`, `model_not_installed`, `insufficient_ram`, `cpu_overloaded`).

### Frontend Changes

- Extended `telemetry.ts` with `AssistantProfile`, `ProfileAvailabilityStatus`, `ProfileStability`, `AgentProfileStatus`, and `LoadedOllamaModelStatus` types, replacing the cloud-only `AgentCloudProfile` usage across the assistant surface.
- `CloudProfileSelector.tsx` now renders a two-section (cloud/local) dropdown with live gating, tooltips, and preview badges driven by the polled profile status list.
- `useApexAssistant.ts` gained a self-scheduling poll of `GET /api/v1/agent/profiles` (paused while a query is in flight or the tab is hidden) and an `unloadLocalModel()` action.
- `AssistantDrawer.tsx` gained an `ActiveLocalModelPanel` showing the loaded model, idle-unload countdown, and manual unload control.

### Documentation Updates

- Updated `README.md`, `frontend/README.md`, `docs/api.md`, and `docs/architecture.md` to document the local Ollama provider, its profiles, lifecycle behavior, and the two new API endpoints.
- Added the Cortex initiative framing to `docs/roadmap.md`, marked v1.13.0 as in progress, and renamed the milestone from "Local Ollama Agentic Tool Calling" to "Cortex: Local Ollama Provider".
- Reorganized `docs/decisions.md` into topic sections and added local inference decision records covering profile naming, model tiering, and the distinction between the assistant's Ollama integration and the still-unimplemented `DEV_AI_SYNTHESIS=slm` briefing path.

---

## v1.12.0 — Cloud Gemini Agentic Tool Calling

**Released:** July 2, 2026

This release adds a Gemini-backed conversational assistant to APEX. A bounded multi-turn agent loop dispatches read-only tools for weather, F1, calendar, reminders, and briefing history, and the HUD gained an input bar and drawer for querying it directly.

---

### What's New

- Implemented a bounded multi-turn agent loop with tool dispatch, execution tracing, and crash-resilient error handling.
- Added a Gemini provider adapter supporting three model profiles (comet, nova, pulsar) with tunable turn and tool-call limits.
- Added retry backoff for Gemini rate-limit and server errors, and Base64 encoding for binary thought signatures to preserve model reasoning across multi-turn function calls.
- Added a registry of seven read-only agent tools: weather forecast, F1 driver standings, F1 season calendar, extended calendar lookback, active reminders, and briefing history.
- Wrapped tool outputs in `<untrusted_tool_output>` blocks with a security-boundary system instruction to reduce prompt-injection risk.
- Injected the latest briefing prose and insights into the assistant's system instruction so it can answer follow-up questions about current HUD state.
- Added deterministic offline demo responses for the assistant under demo mode.
- Added an "Ask APEX" input bar with cloud profile selection and suggestion chips, and an assistant drawer showing query history, execution trace, and follow-up input.
- Added centralized config parsing for assistant feature flags, default profile, and turn/tool-call limits.
- Fixed briefing ledger persistence to run before voice playback instead of inside the playback thread.

### Architecture Changes

- Decoupled the agent loop from the concrete Gemini provider via an `AgentProvider` protocol, replacing the earlier `CortexProvider` protocol.
- Refactored the agent tool dispatcher to raise exceptions instead of returning error strings.
- Added a `system_instruction_override` pathway through the agent loop and provider `send` call, with a configurable `system_instruction` field per model profile.
- Added local Vite dev server origins to the CORS allowlist.
- Renamed all internal "Cortex" naming to "APEX assistant" across the agent loop, model profiles, and API responses.

### API Changes

- Added `POST /api/v1/agent/query`, routing user questions through the Gemini-backed agent loop and returning structured error responses on invalid API key or profile.
- Added `GET /api/v1/config`, exposing the default assistant profile and Ask APEX visibility flag; the frontend syncs both on boot.
- Added typed agent message, request, and response models, and an `agent_system_prompt` config key sourced through `core/config.py`.

### Frontend Changes

- Added `AskApexBar.tsx`, `CloudProfileSelector.tsx`, and `AssistantDrawer.tsx` components.
- Added `useApexAssistant.ts` to manage assistant query state, history, and session reset.
- Adjusted HUD layout to fit the new input bar alongside the briefing digest and command trigger.

### Documentation Updates

- Updated `README.md`, `frontend/README.md`, `docs/api.md`, and `docs/architecture.md` to document the assistant, its tools, and configuration options.
- Added decision records covering stateless assistant sessions and the untrusted tool output boundary in `docs/decisions.md`.
- Marked v1.12.0 complete in `docs/roadmap.md` and renumbered the next planned milestone.

---

## v1.11.1 — Speech Engine Stabilization & Library Pruning

**Released:** June 29, 2026

This patch removes Piper CLI from the active TTS stack, restores Google Cloud TTS as the primary engine, and places Kokoro ONNX on hardware-conditional cold standby. Boot memory overhead and thread count are reduced when Kokoro is not the configured primary engine.

---

### What's New

- Removed Piper CLI as an active TTS engine; all runtime subprocess calls, binary resolution, and voice model selection logic were deleted from `core/speaker.py`.
- Added a silent forward-compatibility redirect: `primary_tts: "piper"` in `config.json` resolves to `"pyttsx3"` at runtime with a logged warning, preserving existing configs without errors.
- Restored Google Cloud TTS as the default primary engine in `config.json`.
- Placed Kokoro ONNX on hardware-conditional cold standby; the warmup thread and lazy imports are skipped at boot when `primary_tts` is not `"kokoro"`, consuming 0 MB RAM and 0 threads.

### Architecture Changes

- Updated `_resolve_tts_diagnostics` in `core/api.py` so Google Cloud TTS bypasses hardware throttle checks; Kokoro retains its existing fallback to `pyttsx3` under load.
- Narrowed `TtsEngine` literal union and the `active_tts_engine` field in `RuntimeMetadata` and `PipelineStatusSnapshot` to `"google" | "kokoro" | "pyttsx3"`, removing `"piper"` from all schema definitions.
- Updated `core/config.py` to enforce the `piper → pyttsx3` redirect at config parse time.

### API Changes

- `TtsEngine` type is now `Literal["google", "kokoro", "pyttsx3"]` across the backend schema and frontend TypeScript types; `"piper"` is no longer a valid or emitted value.

### Frontend Changes

- Unified `VocalOrb.tsx` to a single gold color scheme by removing the `isLocalEngine` conditional branch and the cyan color path it produced.
- Updated `useApexData.ts` and `telemetry.ts` to reflect the narrowed `TtsEngine` union.

### Documentation Updates

- Updated `README.md`, `docs/architecture.md`, `docs/api.md`, `docs/decisions.md`, and `docs/roadmap.md` to reflect the revised engine stack.
- Documented the Lunar Lake latency root cause that motivated the Piper removal in `docs/decisions.md`.

---

## v1.11.0 — Dormant Core & Ambient State Engine

**Released:** June 28, 2026

This release transforms APEX into a standby intelligence appliance. The HUD now enters a dormant visual state when no synthesis is active, with layout animations, logo breathing effects, and mouse-driven parallax depth responding to system state transitions. A dedicated `CommandTrigger` component replaces the inline button header, and the synthesis model was migrated to Gemini 3.1 Flash Lite.

---

### What's New

- Introduced dormant standby mode: when pipeline status is `idle`, the HUD collapses side panels, scales the logo up, and reveals the synthesis trigger as a centered overlay.
- Added `CommandTrigger` component with context-sensitive labels and internal hover/focus state, positioned beneath the `ApexLogo` in dormant layout.
- Promoted pending reminder count from a below-logo label to a pulsing ARIA-live header badge.
- Applied spring-eased `cubic-bezier(0.16, 1, 0.3, 1)` transitions (1000 ms) to all layout, opacity, and scale changes across dormant and active states.
- Added `isDormant` idle state to `ApexLogo`; logo plays a breathing amber keyframe animation when the pipeline is inactive.
- Replaced static green logo fill with `greenSurge` (steps 1–2) and `purpleSurge` (step 3) keyframe animations at 2.5-second loop intervals with per-segment delay cascades.
- Added `apexPurpleMetal` SVG gradient; step 3 of the nebula color logic now emits purple instead of green.
- Split the `Processing` status label into `Collecting Data` (steps 1–2) and `Synthesizing` (step 3) in `SystemDiagnostics`.
- Implemented GPU-accelerated mouse-parallax starfield: passive `mousemove` listener writes `--mouse-x`/`--mouse-y` to `documentElement`; stars classified into three depth tiers (far/mid/near) with `translate3d` displacement ranges of 12 px, 28 px, and 48 px.
- Migrated synthesis model from Gemini 2.5 Flash to Gemini 3.1 Flash Lite in `core/brain.py`.
- Fixed launcher crash when the backend connection times out by adding `TimeoutError` to the readiness check catch block and increasing the connection timeout.

### Architecture Changes

- Replaced three-column CSS grid with a flex row layout in `App.tsx` to enable per-column `max-width` and `flex` animations during state transitions.
- Defined named class-string constants for dormant and active layout states across left wing, right wing, center column, and briefing digest container.
- Wrapped `BriefingDigest` in an animated container using `max-height` clamping for collapse/expand transitions.
- `CommandTrigger` extracted as a standalone component; inline trigger button removed from the header.
- Three `translate3d` parallax utility classes added to `index.css` for depth-tiered star displacement.
- Added `scale-115` to Tailwind config theme extensions.

### Documentation Updates

- Added dormant HUD and active briefing screenshot assets to `docs/assets/` and embedded both in `README.md` under a new "Interface Preview" section.
- Added dormant ambient HUD mode to the README features list.
- Documented dormant canvas mode layout transitions, `CommandTrigger` component, full `ApexLogo` state machine, and mouse-parallax depth multiplier table in `docs/architecture.md`.
- Updated all Gemini 2.5 Flash references to Gemini 3.1 Flash Lite across `README.md`, `docs/architecture.md`, and `docs/decisions.md`.
- Marked v1.11.0 roadmap status as Complete and defined the v1.12.0 objective.

---

## v1.10.0 — Local Neural Voice Matrix

**Released:** June 13, 2026

This release transitions APEX speech synthesis from cloud-first delivery toward a local-first neural voice architecture powered by Kokoro ONNX and Piper, while preserving optional cloud fallback capabilities. It implements dynamic hardware load monitoring to gracefully downgrade to low-overhead speech engines under system resource starvation, introduces a unified voice gender configuration toggle, and adds GPU-accelerated HUD background elements.

---

### What's New

- Integrated Kokoro ONNX for high-quality, network-independent local neural text-to-speech synthesis.
- Pre-warmed the local Kokoro ONNX client session in a background daemon thread at module import to eliminate first-run latency.
- Integrated local Piper CLI subprocess engine execution with dynamic voice model selection support.
- Added system resource monitoring using `psutil` to query RAM and CPU utilization before executing speech synthesis.
- Implemented automatic hardware-load throttling that downgrades heavy synthesis engines to low-overhead fallbacks (Google Cloud TTS to pyttsx3, Kokoro to Piper) under resource starvation.
- Introduced a unified `VOICE_GENDER` configuration parameter in `config.json` supporting male and female options.
- Dynamic gender matching implemented across all active speech engines (Kokoro, Piper, Google Cloud TTS, and pyttsx3).
- Added telemetry indicators for the resolved speech engine (`active_tts_engine`) and system load throttling status (`system_load_throttled`).

### Architecture Changes

- Rebuilt the speech synthesis routing flow into a cascading fallback chain: Kokoro ONNX $\rightarrow$ Google Cloud TTS $\rightarrow$ Piper CLI $\rightarrow$ pyttsx3.
- Added helper utility to package raw 16-bit mono PCM bytes into memory-buffered WAV containers for Pygame audio playback.
- Pruned all deprecated ElevenLabs API endpoints, clients, configurations, and environment variables.
- Updated core pipeline tracking in `api.py` to trace the active speech engine and system load throttling flag.
- Refactored background layout rendering to use GPU-accelerated counter-rotating radial gradient nebula fields.

### API Changes

- Extended `RuntimeMetadata` and `PipelineStatusSnapshot` schemas to expose `active_tts_engine` and `system_load_throttled` fields.
- Added `TtsEngine` literal union type and updated state hook interfaces in the frontend TypeScript files.
- Documented `DEV_TTS_PLAYBACK` and `DEMO_TTS` configuration options for local offline engines in API schemas.

### Frontend Changes

- Replaced legacy CSS nebula animation loops with hardware-accelerated counter-rotating CSS transforms.
- Updated `VocalOrb.tsx` to display a cyan color scheme and wider stasis coordinates when local offline speech engines are operating.
- Configured data attribute flags on the HUD root layout to expose the active TTS engine and throttle states.

### Documentation Updates

- Updated `docs/architecture.md` to document the cascading fallback speech chain and the hardware load throttling behavior.
- Documented new fields and fallback configuration variables (`DEV_TTS_PLAYBACK`/`DEMO_TTS`) in `docs/api.md`.
- Logged design decisions regarding local-first neural speech synthesis and cascading fallbacks in `docs/decisions.md`.
- Updated version `v1.10.0` status to Complete in `docs/roadmap.md`.

---

## v1.9.1 — Stabilization & Maintenance

**Released:** June 11, 2026

This release focuses on backend concurrency hardening, external API payload optimization, database lock mitigation, and pruning dead or deprecated frontend components and context providers to improve overall layout and operational stability.

---

### What's New

- Prevented concurrent briefing pipeline executions by introducing a global thread lock guard.
- Enabled Write-Ahead Logging (WAL) and configured database connection timeouts to mitigate SQLite write locks.
- Optimized Gmail API message querying to retrieve metadata headers instead of the full payload.
- Configured request connection timeouts for the OpenWeatherMap client.
- Corrected the date ordinal suffix lookup logic for sports fixture calendars.
- Pruned the unused `AtmosphericThemeContext`, `ConfidenceBadge`, and `RingGauge` components from the codebase.
- Refactored frontend system diagnostics to prevent duplicate diagnostic hook execution.

### Architecture Changes

- Integrated a global thread lock (`_TRIGGER_LOCK`) to serialize `/api/v1/trigger` calls and enforce safe state resets on exceptions.
- Transitioned SQLite connection configuration to WAL mode, permitting concurrent read transactions during active database writes.
- Resolved database path dynamically using `PROJECT_ROOT` to avoid writing state to the local execution subdirectory.
- Restructured `SystemDiagnostics` to accept diagnostics state directly via props from the parent `App` shell, eliminating duplicate API polling hook executions.
- Discarded React Context for atmospheric theme state in favor of localized CSS variable updates and type-safe mappings.
- Replaced the file-modification time tracking of `clients/.f1_cache.json` with a dedicated caching boolean flag passed directly by the sports client.

### API Changes

- Extended the sports client `fetch_sports_data` return signature to include an explicit cache-status boolean indicator.
- Refactored response payload parsing in the frontend `useApexData` hook to parse and typecast digest insights, scores, and failed connector arrays from a unified response dictionary.
- Simplified `SystemState` types in `telemetry.ts` to a static literal union, and removed the deprecated atmospheric context and insights array interfaces.

### Frontend Changes

- Updated `App.tsx` layout to pass diagnostics state down to the full-width status footer.
- Removed the parent `AtmosphericThemeProvider` wrapper from `App.tsx`.
- Streamlined `BriefingPanel` properties, removing unused loading, speaking, and status tracking inputs.
- Combined separate RAM and Disk storage formatting methods in `SystemDiagnostics.tsx` into a single `formatGbRatio` utility function.
- Deleted the deprecated `ConfidenceBadge.tsx` component.
- Deleted the deprecated `RingGauge.tsx` component.
- Deleted the deprecated `AtmosphericThemeContext.tsx` context file.

### Documentation Updates

- Updated `docs/api.md` to document the cache-status indicator flag and updated confidence rating formulas.
- Modified `docs/architecture.md` directory trees and component descriptions to reflect the removal of `ConfidenceBadge`, `RingGauge`, and `AtmosphericThemeContext`.
- Removed obsolete implementation notes regarding filesystem metadata polling in architectural documents.

---

## v1.9.0 — Standby Core & Unified Status Deck

**Released:** June 11, 2026

This release replaces the auto-firing trigger with an operator-initiated model, introduces a dormant `idle` standby state, and rebuilds the system diagnostics surface as a full-width footer bar outside the telemetry card grid. The HUD now loads into a resting state, shows pending reminders before any synthesis is requested, and consolidates confidence, pipeline, hardware, and time data into a unified status row at the bottom of the layout.

---

### What's New

#### Operator-Initiated Synthesis and Standby State

- Replaced the auto-executing `POST /api/v1/trigger` call on mount with an explicit `triggerSynthesis` callback.
- Added a dormant `idle` standby state that the HUD enters before any synthesis is requested. The trigger does not fire until the operator acts.
- Added an `INITIATE SYSTEM BRIEFING` button to the header toolbar, visible only when status is `idle`.
- Added a global `Enter` keyboard shortcut that calls `triggerSynthesis` when focus is outside inputs and status is `idle`.
- Added `isSynthesisGuarded` to block duplicate trigger requests while a run is already `loading` or pipeline polling is active.
- Added `synthesisAbortRef` to abort any previous in-flight synthesis before starting a new one, and a cleanup effect to abort the controller on component unmount.
- `useApexData` now fetches `GET /api/v1/reminders` on mount to populate `activeReminders` during standby, surfacing pending reminder count below the `ApexLogo` before the first briefing.
- Added `createStandbyTelemetryPayload` to produce a zero-content payload that initializes `ApexDataState` during the dormant phase.

#### Unified Status Footer

- Removed `SystemDiagnostics` from the telemetry card grid and rendered it as a full-width `<footer>` element outside the main bento grid.
- Rebuilt the footer as a six-column horizontal layout: **System Status** label, **Internet** connectivity indicator, **Briefing Status** lifecycle state, **Sync Health** segmented bar, **Hardware Resources** micro-bars, and a **System Clock**.
- Sync Health column: 10 segmented blocks filled proportional to `confidenceScore`, color-coded emerald/amber/red. Hover tooltip lists `failedConnectors` or confirms all connectors healthy.
- Hardware Resources column: CPU, RAM, and disk percentage labels each backed by a horizontal micro-bar. Hover tooltips show CPU frequency (GHz) and RAM/disk as used/total GB.
- Briefing Status column reflects the full pipeline lifecycle: Standby → Processing (pulsing emerald) → Delivering (amber) → Complete (blue) → Fault (rose).
- Removed `ConfidenceBadge` from the header; confidence display consolidated exclusively into the footer Sync Health column.
- Replaced the header status ticker with a `Clock`-icon last-briefing-time display (`lastBriefingTime`), populated from `GET /api/v1/briefings/history` on mount and updated on each successful trigger resolution.
- Added `@keyframes goldGlow` and `.animate-gold-glow` CSS utility to `index.css`.

---

### Architecture Changes

- `useApexData` trigger lifecycle changed from mount-time auto-fire to explicit operator invocation. The hook now initializes into `idle` state rather than immediately entering `loading`.
- `SystemDiagnostics` relocated from inside the `<main>` bento grid to a sibling `<footer>` element, making it layout-independent from the telemetry card count and grid column configuration.
- `SystemState` type extracted from an inline union to a derived `const` array type in `telemetry.ts`, making the valid state set enumerable at runtime.
- `lastBriefingTime` state added to `App.tsx`, hydrated from briefing history on mount and kept current through each trigger resolution.
- `prevStatus` tracking for the `loading → success` transition isolated into a self-contained effect.

---

### Frontend Changes

- `App.tsx` — added `INITIATE SYSTEM BRIEFING` header button, standby reminder count display, `lastBriefingTime` hydration, and `<footer>` mounting for `SystemDiagnostics`.
- `SystemDiagnostics.tsx` — fully rebuilt as a six-column horizontal status bar; `RingGauge` gauges replaced with horizontal micro-bars and segmented sync health indicator; hover tooltip overlays added to Sync Health and Hardware Resources columns; live clock column added.
- `useApexData.ts` — trigger flow restructured for operator-initiated execution; standby reminder fetch added on mount; abort controller wired for cleanup; `isSynthesisGuarded` guard added.
- `telemetry.ts` — `SystemState` extracted from inline union to `const` array type.
- News Wire card empty-state copy corrected; list item key changed from `item.subject` to `item.topic`.

---

### Documentation Updates

| File | Changes |
|---|---|
| `docs/architecture.md` | Updated `SystemDiagnostics` description to the six-column footer bar; documented `ConfidenceBadge` as unused; updated `RingGauge` as unused; updated `useApexData` to reflect idle initialization, standby reminder fetching, and operator-initiated trigger execution |
| `docs/roadmap.md` | Adjusted v1.9.0 roadmap header |
| `README.md` | Minor copy corrections |
| `frontend/README.md` | Minor corrections |
| `docs/decisions.md` | Removed duplicate heading |

---

## v1.8.0 — Briefing Digest & Transcript Layer

**Released:** June 9, 2026

This release adds structured output from the Gemini synthesis stage, a persistent briefing ledger, and connector trust scoring. The `BriefingResponse` API contract, SQLite schema, and `brain.process_telemetry()` return type were all extended. The HUD gained two new components and two new telemetry cards, and the layout was converted to a viewport-locked deck.

---

### What's New

#### Briefing Digest and History Ledger

- `DigestPayload` Pydantic model added to `core/api.py` and wired into `BriefingResponse` as a top-level `digest` field. Fields: `weather_archetype`, `unread_emails_count`, `upcoming_events_count`, `f1_sprint_active`, `reminders_pending_count`, `confidence_score`, `failed_connectors`, `insights`. All carry typed fallback defaults.
- `briefings` table added to `apex_memory.db`: `(id AUTOINCREMENT, timestamp TEXT, briefing TEXT, digest_json TEXT)` with a `timestamp DESC` index. `initialize_db()` creates it on first run.
- `save_briefing()`, `fetch_briefing_history(limit=50)`, and `prune_historical_ledger()` added to `core/database.py`. Ledger capped at 50 rows; pruning runs inside a `BEGIN` / `ROLLBACK` transaction on the TTS worker thread after each production run.
- `_speak_and_cleanup()` updated to call `save_briefing()` and `prune_historical_ledger()` before `global_pipeline_state.reset()`. Writes are production-only.
- `GET /api/v1/briefings/history` added — returns up to 50 `BriefingHistoryRecord` objects (id, timestamp, briefing, DigestPayload) ordered by timestamp descending. Returns three static mock records when `DEMO_MODE=true`.
- `HistoryLedgerModal` in `BriefingDigest.tsx` fetches the history endpoint on open and renders each record with timestamp, briefing prose, and insight bullets. Mounted via `createPortal`; dismissed by backdrop click or `Escape`.

#### Connector Trust Scoring

- `_compute_confidence_and_failures()` added to `core/api.py`. Evaluates each enabled connector's output string against per-connector failure regex constants after Collection. Score: `(earned_weight / total_weight) × 100`, clamped `[0.0, 100.0]`.
- Sports weight split: F1 and football each contribute `0.5` when both enabled; `1.0` when only one active. All other connectors: `1.0` each.
- F1 cache staleness penalty: if `clients/.f1_cache.json` existed before the sports connector ran and its mtime was unchanged after, `confidence_score *= 0.90`.
- Demo mode pinned to `confidence_score: 100.0` and `failed_connectors: []`.

#### Structured Gemini Output (`===SPEECH===` / `===INSIGHTS===`)

- `brain.process_telemetry()` return type changed from `str` to `dict[str, Any]` with keys `briefing` and `insights`. All callers and bypass paths in `core/api.py` updated.
- `_parse_model_output(text)` splits on the two section markers and strips bullet prefixes from the insights lines. Missing markers fall through to `_fallback_output()`, which returns the raw data string with a single placeholder insight.
- `config.json` system prompt updated to mandate the two-section output format.

#### New and Modified HUD Components

- `BriefingDigest.tsx` (new) — insight bullets in the center column above `ApexLogo`. Skeleton loader during pipeline runs; empty state when no insights returned. Hosts "History" button that opens `HistoryLedgerModal`.
- `ConfidenceBadge.tsx` (new) — header pill badge: emerald (≥ 90%), amber (≥ 50%), red (< 50%). Neutral gray before first successful run. Tooltip lists `failedConnectors` on hover/focus. Keyboard-accessible with `tabIndex=0`.
- `BriefingPanel.tsx` — restructured into a collapsible subtitle drawer beneath the header; activates only at stage 4 TTS playback. History ledger state relocated to `BriefingDigest`.
- `SystemDiagnostics.tsx` — `RingGauge` SVG components replaced with horizontal bar layout; compact mode added.
- `TelemetryCard.tsx` — refactored into a single-element flex shell with conditional header rendering and flex-based children containers for internal per-card scrolling.
- `App.tsx` — added `Inbox` and `News Wire` telemetry cards to the right column, surfacing email and news connector output in the HUD for the first time. `ConfidenceBadge` mounted in the header.

#### Antigravity Workspace Rules

- `.agents/rules/` created alongside `.cursor/rules/`. Nine rule files added: `analyst`, `auditor`, `backend`, `builder`, `communicator`, `devops`, `frontend`, `global`, `mechanic`. Glob patterns adjusted for Antigravity activation semantics.

---

### Architecture Changes

- **`brain.process_telemetry()` return shape** — changed from `str` to `dict[str, Any]`. The `briefing` and `insights` keys are guaranteed present on every code path including the exception handler and all `DEV_MODE` bypass branches.
- **Gemini output protocol** — system prompt enforces `===SPEECH===` / `===INSIGHTS===` markers. Model responses without markers fall through to `_fallback_output()`.
- **Viewport-height lock** — root layout converted to `h-dvh overflow-hidden` with `flex min-h-0` propagation. All scrolling is now at the card level; future cards must fit within this constraint.
- **Demo-mode guards on reminder endpoints** — all three reminder endpoints received explicit `DEMO_MODE` branches returning static mock data without database access.

---

### API Changes

- `POST /api/v1/trigger` — `BriefingResponse` gained `digest: DigestPayload` as a top-level field.
- `GET /api/v1/briefings/history` added (see above).
- New Pydantic models: `DigestPayload`, `BriefingHistoryRecord`.
- `telemetry.ts`: added `DigestPayload` and `ActiveReminder` interfaces; `digest?: DigestPayload` on `TelemetryPayload`; `confidenceScore`, `failedConnectors`, and `insights` on `ApexDataState`.
- `useApexData` extracts all three digest fields from the trigger response body; no additional fetch required.

---

### Database Changes

| Change | Detail |
|---|---|
| New table | `briefings (id, timestamp, briefing, digest_json)` with `timestamp DESC` index |
| New function | `save_briefing(briefing, digest_dict)` — persists briefing text and JSON-encoded digest |
| New function | `fetch_briefing_history(limit=50)` — ordered query with JSON parse on return |
| New function | `prune_historical_ledger()` — deletes rows outside the 50 most recent; explicit `BEGIN` / `ROLLBACK` transaction |

---

### Agent Workflow Changes

- `.agents/rules/` established as a parallel rule surface to `.cursor/rules/`. Nine rules present in both locations.
- `docs/decisions.md` AI agent rules table updated to cover all nine rules with activation modes and role descriptions.

---

### Documentation Updates

| File | Changes |
|---|---|
| `docs/api.md` | Added `digest` field table to `POST /api/v1/trigger`; added `GET /api/v1/briefings/history`; added `DigestPayload` and `BriefingHistoryRecord` model listings; added demo-path notes to all three reminder endpoints |
| `docs/architecture.md` | Added `briefings` table and ledger functions to `database.py` section; added `BriefingDigest` and `ConfidenceBadge` component descriptions; added Confidence Scoring section; updated `useApexData` and `telemetry.ts` type documentation |
| `docs/decisions.md` | Updated AI agent rules table |
| `README.md` | Corrected pipeline diagram; added confidence scoring and briefing history to feature bullets |
| `frontend/README.md` | Replaced default Vite scaffold content with project-specific documentation |
| `docs/roadmap.md` | Created. Outlines planned milestones and future capabilities |

---

## v1.7.0 — HUD-Renaissance: Productization

**Released:** June 6, 2026

This release moves APEX from a feature-complete prototype into a shareable, documented product. Three commits introduce a star-field celestial background with explicit HUD z-index layering, a full demo mode that stages the pipeline with mock telemetry and zero live API calls, and a documentation split that extracts architecture, API contracts, and engineering decisions from the README into dedicated reference files.

---

### What's New

#### Celestial Background and HUD Z-Index Layer System

The HUD now renders on top of a static star field with a formalized layer stack.

- `CelestialBackground.tsx` was created. It generates 80 seeded stars distributed across three twinkle-speed tiers using a deterministic pseudo-random sequence. The component mounts behind all HUD content with no dependency on runtime state.
- Five CSS custom properties (`--z-stars`, `--z-nebula`, `--z-bento-hud`, `--z-header`, `--z-portal`) were added to `index.css` to define the full HUD render stack explicitly. All previously hardcoded `z-index` values were replaced with these named properties.
- `isolate` was applied to `<main>` in `App.tsx` to establish a stacking context boundary. Bento grid content was wrapped in a `z-[var(--z-bento-hud)]` container to sit above the nebula layer.
- `hud-glass` was strengthened: backdrop blur increased to `blur(20px)`, opacity reduced, and layered inset shadows added to increase depth.
- `TelemetryCard` was split into an outer shell and an inner glass content wrapper to allow the blur to apply correctly through the z-stack.
- Card hover classes (`hover-warm-*`) were replaced with `hover-blue-subtle`, `hover-blue-medium`, and `hover-blue-strong` across all telemetry cards, aligning the palette with the unified HUD blue accent.
- `--hud-border-color` was changed from a warm-tinted value to a neutral white-alpha value.
- `ApexLogo` received a hover scale and `drop-shadow` transition. Active metal states gained an explicit `transition` property.
- `repomix-output.xml` was added to `.gitignore`.

#### Demo Mode

A self-contained demo mode was added that runs the full pipeline against static fixture data without touching any live API or credentials.

- `DEMO_MODE` and `DEMO_TTS` environment variables were added to `core/config.py` and documented in `.env.example`. `DEMO_MODE` activates the mock pipeline path; `DEMO_TTS` selects the TTS engine used during demo playback.
- `core/mock/telemetry.json` was created as a static fixture shaped to match `TelemetryPayload`. It carries representative values for all telemetry fields without live data.
- `_run_demo_briefing()` was added to `core/api.py`. It advances the pipeline through all four stages with fixed inter-stage delays, serves the mock telemetry fixture at `/api/v1/trigger`, and exits without calling any external client.
- `RuntimeMetadata` was extended with a `demo_mode_active` boolean field. The field propagates `false` in the live briefing path so the frontend always has a reliable signal.
- `_route_tts_playback()` was extracted in `core/speaker.py` to eliminate duplicated TTS branch logic that previously existed across the dev-mode and production code paths. A `tts_override` keyword argument was added to `speaker.speak()` for per-call engine selection without touching global routing.
- `demoModeActive` was added to `ApexDataState` in `telemetry.ts` and extracted from the briefing response metadata in `useApexData.ts`.
- A pulsing amber `DEMO MODE ACTIVE` badge renders in the HUD header when `demoModeActive` is `true`.

#### Documentation Split

The monolithic `README.md` was broken apart into three dedicated reference documents.

- `docs/architecture.md` was created, containing the full system architecture walkthrough previously embedded in the README: data flow, component relationships, backend subsystems, and the launcher orchestration model.
- `docs/api.md` was created, containing all API endpoint contracts: route signatures, request and response shapes, error behavior, and polling semantics.
- `docs/decisions.md` was created, containing the engineering decision log: `.env` vs `config.json` separation, TTS fallback design, synchronous trigger rationale, speaker state authority, and launcher environment isolation.
- `README.md` was rewritten as a concise project overview (631 → 185 lines) with cross-links to the new files.
- The dead `inworld_api_key` field was removed from `config.json`.

---

### Files Changed

| Area | Files |
|---|---|
| Frontend Components | `CelestialBackground.tsx` (new), `TelemetryCard.tsx`, `ApexLogo.tsx`, `App.tsx` |
| Frontend Styles | `index.css` |
| Frontend Hooks | `useApexData.ts` |
| Frontend Types | `telemetry.ts` |
| Backend API | `core/api.py` |
| Backend Config | `core/config.py` |
| Backend Speaker | `core/speaker.py` |
| Mock Fixtures | `core/mock/telemetry.json` (new) |
| Config & Env | `config.json`, `.env.example` |
| Docs | `docs/architecture.md` (new), `docs/api.md` (new), `docs/decisions.md` (new), `README.md` |
| Repo Config | `.gitignore` |

---

### Summary Stats

- **3 commits** merged into `v1.7.0`
- **~1,383 lines added**, **~657 lines removed** across 19 files
- **1 new React component** (`CelestialBackground`)
- **1 new mock fixture** (`core/mock/telemetry.json`)
- **3 new documentation files** (`architecture.md`, `api.md`, `decisions.md`)
- **1 named z-index layer system** added (5 CSS custom properties)
- **1 full demo mode pipeline** added (`DEMO_MODE` + `_run_demo_briefing()`)
- **1 TTS refactor** (`_route_tts_playback()` extraction eliminating duplicated branch logic)
- **1 dead config field removed** (`inworld_api_key`)

---

## v1.6.0 — HUD-Renaissance: Atmospheric Resonance

**Released:** June 5, 2026

This release transforms the APEX HUD from a functional dashboard into a fully animated, state-reactive interface. Seven commits introduce a persistent animated header, a pipeline-driven nebula background layer, a live-speaker orbital component, an SVG vector logo with segment-gated activation, a weather condition archetype system, glass-panel surface treatment across all cards, and a speaking border animation on briefing delivery. The backend gained a real speaker state query, extended system vitals, and a typed pipeline status model. Legacy diagnostic components were removed and replaced with cleaner header-integrated equivalents.

---

### What's New

#### Animated HUD Header and Status Ticker

A persistent header bar was added to the top of the dashboard with integrated pipeline and system state feedback.

- A `<header>` element was added to `App.tsx` with a live `headerTicker` indicator that reflects `status` and the active pipeline step label in real time.
- A CSS shimmer animation was added to the APEX title in `index.css`. The gradient sweep fires while pipeline polling is active and stops on completion.
- `DiagnosticProgress.tsx` was deleted. The pipeline step label it previously rendered is now surfaced through the header ticker, reducing the component count without losing visibility.

#### Pipeline-Driven Nebula Background

The HUD background layer now reacts to pipeline execution state with animated radial-gradient blobs.

- Three animated nebula blobs were added to `App.tsx` as CSS radial-gradient layers that appear when a pipeline run is active.
- Blob color shifts by stage: emerald for stages 1–3 (gate, collection, synthesis) and amber for stage 4 (delivery). On `status === 'success'`, the nebula color persists at gold.
- `--hud-bg` was updated to `#000000` to increase contrast against the nebula layer.

#### VocalOrb — Live Speaker State Component

A new SVG component was added to the header that reflects real-time audio playback state.

- `VocalOrb.tsx` was created. When `isSpeaking` is false it renders a static stasis line; when true it transitions to two counter-rotating gyro rings with a glow filter.
- `gyroClockwise` and `gyroCounter` keyframe animations were added to `index.css`.
- `is_speaking()` was added to `core/speaker.py`. It checks the threading lock and `pygame.mixer` busy state to determine whether audio is actively playing.
- `is_speaking` was added to the `PipelineState` snapshot in `core/api.py` and exposed through `GET /api/v1/status` via a new `PipelineStatusSnapshot` Pydantic model.
- `is_speaking` was added to the `PipelineState` and `ApexDataState` TypeScript interfaces in `telemetry.ts`.
- The frontend-side derived calculation `isSpeaking = isPipelinePolling && activeStep === 4` was removed. Speaker state is now sourced directly from the backend.
- `VocalOrb` is mounted in the header center column. The header layout was converted to a three-column CSS grid to keep the orb visually centered between the title and the ticker.

#### APEX Vector Logo with Pipeline Segment Activation

A multi-layer SVG logo was added to the HUD center column with pipeline-reactive rendering.

- `ApexLogo.tsx` was created with five inline gradient definitions and step-gated segment activation tied to the pipeline state integer.
- A `--glow-color`-driven drop-shadow filter reflects the active pipeline stage through the logo.
- An `isSpeaking` prop was added to `ApexLogo`. The gold core persists after `status === 'success'` and pulses during audio delivery at stage 4.
- `reminderPulseCount` state was added in `App.tsx` with an 800 ms pulse flash triggered by successful reminder submission, routed through an `onReminderSaved` callback on `ReminderTerminal`.

#### Weather Condition Archetype System

Weather card rendering is now driven by a typed condition classification system rather than raw string comparisons.

- `WeatherConditionArchetype` union type was added to `telemetry.ts` and extended into `TelemetryPayload` as `weatherCondition`.
- `resolveWeatherCondition()` was added to `useApexData.ts`. It derives the archetype from the weather detail string and branches on time of day for clear conditions (`"ClearDay"` vs `"ClearNight"`).
- `TelemetryCard.tsx` received per-archetype animated background glow, border color, and a condition icon rendered from the archetype value.
- Five CSS keyframe animations and `animate-weather-*` utility classes were added to `index.css` to back the per-condition visual treatments.
- The Weather `TelemetryCard` in `App.tsx` was updated from inline string logic to a `weatherBorderByCondition` record keyed on `WeatherConditionArchetype`.
- The "Schedule" card label was renamed to "Events" and the "F1 Schedule" card label was renamed to "Next F1 Race".

#### Glass Panel Surface Treatment and Animated Diagnostics

All telemetry cards received a visual finish pass and the system diagnostics component was significantly expanded.

- A `.hud-glass` backdrop-blur utility class and per-card hover color classes were applied to all telemetry card panels in `index.css` and `TelemetryCard.tsx`.
- `SpeakingBorderMask` was implemented in `BriefingPanel.tsx` as a spinning conic-gradient border overlay that activates at pipeline stage 4 during audio delivery.
- `RingGauge.tsx` received a `subText` prop for secondary label rendering and severity-driven ring colors: blue for normal load, amber for elevated, red for critical.
- `SystemDiagnostics.tsx` was expanded with a severity-driven radial glow and a looping scan sweep animation that fires continuously in the background.
- `sample_system_vitals()` in `core/scanner.py` was extended to emit `cpu_freq`, raw RAM bytes, and raw disk bytes alongside the existing percentage fields.
- Corresponding fields were added to `telemetry.ts` and consumed by `useSystemDiagnostics.ts`.
- `tzdata` was added to `requirements.txt` for reliable timezone resolution.

#### Collapsible Reminder Terminal

The reminder input component was refactored from a fixed full-page overlay into an inline collapsible dock inside the Reminders card.

- `ReminderTerminal` was relocated from a fixed overlay in `App.tsx` into the Reminders `TelemetryCard`.
- `isOpen` and `dockVisible` state was added to manage a dock-button-to-form transition.
- Auto-collapse fires after successful submission. `Escape` key press and focus-out events also collapse the terminal.
- `ReminderTerminal` was wrapped in `createPortal` to resolve z-index stacking issues against the HUD grid.
- Success-pulse and icon color was changed from green to blue for consistency with the unified HUD palette.

---

### Fixes

#### Pipeline Polling Through Stage 4

- The early `PIPELINE_COMPLETE_STEP` exit guard was removed from `useApexData.ts`. The polling loop now remains active through stage 4, ensuring speaker state and nebula glow receive their final update before the run is marked complete.

#### Speaker Cleanup Ordering

- `_speak_and_cleanup()` was extracted in `core/api.py` to defer `global_pipeline_state.reset()` until after audio playback completes. Previously, the pipeline state could reset before the frontend had polled the speaking stage, causing the speaking border and orb animation to be skipped.

#### Duplicate Theme Writes

- Redundant `document.documentElement.style.setProperty` calls were removed from `AtmosphericThemeContext.tsx`. CSS variable writes now originate from a single location.

#### ReminderListRow Dismiss Race Condition

- `ReminderListRow` was updated to fire `POST /api/v1/reminders/read` before the dismiss animation starts rather than after. The previous order allowed the animation to complete and the component to unmount before the API call returned, causing intermittent state drift.

#### Weather Detail Capitalization

- `resolveWeatherDetail()` was fixed to capitalize extracted condition words. Previously, raw lowercase strings from the weather API were surfaced directly into the HUD.

---

### Refactors

#### HUD Grid Structure

- The dashboard grid was restructured in `App.tsx` into explicit left-wing, center-core, and right-wing column groups using `xl:order-*` utilities. `xl:contents` overrides were removed.
- `SystemDiagnostics` was expanded to full three-column width at `xl` breakpoint.
- `ApexLogo` was scaled to `h-64 xl:h-72`.

#### BriefingPanel Simplification

- The word-by-word interval reveal was removed from `BriefingPanel`. Section class construction was consolidated into a `sectionShellClassName` helper.
- The `isSpeaking` prop and glow-pulse side effect were removed from `BriefingPanel`; speaking state is now derived from `useApexData` directly.
- A `clip-path` curtain reveal animation was added that fires once on briefing delivery.

#### Typed Pipeline Status Model

- `PipelineStatusSnapshot` was added to `core/api.py` as a typed Pydantic response model for `GET /api/v1/status`, replacing the previously untyped dict return.
- `parsePipelineStatus()` was added on the frontend side in `useApexData.ts` to validate the response before assignment, replacing the previous unguarded `response.json()` cast.

---

### Files Changed

| Area | Files |
|---|---|
| Backend API | `core/api.py` |
| Backend Speaker | `core/speaker.py` |
| Backend Scanner | `core/scanner.py` |
| Frontend Components | `ApexLogo.tsx` (new), `VocalOrb.tsx` (new), `BriefingPanel.tsx`, `TelemetryCard.tsx`, `SystemDiagnostics.tsx`, `RingGauge.tsx`, `ReminderTerminal.tsx`, `ReminderListRow.tsx` |
| Frontend Hooks | `useApexData.ts`, `useSystemDiagnostics.ts` |
| Frontend Context | `AtmosphericThemeContext.tsx` |
| Frontend Types | `telemetry.ts` |
| Frontend Styles | `index.css` |
| App Shell | `App.tsx` |
| Frontend Entry | `index.html` |
| Deleted | `DiagnosticProgress.tsx` |
| Dependencies | `requirements.txt` |
| Repo Config | `.cursor/rules/frontend.mdc`, `.cursor/rules/auditor.mdc` |
| Docs | `README.md` |

---

### Summary Stats

- **7 commits** merged into `v1.6.0`
- **~1,906 lines added**, **~399 lines removed** across 24 files
- **2 new React components** (`ApexLogo`, `VocalOrb`)
- **1 component deleted** (`DiagnosticProgress`)
- **1 new backend function** (`is_speaking()` in `speaker.py`)
- **1 new Pydantic model** (`PipelineStatusSnapshot`)
- **1 new typed archetype system** (`WeatherConditionArchetype`)
- **1 race condition fixed** (reminder dismiss ordering)
- **1 pipeline polling gap closed** (stage 4 speaker state propagation)

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
