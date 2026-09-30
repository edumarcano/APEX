# Architecture

APEX is a local-first personal intelligence HUD. FastAPI serves the backend, React opens on a Launch screen and provides Overview, Briefing, Cortex, and Reports as peer workspaces, SQLite owns durable application state, and optional providers and connectors stay behind explicit capability and privacy boundaries.

## Core model

- **Launch** is the initial view after each page load. It exposes workspace navigation, Settings, and the active DEMO/DEVELOPER indicator without loading a snapshot or starting collection.
- **Overview** initially shows only its central identity card and **Collect Telemetry**. The explicit action runs preflight, refreshes sources, then opens the grid when a usable snapshot exists; unavailable sources leave a centered retry state. Workspace navigation itself has no collection or voice-cue side effect.
- **Briefing** covers profile controls, the saved briefing thread, and a single telemetry panel. It opens without activation; generation and setup stay Briefing-local.
- **Cortex** is the control surface for conversations, model settings, tool selection, context, and approval-gated actions.
- **Reports** is the dedicated list-and-detail workspace for immutable, untrusted reports with caller-claimed source labels.
- **APEX Agent** is the single native personal operations assistant. It understands APEX briefings, trusted context, connected services, and APEX tools.
- **Cortex Engine** executes bounded model turns and tool loops. It is model-routed, not Agent-routed.

