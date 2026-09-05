# Architecture

APEX is a local-first personal intelligence HUD. FastAPI serves the backend, React provides Home and Cortex, SQLite owns durable application state, and optional providers and connectors stay behind explicit capability and privacy boundaries.

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

Conversation storage owns prompts and answers. Turn request metadata records the resolved model, provider, runtime, and effective controls so idempotent replay distinguishes executions that use the same Apex Agent identity.

## Tool and action boundary

Tool exposure is the intersection of user selection, Apex Agent policy, runtime availability, sandbox restrictions, risk controls, and MCP allowlists. An empty selection means no APEX-managed tools. Provider-hosted grounding is separate from APEX and MCP tool schemas.

Write-capable tools create approval-gated action proposals. New proposals use `agent_key="apex"`; historical action records retain their immutable provenance and checksums.

## Local runtime coordination

APEX permits one local inference execution across Ollama and llama.cpp. The coordinator validates reachability, resident models, installed aliases, and resource gates before loading. The selected model’s context and reasoning controls apply on the next relevant request; unloading remains provider-neutral.

## Bounded run coordination and live activity

Cortex runs execute asynchronously through the `CortexRunCoordinator`. A run carries one request through bounded model turns, tool execution, and action proposals:

- **Admission and concurrency:** A thread pool bounds active runs (`max_concurrent_runs`, default 2). The coordinator enforces one active run per conversation, returning `409` on overlap and `429` on pool saturation. Identical turn requests matching an existing `agent_message_id` return the existing run without consuming a slot.
- **Durable run ledger:** SQLite records run metadata in the `cortex_runs` table partitioned by `production` and `sandbox`. Records capture limits, token totals, turn/tool counts, timings, stop reasons, and completion evidence. Message text stays in conversation persistence rather than being duplicated in the ledger. On startup, unfinished runs are safely finalized as `interrupted`.
- **Live streaming:** Process-local Server-Sent Events stream live status, deltas, tool activity, and runtime measurements. Streams support reconnect replay from bounded in-memory buffers; disconnecting a client does not cancel the underlying run.
- **Cooperative cancellation:** Active runs poll for cancellation at turn and tool boundaries, writing a cancellation marker and finalizing as `cancelled`.

## Distributed tracing

When configured, APEX exports failure-isolated distributed traces using OpenTelemetry GenAI semantic conventions. Tracing covers the root run span (`invoke_agent`), model provider calls, and tool execution. Spans record model identifiers, tokens, counters, and timings, while preserving a zero-content privacy guarantee that omits prompt text, answers, and raw exceptions.

## Briefing routes

Interactive selection never changes briefing execution. Focused uses OpenRouter DeepSeek V4 Flash with High reasoning, Flash uses the fixed Gemma E2B llama.cpp route at 16K with reasoning disabled, and Structured is deterministic. Fallback is Focused, Flash, then Structured.
