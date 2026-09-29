# APEX Identity and Naming

This document defines the product names used in APEX. Runtime behavior belongs in [Architecture](architecture.md), settings in [Configuration](configuration.md), and HTTP contracts in [API](api.md).

## Main names

```text
APEX
├── Overview
│   └── Telemetry, reminders, and connector health
├── Briefing
│   ├── Profiles: Daily, Catch Up, Deep
│   └── Saved sessions and linked conversations
├── Cortex
│   ├── Cortex workspace
│   ├── APEX Agent (Lynx by default; full workspace)
│   └── Cortex Engine
└── Reports
    └── External activity reports
```

- **APEX** is the complete local-first product: Overview, Briefing, Cortex, Reports, telemetry, briefings, voice, connectors, settings, and persistence.
- **Overview** is the telemetry-first workspace for reminders, connector health, and the grid shown after an explicit telemetry collection.
- **Briefing** is the workspace for profile controls, saved briefing sessions, linked conversations, and briefing-local telemetry.
- **Cortex** is the detailed workspace for conversations, model settings, tools, context, action review, and local-model lifecycle.
- **Reports** is the workspace for untrusted external activity reports, their reversible dispositions, and links to existing context reviews.
- **Cortex Engine** is the backend execution boundary for bounded Agent turns, context assembly, tools, providers, and local runtime coordination.
- **APEX Agent** is APEX's single built-in personal operations assistant role, with a compact Overview and Briefing prompt and a full Cortex workspace.
- **Lynx** is the default user-facing display name and prompt identity for the APEX Agent when no custom name is configured.
- A **model** is the selected execution model. Its catalog profile determines whether the turn uses a cloud provider or local runtime and which controls are available.

## APEX Agent and Lynx

**APEX Agent** is the canonical architectural and product role for APEX's native assistant. It works with briefings, trusted personal context, connected services, and APEX actions. Its role is fast, everyday operation within APEX. It is not intended to compete with general-purpose autonomous agents or external chat products.

**Lynx** is the default user-facing display name and prompt identity for the APEX Agent when no custom name is configured. A local display name preference (`agent_display_name`) may replace Lynx in visible HUD surfaces and prompt self-addressing, while the canonical role remains APEX Agent and the internal stable key remains `apex`.

The name **Lynx** connects the product's deep-space aesthetic with its personal intelligence focus: it refers both to the northern constellation cataloged by Johannes Hevelius (chosen because its faint stars require keen sight to discern) and the animal known for acute observation and precision.

The Agent identity, safety policy, and APEX-specific instructions stay consistent. Selecting a model changes execution characteristics such as provider or runtime, reasoning choices, local context limits, hosted capabilities, availability, and price. It does not select a different Agent.

Overview, Briefing, and Cortex use the same singular **APEX Agent** role and shared model selection. Selecting a model never selects a different Agent. A local display name may replace Lynx as the visible name and the assistant's self-name in prompts; it is not a second Agent.

## Briefing profiles

**Daily**, **Catch Up**, and **Deep** are profiles for the single briefing-session engine. Daily provides orientation, Catch Up compares source evidence with the last presented complete session, and Deep adds bounded read-only investigation when needed. Each profile uses the selected APEX Agent model and never silently substitutes another model. Sessions retain the selected model, canonical artifact, evidence, and a linked Cortex conversation.

Legacy briefing rows and their runtime metadata are permanently dropped during the schema upgrade. Saved sessions use the current Daily, Catch Up, and Deep profiles; retired Flash, Focused, and Structured preferences are ignored rather than migrated.

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
- Use **APEX Agent** for the canonical architectural and product role of the native assistant.
- Use **Lynx** for the default visible display name and prompt identity of the APEX Agent.
- Use **Cortex workspace** for the user interface and **Cortex Engine** for backend execution.
- Use model, provider, and runtime names directly; do not turn them into Agent identities.
- Use **Daily**, **Catch Up**, and **Deep** only for briefing profiles.
