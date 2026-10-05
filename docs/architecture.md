# Architecture

APEX is a local-first personal intelligence workspace. React provides the interface, FastAPI owns application services and execution, and SQLite stores durable application records. Optional connectors, model providers, and speech services can send data outside the local process; [Privacy](privacy.md) describes those boundaries.

This document explains how collection, conversations, briefings, and personal context fit together. Use [Configuration](configuration.md) for settings, [API](api.md) for HTTP behavior, and the [frontend guide](../frontend/README.md) for browser state and presentation loading.

## Runtime resource and data paths

APEX resolves immutable application resources separately from operator data. In a source checkout, the backend module locates resources and the data directory defaults to that checkout, independent of the current working directory. An absolute `APEX_DATA_DIR` selects another source data directory. Frozen Windows runs use bundled resources and default data to `%LOCALAPPDATA%\APEX`; their data directory cannot be inside the resources or executable installation directory.

Path resolution does not create directories or files. Startup reads the selected profile's `.env` after choosing the data directory. The `.env` file cannot retarget that choice, and `PYTHON_DOTENV_DISABLED` disables loading. Writers create their required data directories when persistence is initialized. APEX does not copy or migrate operator state when the selected data directory changes. See [Configuration](configuration.md#where-settings-live) for the configuration-layer order and operator controls.

## Backend hosting

The backend host supports standalone serving and a managed child with private stdin/stdout control. Both serve the existing HTTP API on `127.0.0.1:8000`. The source launcher uses managed hosting while retaining its static frontend server and browser presentation. The CLI remains an independent HTTP client.

Before application startup, the host reserves the loopback socket and acquires an OS lock in the selected data directory. A port conflict leaves the existing listener untouched. The profile lease prevents another backend from initializing or recovering the same profile; its `.apex-host.lock` marker remains after shutdown, and file existence alone does not imply an active owner. Direct ASGI development also acquires the lease before lifespan startup writes.

