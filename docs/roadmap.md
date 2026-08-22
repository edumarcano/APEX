# APEX Roadmap

> [!NOTE]
> This roadmap records how APEX has changed, what each phase set out to solve, and where the project is heading next.
> Completed milestones provide historical context; [the changelog](../CHANGELOG.md) remains the detailed record of released changes.
> Planned milestones reflect current intent. Their order, scope, implementation details, and phase boundaries may change as development progresses.
> Planned milestones may include more detail while they are still being designed. Once completed, they are shortened to their final outcome while the changelog keeps the release details.

## Current Focus

**Current Phase:** [Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta)
**Active Milestone:** [v2.0.0-beta.2 - Cortex: Bounded Runs & Live Activity](#v200-beta2---cortex-bounded-runs--live-activity)
**Current Initiative:** [Cortex Initiative - Continued](#cortex-initiative---continued)

**Next Milestone:** [v2.0.0-beta.3 - Cortex: Trusted Context & Reconciliation](#v200-beta3---cortex-trusted-context--reconciliation)

### Navigation

[Phase I: Foundational](#phase-i-foundational) ·
[Phase II: Modernization](#phase-ii-modernization) ·
[Phase III: Cognitive Interface](#phase-iii-cognitive-interface) ·
[Phase IV: Interactive Intelligence](#phase-iv-interactive-intelligence) ·
[Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta) ·
[Phase VI: Native Platform & Physical Integration](#phase-vi-native-platform--physical-integration)

---

# Roadmap Summary

APEX began as a collection of single-purpose Python automation scripts and has grown into a local-first personal context and operations platform.

Its development has moved through several stages:

- **Foundational automation:** Collect personal data, run scheduled tasks, and establish the first client-server version of APEX.
- **Modern interface architecture:** Move to the React and Vite HUD, make system activity visible, and establish the visual and interaction model used today.
- **Cognitive interaction:** Add conversational AI, local and cloud models, briefing generation, and the beginnings of Cortex.
- **Interactive Agent execution:** Give Apex Agents tools, controlled write actions, verification, and a CLI that can use Cortex without the HUD.
- **Personal context and connected tools:** Keep a lasting, sourced understanding of the user's world and make it available to approved models, clients, workflows, and workers without giving those systems ownership of it.
- **Native and physical integration:** Move the interface into a native desktop shell and connect APEX to independent physical systems such as Tyto-S3.

APEX does not need to become its own version of every AI or automation tool it uses. Mature projects can continue to handle model inference, workflow execution, autonomous coding, system monitoring, remote access, service automation, and device communication.

APEX should focus on the personal layer that ties those tools together: context, source history, permissions, approvals, verified actions, and a consistent interface.

The model, worker, workflow engine, and automation platform should all remain replaceable. The user's accumulated context should not.

The local-first, single-user focus remains the same. External access is optional and limited to the parts of APEX that the operator chooses to expose.

---

# Phase I: Foundational

**Status:** Complete

**Core Focus:**
Establishing core data ingestion, automation capabilities, and the first operational proof-of-concept.

---

## v0.1.0 - Core Stability

**Status:** Complete

**Objective:**
Resolve critical reminder storage defects and stabilize Gemini API connectivity.

---

## v0.2.0 - Daily Operations

**Status:** Complete

**Objective:**
Integrate personal productivity systems, including Gmail and Google Calendar.

---

## v0.3.0 - Global Awareness

**Status:** Complete

**Objective:**
Expand APEX beyond personal operations by integrating external telemetry streams such as sports, news, and world events.

---

## v0.4.0 - Optimization and Polish

**Status:** Complete

**Objective:**
Introduce configurable personas, feature flags, and cloud-based text-to-speech services.

---

## v1.0.0 - Nexus: Client-Server Transition

**Status:** Complete

**Objective:**
Establish the first official APEX platform release through a FastAPI backend, structured JSON telemetry contracts, and the launcher orchestration framework.

---

# Phase II: Modernization

**Status:** Complete

**Core Focus:**
Migrating APEX from a traditional Python interface into a scalable React/Vite intelligence HUD.

[Back to Current Focus](#current-focus) · [Back to Roadmap Navigation](#navigation)

---

## HUD-Renaissance Initiative

The HUD-Renaissance initiative encompassed the transformation of APEX from a functional telemetry viewer into a visually rich, state-aware command interface.

This initiative established:

* Real-time pipeline visibility
* Reactive atmospheric systems
* Interactive operator controls
* SVG telemetry visualization
* Modern frontend architecture
* Productization and demo workflows

The initiative spans v1.2.0 through v1.7.0.

---

## v1.1.0 - UI Foundation

**Status:** Complete

**Objective:**
Establish the Vite, React, and TypeScript frontend stack alongside the initial Bento-grid HUD architecture.

---

## v1.1.1 - AI Workforce Calibration

**Status:** Complete

**Objective:**
Refactor development workflows and AI workforce rules to support the new frontend/backend separation model.

---

## v1.2.0 - HUD-Renaissance: Pipeline State Visibility

**Status:** Complete

**Objective:**
Expose real-time pipeline progression from backend Gate through frontend Delivery.

---

## v1.3.0 - HUD-Renaissance: Data as Geometry

**Status:** Complete

**Objective:**
Introduce SVG Ring Gauges and the atmospheric theme engine.

---

## v1.4.0 - DX & Local Sandbox Recalibration

**Status:** Complete

**Objective:**
Improve local development workflows, mock telemetry systems, and offline execution environments.

---

## v1.5.0 - HUD-Renaissance: The Control Deck

**Status:** Complete

**Objective:**
Deploy an interactive terminal interface for reminder management.

---

## v1.6.0 - HUD-Renaissance: Atmospheric Resonance

**Status:** Complete

**Objective:**
Replace the diagnostic progress rail with a centralized vector identity system and dynamic status presentation layer.

---

## v1.7.0 - HUD-Renaissance: Productization

**Status:** Complete

**Objective:**
Introduce the layered atmospheric canvas architecture, DEMO_MODE workflows, and modular documentation systems.

---

# Phase III: Cognitive Interface

**Status:** Complete

**Core Focus:**
Transforming APEX from a telemetry dashboard into an intelligence presence through structured briefing delivery, local speech synthesis, synchronized communication, and intentional operator interaction.

---

## v1.8.0 - Briefing Digest & Transcript Ledger

**Status:** Complete

**Objective:**
Replace the monolithic briefing presentation with structured intelligence digests, operational confidence scoring, transcript history management, and persistent local briefing storage.

---

## v1.9.0 - Standby Core & Unified Status Deck

**Status:** Complete

**Objective:**
Refactor APEX into a deliberate, operator-initiated workflow by eliminating automatic startup synthesis and introducing manual execution pathways and dormant-state awareness.

---

## v1.9.1 - Stabilization & Maintenance

**Status:** Complete

**Objective:**
Harden multi-threaded execution safety, eliminate database write contention, resolve duplicate network requests, and prune dead assets.

---

## v1.10.0 - Local Neural Voice Matrix

**Status:** Complete

**Objective:**
Transition speech synthesis from cloud-first delivery toward a local-first neural voice architecture powered by Kokoro ONNX and Piper, while preserving optional cloud fallback capabilities.

---

## v1.11.0 - Dormant Core & Ambient State Engine

**Status:** Complete

**Objective:**
Transform APEX into a standby intelligence appliance featuring manual synthesis activation, adaptive atmospheric awareness, state-driven environmental feedback, and command-console interaction patterns.

---

## v1.11.1 - Speech Engine Stabilization & Library Pruning

**Status:** Complete

**Objective:**
Revert the active primary speech synthesis path to Google Cloud TTS, deprecate and prune the Piper CLI engine to eliminate binary bloat, and configure Kokoro ONNX as a zero-overhead, optional local engine.

---

# Phase IV: Interactive Intelligence

**Status:** Complete

**Core Focus:**
Turning APEX from a briefing and query interface into an operator-directed Agent system that can use tools, work with cloud and local models, and make verified personal changes when approved.

[Back to Current Focus](#current-focus)

---

## Cortex Initiative

The Cortex initiative is a multi-phase effort to grow APEX from a briefing-oriented interface into a persistent personal operations agent.

During Phase IV, Cortex establishes the interactive foundation: named cloud and local Agents, shared tools, conversations, runtime controls, approved write actions, and access from both the HUD and CLI.

Phase V builds on that foundation with APEX-owned personal context, longer controlled workflows, reusable procedures, outside workers and models where useful, and proactive responses to meaningful changes.

---

## v1.12.0 - Cortex: Cloud Gemini Agentic Tool Calling

**Status:** Complete

**Objective:**
Transform APEX from a push-based summarization system into an interactive cloud-agent framework capable of tool execution, conversational preemption, stateful reasoning, and controlled action loops.

---

## v1.13.0 - Cortex: Local Ollama Provider

**Status:** Complete

**Objective:**
Enable local agentic execution through Ollama-powered models while reducing cloud dependency. Introduce runtime model switching, local inference management, and automatic memory lifecycle control.

---

## v1.14.0 - Central Command Atmosphere

**Status:** Complete

**Objective:**
Rebuild APEX as a fullscreen central command HUD with inline chat, strict bento layout, glass atmosphere, structured tool cards, and a market ticker.

---

## v1.15.0 - Synthesis Routing and Profile Tuning

**Status:** Complete

**Objective:**
Add profile-specific Gemini thinking levels, introduce local Ollama briefing synthesis, expose live and resolved synthesis state to the HUD, and centralize local-model lifecycle controls beneath the APEX logo.

---

## v1.16.0 - Command Console & Runtime Control Deck

**Status:** Complete

**Objective:**
Give APEX runtime control surfaces for configuration, model/provider behavior, service state, and operational visibility.

---

## v1.17.0 - Runtime Hardening & Decoupling

**Status:** Complete

**Objective:**
Complete APEX's reproducibility, API, telemetry, persistence, startup, and documentation foundations, then separate HUD activation, telemetry collection, assistant availability, briefing synthesis, and voice delivery into independent runtime flows.

---

## v1.18.0 - Cortex: MCP Client Foundation & Read-Only Integrations

**Status:** Complete

**Objective:**
Establish APEX’s provider-neutral capability layer, approved external MCP client integrations, operator controls, expanded read-only assistant tools, full seven-day calendar awareness, and bounded local assistant command scopes with context-aware budgets for local Agents.

This milestone also establishes delegated read-only Microsoft To Do access and normalized task contracts for the separately reviewed personal-action migration.

---

## v1.19.0 - Apex Agents & Cortex Workspace

**Status:** Complete

**Objective:**
Establish Apex Agents as APEX's provider-neutral intelligence abstraction, unify cloud and local runtime behavior, expand local execution across multiple providers, and evolve the Cortex Workspace into the primary surface for Agent configuration, tool policy, runtime control, and interaction.

---

## v1.19.1 - Runtime Reliability & Maintenance

**Status:** Complete

**Objective:**
Improve APEX’s reliability, consistency, and overall polish across its runtime, integrations, Agents, and user experience before the next phase of Cortex development.

---

## v1.20.0 - Cortex: Verified Personal Actions & Headless Control

**Status:** Complete

**Objective:**
Give Cortex its first safe write path through verified Microsoft To Do actions, move Home reminders to Microsoft To Do with local offline support, and add a CLI for using core APEX features without the HUD.

---

# Phase V: APEX 2.0 Beta

**Status:** In Progress

**Core Focus:**
Building and stabilizing the new APEX 2.0 architecture around personal context, source history, permissions, approvals, verified actions, and a consistent way to connect outside tools.

APEX should not try to become a production-grade workflow engine, automation platform, system monitor, remote-access service, device hub, or general autonomous Agent runtime. When a mature tool already solves one of those problems well, APEX should connect to it through a small adapter and keep only the state needed to explain, govern, and review its use.

[Back to Current Focus](#current-focus)

---

## Cortex Initiative - Continued

Phase V makes Cortex the personal layer between APEX context and the tools that do the work.

APEX keeps the long-term context and decides what each model, client, workflow, or worker is allowed to see. It also decides which actions need approval, what evidence is required, and whether new information should become part of trusted personal context.

The tools behind Cortex can change over time. A cloud model can replace another cloud model. A local runtime can replace another local runtime. A workflow or automation tool can be swapped without moving APEX's personal state into it.

The rule for this phase is simple: build the small parts that are specific to APEX and connect mature tools for the general problems they already solve.

---

## v2.0.0-beta.1 - Cortex: Persistent Context, World Model & Retrieval

**Status:** Complete

**Objective:**
Establish the APEX 2.0 beta foundation with persistent conversations, personal context and retrieval, simplified Agents, and the updated Cortex and briefing experience.

---

## v2.0.0-beta.2 - Cortex: Bounded Runs & Live Activity

**Status:** In Progress

**Objective:**
Let Cortex carry a task through several steps without turning APEX into a general autonomous Agent runtime.

A run can retrieve context, reason, call tools, propose or complete allowed actions, check the result, and stop when there is enough evidence that the task is finished. APEX, rather than the model alone, sets the limits for iterations, time, token use, retries, cancellation, and failure handling.

Cortex should gain an APEX-owned streaming path for response text, tool activity, action proposals, runtime measurements, completion, and errors. The assistant-ui frontend can display that stream without becoming part of the Cortex runtime.

Run details should use standard tracing where practical. APEX can send detailed traces to an optional OpenTelemetry-compatible viewer such as Phoenix instead of building a complete AI tracing and evaluation product of its own.

The HUD should show the resource information that is useful for APEX, including active runs, local inference processes, loaded models, memory use, and configured limits. General CPU, memory, disk, and process data can come from the operating system or an existing monitor such as Glances. APEX does not need to recreate a full Task Manager.

The CLI should be able to inspect active runs, cancel work, show completion evidence, and open or reference the related trace.

---

## v2.0.0-beta.3 - Cortex: Trusted Context & Reconciliation

**Status:** Planned

**Objective:**
Make the context introduced in beta.1 easier to trust, correct, and understand before APEX begins accepting more information from outside systems.

Stored claims should keep their source, timestamp, and history. APEX should distinguish between something the operator stated directly, something imported from a connected source, and something inferred by a model.

New information should not silently replace older information. APEX should be able to mark a claim as current, disputed, rejected, or superseded while keeping the earlier record available.

Clear updates can be handled through simple rules. Conflicts, sensitive changes, uncertain matches, and model inferences should be available for review.

Information submitted by an outside model or worker should first enter an evidence inbox. It may suggest new claims or changes, but it does not become trusted context until APEX accepts or reconciles it.

The HUD and CLI should make it possible to inspect sources, correct a record, review a conflict, and understand why APEX currently believes something.

This work should build on the existing SQLite knowledge and retrieval system. APEX does not need to become a general knowledge-graph database or a separate memory platform.

---

## v2.0.0-beta.4 - Cortex: Context Access & External Clients

**Status:** Planned

**Objective:**
Allow approved outside clients to use APEX context without exposing the main backend, database, or unrestricted personal history.

APEX should add a small access gateway that is separate from the main FastAPI service. The main backend can continue to bind locally while the gateway exposes only a narrow set of approved capabilities.

MCP should be the first external protocol. The gateway should use the authorization model expected by MCP rather than inventing a custom login system.

Gemini Spark should be the first real client used to prove the design. It should be able to request an approved slice of APEX context and submit sourced findings from an autonomous task. It should not be able to browse the APEX database, read unrelated personal context, or change trusted knowledge directly.

External clients may receive capabilities such as:

* searching approved context;
* reading a specific entity or project;
* retrieving a relevant timeline;
* submitting evidence;
* proposing a context change;
* proposing an action.

Direct world-model writes should not be exposed.

Each client should have its own identity and permissions. APEX should record what context was shared, what the client returned, and which client was responsible.

Network reachability should come from an existing private network, tunnel, or reverse proxy. APEX should not build its own VPN, tunneling service, certificate system, or public identity provider. The general APEX API should never be exposed simply because an MCP client needs access.

The authoritative context remains on the APEX machine. The first version may require that machine to be online. Cloud replication and continuous synchronization are not part of this milestone.

---

## v2.0.0-beta.5 - Cortex: Connected Workflows & Task Handoffs

**Status:** Planned

**Objective:**
Let APEX hand off complicated multi-step work to an existing workflow or automation tool when the normal bounded Cortex run is no longer enough.

APEX should define a small handoff format that includes the task, allowed context, permissions, limits, expected result, and evidence requirements. The outside runtime can then handle the mechanics of running the workflow.

A real APEX use case should choose the first integration. LangGraph may be useful for code-defined Agent workflows with branching, checkpoints, and approval pauses. n8n may be a better fit for service automation, webhooks, and visual workflows. APEX does not need to adopt both before there is a reason to use them.

The connected tool should own graph scheduling, checkpoints, parallel branches, retries, and its own workflow editor. APEX should own what each step is allowed to know and do, which actions require approval, and what results are accepted back into personal context.

Workflow status should be translated into the same run and activity model introduced in beta.2 so the HUD and CLI can show it without recreating the external tool's full interface.

The normal bounded Cortex run should remain the default. A workflow handoff is for tasks that clearly benefit from a mature external runtime.

APEX should not build its own general graph engine, visual workflow builder, connector marketplace, or distributed task scheduler.

---

## v2.0.0-beta.6 - Cortex: External Workers & Portable Skills

**Status:** Planned

**Objective:**
Let Cortex delegate bounded work to a more autonomous external Agent without placing that Agent inside the APEX trust boundary.

Hermes Agent should be the first reference worker, but it should remain optional. The intended reference setup is Hermes running on an isolated machine or inside a whole-process sandbox rather than sharing the APEX host environment.

For the first deployment, APEX can connect to Hermes on a separate device through a private authenticated connection. APEX should treat Hermes as a remote service, not as a Python library embedded into Cortex.

Each job should include only the context, files, tools, network access, credentials, limits, and output requirements needed for that task. Hermes should not receive the APEX database, the full conversation archive, the operator's home directory, or the general APEX environment.

Hermes should return results, artifacts, evidence, proposed actions, errors, and useful execution details. APEX then decides what to keep, what to verify, and what may change trusted context.

The same worker interface should be usable by future Agent runtimes so that Hermes does not become a permanent architectural dependency.

Reusable procedures should follow the open Agent Skills format instead of using an APEX-only skill format. APEX may keep a personal catalog that records where a skill came from, which version is installed, what tools it needs, and whether it is enabled.

APEX may help turn a successful run into a proposed skill draft, but the operator should review it before it becomes active. APEX does not need to build an autonomous learning system, a separate skill execution engine, or a public skill marketplace.

---

## v2.0.0-beta.7 - Cortex: Events & Proactive Response

**Status:** Planned

**Objective:**
Let existing tools tell APEX when something changes so Cortex can respond without constantly rescanning every connected source.

Schedules, webhooks, service triggers, device events, and general automation should come from tools that already specialize in them. n8n can handle digital-service automation, while Home Assistant and MQTT can handle device and sensor events. Existing direct APEX integrations may also submit events.

APEX should accept those events through a small shared format that records the source, event type, time, sensitivity, affected subject, and a reference to the original information.

When an event arrives, APEX decides whether it matters. It may update the evidence inbox, flag a conflict, start a bounded Cortex run, hand work to a connected workflow, propose an action, notify the operator, or ignore the event.

The outside platform should keep responsibility for schedules, connector setup, message delivery, and automation editing. APEX keeps responsibility for personal relevance, context, permissions, approvals, evidence, and verification.

No external event should be able to cause a sensitive write on its own. Proactive work should follow the same limits and approval rules as work started by the operator.

The HUD and CLI should show recent events, what APEX did with them, and any actions waiting for review. They do not need to replace the full n8n or Home Assistant interface.

The same event path can later receive observations from Tyto-S3.

---

## v2.0.0 - APEX 2.0 Stable

**Status:** Planned

**Objective:**
Turn the Phase V beta work into a stable APEX 2.0 platform without adding another large feature area.

This release should settle the contracts for personal context, evidence, permissions, actions, runs, external clients, workflow handoffs, workers, and events.

Old 1.x tables, settings, aliases, persistence paths, and compatibility code should be removed or migrated when they are no longer useful. Important operator data should be preserved wherever practical.

Fresh installations and upgraded installations should end with the same current schema, configuration, and runtime behavior.

External tools should remain optional. APEX should still start, keep its personal context, and support its core local features when a tracing viewer, system monitor, workflow tool, Hermes worker, automation platform, or device hub is unavailable.

The stable release should include migration testing, security review of the external gateway and worker boundaries, graceful-degradation testing, and clear documentation of which system owns each kind of state.

---

# Phase VI: Native Platform & Physical Integration

**Status:** Planned

**Core Focus:**
Build on the stable APEX 2.0 platform by improving how the operator accesses it and by connecting independent physical systems through existing desktop and device ecosystems.

[Back to Current Focus](#current-focus)

---

## v2.1.0 - Native Desktop App

**Status:** Planned

**Objective:**
Package the existing APEX interface as a Tauri desktop application while keeping Cortex, persistence, APIs, and the CLI independent of the desktop shell.

The desktop app should remain a client of the APEX backend. It should not become the place where personal context or Cortex runtime state lives.

Tauri and its maintained plugins should handle desktop concerns such as windows, startup, notifications, permissions, the system tray, deep links, updates, and distribution. APEX does not need to build its own cross-platform native framework.

The backend and CLI should continue to work without the desktop application. Desktop-only features should go through small platform services rather than being called directly from Cortex or scattered across frontend components.

The goal is to make APEX feel native without tying the platform to one interface.

---

## v2.2.0 - Tyto Physical Context Integration

**Status:** Planned

**Objective:**
Connect [Tyto-S3](https://github.com/edumarcano/Tyto-S3) to APEX as an independent source of physical context without turning APEX into a device-management or home-automation platform.

Tyto should expose measurements, health, availability, and events through a stable interface such as MQTT or a small versioned API. Home Assistant may act as the first device hub and history source, while a narrow direct MQTT connection can remain possible where useful.

Tyto, the MQTT broker, and Home Assistant should own device discovery, message delivery, reconnect behavior, general sensor history, and device automation.

APEX should consume the measurements and events that are useful as personal context. It should preserve the device identity, timestamp, and source of each observation.

Cortex should be able to answer questions about current conditions, use recent history in briefings, explain important changes, and respond to selected events through the event path added in beta.7.

APEX should not directly manage Tyto firmware or silently turn sensor changes into external actions. Tyto must remain useful when APEX is unavailable.

### Integration Readiness

Work on this milestone assumes Tyto has reached enough standalone maturity for reliable integration.

Before integration begins, Tyto should provide:

* reliable unattended operation;
* stable measurements and derived values;
* persistent or exportable history;
* clear freshness and device-health information;
* a versioned telemetry format;
* network interruption and reconnect handling;
* authenticated access;
* documented protocol and compatibility behavior.

---

# Long-Term Vision

APEX is intended to become the personal layer around the tools the operator chooses to use.

It should keep a lasting, sourced understanding of the user's world: people, projects, ideas, preferences, decisions, commitments, history, connected services, files, and physical observations.

That context belongs to APEX rather than to a model provider, workflow tool, autonomous Agent, or automation platform.

Cortex and approved outside clients should be able to retrieve the parts that matter for a task without receiving the full personal history. Outside systems may return findings, artifacts, and proposed changes, but APEX decides what becomes trusted context.

APEX does not need to outperform Open WebUI as a general AI interface, LangGraph as a workflow runtime, Hermes as an autonomous Agent, n8n as an automation platform, Home Assistant as a device hub, or Tailscale and similar tools as secure networking systems.

It should connect those tools and make them feel like parts of one personal system.

When those projects improve, APEX should benefit from their progress rather than having to compete with it.

The local-first model remains the default. The authoritative context stays under the operator's control, APEX continues to work without a cloud service, and remote access is optional, authenticated, limited, and recorded.

## Current Focus

APEX is currently in **Phase V: APEX 2.0 Beta**.

**Active milestone:**
[v2.0.0-beta.2 - Cortex: Bounded Runs & Live Activity](#v200-beta2---cortex-bounded-runs--live-activity)

