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

## Briefing routes

Interactive selection never changes briefing execution. Focused uses OpenRouter DeepSeek V4 Flash with High reasoning, Flash uses the fixed Gemma E2B llama.cpp route at 16K with reasoning disabled, and Structured is deterministic. Fallback is Focused, Flash, then Structured.