Managed control uses version 1 UTF-8 newline-delimited JSON with request correlation, a 64 KiB frame limit, and bounded queues. Ordinary Python and native-library output goes to stderr; stdout is reserved for protocol frames. The parent supplies a launch UUID and compares the child’s private readiness identity with [runtime identity](api.md#get-apiv1runtime) over HTTP before opening the interface. No HTTP shutdown endpoint is exposed.

Parent-channel loss and explicit shutdown use the same bounded lifecycle path. The host advertises the configured application drain interval plus thirty seconds for HTTP task shutdown, dependency cleanup, and forced exit. If work cannot drain, it leaves dependencies and the profile lease intact until process termination. Forced cleanup targets explicitly registered speech-export and managed llama.cpp children, preserving external services and browsers.

Successful Cortex and Briefing runs can emit a private completion event after durable finalization. The event contains only instance identity, run identity, and completion status. Delivery failure does not change the committed run, and the completion event contains no location data.

Speech export is an allowlisted worker subcommand dispatched before backend startup or profile ownership. Source operation invokes Python; frozen operation invokes the bundled application executable. Packaging and desktop presentation are separate from backend API ownership.

## Desktop shell ownership

The packaged Windows desktop application uses Tauri for native presentation and process supervision. It loads the bundled React interface directly in WebView2 and owns one managed backend child on `127.0.0.1:8000`. The shell does not start the source launcher's static frontend server or a separate browser window. The source launcher keeps its existing browser workflow for development and standalone use.

Before admitting API-dependent workspaces, the shell waits for its child and compares the private managed-start identity with `GET /api/v1/runtime`. A port conflict leaves the existing listener untouched and presents a retryable startup state. A child crash returns the shell to a recoverable state; retry must match a new managed backend identity. API requests, Cortex and Briefing streams, and cancellation continue through the existing HTTP contracts. The desktop layer does not own conversations, Briefing artifacts, Agent execution, or persistence.

The WebView uses the native application origin and scoped Tauri capabilities. Frontend platform-specific integrations stay behind the platform boundary; the browser presentation does not load native APIs. Closing the desktop window hides it to the tray and leaves the same backend and CLI available. Tray **Show** restores that window; tray **Quit** shuts down its owned backend through the bounded host lifecycle. A second native launch activates the existing window instead of starting another backend. The shell retains and restores window geometry.

Startup and completion notifications are opt-in Runtime Settings stored in the private `desktop_preferences` control message. The native shell applies OS-level settings and reports OS failures separately from saved preferences. Completion notifications are derived only from successful committed Cortex or Briefing completions, deduplicated for the app session, and use the generic title `APEX` and body `An APEX run has completed.` A hidden or minimized session can show them; run text, identifiers, and provider details are not included.

### Desktop first-run import

The native shell gates its first run on the selected data profile. It offers Fresh Start or a user-selected Import source, while the backend owns preview, validation, copy, and journal recovery. Import takes a consistent SQLite backup and stages managed files before committing; it refuses an active source and any existing destination database. Fresh Start never clears a folder. An incomplete import blocks every host entrypoint from loading profile configuration or persistence until recovery completes. Source data remains intact, and a profile marker records desktop Fresh Start for a database-less profile. External destinations and same-user encrypted Microsoft storage keep their existing ownership rules. See [Configuration](configuration.md#desktop-first-run-and-import) for import inventory and path behavior.

### Device context and Weather

A lifespan-owned backend device-context service stores opt-in, session permission, and a short-lived in-memory fix. Versioned private control messages carry preference revisions, correlated acquisition requests, native results, and coordinate-free state. Instance identity and preference revision fence late responses across disable, retry, and shutdown. The Windows WinRT adapter requests permission only through an explicit foreground Settings action and uses bounded one-time reads; it subscribes to capability changes without collecting continuous position updates.

Weather telemetry and default-location forecast tools share the resolver: explicit location, permitted current device location, then configured `TARGET_LOCATION`. Preflight and catalog checks inspect eligibility without acquiring a fix. Device-backed snapshots are revalidated on an actual Weather refresh, including refreshes within ordinary telemetry cache windows. Configured and headless collection preserve their existing cache behavior. Raw fixes remain private to acquisition and provider parameters; public status and saved Weather evidence contain only source and freshness information. See [Device location](configuration.md#device-location-for-weather) and [Privacy](privacy.md#device-location).

## System components

The browser opens on Launch and provides four peer workspaces: Overview, Briefing, Cortex, and Reports. Navigation does not start telemetry collection or briefing generation. The shared conversation runtime and app-level state owners stay mounted while workspace presentations load on demand. Loading and retry states remain within the requested workspace; see [Presentation loading](../frontend/README.md#presentation-loading).

FastAPI owns connectors, telemetry snapshots, settings, conversations, runs, tools, actions, knowledge, retrieval, briefing sessions, and speech. Its lifespan initializes services, recovers interrupted work, starts background workers, and drains work before closing dependencies. Optional embedding, Kokoro, and managed llama.cpp runtimes are not started by application startup. Retrieval and speech load their optional local engines on demand; an idle sweep releases embedding and Kokoro sessions after five minutes. Configured local LLM idle controls continue to govern their own runtimes.

The **APEX Agent** is the single built-in assistant, identified internally as `apex`. The **Cortex Engine** runs its model turns and tool loops. A model choice determines the provider or local runtime, context limits, reasoning controls, pricing, availability, and supported hosted tools. It does not change the Agent's identity. Naming and workspace definitions belong in [Identity and naming](identity-and-naming.md).

## Telemetry collection

Telemetry collection gathers status from enabled connectors without requiring model inference. Overview begins with Collect Telemetry; preflight and an explicit refresh precede the first usable grid. A failed or unusable first collection leaves a retry or no-data state. Briefing can also collect telemetry without leaving its workspace.

```text
Explicit collection request
    -> connector refresh lifecycle
    -> shared snapshot with source health and freshness
    -> Overview display or briefing evidence selection
```

Connector refreshes run sequentially. The shared snapshot records usable data and source limitations, so one unavailable connector need not hide the others. Cached values retain freshness labels rather than being treated as live observations.

Market uses a separate file-backed cache owned by its client. Collection can fetch Alpha Vantage data; the Market API only reads the cache. Per-symbol request gates handle successful daily fetches, throttling, quota exhaustion, and failure backoff. The frontend reloads Market data when telemetry publishes a collection revision. Charts use daily OHLCV history, while briefings use bounded ticker snapshots and price moves. See [Market data](configuration.md#market-data) for cache and request settings.

Overview includes Weather, Events, Email, Market, and Reminders; APEX no longer collects News headlines as telemetry. Independent read tools such as Brave and Alpha Vantage news search remain available under their own tool and provider policies. Previously saved briefings retain their News evidence and remain readable; new briefing collection does not create News evidence.

## Conversations and model execution

Conversation requests resolve their model and effective controls before entering the Agent loop:

```text
Conversation turn
    -> resolved model, controls, and partition
    -> permitted context and tools
    -> Cortex Engine bounded model/tool loop
    -> provider or local runtime
    -> saved answer, execution metadata, and action evidence
```

Conversation storage owns prompts and answers. Request metadata records the model, provider, runtime, controls, and accepted production or sandbox partition. Idempotent replay uses those choices as well as the Agent identity. Once an asynchronous run is accepted, later settings changes affect subsequent requests rather than changing that run's execution choices.

Provider profiles, tool defaults, hosted capabilities, and schema projections follow the effective request model, including an explicit override. Gemini, OpenAI Responses, and llama.cpp consume native streams even without a live browser observer. Providers own stream cleanup and bounded retries. Gemini can recover an empty non-structured STOP result with one bounded unary call. OpenAI requests use `store=False` and send bounded APEX history instead of relying on provider-owned conversation state.

### Tools and actions

Tool exposure depends on user selection, Agent policy, runtime availability, sandbox restrictions, risk controls, and MCP allowlists. An empty selection exposes no APEX-managed tools. Provider-hosted grounding is controlled separately from APEX and MCP tool schemas.

Write-capable tools create action proposals for operator approval before execution. New proposals use `agent_key="apex"`; historical action records retain their original provenance and checksums. Execution and verification belong to the action service, which records outcomes for later inspection.

### Local inference

One coordinator permits a single local inference execution across Ollama and llama.cpp. Before loading a model, it checks reachability, resident models, installed aliases, and resource gates. Context and reasoning changes apply to the next relevant request. Loading, switching, and unloading share the coordination boundary with inference.

### Runs and activity

The `CortexRunCoordinator` executes asynchronous work in a bounded thread pool. It permits one active run per conversation, returns `409` for overlap and `429` when the pool is full, and reuses an existing run for an identical turn request without taking another slot. [Bounded run limits](configuration.md#bounded-run-limits) defines the settings.

SQLite stores run limits, token accounting, turn and tool counts, timings, stop reasons, and completion evidence in a ledger separate from message text. Unfinished runs become `interrupted` on startup. Cancellation is cooperative: execution checks for it at model-turn and tool boundaries.

Server-Sent Events carry live status, answer deltas, tool activity, and measurements. Bounded process-local buffers support reconnect replay; disconnecting the browser does not cancel the run. These buffers do not survive a server restart.

Completed conversation messages also retain a bounded, sanitized activity timeline. Saved history can show model and tool progress without reconstructing the live event stream. Activity excludes model reasoning and tool argument or result bodies; answer content and tool outputs have their own presentation paths.

## Briefing routes

Briefings create durable sessions through a shared collection, comparison, synthesis, and artifact pipeline:

```text
Profile and explicit model choice
    -> current telemetry and permitted personal evidence
    -> comparison with presented source checkpoints
    -> bounded investigation for Deep
    -> synthesis and validation, or a no-change Catch Up result
    -> canonical artifact, saved evidence, and linked conversation
```

Daily selects current evidence for an orientation. Catch Up compares current source state with compatible checkpoints from completed, presented sessions; different sources can use different prior sessions. Showing an artifact marks it as presented, which is separate from completing generation. When comparison finds no material changes and no synthesis candidates, Catch Up can save a no-change result without a model call.

Accepted context, pending reviews, relevant external reports, and verified action outcomes enter evidence selection only when the selected runtime permits personal context and development mode is off. Pending proposals and reports keep their distinct trust labels. They do not become accepted knowledge by appearing in a briefing.

The session stores the canonical artifact, observed evidence, coverage, comparison, model configuration, and limitations. Its opening conversation message is a rendered copy linked to that artifact. Follow-ups use normal conversation history and context policy, with a small, relevance-ranked slice of cited saved evidence inside the untrusted reference boundary and context budget. Personal-context-derived snapshots remain subject to the selected runtime's retrieval setting. The evidence inspector reads full saved snapshots on demand. Existing saved sessions keep their captured News evidence and comparison records; current source collection and new comparisons do not include News.

Briefings do not silently switch models when the requested model is unavailable or cannot fit a useful prompt. Cancellation, global execution limits, invalid synthesis after repair, and persistence errors do not produce a completed artifact. Demo mode supplies deterministic Daily and Catch Up fixtures; Deep is unavailable.

### Deep investigation

Deep inserts an investigation before synthesis using the shared Agent loop. It selects up to eight relevant read capabilities from current evidence, separately from the saved Agent tool profile. Policy, partition, connector availability, and MCP permissions are checked at selection and invocation. Write, destructive, and provider-hosted tools are excluded.

The investigation prompt includes bounded current evidence and paired historical records with source roles, trust labels, and capture times. It permits at most four calls, 1,024 generated tokens per turn or the lower session output limit, and 180 seconds or half the remaining run time. Model and run limits reserve at least two turns for synthesis, including one repair. Local investigation releases its inference slot before synthesis acquires one.

Selected read results become labeled evidence. The artifact records investigation status and limitations, while the raw investigation transcript is not persisted.

### API and history

The briefing API consists of `GET /api/v1/briefing-profiles` and the `/api/v1/briefing-sessions` routes. The CLI uses the same asynchronous API with origin `cli`; it does not call services or SQLite directly.

The Agent's `get_briefing_history` tool reads at most five newest completed sessions with canonical artifacts from the active partition. It returns bounded content, profile and model identity, timestamps, presentation status, and limitations. Failed or incomplete sessions are excluded before applying the limit. The retired transcript-based briefing pipeline and routes are not supported.

### Speech derived from briefings

Speech preparation starts from a completed canonical artifact. A separate worker makes a bounded adaptation call using the session's model and artifact, validates the resulting highlights, and synthesizes audio through the selected voice engine. It does not collect fresh evidence or run an independent investigation.

The session stores the speech script and references to local audio chunks, tied to the artifact's hash. Playback reuses prepared audio on the APEX host without another model or synthesis call. One speech worker serializes preparation and playback, with explicit stop and shutdown cancellation. Speech failure leaves the canonical briefing available. See the [Speech runtime guide](speech-runtime.md) for delivery behavior and [Privacy](privacy.md#speech) for data sent to voice services.

## Personal context and review

The knowledge store separates immutable source evidence from normalized claims. Sources record origin, occurrence time when known, and capture time. Claim-to-source links distinguish direct statements, model interpretations, and unknown derivation; approval does not change how the evidence originated.

Knowledge history records status changes, evidence links, corrections, conflict decisions, and entity reconciliation. Existing `migration_baseline` entries remain historical records; bootstrap does not create new baselines.

Review proposals freeze source evidence, the proposed mutation, reason codes, and affected record, entity, and alias snapshots. Pending proposals stay outside retrieval. Acceptance uses the action executor and verifier, committing the knowledge mutation, history, retrieval synchronization, and decision in one SQLite write transaction. A stale decision must be refreshed before the operator decides again.

Context assembly reloads retrieved records from the knowledge store before adding them to a prompt. Only active or explicitly conflicting records are eligible, so stale retrieval entries cannot restore superseded or retracted claims. Claims carry provenance, effective-time labels, and inspection references. A pending review marks the current claim as uncertain without inserting its proposed replacement into retrieved context. Briefing selection can include pending proposals separately, as described above.

Retrieved context remains untrusted reference material and counts against the cloud or local context budget. Cortex's Context inspector exposes current wording, original evidence, history, and review decisions separately.

## Context vault publication

The knowledge store remains canonical; the configured vault is a generated Markdown copy. A worker owned by the FastAPI lifespan coalesces committed production changes and publishes selected scopes off the event loop. Manual refresh and managed-copy removal use the same serialization boundary.

Each source transaction advances the production knowledge revision. The worker checks revisions before and after snapshots and publication. If knowledge or the saved selection changes during a refresh, it keeps the state dirty and reconciles again.

SQLite retains ownership hashes, interrupted work, revisions, counts, timestamps, and sanitized errors. Startup recovers pending publication. Failures keep dirty state, receive bounded retries, and then wait for a new change or manual refresh. Disabling publication keeps existing copies; explicit removal deletes tracked files without pruning the destination tree. Completion means files were published locally, not that another application synced or indexed them. See the [Context vault guide](context-vault.md) for selection and cleanup.

## External activity reports

External reports are immutable input, separate from accepted knowledge. Their store records receipt identity, partition, caller-claimed source label, and idempotency key. The separate `new`, `reviewed`, or `dismissed` disposition can change without modifying the report. Valid source-label syntax does not authenticate the caller.

Reports are not indexed for general personal-context retrieval or promoted automatically. When personal-context policy permits, briefing selection can include at most three relevant, non-dismissed reports from the newest 50 candidates as untrusted evidence.

Cortex exposes `search_activity_reports` and `get_activity_report` as native read-only tools in the Reports family and Personal Ops profile. Discovery searches titles, outcomes, subjects, and projects, excluding dismissed reports unless requested. Exact reads can include dismissed reports. Results are bounded to 8,000 serialized characters and return continuation cursors for older receipts or remaining report content. Markdown and finding text are readable through the detail tool but are not searched.

Cortex report reads require the effective model runtime's personal-context setting and a production run outside demo and development modes. Execution binds the admitted partition and model to the capability worker, and each read rechecks access. Report content remains untrusted, source labels remain caller-declared, and reading does not change disposition or accept knowledge. References are returned without fetching URLs or files. Deep retains its existing report-evidence selection and does not gain these tools.

An operator can select a finding for a pending context review. The server freezes its text, evidence locator, external origin, and occurrence time. Locators identify `/findings/<index>`, or `/outcome` and `/markdown_body` when no structured finding exists. A declared `model_interpretation` remains an interpretation; otherwise derivation is `unknown`. Only acceptance creates a knowledge record eligible for retrieval.

The Reports workspace reads a bounded list and exact details, changes disposition, and opens linked reviews in Cortex. It retains the selected partition. Report text and external references remain untrusted display data: Markdown renders without raw HTML and links are limited to HTTP(S).

The opt-in loopback gateway exposes submission through JSON HTTP and Streamable HTTP MCP. It shares the activity store with CLI and file import, uses the local `operator` principal, and derives the partition server-side. It does not expose report reads, main application routes, Agent execution, actions, or proxy access. Its process-wide limit is 30 combined JSON and MCP attempts per minute. Because it does not authenticate remote callers, it must not be exposed through a tunnel or reverse proxy. Setup belongs in [Configuration](configuration.md#external-activity-gateway).

## Persistence and lifecycle

SQLite owns conversations, runs, briefing sessions, knowledge and review history, actions, external reports, and derived retrieval records. The browser owns presentation state; vault notes, retrieval indexes, and speech output are derived from application records rather than replacing them.

On shutdown, FastAPI signals speech cancellation and closes run admission. It drains active runs and application-owned tasks, then the speech worker, before releasing stores, connectors, and other dependencies. A failed drain leaves dependencies open, avoiding cleanup underneath a running worker. The [backend host](#backend-hosting) enforces the overall shutdown deadline and retains profile ownership until it can release safely or the process exits.

### Persistence compatibility

The v2.0.0-beta.6 database schema is the supported upgrade floor. Before bootstrap or recovery, startup checks core persistence versions and required table shapes through a read-only connection. Fresh databases receive the current schema. Unsupported core schemas stop startup without rewriting data or deleting tables; APEX does not automatically migrate older schemas.

Fresh `cortex_runs` tables no longer allow `max_total_tokens` as a stop reason. Existing databases may retain that older table constraint; this does not block startup, and APEX does not rebuild it automatically. To normalize an existing database, stop APEX and run `uv run python scripts/normalize_run_constraint.py --database path\to\apex_memory.db --apply`. Without `--apply`, the command checks eligibility without changing the database. It refuses unsupported table shapes and rows that use the retired stop reason. On an eligible apply, it takes a uniquely named adjacent SQLite backup, then rebuilds only the `cortex_runs` table and validates its rows, indexes, triggers, foreign keys, and database integrity before committing. The `RunLimitSnapshot` reader still accepts historical snapshots containing `max_total_tokens`.

Unsupported retrieval persistence disables retrieval for that run while canonical knowledge writes continue without derived synchronization. Conversation deletion and archived-conversation retention are also deferred because message deletion triggers can update retrieval rows. Manual deletion returns `409 Conflict`; retention logs the failed sweep and retries on its next scheduled pass.

Initialization leaves any residual retired `briefings` table untouched. See [Configuration](configuration.md#briefing-profiles) for ignored legacy preferences and [Privacy](privacy.md#retention-and-deletion) for retained data and deletion boundaries.

## Distributed tracing

When configured, OpenTelemetry exports failure-isolated traces for the root run (`invoke_agent`), model calls, and tool execution using GenAI semantic conventions. Explicit attributes contain model identifiers, tokens, counters, and timings without adding prompt or answer content. Exceptions escaping tracing contexts can still record messages and stack traces. See [Configuration](configuration.md#opentelemetry-genai-tracing) for setup and [Privacy](privacy.md#distributed-tracing) for that limitation.
