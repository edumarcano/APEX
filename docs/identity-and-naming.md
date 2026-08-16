# APEX Identity and Naming

This document defines the main names used throughout APEX and the ideas behind them. It focuses on durable product identity: what APEX, Cortex, and the Apex Agents mean, how the two-Agent model is organized, and how names should be used across the product and documentation.

APEX currently has two durable Agent identities: **Apex Panthera** for cloud work and **Apex Felis** for local work. Models, providers, and local runtimes are replaceable execution choices underneath those identities.

## APEX

**APEX** stands for **Automated Personal Environment Xylem**.

An apex is the highest point of a structure. In APEX, it represents the place where information from across a personal digital environment comes together into one view.

Xylem is the plant tissue that carries water and minerals upward. APEX uses that as an analogy for collecting signals from calendars, messages, reminders, weather, markets, system telemetry, and other sources and bringing the useful parts into one interface.

The name also suggests an **apex predator**, which connects the product to the animal names used by Apex Agents.

## The APEX logo

The logo combines the same ideas visually.

Its outer structure forms an **A** and resembles the levels of a food-chain pyramid leading to an apex. The inner structure resembles a trunk or xylem channel carrying information upward.

The logo therefore combines:

- the letter **A** for APEX;
- a food-chain pyramid leading to an apex predator;
- a trunk or xylem channel carrying information upward;
- and the apex where that information comes together.

<p align="center">
  <img
    src="assets/apex-logo.png"
    alt="The APEX logo, combining an angular A-shaped outer structure with a central upward xylem channel"
    width="420"
  >
</p>

## Product vocabulary

The main APEX terms refer to different layers of the product.

```text
APEX
├── Home
└── Cortex
    ├── Cortex workspace
    ├── Cortex Engine
    └── Apex Agents
        ├── Apex Panthera
        │   └── Cloud model
        │       └── Provider inferred from the model
        └── Apex Felis
            └── Local model
                └── Runtime inferred from the model
```

### APEX

**APEX** is the complete application and local operating environment. It includes Home, Cortex, telemetry, briefings, voice, connectors, settings, and the available Agents.

### Home

**Home** is the main operational workspace. It presents the current state of the user's environment through telemetry, briefings, connector health, reminders, system status, and compact Agent access.

### Cortex

**Cortex** is the Agent-facing part of APEX. It includes the Cortex workspace and Cortex Engine.

The **Cortex workspace** is the detailed interface for conversations, Agent selection, model selection, reasoning and local-model settings, tools, conversation history, and execution information.

The **Cortex Engine** is the backend that runs Agent requests, coordinates context and tools, calls the selected model through its provider or local runtime, and manages local-model lifecycle.

### Apex Agent

An **Apex Agent** is a durable product role inside APEX. The Agent defines the identity and policy for a class of work; it is not a name for one specific model.

An Agent can define instructions, context rules, memory behavior, tool policy, privacy boundaries, and other behavior that should remain meaningful even when the underlying model changes.

### Model

A **model** is the replaceable intelligence implementation used by an Agent for a request. Model selection lives underneath the Agent identity.

The selected model determines its provider or local runtime. APEX does not expose provider or runtime as an independent routing choice when the model already defines that route.

### Provider and runtime

A **provider** is the cloud service used to execute a cloud model. A **runtime** is the local inference system used to execute a local model.

These are execution details derived from the selected model rather than separate product identities.

### Agent query

An **Agent query** is a request sent to the selected Apex Agent. It is the interaction itself, not the Agent identity.

## The two-Agent model

APEX intentionally keeps its Agent roster small.

```text
Agent
└── Model
    └── Provider or runtime
        └── Model-supported settings and capabilities
```

The current system exposes two durable Agents:

- **Apex Panthera** — `Cloud · Generalist`
- **Apex Felis** — `Local · Private`

This split is based on durable product roles rather than individual models or providers. Panthera can change cloud models without becoming a different Agent. Felis can change local models or move between supported local runtimes without becoming a different Agent.

Model-specific capabilities stay underneath the Agent. A reasoning option, hosted tool, context size, runtime feature, or stability label belongs to the model unless it changes the Agent's durable role.

## Apex Panthera

**Apex Panthera** is the cloud Agent.

