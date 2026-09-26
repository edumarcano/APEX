# Architecture

APEX is a local-first personal intelligence HUD. FastAPI serves the backend, React provides Home, Cortex, and Inbox, SQLite owns durable application state, and optional providers and connectors stay behind explicit capability and privacy boundaries.

## Core model

- **Home** moves between Standby, Overview (telemetry and reminders), and Briefing (profile controls, the saved briefing thread, and a telemetry rail).
- **Cortex** is the control surface for conversations, model settings, tool selection, context, and approval-gated actions.
- **Inbox** is the dedicated list-and-detail workspace for immutable, untrusted reports with caller-claimed source labels.
- **Apex Agent** is the single native personal operations assistant. It understands APEX briefings, trusted context, connected services, and APEX tools.
- **Cortex Engine** executes bounded model turns and tool loops. It is model-routed, not Agent-routed.

The selected model determines cloud versus local execution, provider/runtime, model limits, pricing, availability, supported reasoning and context controls, and hosted tools. The stable Agent identity is always `apex`.

## Request flow

```text
Home or Cortex
    -> selected model and effective controls
    -> Apex Agent policy and tool projection
    -> Cortex Engine bounded loop
    -> provider or local runtime
    -> durable conversation metadata and action evidence
```

Conversation storage owns prompts and answers. Turn request metadata records the resolved model, provider, runtime, effective controls, and accepted partition so idempotent replay distinguishes executions that use the same Apex Agent identity. An accepted asynchronous run keeps those execution choices through completion even if later settings changes affect subsequent requests.

## Tool and action boundary

Tool exposure is the intersection of user selection, Apex Agent policy, runtime availability, sandbox restrictions, risk controls, and MCP allowlists. An empty selection means no APEX-managed tools. Provider-hosted grounding is separate from APEX and MCP tool schemas.

Write-capable tools create approval-gated action proposals. New proposals use `agent_key="apex"`; historical action records retain their immutable provenance and checksums.

## Personal context provenance

Personal context keeps immutable source evidence separate from the normalized claim derived from it. A source records its origin, occurrence time when known, and capture time. Each claim-to-source link records whether the claim was direct, model-interpreted, or unknown, so approval does not turn a model interpretation into a direct operator statement.

Knowledge history records later status changes, evidence links, corrections, conflict decisions, and entity reconciliation against the affected claim. Records upgraded from earlier schemas receive a `migration_baseline` history entry with unknown provenance; it marks the start of durable history without inventing older events or attribution.

## External activity boundary

External activity reports use their own SQLite table, receipt identity, partition, caller-claimed source label, idempotency key, and reversible inbox disposition. The ID syntax is checked at the shared service boundary but does not authenticate the caller. Their structured JSON and Markdown body stay immutable after receipt. Stable future-review evidence locations point to `/findings/<index>`, or to `/outcome` and `/markdown_body` when no structured finding exists.

Activity reports have no retrieval synchronization, general prompt assembly caller, attention integration, or automatic trust-promotion path. A Daily run may select up to three relevant, non-dismissed reports from the newest 50 candidates and include bounded excerpts as explicitly untrusted evidence. An operator may also select one immutable finding and create a linked pending context review. The server freezes the selected report text, locator, external source origin, and occurrence time as `external_activity` evidence; a finding can declare `model_interpretation`, otherwise its derivation is `unknown`. Only accepted context reviews write a normal knowledge record and retrieval entry.

Inbox reads a bounded report list and exact report detail, lets the operator set the separate `new`, `reviewed`, or `dismissed` disposition, and opens linked decisions in Cortex Review. It never changes partitions automatically. Report text, Markdown, and external references remain untrusted display data; the HUD renders text without raw HTML and enables only HTTP(S) links.

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

Market is a telemetry connector for Home rather than a briefing fact source. Telemetry refreshes it in the normal sequential connector lifecycle and records its health in the shared snapshot. The Market client owns Alpha Vantage access, a versioned file-backed cache, and per-symbol daily request gates; the Market route only reads that cache. A symbol can make at most one request per UTC calendar day. Repeated failures back off for 1, 2, 4, then up to 8 days, while provider-wide transport, authentication, or rate failures defer remaining requests until the next UTC day. Daily OHLCV history stays in the Market display projection, while the telemetry snapshot carries only bounded symbol summaries and a collection revision. This keeps chart data out of briefing payloads and lets Home update the card only after collection.

## Local runtime coordination

APEX permits one local inference execution across Ollama and llama.cpp. The coordinator validates reachability, resident models, installed aliases, and resource gates before loading. The selected model’s context and reasoning controls apply on the next relevant request; unloading remains provider-neutral.

## Bounded run coordination and live activity

Cortex runs execute asynchronously through the `CortexRunCoordinator`. A run carries one request through bounded model turns, tool execution, and action proposals:

- **Admission and concurrency:** A thread pool bounds active runs (`max_concurrent_runs`, default 2). The coordinator enforces one active run per conversation, returning `409` on overlap and `429` on pool saturation. Identical turn requests matching an existing `agent_message_id` return the existing run without consuming a slot.
- **Durable run ledger:** SQLite records run metadata in the `cortex_runs` table partitioned by `production` and `sandbox`. Records capture limits, token totals, turn/tool counts, timings, stop reasons, and completion evidence. Message text stays in conversation persistence rather than being duplicated in the ledger. On startup, unfinished runs are safely finalized as `interrupted`.
- **Live streaming:** Process-local Server-Sent Events stream live status, deltas, tool activity, and runtime measurements. Streams support reconnect replay from bounded in-memory buffers; disconnecting a client does not cancel the underlying run.
- **Cooperative cancellation:** Active runs poll for cancellation at turn and tool boundaries, writing a cancellation marker and finalizing as `cancelled`.
- **Shutdown ownership:** Application shutdown first closes run admission and signals active runs, then drains the retrieval warmup, managed llama.cpp startup, and idle-model monitor before releasing conversation, run, retrieval, connector, and action dependencies. One bounded shutdown window reports failure and leaves those dependencies open if a run worker or application-owned task remains active.

## Distributed tracing

When configured, APEX exports failure-isolated distributed traces using OpenTelemetry GenAI semantic conventions. Tracing covers the root run span (`invoke_agent`), model provider calls, and tool execution. Spans record model identifiers, tokens, counters, and timings, while preserving a zero-content privacy guarantee that omits prompt text, answers, and raw exceptions.

## Briefing routes

Home's Daily action creates a durable session, runs bounded collection and synthesis with the explicitly selected Apex Agent model, and stores a canonical artifact with its source coverage and evidence. The session owns a conversation whose rendered opening assistant message is linked to the artifact; the canonical artifact and evidence remain in briefing-session storage. Follow-up turns use the ordinary conversation history and context policy. A small, relevance-ranked slice of cited saved evidence is attached inside the existing untrusted retrieved-context boundary and budget; personal-context-derived snapshots follow the selected runtime's retrieval setting. The saved evidence inspector still reads the complete snapshots on demand. Daily does not silently switch models when the selected model is unavailable or its context cannot fit a useful prompt.

The legacy compatibility routes retain their fixed behavior: Focused uses OpenRouter DeepSeek V4 Flash with High reasoning, Flash uses the fixed Gemma E2B llama.cpp route at 16K with reasoning disabled, and Structured is deterministic. Their fallback order remains Focused, Flash, then Structured.
