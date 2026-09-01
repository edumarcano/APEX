# APEX Identity and Naming

This document defines the product names used in APEX. Runtime behavior belongs in [Architecture](architecture.md), settings in [Configuration](configuration.md), and HTTP contracts in [API](api.md).

## Main names

```text
APEX
├── Home
│   └── Briefing modes: Focused, Flash, Structured
└── Cortex
    ├── Cortex workspace
    ├── Cortex Engine
    └── Apex Agent
        ├── Cloud models
        └── Local models
```

- **APEX** is the complete local-first product: Home, Cortex, telemetry, briefings, voice, connectors, settings, and persistence.
- **Home** is the day-to-day workspace for telemetry, briefings, reminders, connector health, and a compact Apex Agent prompt.
- **Cortex** is the detailed workspace for conversations, model settings, tools, context, action review, and local-model lifecycle.
- **Cortex Engine** is the backend execution boundary for bounded Agent turns, context assembly, tools, providers, and local runtime coordination.
- **Apex Agent** is APEX's single built-in personal operations assistant.
- A **model** is the selected execution model. Its catalog profile determines whether the turn uses a cloud provider or local runtime and which controls are available.

## Apex Agent

Apex Agent works with briefings, trusted personal context, connected services, APEX actions, and results returned by external workers. Its role is fast, everyday operation within APEX. It is not intended to compete with general-purpose autonomous agents or external chat products.

The Agent identity, safety policy, and APEX-specific instructions stay consistent. Selecting a model changes execution characteristics such as provider or runtime, reasoning choices, local context limits, hosted capabilities, availability, and price. It does not select a different Agent.

The product uses the singular name **Apex Agent**. A future distinct assistant would need a different durable role, not merely a different model or provider.

## Briefing modes

**Focused**, **Flash**, and **Structured** are briefing modes, not Agent identities.

- **Focused** uses the fixed OpenRouter DeepSeek V4 Flash route with High reasoning.
- **Flash** uses the fixed local Gemma E2B llama.cpp route at 16K with reasoning disabled.
- **Structured** renders normalized facts without a model.

The interactive model selection does not change these routes. Historical briefing records can retain older runtime metadata as evidence of how they were produced.

## APEX and the logo

**APEX** stands for **Automated Personal Environment Xylem**. An apex is the highest point of a structure; xylem carries material upward through a plant. Together they describe the product’s purpose: bring useful local and connected signals into one place for review.

The logo combines those ideas. Its outer shape forms an A and suggests a layered apex, while its center resembles an upward xylem channel.

<p align="center">
  <img
    src="assets/apex-logo.png"
    alt="The APEX logo, combining an angular A-shaped outer structure with a central upward xylem channel"
    width="420"
  >
</p>

## Naming rules

- Use **APEX** for the product by itself.
- Use **Apex Agent** for the native assistant.
- Use **Cortex workspace** for the user interface and **Cortex Engine** for backend execution.
- Use model, provider, and runtime names directly; do not turn them into Agent identities.
- Use **Focused**, **Flash**, and **Structured** only for briefing modes.

The former cloud/local runtime identities were retired. They can appear only in migration code and preserved historical records, such as the changelog and roadmap.
