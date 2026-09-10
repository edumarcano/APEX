# Architecture

APEX is a local-first personal intelligence HUD. FastAPI serves the backend, React provides Home and Cortex, SQLite owns durable application state, and optional providers and connectors stay behind explicit capability and privacy boundaries.

## Market telemetry

Market is a telemetry connector for Home rather than a briefing fact source. Telemetry refreshes it in the normal sequential connector lifecycle and records its health in the shared snapshot. The Market client owns Alpha Vantage access, a versioned file-backed cache, and per-symbol daily request gates; the Market route only reads that cache. A symbol can make at most one request per UTC calendar day. Repeated failures back off for 1, 2, 4, then up to 8 days, while provider-wide transport, authentication, or rate failures defer remaining requests until the next UTC day. Daily OHLCV history stays in the Market display projection, while the telemetry snapshot carries only bounded symbol summaries and a collection revision. This keeps chart data out of briefing payloads and lets Home update the card only after collection.

## Core model

- **Home** presents briefings, telemetry, reminders, and quick interaction.
- **Cortex** is the control surface for conversations, model settings, tool selection, context, and approval-gated actions.
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

## Context review

The knowledge store owns durable review proposals. A review freezes source
evidence, the proposed mutation, reason codes, and affected record, entity, and
alias snapshots before a decision. Pending proposals remain outside retrieval. Acceptance uses
the existing action executor and verifier, and commits the knowledge mutation,
history, retrieval synchronization, and review decision in one SQLite write
transaction.

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

Interactive selection never changes briefing execution. Focused uses OpenRouter DeepSeek V4 Flash with High reasoning, Flash uses the fixed Gemma E2B llama.cpp route at 16K with reasoning disabled, and Structured is deterministic. Fallback is Focused, Flash, then Structured.
