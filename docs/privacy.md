# Privacy

APEX is local-first: durable settings, conversation history, retrieval data, context records, action evidence, the Cortex run ledger, and briefing history remain on the local machine unless a selected operation requires an enabled connector or model provider.

## Interactive models

The selected model determines the inference boundary. Cloud model requests may send the bounded prompt, active-branch history, explicitly selected APEX or MCP schemas, and any context allowed by the relevant runtime policy. Local model requests use the configured Ollama or llama.cpp endpoint. Personal-context retrieval is disabled by default for both runtimes.

Provider-hosted grounding is separate from APEX-managed tool calls. It is enabled only when the selected cloud model supports it and the corresponding Runtime Settings switch is enabled.

## Briefings

Focused briefings use the fixed OpenRouter DeepSeek V4 Flash route with its privacy requirements. Flash briefings use the fixed local Gemma route. Interactive model selection does not affect either briefing route. Structured briefings call no model.

## Tools and actions

APEX tools pass only the arguments required for the requested operation. Tool output is treated as untrusted model data. Write operations are approval-gated, create local action evidence, and are not replayed automatically after ambiguous outcomes.

## Distributed tracing

OpenTelemetry tracing is optional and disabled by default. When an operator configures an OTLP export endpoint in `.env`, trace spans are sent to that destination. Tracing adheres to GenAI semantic conventions and preserves a zero-content privacy guarantee: spans capture run metadata, model names, token counts, timings, and status, but never include prompt text, model answers, or raw exception payloads.

## Development and demo

`DEV_MODE` masks sensitive briefing inputs before sandbox use. Sandbox uses a restricted non-personal tool allowlist and isolated history. `DEMO_MODE` uses deterministic fixtures and does not contact configured connectors or model providers on demo paths.

Credentials belong in `.env` or the local environment, never in `config.json`, `config.local.json`, documents, or source control.
