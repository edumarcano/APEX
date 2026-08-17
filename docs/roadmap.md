# APEX Roadmap

> [!NOTE]
> This roadmap records how APEX has changed, what each phase set out to solve, and where the project is heading next.
> Completed milestones provide historical context; [the changelog](../CHANGELOG.md) remains the detailed record of released changes.
> Planned milestones reflect current intent. Their order, scope, implementation details, and phase boundaries may change as development progresses.
> Planned milestones may include more detail while they are still being designed. Once completed, they are shortened to their final outcome while the changelog keeps the release details.

## Current Focus

**Current Phase:** [Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta)
**Active Milestone:** [v2.0.0-beta.1 - Cortex: Persistent Context, World Model & Retrieval](#v200-beta1---cortex-persistent-context-world-model--retrieval)
**Current Initiative:** [Cortex Initiative - Continued](#cortex-initiative---continued)

**Next Milestone:** [v2.0.0-beta.2 - Cortex: Bounded Task Execution & Observability](#v200-beta2---cortex-bounded-task-execution--observability)

### Navigation

[Phase I: Foundational](#phase-i-foundational) ·
[Phase II: Modernization](#phase-ii-modernization) ·
[Phase III: Cognitive Interface](#phase-iii-cognitive-interface) ·
[Phase IV: Interactive Intelligence](#phase-iv-interactive-intelligence) ·
[Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta) ·
[Phase VI: Platform Consolidation & Physical Integration](#phase-vi-platform-consolidation--physical-integration)

---

# Roadmap Summary

APEX began as a collection of single-purpose Python automation scripts and has grown into a local-first personal context and operations platform.

Its development has moved through several stages:

* **Foundational automation:** Collect personal data, run scheduled tasks, and establish the first client-server version of APEX.
* **Modern interface architecture:** Move to the React/Vite HUD, make system activity visible, and build the visual and interaction model used today.
* **Cognitive interaction:** Add conversational AI, local and cloud models, briefing generation, and the beginnings of Cortex.
* **Interactive agent execution:** Give Apex Agents tools, controlled write actions, verification, and a CLI that can use Cortex without the HUD.
* **Persistent personal context and agent operation:** Give APEX a durable record of useful personal context, make that context available to Cortex and approved models when relevant, and let Cortex use it for longer tasks, reusable procedures, and proactive work.
* **Platform consolidation and physical integration:** Clean up the 1.x foundations, move toward a native desktop application, and connect APEX to independent physical systems such as Tyto-S3.

Across these phases, APEX is moving from a system that mainly gathers and presents information toward one that can keep a lasting understanding of the user's world and use it across different Agents and models.

APEX should own that context rather than leaving it tied to a single model provider. Cortex can use the same context to complete and verify work, while approved outside LLMs can retrieve only what is relevant to the current task.

The local-first, single-user focus remains the same throughout that evolution.

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
Building the new APEX 2.0 architecture around persistent personal context, bounded Agent execution, reusable workflows, and proactive operation before the stable 2.0 release.

APEX should remain the owner of its personal context even when outside models or workers are allowed to use parts of it.

[Back to Current Focus](#current-focus)

---

## Cortex Initiative - Continued

Phase V takes Cortex from interactive requests into persistent operation and makes APEX the long-term home for useful personal context.

APEX should be able to remember information given directly by the operator as well as context gathered from connected sources. It should keep a sourced model of people, projects, ideas, preferences, decisions, relationships, and changes, then retrieve only the parts that matter for the current task.

Cortex should use that same context for longer tasks, workflow graphs, reusable skills, and proactive work. Approved outside models and workers may also use relevant context without becoming owners of APEX memory.

The design should keep software in control of permissions and limits. Evidence should matter more than model confidence, APEX should keep one authoritative world model, and learned procedures should be versioned and reviewable rather than allowing unrestricted self-modification.

---

## v2.0.0-beta.1 - Cortex: Persistent Context, World Model & Retrieval

**Status:** In Progress

**Objective:**
Give APEX durable personal context that Cortex and Apex Agents can build from conversations, direct input, connected data, and other trusted sources, along with a retrieval system that can pull in the right context for the current task.

The milestone should add persistent session history, multiple conversations, conversation forking, editable messages, and per-session metadata while keeping conversation history separate from the world model.

When the operator gives APEX an idea, preference, plan, decision, or other information worth keeping, an Apex Agent should be able to turn it into structured context while preserving the original source. Conversation text should not automatically become trusted knowledge; APEX should keep the original input, Agent interpretation, and stored context distinct.

The world model should record entities, observations, claims, decisions, relationships, sources, and changes over time. It should keep source information, contradictions, superseded facts, and useful history instead of silently overwriting them.

Retrieval should combine structured filters, full-text search, semantic search, and relationship lookup where each is useful. Agents should receive the smallest useful set of personal context for the current request rather than loading the full world model into every conversation.

The Cortex Workspace should adopt assistant-ui for reusable conversation behavior such as threads, messages, the composer, message actions, branching, and session navigation. APEX should remain responsible for conversation storage, Agents, tools, actions, context, and backend behavior, with a thin adapter between assistant-ui and the existing Cortex API.

As an early real use of the context engine, Cortex should be able to search APEX repository documentation, return cited excerpts, keep retrieved instructions isolated from system instructions, and update its index when the docs change.

---

## v2.0.0-beta.2 - Cortex: Bounded Task Execution & Observability

**Status:** Planned

**Objective:**
Let Cortex work through a task in repeated, bounded steps: observe, retrieve context, reason, act, verify, and stop when there is enough evidence that the task is complete.

The loop should have clear limits for iterations, time or execution budget, cancellation, retries, failure handling, verification, traces, and completion evidence. Software rules, not the model alone, should decide when the loop must stop.

Cortex should also gain an APEX-owned streaming path for response text, tool activity, action proposals, runtime measurements, completion, and errors. The frontend can use this stream for live responses and execution state without making its chat library part of the Cortex runtime.

This milestone should also improve structured outputs where providers support them and expose useful inference measurements such as tokens per second, time to first token, and context-window use.

APEX should also gain a Task Manager-like resource view for CPU, memory, local inference processes, loaded models, and other useful system information. The same resource service can later help Cortex decide when local work is safe to run.

The CLI should grow with the loop runtime so it can inspect resources and active runs, cancel work, and view execution traces.

---

## v2.0.0-beta.3 - Cortex: Workflow Graphs & Worker Orchestration

**Status:** Planned

**Objective:**
Add explicit workflow graphs for tasks that genuinely need branching, parallel work, joins, specialist workers, independent checks, or approval points.

A bounded Agent loop remains the normal way to run a task. Graphs should be used only when the shape of the work is easier to express that way.

The first graph runtime should support sequential steps, conditions, parallel branches, joins, retries, verification, approval gates, failure paths, and explicit state changes.

Workflow graphs should describe how work runs. They should remain separate from the world model, which describes what APEX knows.

Each graph step should use a common worker interface so APEX can send work to Apex Agents, normal code, or future external Agent runtimes without tying the graph itself to one model provider. Workers should receive only the context and permissions needed for their part of the task.

---

## v2.0.0-beta.4 - Cortex: Procedural Learning & Skills

**Status:** Planned

**Objective:**
Let Cortex recognize procedures that worked repeatedly and turn them into reusable, versioned skills after they have been reviewed and validated.

The world model should store what Cortex knows about the user and environment. Procedural skills should instead store how a recurring kind of task can be completed reliably.

A skill candidate should record when it applies, what tools it needs, the steps to follow, what evidence to expect, how to verify success, how failures are handled, where the procedure came from, and how well it has worked.

New procedures should be reviewable, reversible, and subject to operator or policy approval. Cortex should not be able to rewrite its own behavior without those controls.

---

## v2.0.0-beta.5 - Cortex: Hermes Worker Integration

**Status:** Planned

**Objective:**
Use Hermes Agent as an optional sandboxed worker for tasks that benefit from a more mature autonomous execution environment, while APEX keeps control of permissions, verification, persistent state, and orchestration.

Hermes should receive a tightly scoped task with the context, tools, workspace access, execution budget, network policy, and output requirements it is allowed to use.

It should return results, artifacts, actions, evidence, errors, and execution details to Cortex so APEX can verify and reconcile them independently.

Hermes should receive only the personal context needed for the assigned task. If it discovers useful new context, it should return that information and its evidence to APEX rather than changing the world model directly.

Hermes should not keep its own personal or world-state memory at first. APEX should remain the authoritative memory system.

---

## v2.0.0-beta.6 - Cortex: Context Access & Workspace Integration

**Status:** Planned

**Objective:**
Let trusted outside sources add context to APEX and let approved outside LLM clients retrieve relevant personal context from APEX without bypassing source tracking, permissions, or local-first ownership.

This milestone should add a narrowly scoped APEX MCP server or equivalent context interface. It should support both directions: new evidence entering APEX and approved clients asking APEX for context relevant to a question or task.

Outside clients should not receive unrestricted access to the APEX database, wider backend, or direct world-model writes. New information should pass through the same source-tracked review and reconciliation path before it becomes part of APEX's trusted context.

External access should be optional and authenticated. The authoritative world model should remain local by default, and the first version may require the APEX host to be online. A continuously available cloud copy of personal context is not required for this milestone.

APEX should also add a permissioned device-context service for information such as current location and timezone. Features such as weather can then use device state without owning location detection themselves.

Workspace support may include an APEX-managed Markdown knowledge folder using portable frontmatter and wikilinks, with optional compatibility with tools such as Obsidian rather than a runtime dependency on them.

---

## v2.0.0-beta.7 - Cortex: Proactive Automation & Event Response

**Status:** Planned

**Objective:**
Let Cortex respond to meaningful changes in connected data, keep its world model current, and start bounded workflows when a change actually needs attention.

Instead of repeatedly rescanning every source, Cortex should react to structured changes and events, decide whether they affect known people, tasks, commitments, projects, or goals, and run only the work that is needed.

Scheduled and event-triggered workflows should support proactive briefings, stale-state checks, contradiction discovery, commitment tracking, threshold monitoring, and action proposals.

By this point, persistent context, verified actions, learned procedures, execution graphs, Apex Agents, normal software workers, and optional external runtimes should work together under the same permissions and verification rules.

---

# Phase VI: Platform Consolidation & Physical Integration

**Status:** Planned

**Core Focus:**
Cleaning up the APEX 2.x foundation, moving the main interface to a native desktop application, and connecting APEX to independent physical sensing systems without making those systems depend on Cortex.

Phase VI is where APEX can stop carrying forward temporary 1.x compatibility choices. The goal is to simplify the platform around the runtime, persistence, Agent, memory, and action systems that proved useful before expanding further into desktop and physical integrations.

[Back to Current Focus](#current-focus)

---

## v2.0.0 - Platform Consolidation

**Status:** Planned

**Objective:**
Graduate the Phase V beta architecture into the stable APEX 2.0 platform, removing obsolete 1.x compatibility layers and settling on the persistence, configuration, API, and runtime structures that future work should use.

This milestone should audit the database, configuration system, APIs, persistence paths, runtime code, naming, and compatibility code.

Old tables, columns, profile-era records, deprecated settings, unused telemetry structures, migration scaffolding, aliases, and replaced persistence paths should be removed or migrated when they are no longer needed.

Useful operator data should be preserved where practical, including Cortex conversations, world-model knowledge, evidence, learned procedures, execution history, meaningful configuration, and audit records.

Fresh installations and systems upgraded through APEX 1.x should end up with the same current schema, configuration shape, and runtime behavior.

Some old internal contracts may be removed when keeping them would make the 2.x code harder to understand or maintain.

---

## v2.1.0 - Native Desktop Application

**Status:** Planned

**Objective:**
Move the main APEX HUD from a browser-oriented shell to a native Tauri desktop application while keeping the existing separation between the interface, backend, API, and CLI.

The Tauri app should remain a client of the APEX platform rather than moving Cortex or backend logic into the desktop shell.

The CLI and backend should continue to work independently. The desktop app can then improve startup and shutdown, window behavior, local permissions, notifications, system integration, and distribution without becoming the only way to run APEX.

Native features should go through clear platform services when possible instead of being accessed directly by Cortex or individual frontend components.

The goal is to keep the current HUD experience while giving desktop-specific features a cleaner home.

---

## v2.2.0 - Tyto Environmental Integration

**Status:** Planned

**Objective:**
Connect [Tyto-S3](https://github.com/edumarcano/Tyto-S3) to APEX so environmental measurements, device health, history, and detected events can become part of Cortex context while Tyto remains a fully independent system.

APEX should talk to Tyto through a versioned, authenticated device interface instead of depending on firmware implementation details.

The integration should cover current measurements, derived climate values, sensor and device health, historical observations, environmental events, firmware and protocol compatibility, and temporary network outages.

Cortex tools should be able to query current Tyto data and relevant history. Important observations can later enter the world model with their source and timestamp intact.

Tyto events should also be able to enter the APEX event path and contribute to briefings, context retrieval, anomaly detection, or bounded Cortex workflows when useful.

Tyto must keep working when APEX is unavailable. APEX should treat it as an independent source of physical-world data, not as a peripheral that needs Cortex to function.

### Integration Readiness

Development of this milestone assumes Tyto has reached sufficient standalone maturity for reliable integration.

Before APEX v2.2.0 integration work begins, Tyto should provide:

* reliable unattended operation;
* stable environmental sensing and derived measurements;
* persistent or exportable history;
* explicit freshness and device-health state;
* a versioned telemetry contract;
* network interruption and reconnection handling;
* authenticated external access;
* documented protocol and compatibility behavior.

---

# Long-Term Vision

APEX is intended to become a local-first personal context and operations platform.

It should act as the long-term home for useful personal knowledge: ideas, preferences, decisions, people, projects, relationships, history, and context gathered from connected services, files, and devices.

That knowledge should belong to APEX rather than a particular model provider. Cortex, Apex Agents, and approved outside LLM clients should be able to retrieve the parts that are relevant to what they are doing without needing the full personal history every time.

Cortex should use the same context to complete and verify bounded actions, coordinate longer workflows, learn reusable procedures, and respond to meaningful changes.

The single-user, local-first model remains the default. External access should be optional, authenticated, and narrowly scoped rather than requiring APEX or its authoritative world model to move to the cloud.

## Current Focus

APEX is currently in **Phase V: APEX 2.0 Beta**.

**Active milestone:**
[v2.0.0-beta.1 - Cortex: Persistent Context, World Model & Retrieval](#v200-beta1---cortex-persistent-context-world-model--retrieval)