*Panthera* is the genus that includes lions, tigers, leopards, jaguars, and snow leopards. Its larger range and adaptability fit the role of a general-purpose cloud Agent that can use stronger remote models and broader cloud capabilities.

Panthera is intended for thoughtful answers, planning, research, and complex everyday work across many kinds of tasks.

Panthera owns the durable cloud role. Its selected model can come from different supported cloud providers. The model profile determines the provider and exposes only the reasoning options, hosted tools, and other capabilities that the selected model supports.

Changing from one cloud model or provider to another does not create a new Agent as long as the role remains the same.

## Apex Felis

**Apex Felis** is the local Agent.

*Felis* is the genus of small cats. Its smaller scale, close territory, and independent operation fit the role of an on-device Agent focused on privacy and local execution.

Felis is intended for work that should stay on the local machine or use locally managed models.

Felis owns the durable local role. Its selected model determines whether execution uses a supported local runtime such as Ollama or llama.cpp. Context, reasoning, and runtime-specific options are exposed only when the selected model supports them.

Changing the local model, quantization, context preset, or runtime does not create a new Agent as long as the local/private role remains the same.

## Agent identity is not model identity

Apex Agents and models serve different purposes.

| Concept | What it represents |
|---|---|
| Agent | Durable product role and identity |
| Model | Replaceable intelligence implementation |
| Provider/runtime | Execution route derived from the model |
| Model settings | Capabilities and controls supported by that model |

A new model does not automatically justify a new Agent. Neither does a new provider, runtime, context size, privacy setting, or experimental label.

A new Agent should exist only when APEX needs a durable role that is meaningfully different from Panthera or Felis and would still make sense after its underlying model changes.

This rule keeps the product roster understandable and prevents implementation details from turning into permanent product identities.

## Agent policy and model capability

The Agent and the selected model both affect what a request can do.

The Agent defines what is allowed for its role. The model defines what it can technically support. The effective capability is the intersection of those two boundaries.

For example, an Agent may allow hosted search, but that option should only be available when the selected model supports it. Likewise, a model may technically support a feature that APEX chooses not to allow for that Agent or mode.

This keeps Agent identity stable while allowing model capabilities to vary safely underneath it.

## Naming conventions

Use the product names consistently across user-facing text and documentation.

- Use **APEX** when referring to the product by itself.
- Use **Apex** when it is part of a longer proper name, such as **Apex Panthera** or **Apex Felis**.
- Use **Apex Panthera** and **Apex Felis** as the full Agent names.
- Use **Panthera** and **Felis** where space is limited or the Agent context is already clear.
- Do not turn model, provider, or runtime names into Apex Agent names unless they represent a new durable product role.
- Code identifiers follow normal language and code-style conventions rather than forcing product capitalization mechanically.

## Why the Agents use genus names

The genus names give the Agents related but distinct identities without tying them to a particular vendor or model generation.

The biological metaphor is deliberately simple:

- **Panthera** suggests broader range and larger-scale cloud capability.
- **Felis** suggests smaller-scale, close-to-home, local and private operation.

The names are product metaphors, not a scientific ranking of intelligence or capability.

## Development and experimental models

`DEV_MODE`, preview status, experimental status, and sandbox behavior do not create separate Apex Agents.

Development-only and experimental models remain model-catalog concerns underneath Panthera or Felis. Sandbox behavior is a policy mode applied to the relevant Agent rather than a separate Agent identity.

This keeps testing and development flexibility without expanding the permanent product roster.

## Previous naming

Earlier APEX versions experimented with cloud and local profiles and later with a larger genus-based Agent family. Those designs tied product identity too closely to individual models, providers, runtimes, and specialized configurations.

The current design replaces that approach with Panthera and Felis as durable cloud and local roles. Former Agent names are project history rather than active runtime or configuration identities.

Detailed historical changes belong in the changelog and release history rather than in the current Agent model.

## Closing idea

The naming system should make APEX easier to understand, not add another layer of configuration.

APEX is the product. Cortex is the Agent-facing system. Panthera and Felis are durable roles. Models are replaceable implementations underneath those roles, and providers or local runtimes are execution details inferred from the selected model.

That separation lets APEX change models and infrastructure without constantly changing the product identities users interact with.

For runtime responsibilities and system boundaries, see [Architecture](architecture.md). For current models and settings, see [Configuration](configuration.md). For visual treatment, see the [Design System](design-system.md).
