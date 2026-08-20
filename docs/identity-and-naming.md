# APEX Identity and Naming

This document explains the main names used in APEX and why they exist. The goal is to keep the naming easy to understand as the project grows.

APEX currently has two Agents: **Apex Panthera** for cloud models and **Apex Felis** for local models. The model can change without changing the Agent name.

## APEX

**APEX** stands for **Automated Personal Environment Xylem**.

An apex is the highest point of a structure. In APEX, it represents the place where information from across a personal digital environment comes together.

Xylem is the plant tissue that carries water and minerals upward. The name fits the idea behind APEX: collecting useful signals from calendars, messages, reminders, weather, markets, system telemetry, and other sources and bringing them into one place.

The name also suggests an **apex predator**, which connects naturally to the animal names used for the Agents.

## The APEX logo

The logo combines the same ideas visually.

Its outer shape forms an **A** and resembles the levels of a food-chain pyramid leading to an apex. The middle resembles a trunk or xylem channel carrying information upward.

<p align="center">
  <img
    src="assets/apex-logo.png"
    alt="The APEX logo, combining an angular A-shaped outer structure with a central upward xylem channel"
    width="420"
  >
</p>

## The main names

```text
APEX
├── Home
└── Cortex
    ├── Cortex workspace
    ├── Cortex Engine
    └── Apex Agents
        ├── Apex Panthera
        │   └── Cloud model
        └── Apex Felis
            └── Local model
```

### APEX

**APEX** is the whole application. It includes Home, Cortex, telemetry, briefings, voice, connectors, settings, and the Agents.

### Home

**Home** is the main day-to-day workspace. It shows things such as telemetry, briefings, connector health, reminders, and system status.

Briefing modes are product behaviors, not Agent identities: **Flash**, **Focused**, and **Structured** are the only canonical mode names. Panthera and Felis remain Agent names used as resolved runtime metadata.

### Cortex

**Cortex** is where the operator interacts with the Agents in more detail.

The **Cortex workspace** contains conversations, Agent and model selection, reasoning and local-model controls, tools, history, and execution details.

The **Cortex Engine** is the backend that runs Agent requests, gathers context and tools, sends work to the selected model, and manages local models when needed.

### Apex Agent

An **Apex Agent** is a named role in APEX. It is not the same thing as a model.

An Agent can have its own instructions, tools, context rules, memory behavior, privacy rules, and other behavior. Those things can stay the same even when the model underneath the Agent changes.

### Model

A **model** is the AI model used by an Agent for a request.

The model also determines where it runs. A cloud model already implies its provider, and a local model already implies its runtime, so APEX does not need separate provider or runtime choices on top of model selection.

### Agent query

An **Agent query** is simply a request sent to the selected Agent.

## Why there are only two Agents

Earlier versions of APEX gave many individual models or configurations their own Agent names. That made the Agent list grow along with the model list.

The current system keeps the distinction simpler:

```text
Agent
└── Model
    └── Provider or local runtime
```

There are two Agents because there are two useful long-term roles:

- **Apex Panthera** — `Cloud · Generalist`
- **Apex Felis** — `Local · Private`

Panthera can move between supported cloud models without becoming a different Agent. Felis can move between supported local models or runtimes without becoming a different Agent.

Things such as reasoning levels, context sizes, hosted tools, model stability, and runtime-specific options belong to the selected model rather than becoming separate Agent identities.

## Apex Panthera

**Apex Panthera** is the cloud Agent.

*Panthera* is the genus of big cats, including lions, tigers, leopards, jaguars, and snow leopards. The name fits an Agent that can reach beyond the local machine and use larger cloud models.

Panthera is the general-purpose Agent for cloud work: answering questions, planning, research, and other tasks where a cloud model makes sense.

Its selected model can come from different supported providers. Changing the model or provider does not change Panthera's identity.

## Apex Felis

**Apex Felis** is the local Agent.

*Felis* is the genus that includes the domestic cat and several closely related small wild cats. The name fits an Agent that stays close to home: local, private, and running on the user's own machine.

Felis is for work that should stay local or use locally managed models.

Its selected model determines whether APEX uses a local runtime such as Ollama or llama.cpp. Changing the model, quantization, context size, or runtime does not make it a different Agent.

## Agent and model are different things

The easiest way to think about the split is:

- **Agent** — what role the user is choosing.
- **Model** — what AI model does the work.
- **Provider or runtime** — where that model runs.
- **Model settings** — the controls that particular model supports.

Adding a new model should usually mean adding it under Panthera or Felis, not creating another Agent.

A new Agent only makes sense if APEX eventually needs a genuinely different role that would still be useful even if its underlying model changed.

## Agent rules and model support

An Agent can allow a feature, but the selected model still needs to support it.

For example, Panthera may allow hosted search, but APEX should only show that option for models that actually provide it. The same applies to reasoning levels, context sizes, and other model-specific features.

This lets Panthera and Felis stay simple while the models underneath them can have different capabilities.

## Naming conventions

- Use **APEX** when referring to the product by itself.
- Use **Apex** when it is part of a longer name, such as **Apex Panthera** or **Apex Felis**.
- Use **Apex Panthera** and **Apex Felis** as the full Agent names.
- Use **Panthera** and **Felis** when the shorter name is clearer or space is limited.
- Model, provider, and runtime names should stay model, provider, and runtime names rather than becoming Agent names.
- Code follows normal naming conventions, so identifiers do not need to copy the product capitalization exactly.

## Why Panthera and Felis

The animal naming is meant to give the two Agents some identity without tying them to a vendor or model generation.

**Panthera** suggests a larger range and fits the cloud Agent.

**Felis** suggests something smaller and closer to home, which fits the local Agent.

The names are just a simple product metaphor. They are not meant to rank the Agents by intelligence or capability.

## Development and experimental models

Development-only models, experimental models, and Sandbox Mode do not need separate Agent names.

They remain options under Panthera or Felis. This keeps testing flexible without growing the permanent Agent list again.

## Previous naming

Earlier versions of APEX used several different profile and Agent names. Over time, those names became too closely tied to individual models, providers, and local configurations.

Panthera and Felis replace that approach with one cloud Agent and one local Agent. The older names remain part of the project's history, but they are no longer active runtime or settings identities.

The changelog and release history keep the details of those earlier versions.

## In short

APEX is the product. Cortex is where the Agents live. Panthera is the cloud Agent, and Felis is the local Agent. Models sit underneath those two names and can change over time without forcing the Agent system to change with them.

For runtime details, see [Architecture](architecture.md). For current models and settings, see [Configuration](configuration.md). For visual treatment, see the [Design System](design-system.md).
