# APEX Identity and Naming

This document explains the origins of APEX's names and logo, what each name refers to, and how to use them consistently. Runtime behavior belongs in [Architecture](architecture.md), settings in [Configuration](configuration.md), and HTTP contracts in [API](api.md).

## APEX and the logo

**APEX** is a local-first personal intelligence workspace. Its name stands for **Automated Personal Environment Xylem** and draws its meaning primarily from nature.

In a plant, xylem carries water and minerals upward from the roots. APEX follows a similar idea when preparing a briefing: it collects telemetry from connected sources and brings that information together for review. The sources act as the roots, supplying the material that flows into the briefing.

The word *apex* adds the food-chain imagery: the top of a pyramid and the position of an apex predator. The logo brings these ideas together in an A-shaped food-chain pyramid with an upward xylem channel at its center.

<p align="center">
  <img
    src="assets/apex-logo.png"
    alt="The APEX logo, combining an A-shaped food-chain pyramid with a central upward xylem channel"
    width="420"
  >
</p>

## APEX Agent and Lynx

**Lynx** is the default name of the **APEX Agent**, the application's single built-in assistant. The animal connects its name to the predator theme of the pyramid, while the northern constellation connects it to APEX's deep-space aesthetic. Introduced by Johannes Hevelius, the constellation was named for the keen eyesight needed to discern its faint stars. Observation is the link between the two references.

The Agent works with briefings, trusted personal context, connected services, and actions. Overview, Briefing, and Cortex provide access to the same assistant, with Cortex offering its full conversation workspace.

A local display name preference (`agent_display_name`) can replace Lynx in the interface and the name the assistant uses for itself. Its role remains APEX Agent, with the internal key `apex`.

The selected **model** determines how the Agent runs, including its provider or local runtime, reasoning controls, context limits, and available model capabilities. Changing the model does not select a different Agent. The assistant role and APEX's safety rules remain the same.

**Cortex Engine** names the backend that runs Agent turns and coordinates context, tools, model providers, and local inference. It is distinct from the Cortex workspace, which is part of the interface.

## Screens and workspaces

APEX opens on **Launch**, the starting screen for entering one of four workspaces:

| Name | Purpose |
|---|---|
| **Overview** | Collect telemetry, check connector health and freshness, and manage reminders |
| **Briefing** | Choose a briefing profile, generate briefings, revisit saved sessions, and follow up in linked conversations |
| **Cortex** | Talk with the Agent, choose models and tools, manage personal context, and review actions |
| **Reports** | Read external activity reports and review findings that might belong in personal context |

Launch is the opening screen; Overview, Briefing, Cortex, and Reports are peer workspaces. Telemetry means the status collected from connected services.

## Briefing profiles

**Daily**, **Catch Up**, and **Deep** name the three briefing profiles:

- **Daily** gives an orientation from current sources.
- **Catch Up** compares current sources with previously presented briefing evidence.
- **Deep** adds a limited investigation using read-only tools.

These are briefing profiles, not separate Agents or models. See [Configuration](configuration.md#briefing-profiles) for profile settings and [Architecture](architecture.md#briefing-routes) for how sessions run.

## Naming rules

- Use **APEX** for the application as a whole.
- Use **APEX Agent** when referring to the built-in assistant role, and **Lynx** when referring to its default name.
- Use **Cortex workspace** for the user interface and **Cortex Engine** for backend execution.
- Use model, provider, and runtime names directly; do not turn them into Agent identities.
- Use **Daily**, **Catch Up**, and **Deep** only for briefing profiles.
