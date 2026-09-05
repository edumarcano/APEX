# APEX Roadmap

> [!NOTE]
> This roadmap records how APEX has changed, what each phase set out to solve, and where the project is heading next.
> Completed milestones provide historical context; [the changelog](../CHANGELOG.md) remains the detailed record of released changes.
> Planned milestones reflect current intent. Their order, scope, implementation details, and phase boundaries may change as development progresses.
> Planned milestones may include more detail while they are still being designed. Once completed, they are shortened to their final outcome while the changelog keeps the release details.

## Current Focus

**Current Phase:** [Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta)
**Active Milestone:** [v2.0.0-beta.3 - Trusted Context & Review](#v200-beta3---trusted-context--review)
**Current Direction:** [APEX 2.0 Direction](#apex-20-direction)

**Next Milestone:** [v2.0.0-beta.4 - External Activity Inbox](#v200-beta4---external-activity-inbox)

### Navigation

[Phase I: Foundational](#phase-i-foundational) ·
[Phase II: Modernization](#phase-ii-modernization) ·
[Phase III: Cognitive Interface](#phase-iii-cognitive-interface) ·
[Phase IV: Interactive Intelligence](#phase-iv-interactive-intelligence) ·
[Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta) ·
[Phase VI: Native Platform & Physical Context](#phase-vi-native-platform--physical-context)

---

# Roadmap Summary

APEX began as a collection of small Python automation scripts and has grown into a local-first personal context and operations platform.

Its development has moved through several stages:

* **Foundational automation:** Collect personal data, run scheduled tasks, and establish the first client-server version of APEX.
* **Modern interface architecture:** Move to the React and Vite HUD, make system activity visible, and establish the visual model used today.
* **Cognitive interaction:** Add conversational AI, cloud and local models, briefing generation, and the beginnings of Cortex.
* **Native assistance and verified actions:** Give APEX a built-in assistant that can use tools, work with personal context, and propose verified changes through both the HUD and CLI.
* **Trusted context and connected tools:** Keep a lasting, sourced understanding of the operator's environment and accept useful information from outside tools without giving those tools ownership of APEX.
* **Native and physical context:** Improve how the operator accesses APEX and connect it to independent physical systems such as Tyto-S3.

APEX should become exceptionally good at understanding, protecting, connecting, and presenting the operator's personal environment.

It does not need to become the place where every task is performed. General-purpose AI products, coding Agents, research tools, workflow systems, automation platforms, and device hubs can keep their own interfaces and remain responsible for the work they already do well.

APEX should connect to those tools without becoming dependent on them. It should receive useful results, relate them to personal context, preserve their sources, and show what deserves attention.

The Apex Agent is the native assistant for this environment. It should be unusually good at working with APEX context, telemetry, connected services, briefings, and verified actions. It does not need to compete with general-purpose Agent products.

Models, external tools, and connection methods can change. The operator's accumulated context should not.

The local-first, single-user model remains the default. External access is optional and limited to the specific capabilities the operator chooses to expose.

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
Build and stabilize the parts of APEX that should remain specific to the operator: personal context, source history, review, permissions, verified actions, attention, and a consistent interface.

APEX should not try to recreate production-grade tools for general-purpose Agent work, workflow execution, automation, system monitoring, remote networking, or device management.

When another project already solves one of those problems well, APEX should connect to it through a small, replaceable adapter. The outside tool should keep responsibility for its own execution and interface. APEX should keep only the information needed to understand, present, review, and safely use its results.

[Back to Current Focus](#current-focus)

---

## Cortex Initiative continued

The Cortex initiative established APEX's interactive foundation: model and provider support, tool use, runtime controls, persistent conversations, verified actions, and access from both the HUD and CLI.

Earlier versions explored a larger family of named Agents and later reduced it to separate cloud and local Agents. That structure was eventually consolidated into one Apex Agent.

Apex Agent is now APEX's built-in personal operations assistant. The selected model determines whether a request runs through a cloud provider or a local runtime.

This keeps the useful model, tool, and action infrastructure without treating every model or runtime as a separate Agent identity.

Phase V builds on that simpler foundation by improving how APEX stores context, reviews evidence, receives information from outside tools, prepares briefings, and decides what deserves the operator's attention.

---

## APEX 2.0 Direction

APEX should be the trusted home for the operator's personal environment.

It should understand useful information from conversations, connected services, files, outside AI tools, and future devices. It should preserve where that information came from, distinguish direct facts from model interpretations, and keep important history when something changes.

Outside tools should normally be used through their native interfaces. APEX does not need custom control panels for tools like Gemini Spark, Grok Bot, Hermes Agent, or other AI products.

Instead, those tools should be able to leave useful reports, findings, evidence, and follow-up items in one shared APEX inbox. APEX can then relate those results to projects, commitments, existing knowledge, and current telemetry.

Connections should be easy to add, disable, or replace. Stopping use of one external product should usually mean revoking or removing a client configuration, not editing the APEX codebase.

Apex Agent remains the native conversational interface to APEX itself. It can explain personal context, compare connected information, prepare briefings, answer questions about the environment, and propose APEX-managed actions.

The rule for this phase is simple: build the personal layer in APEX and connect mature tools for the general work.

---

## v2.0.0-beta.1 - Cortex: Persistent Context, World Model & Retrieval

**Status:** Complete

**Objective:**
Establish the APEX 2.0 foundation with persistent conversations, personal context and retrieval, the assistant-ui-based Cortex workspace, and the updated briefing experience.

---

## v2.0.0-beta.2 - Cortex: Bounded Runs & Live Activity

**Status:** Complete

**Objective:**
Unify models and runtimes under a single Apex Agent, and introduce bounded execution with APEX-enforced limits, a durable run ledger, live event streaming, an in-HUD activity inspector, OpenTelemetry GenAI tracing, and CLI run controls.

---

## v2.0.0-beta.3 - Trusted Context & Review

**Status:** In Progress

**Objective:**
Make the context introduced in beta.1 easier to trust, correct, and understand before APEX begins accepting larger amounts of information from outside tools.

Stored knowledge should keep its source, timestamp, and history. APEX should distinguish between:

* something the operator stated directly;
* a record imported from a connected service;
* an observation submitted by an outside tool;
* an interpretation inferred by a model.

New information should not silently overwrite older information. A claim may become current, disputed, rejected, or superseded while the earlier record and its source remain available.

APEX should keep original evidence separate from the normalized context it derives from that evidence. This should allow it to answer both “What did I originally say?” and “What is my current plan?”

Frequently useful defaults and preferences may be kept in a small operator profile, but they should remain explicit and sourced. APEX should not build an unsupported personality profile from model guesses.

Clear updates can be handled through simple rules. Conflicts, sensitive changes, uncertain matches, and model interpretations should be placed in a review queue.

The HUD and CLI should make it possible to inspect a source, correct a record, compare conflicting information, accept or reject a proposed change, and understand why APEX currently believes something.

This should continue to use the existing SQLite knowledge and retrieval foundation. APEX does not need to become a general knowledge-graph database or a separate memory product.

---

## v2.0.0-beta.4 - External Activity Inbox

**Status:** Planned

**Objective:**
Give outside tools one simple way to report completed work, findings, evidence, and follow-up items into APEX.

The first version should be inbound-only. External clients may submit information, but they should not be able to retrieve personal context, call Cortex tools, approve actions, or change trusted knowledge directly.

APEX should define one internal external-activity format. A useful report may include:

* the source client;
* the task title and status;
* a concise outcome;
* important findings;
* evidence and links;
* artifacts;
* unresolved questions;
* suggested follow-up;
* affected projects or subjects;
* a link back to the task in its native application.

APEX should not import an outside tool's full conversation or internal task history by default.

Different connection methods should feed the same internal service. Initial adapters may include:

* an APEX CLI command for local and desktop tools;
* JSON or Markdown file import;
* a narrow authenticated HTTP submission route;
* remote MCP tools where the client supports them.

Gemini Spark should be the first real client because it is already part of the operator's workflow.

A second client, such as Grok Bot, should be used to prove that the design is generic. Adding the second source should mainly require a client registration and credentials rather than product-specific application code.

Outside tools should continue to use their own interfaces for task creation, progress, configuration, and detailed results. APEX should show a concise activity record and a link back to the original work instead of recreating those interfaces.

Every client should have a separate, revocable identity. Submissions should be size-limited, rate-limited, attributed, and treated as untrusted until reviewed or reconciled.

The main APEX backend and database should remain private. Public reachability, encrypted transport, and authentication should use existing networking and identity tools rather than an APEX-built tunnel or account system.

Removing an external tool should not require a code change. Its access can be revoked while its earlier submissions remain available as historical sources.

---

## v2.0.0-beta.5 - Cortex: Personal Attention & Briefings

**Status:** Planned

**Objective:**
Turn personal context, connected-service state, external activity, commitments, conflicts, and pending actions into a clearer view of what deserves attention.

APEX briefings should move beyond summarizing available data. They should help answer:

* What changed since the last review?
* What needs my attention now?
* What can safely wait?
* What is blocked or overdue?
* Which outside tasks completed?
* Which findings conflict with current APEX context?
* Which commitments or decisions may be affected?
* Which actions are waiting for approval?

APEX should keep a small, persistent attention queue. An item should retain its source and may be marked new, reviewed, dismissed, resolved, or superseded.

Attention items may come from personal context, calendar events, tasks, email, connector failures, outside activity reports, unresolved conflicts, action proposals, and later device events.

The Home workspace should present these items in a concise way, with links to the supporting source or the native outside application.

Apex Agent can synthesize the briefing and explain why something matters, but software should select and bound the source material first. The model should not receive unrestricted raw history or decide on its own which records are authoritative.

Briefings should retain a useful deterministic fallback when a model is unavailable or when a model-generated summary would add little value.

The goal is not to create another feed of Agent summaries. The goal is to relate activity from several systems to the operator's personal projects, commitments, decisions, and current environment.

---

## v2.0.0-beta.6 - Scoped Context Access

**Status:** Planned

**Objective:**
Allow approved outside clients to retrieve limited APEX context after the inbound activity path has proven useful.

This should extend the gateway created for external activity rather than expose the wider APEX backend.

MCP should be the first context-access adapter where it fits, but APEX's permissions and retrieval rules should remain independent of MCP so another protocol can replace it later.

Each client should have its own identity and a narrow set of permissions. Access may be limited by project, context type, source, sensitivity, or operation.

A client may be allowed to:

* search an approved part of personal context;
* retrieve information about a specific project or subject;
* read an approved timeline;
* receive a context package prepared for one task.

A client should not receive direct database access, unrestricted search across personal history, general Cortex tool access, or a direct world-model write operation.

Information returned by the client should still enter through the external activity and review path created in beta.4. Read access should not give the client authority to write.

APEX should record which client requested context, what scope was used, and which records were included. Sensitive results may be redacted or withheld according to policy.

The main backend should remain local. Remote reachability and identity should come from established private networking, tunneling, reverse-proxy, and authorization tools rather than custom APEX networking infrastructure.

External context access should remain optional. The first version may require the APEX machine to be online. A cloud copy or continuously synchronized replica of the personal world model is not part of this milestone.

Gemini Spark may serve as the first reference client if its available connection method supports the required access. The design should not depend on Spark or any other individual product remaining available.

---

## v2.0.0-beta.7 - Events & Proactive Attention

**Status:** Planned

**Objective:**
Let connected systems tell APEX when something changes so that APEX can update its attention view without repeatedly rescanning every source.

APEX should define a small event format that records:

* the source;
* the event type;
* the time;
* the affected subject;
* the sensitivity;
* a duplicate or idempotency key;
* a reference to the original information.

Events may come from existing APEX connectors, webhooks, operating-system services, automation platforms, device hubs, message brokers, or future physical systems.

Existing tools should remain responsible for schedules, connector setup, message delivery, polling, device communication, and general automation editing. APEX should not build its own automation platform, workflow editor, scheduler, or device hub.

When an event arrives, APEX should decide whether it affects trusted context or deserves attention. It may:

* add evidence for review;
* update an attention item;
* flag a conflict;
* start a bounded Apex Agent run;
* propose an APEX action;
* notify the operator;
* ignore the event.

No outside event should directly perform a sensitive write. Event-triggered work should follow the same limits, approval rules, and verification requirements as work started by the operator.

The HUD and CLI should show important recent events, what APEX did with them, and any resulting items waiting for review.

External event sources should be registered through configuration and removable without changing APEX code.

The same event path should later accept selected Tyto-S3 observations.

---

## v2.0.0 - APEX 2.0 Stable

**Status:** Planned

**Objective:**
Turn the Phase V beta work into a stable APEX 2.0 platform without adding another major feature area.

The release should settle the contracts for:

* conversations and personal context;
* sources and evidence;
* review and reconciliation;
* Apex Agent runs;
* verified actions;
* external activity;
* attention items and briefings;
* scoped client access;
* connected events.

Old 1.x tables, settings, aliases, persistence paths, and compatibility code should be removed or migrated when they are no longer useful.

Important operator data should be preserved wherever practical, including conversations, personal context, evidence, review history, action records, run summaries, external activity, attention history, and configuration.

Fresh installations and upgraded installations should end with the same current schema, configuration, and runtime behavior.

External services should remain optional. APEX should still start, preserve personal context, and support its core local features when an outside client, tracing viewer, tunnel, automation platform, or device source is unavailable.

The stable release should include:

* migration and upgrade testing;
* security review of external access;
* graceful-degradation testing;
* demo scenarios covering normal, busy, quiet, and degraded states;
* documentation explaining which system owns each kind of data;
* removal of temporary beta compatibility paths.

---

# Phase VI: Native Platform & Physical Context

**Status:** Planned

**Core Focus:**
Improve how the operator accesses APEX and connect independent physical sources without moving APEX state into the desktop shell or turning APEX into a device platform.

[Back to Current Focus](#current-focus)

---

## v2.1.0 - Native Desktop Application

**Status:** Planned

**Objective:**
Package the existing APEX interface as a Tauri desktop application while keeping Cortex, persistence, APIs, and the CLI independent of the desktop shell.

The desktop application should remain a client of the APEX backend. It should not become the owner of personal context or Cortex runtime state.

Tauri and maintained plugins should handle desktop concerns such as windows, startup, notifications, permissions, the system tray, deep links, updates, and distribution.

Desktop services may also provide permissioned device context such as current timezone, location, presence, or power state when there is a clear APEX use for it.

The weather connector and other features should consume shared device context rather than each implementing their own location detection.

The backend and CLI should continue to work without the desktop application. Desktop-only behavior should go through small platform services rather than being called directly from Cortex or scattered across frontend components.

Theme choices and other application-shell preferences may be expanded during this milestone, but a full visual theme editor should remain optional rather than blocking the native application.

The goal is to make APEX feel native without tying the platform to one interface.

---

## v2.2.0 - Tyto Physical Context Integration

**Status:** Planned

**Objective:**
Connect Tyto-S3 to APEX as an independent source of physical context without turning APEX into a device-management or home-automation platform.

Tyto should expose measurements, health, availability, and events through a stable, authenticated interface such as MQTT or a small versioned API.

An existing device hub or message broker may handle discovery, delivery, history, reconnect behavior, and device automation. APEX should not recreate those systems.

APEX should consume the measurements and events that are useful as personal context. It should preserve device identity, timestamps, and source information.

Cortex should be able to answer questions about current conditions, use recent history in briefings, explain important changes, and respond to selected events through the event path introduced in beta.7.

APEX should not directly manage Tyto firmware or silently turn sensor changes into outside actions.

Tyto must remain useful when APEX is unavailable.

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

# Unscheduled Possibilities

The following ideas are intentionally not assigned to a version.

They should be added to the roadmap only after a real APEX use case proves that they are needed.

* **External task delegation:** APEX may eventually assign bounded work to Hermes Agent or another autonomous runtime. Hermes should remain isolated and connect through a generic worker or activity interface. Installing Hermes is not enough reason to build the integration.
* **Workflow runtime integration:** LangGraph, n8n, or another workflow tool may be connected when an actual APEX task requires branching, checkpoints, visual automation, or long-running coordination. APEX should not build its own graph engine.
* **Portable procedural skills:** APEX may adopt an existing skill format when repeated procedures begin to appear. It should not invent a skill ecosystem in advance.
* **Cloud context replication:** A synchronized cloud projection may be considered only if access while the APEX machine is offline becomes important enough to justify encryption, synchronization, conflict handling, and deletion propagation.
* **External Agent control interfaces:** Custom APEX replacements for the native Spark, Grok Bot, Hermes, ChatGPT, or other Agent interfaces are not planned.

---

# Long-Term Vision

APEX is intended to become the trusted personal dashboard and context home around the tools the operator chooses to use.

It should understand the operator's environment, protect access to it, connect useful outside sources, and present what matters clearly.

That environment may include people, projects, ideas, decisions, preferences, commitments, conversations, connected services, outside Agent work, system state, files, and physical observations.

Apex Agent is the native assistant for that environment. It should be especially good at answering questions about APEX context, explaining why something matters, comparing personal information, preparing briefings, and proposing verified APEX actions.

General-purpose tools should remain general-purpose tools. Their native applications can continue to handle research, coding, browser work, terminal access, long autonomous tasks, and other specialized execution.

APEX should receive the parts of that work that matter afterward: results, evidence, changes, unresolved questions, and items requiring attention.

An outside tool should be easy to add and easy to remove. Its disappearance should not take personal context with it or leave product-specific code spread throughout APEX.

APEX briefings should become a personal review of the environment rather than a generic summary feed. They should show what changed, what conflicts, what is waiting, what needs a decision, and why it matters to the operator.

The model, provider, outside Agent, connection protocol, automation platform, and device hub should all remain replaceable.

The authoritative personal context should remain under the operator's control.

The local-first model remains the default. APEX should continue to work without a hosted APEX account, while optional external access remains authenticated, limited, revocable, and recorded.

## Current Focus

APEX is currently in **Phase V: APEX 2.0 Beta**.

**Active milestone:**
[v2.0.0-beta.3 - Trusted Context & Review](#v200-beta3---trusted-context--review)