Launch and Overview load with the app shell; Settings loads on first open, while Briefing, Cortex, and Reports load when selected. The shared `ApexAssistantRuntime` and app-level state owners remain mounted as those workspace presentations load. Loading and retry states stay within the requested workspace, so navigating between views does not discard conversation drafts, history, or active work. See the [frontend guide](../frontend/README.md#presentation-loading) for loading ownership and the production loading check.

The selected model determines cloud versus local execution, provider/runtime, model limits, pricing, availability, supported reasoning and context controls, and hosted tools. The stable Agent identity is always `apex`.

## Request flow

```text
Overview, Briefing, or Cortex
    -> selected model and effective controls
    -> APEX Agent policy and tool projection
    -> Cortex Engine bounded loop
    -> provider or local runtime
    -> durable conversation metadata and action evidence
```

Conversation storage owns prompts and answers. Turn request metadata records the resolved model, provider, runtime, effective controls, and accepted partition so idempotent replay distinguishes executions that use the same APEX Agent identity. An accepted asynchronous run keeps those execution choices through completion even if later settings changes affect subsequent requests.

Provider profiles, tool defaults, hosted capabilities, and schema projections follow the effective request model, including an explicit override. Gemini, OpenAI Responses, and llama.cpp consume native streams even without a live UI observer. Stream cleanup and bounded retries remain provider-owned; Gemini can recover an empty non-structured STOP result with one bounded unary call. OpenAI requests use `store=False` and carry bounded APEX history rather than relying on provider-owned conversation state.

## Tool and action boundary

Tool exposure is the intersection of user selection, APEX Agent policy, runtime availability, sandbox restrictions, risk controls, and MCP allowlists. An empty selection means no APEX-managed tools. Provider-hosted grounding is separate from APEX and MCP tool schemas.

Write-capable tools create approval-gated action proposals. New proposals use `agent_key="apex"`; historical action records retain their immutable provenance and checksums.

## Personal context provenance

Personal context keeps immutable source evidence separate from the normalized claim derived from it. A source records its origin, occurrence time when known, and capture time. Each claim-to-source link records whether the claim was direct, model-interpreted, or unknown, so approval does not turn a model interpretation into a direct operator statement.

Knowledge history records later status changes, evidence links, corrections, conflict decisions, and entity reconciliation against the affected claim. Existing `migration_baseline` entries remain historical records; current bootstrap does not synthesize new baselines.

## External activity boundary

External activity reports use their own SQLite table, receipt identity, partition, caller-claimed source label, idempotency key, and reversible report disposition. The ID syntax is checked at the shared service boundary but does not authenticate the caller. Their structured JSON and Markdown body stay immutable after receipt. Stable future-review evidence locations point to `/findings/<index>`, or to `/outcome` and `/markdown_body` when no structured finding exists.

Activity reports have no retrieval synchronization, general prompt assembly caller, attention integration, or automatic trust-promotion path. A Daily run may select up to three relevant, non-dismissed reports from the newest 50 candidates and include bounded excerpts as explicitly untrusted evidence. An operator may also select one immutable finding and create a linked pending context review. The server freezes the selected report text, locator, external source origin, and occurrence time as `external_activity` evidence; a finding can declare `model_interpretation`, otherwise its derivation is `unknown`. Only accepted context reviews write a normal knowledge record and retrieval entry.

Reports reads a bounded report list and exact report detail, lets the operator set the separate `new`, `reviewed`, or `dismissed` disposition, and opens linked decisions in Cortex Review. It never changes partitions automatically. Report text, Markdown, and external references remain untrusted display data; the HUD renders text without raw HTML and enables only HTTP(S) links.

An opt-in process on loopback can expose only activity submission through JSON HTTP and Streamable HTTP MCP. It opens the same activity store as local CLI and file import, resolves the generic local `operator` principal, and derives the current partition server-side. The process has no main API routes, Cortex initialization, connectors, report reads, resources, prompts, actions, or proxy behavior. Its process-wide rate limit allows 30 combined JSON and MCP attempts per minute. The gateway does not authenticate remote callers and must not be placed behind a tunnel or reverse proxy.

## Context review

The knowledge store owns durable review proposals. A review freezes source
evidence, the proposed mutation, reason codes, and affected record, entity, and
alias snapshots before a decision. Pending proposals remain outside retrieval. Acceptance uses
the existing action executor and verifier, and commits the knowledge mutation,
history, retrieval synchronization, and review decision in one SQLite write
transaction.

Context assembly reloads each selected personal record from the knowledge store
before it enters a prompt. It includes only active or explicitly conflicting
records, so stale retrieval entries cannot restore superseded or retracted
claims. Each rendered claim carries concise provenance and effective-time labels
plus pointers to its source and history inspection views. A pending review
labels the current claim as uncertain without adding the proposed text.
Retrieved context remains inside the untrusted reference boundary and counts
against the existing cloud or local context budget.

Cortex's Context inspector keeps record evidence and review decisions separate.
Its Records view shows current normalized wording beside immutable source text,
times, history, and related records. Its Review view compares pending proposed
information with current evidence; proposed text remains non-current until the
operator accepts it. A stale decision must be refreshed and deliberately
decided again.

## Context vault publication

APEX keeps canonical knowledge in the knowledge store and treats the configured
vault as a generated local copy. One worker owned by the FastAPI lifespan
coalesces committed production changes, snapshots all enabled scopes, renders
Markdown, and publishes files off the event loop. Manual refresh and managed
copy removal use the same serialization boundary. SQLite advances the
production knowledge revision in each source transaction; a before-and-after
revision check catches changes across the per-scope snapshots and publication.
If the revision or saved selection changes mid-refresh, the worker leaves the
state dirty and reconciles again.

The publisher and runtime keep ownership hashes, interrupted work, revisions,
counts, timestamps, and sanitized errors in the local application database.
Startup reconciles enabled scopes and recovers pending publication. Failures
retain dirty state, receive a bounded retry window, and wait for a new change or
manual refresh afterward. Disablement retains generated files; explicit removal
deletes only tracked files and never prunes the destination tree. Export status
reports local completion, not sync or indexing by another application.

The [Context vault guide](context-vault.md) covers selection, sharing, and cleanup from the operator's view.

## Market telemetry

Market participates in both Overview telemetry and briefing evidence collection. Telemetry refreshes it in the normal sequential connector lifecycle and records its health in the shared snapshot. The Market client owns Alpha Vantage access, a versioned file-backed cache, and per-symbol daily request gates; the Market route only reads that cache. A successful symbol fetch is limited to once per UTC calendar day. Temporary provider throttling uses a short same-day cooldown, daily quota exhaustion defers requests until the next UTC day, and other symbol failures use exponential date-based backoff up to eight days. Daily OHLCV history stays in the Market display projection, while briefing evidence captures bounded ticker snapshots and price moves for synthesis and Catch Up comparison without chart payload overhead. Overview updates its card only after collection.

## Local runtime coordination

APEX permits one local inference execution across Ollama and llama.cpp. The coordinator validates reachability, resident models, installed aliases, and resource gates before loading. The selected model’s context and reasoning controls apply on the next relevant request; unloading remains provider-neutral.

## Bounded run coordination and live activity

Cortex runs execute asynchronously through the `CortexRunCoordinator`. A run carries one request through bounded model turns, tool execution, and action proposals:

- **Admission and concurrency:** A thread pool bounds active runs (`max_concurrent_runs`, default 2). The coordinator enforces one active run per conversation, returning `409` on overlap and `429` on pool saturation. Identical turn requests matching an existing `agent_message_id` return the existing run without consuming a slot.
- **Durable run ledger:** SQLite records run metadata in the `cortex_runs` table partitioned by `production` and `sandbox`. Records capture limits, token totals, turn/tool counts, timings, stop reasons, and completion evidence. Message text stays in conversation persistence rather than being duplicated in the ledger. On startup, unfinished runs are safely finalized as `interrupted`.
- **Live streaming:** Process-local Server-Sent Events stream live status, deltas, tool activity, and runtime measurements. Streams support reconnect replay from bounded in-memory buffers; disconnecting a client does not cancel the underlying run.
- **Cooperative cancellation:** Active runs poll for cancellation at turn and tool boundaries, writing a cancellation marker and finalizing as `cancelled`.
- **Shutdown ownership:** Application shutdown signals briefing-speech cancellation and closes run admission, then drains active Cortex runs and application-owned tasks before draining the speech worker and releasing conversation, run, retrieval, connector, and action dependencies. One bounded shutdown window reports failure and leaves those dependencies open if a Cortex run, speech worker, or application-owned task remains active.

## Distributed tracing

When configured, APEX exports failure-isolated distributed traces using OpenTelemetry GenAI semantic conventions. Tracing covers the root run span (`invoke_agent`), model provider calls, and tool execution. Spans record model identifiers, tokens, counters, and timings, while preserving a zero-content privacy guarantee that omits prompt text, answers, and raw exceptions.

## Briefing routes

Briefing's Daily, Catch Up, and Deep actions create durable sessions and use the same bounded collection, history, synthesis, and artifact path with the explicitly selected APEX Agent model. Deep adds an `investigating` stage that offers up to eight evidence-selected read capabilities through the shared Agent loop, with current policy, partition, connector, and MCP checks enforced both at selection and invocation. Its bounded investigation prompt includes selected current evidence and paired historical records with their role, capture time, trust, and content. The stage is limited to four calls, at most 1,024 generated tokens per turn or the lower session output limit, and at most 180 seconds or half of remaining run time; run/model turn limits reserve at least two turns for synthesis, including one repair. Local investigation admission is released before synthesis admission, avoiding a nested local-model lease. A completed artifact records bounded investigation status and limitations; cancellation, global run limits, invalid synthesis, and persistence errors do not produce a completed artifact. The session owns a conversation whose rendered opening assistant message is linked to the artifact; the canonical artifact and evidence remain in briefing-session storage. Follow-up turns use the ordinary conversation history and context policy. A small, relevance-ranked slice of cited saved evidence is attached inside the existing untrusted retrieved-context boundary and budget; personal-context-derived snapshots follow the selected runtime's retrieval setting. The saved evidence inspector still reads the complete snapshots on demand. Briefings do not silently switch models when the selected model is unavailable or its context cannot fit a useful prompt. Deep is unavailable in demo mode.

The canonical briefing API consists of `GET /api/v1/briefing-profiles` and the `/api/v1/briefing-sessions` routes. The CLI uses the same asynchronous session API and marks its constrained origin as `cli`; it does not call services or SQLite directly. The Agent's `get_briefing_history` tool queries at most five newest completed artifact-backed sessions from the active partition in one joined read and returns bounded canonical content, profile/model identity, timestamps, presentation status, and limitations. Failed or incomplete sessions are skipped before applying the limit. The old transcript-based pipeline, mode settings, routes, and status poll are retired.

## Persistence compatibility

The beta.6 database schema is the supported upgrade floor. A fresh database is bootstrapped to the current schema. Before startup performs any bootstrap or recovery, APEX checks core persistence versions and required table shapes through a read-only connection. An unsupported core schema stops startup without rewriting data or deleting tables. A database with an unsupported retrieval schema can still start with retrieval disabled for that run; canonical knowledge writes continue without derived retrieval synchronization. Conversation deletion and archived-conversation retention are also deferred while retrieval persistence is unsupported, because message deletion triggers can update retrieval rows. Manual deletion returns `409 Conflict`; the retention worker logs the failed sweep and retries on its next scheduled pass. APEX does not automatically migrate older database schemas. Current initialization leaves any residual retired `briefings` table untouched. See [Configuration](configuration.md#briefing-profiles) for the ignored legacy preference behavior and [Privacy](privacy.md#briefings) for local storage implications.
