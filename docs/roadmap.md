# APEX Roadmap

> [!NOTE]
> This roadmap records APEX's product and architectural evolution: the problems each phase set out to solve, the initiatives that shaped the current system, and the directions still under consideration.
> Completed milestones provide historical context; [the changelog](../CHANGELOG.md) remains the detailed record of released changes.
> Planned milestones reflect current intent. Their ordering, scope, implementation details, and phase boundaries may change as development progresses.
> Planned milestones may include additional implementation direction; once completed, they are summarized around their final architectural outcome, with release details preserved in the changelog.

## Current Focus

**Current Phase:** [Phase IV: Interactive Intelligence](#phase-iv-interactive-intelligence)
**Active Milestone:** [v1.19.0 - Apex Agents & Cortex Workspace](#v1190---apex-agents-cortex-workspace)
**Current Initiative:** [Cortex Initiative](#cortex-initiative)

**Next Milestone:** [v1.19.1 - Runtime Reliability & Maintenance](#v1191---runtime-reliability-maintenance)

### Navigation

[Phase I: Foundational](#phase-i-foundational) ·
[Phase II: Modernization](#phase-ii-modernization) ·
[Phase III: Cognitive Interface](#phase-iii-cognitive-interface) ·
[Phase IV: Interactive Intelligence](#phase-iv-interactive-intelligence) ·
[Phase V: Persistent Agent Runtime](#phase-v-persistent-agent-runtime) ·
[Phase VI: Platform Consolidation & Physical Integration](#phase-vi-platform-consolidation-physical-integration)

---

# Roadmap Summary

APEX began as a collection of single-purpose Python automation scripts and has progressively evolved into a local-first personal intelligence and operations platform.

Its development has moved through several distinct architectural stages:

* **Foundational automation** — personal data ingestion, scheduled workflows, telemetry collection, and the original client-server platform.
* **Modern interface architecture** — the React/Vite HUD, real-time pipeline visibility, interactive controls, visualization systems, and a more cohesive operator experience.
* **Cognitive interaction** — conversational AI, local and cloud inference, provider routing, synthesis, and the foundations of Cortex.
* **Interactive agent execution** — provider-neutral Apex Agents, tool and capability orchestration, approval-gated actions, verified execution, and headless operation through the APEX CLI.
* **Persistent agent operation** — durable context, a provenance-aware world model, structured retrieval, bounded reasoning loops, execution graphs, procedural learning, and proactive event-driven orchestration.
* **Platform consolidation and physical integration** — a clean APEX 2.x architectural baseline, native desktop operation, and carefully scoped integration with independent physical sensing systems such as Tyto-S3.

Across these phases, APEX is evolving from a system that primarily gathers and presents information into one that can maintain an operational understanding of the user's world, retrieve relevant context, coordinate bounded multi-step work, verify its own actions through evidence, learn reusable procedures, and respond proactively to meaningful changes.

Each phase represents a major shift in the project's architecture and role while preserving the local-first, single-user focus that defines APEX.

---

# Phase I: Foundational

**Status:** Complete (100%)

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

**Status:** Complete (100%)

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

**Status:** Complete (100%)

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

**Status:** In Progress

**Core Focus:**
Transitioning APEX from an intelligence presence into an operator-directed agent capable of reasoning, conversational interaction, tool use, provider-neutral execution, and verified personal actions.

[Back to Current Focus](#current-focus)

---

## Cortex Initiative

The Cortex initiative is a multi-phase effort to evolve APEX from a briefing-oriented intelligence interface into a persistent personal operations agent.

During Phase IV, Cortex establishes the interactive foundations of that architecture: provider-neutral reasoning, cloud and local Apex Agents, capability orchestration, conversational execution, runtime controls, approval-gated actions, and headless operator access.

Phase V continues the Cortex initiative by extending these interactive capabilities into durable context, evidence-driven agent loops, explicit execution graphs, procedural learning, external Agent-runtime delegation, and proactive event-driven orchestration.

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

**Status:** In Progress

**Objective:**
Resolve known backend and speech-runtime technical debt before Cortex begins relying on longer-running, repeated, and increasingly concurrent execution workflows.

This milestone includes shared HTTP connection-pool refactoring, asynchronous multi-source request optimization where appropriate, and improvements to Kokoro and speech subsystem lifecycle management, long-text chunking, progressive playback, readiness checks, dependency isolation, Unicode handling, cancellation, fallback behavior, and failure testing.

---

## v1.20.0 - Cortex: Verified Personal Actions & Headless Control

**Status:** Planned

**Objective:**
Establish APEX's native write-capability and verification architecture through approval-gated personal actions, deterministic outcome verification, action auditing, Microsoft To Do reminder migration, and a new APEX CLI capable of operating Cortex without the HUD.

The milestone introduces a consistent execution lifecycle in which proposed actions pass through policy evaluation, operator approval when required, execution, independent result verification, and persistent audit recording.

The initial APEX CLI should provide headless access to core capabilities such as system status, briefings, Apex Agent interaction, model and provider state, service state, and Cortex queries while reusing the same backend and execution services as the HUD.

Cortex response rendering should also be improved so structured result cards reflect the actual scope and evidence returned by tool execution rather than presenting unrelated or globally cached telemetry.

---

# Phase V: Persistent Agent Runtime

**Status:** Planned

**Core Focus:**
Transforming Cortex from an interactive agent into a persistent, verifiable personal operations runtime capable of maintaining durable context, coordinating bounded autonomous workflows, learning reusable procedures, and responding proactively to meaningful changes in operator state.

[Back to Current Focus](#current-focus)

---

## Cortex Initiative - Continued

Phase V advances the Cortex initiative from interactive execution into persistent agent operation.

Cortex gains a durable operational world model, structured retrieval, bounded reasoning loops, explicit workflow graphs, reusable procedural skills, external Agent-runtime workers, secure context ingestion, and event-driven orchestration.

The architecture favors bounded loops before multi-node graphs, independently verifiable evidence over model confidence, one authoritative APEX world model, deterministic software control over orchestration and permissions, and versioned procedural learning rather than unrestricted self-modification.

---

## v1.21.0 - Cortex: Persistent Context, World Model & Retrieval

**Status:** Planned

**Objective:**
Establish durable Cortex state through persistent conversation sessions, a provenance-aware operational world model, and a context engine capable of retrieving compact, task-relevant information across APEX data sources.

The milestone introduces persistent session history, multiple conversations, conversation forking, editable messages, and per-session metadata while keeping conversational history distinct from canonical world-model state.

The Cortex world model should represent entities, observations, claims, decisions, relationships, sources, and temporal changes while preserving provenance, superseded information, contradictions, and historical context.

Retrieval should combine precise structured filtering, full-text search, semantic retrieval, and graph-aware relationship expansion where appropriate.

As an initial production use of the context engine, Cortex should gain read-only retrieval over APEX repository documentation using heading-aware indexing, hybrid full-text and local-embedding search, cited excerpts, instruction isolation, and incremental reindexing when documentation changes.

---

## v1.22.0 - Cortex: Loop Runtime, Structured Execution & Runtime Observability

**Status:** Planned

**Objective:**
Establish a bounded Cortex agent-loop runtime that repeatedly observes, retrieves context, reasons, acts, verifies, and records progress until an evidence-based completion condition is reached.

The runtime should introduce explicit iteration limits, execution budgets, cancellation, retry policy, failure classification, verifier support, execution traces, completion evidence, and deterministic termination rules.

This milestone should also expand structured-output support, including JSON Schema enforcement where supported, and expose inference telemetry such as tokens per second, time to first token, and context-window utilization.

APEX should additionally gain a Task Manager-inspired resource monitoring surface that exposes host and APEX runtime health, including CPU, memory, local inference processes, model residency, and other relevant resource telemetry.

The underlying resource service should support both HUD visualization and Cortex runtime gating so system state can inform future worker scheduling and execution decisions.

The APEX CLI should expand alongside the loop runtime with commands for resource inspection, active runs, cancellation, and execution traces.

---

## v1.23.0 - Cortex: Execution Graphs & Multi-Worker Orchestration

**Status:** Planned

**Objective:**
Extend the Cortex loop runtime with explicit execution graphs for workflows that require branching, parallel execution, joins, specialist workers, independent verification, approval gates, or deterministic state transitions.

A bounded agent loop remains the default execution primitive. Execution graphs should be introduced only when workflow topology provides a clear advantage over a single loop.

The initial graph runtime should support sequential nodes, conditional branches, parallel fan-out, joins, retries, verification nodes, approval gates, failure paths, and explicit state transitions.

Graph nodes should operate through a common worker abstraction capable of routing work to Apex Agents, deterministic code, and future external Agent runtimes without coupling orchestration logic to a specific model provider.

---

## v1.24.0 - Cortex: Learning Loops & Procedural Skills

**Status:** Planned

**Objective:**
Allow Cortex to identify repeatable successful procedures from completed execution trajectories and safely promote them into reusable, versioned procedural skills.

The learning system should distinguish operational knowledge from procedural knowledge. World-model memory records what Cortex believes about the operator and environment, while procedural skills record how recurring classes of tasks can be executed reliably.

Skill candidates should define applicability conditions, required capabilities, execution procedures, expected evidence, verification criteria, failure handling, provenance, success history, and version metadata.

Learning should follow a controlled promotion model in which discovered procedures are validated, auditable, reversible, and subject to operator or policy approval rather than allowing unrestricted self-modification.

---

## v1.25.0 - Cortex: Hermes Agent Runtime Integration

**Status:** Planned

**Objective:**
Integrate Hermes Agent as an optional sandboxed external Agent-runtime worker for bounded tasks that benefit from a mature autonomous execution harness while preserving Cortex ownership of orchestration, permissions, verification, persistent state, and world-model memory.

Hermes should operate through the same worker abstraction used by Cortex execution graphs and receive tightly scoped task requests defining context, allowed tools, workspace access, execution budgets, network policy, and output requirements.

Hermes results should return structured outcomes, artifacts, actions, evidence, errors, and execution metadata to Cortex for independent verification and reconciliation.

Persistent Hermes personal or world-state memory should remain disabled initially so APEX preserves one authoritative operational memory system.

---

## v1.26.0 - Cortex: Secure Context Ingestion & Workspace Interoperability

**Status:** Planned

**Objective:**
Create a structured, authenticated inbound context layer that allows external services, files, devices, and knowledge workspaces to contribute evidence to the Cortex world model without bypassing provenance, trust, or permission boundaries.

This milestone should include a narrowly scoped APEX MCP ingestion surface, structured source identity, provenance-aware file and context ingestion, and secure routing of newly received evidence through Cortex reconciliation and retrieval systems.

APEX should also introduce a permissioned device-context abstraction for information such as current location and timezone, allowing capabilities such as weather to consume device state without directly owning location-detection logic.

Workspace interoperability may include an APEX-managed Markdown knowledge workspace using portable frontmatter and wikilink conventions, allowing optional compatibility with tools such as Obsidian without making external note-taking software a runtime dependency.

---

## v1.27.0 - Cortex: Proactive Life OS & Event-Driven Orchestration

**Status:** Planned

**Objective:**
Evolve Cortex into a proactive personal operations system that responds to meaningful changes in connected state, maintains its operational world model, and coordinates bounded multi-step workflows under explicit trust, verification, and approval policies.

Rather than continuously rescanning every connected source, Cortex should operate from structured change and event streams, determine which changes materially affect known entities, tasks, commitments, projects, or operator goals, and invoke the minimum necessary loop or execution graph.

Scheduled and event-triggered workflows should support proactive briefings, stale-state detection, contradiction discovery, commitment tracking, threshold monitoring, and bounded action proposals.

The resulting system should combine persistent context, verified execution, learned procedural skills, execution graphs, Apex Agents, deterministic workers, and optional external runtimes into a controlled personal operations architecture.

---

# Phase VI: Platform Consolidation & Physical Integration

**Status:** Planned

**Core Focus:**
Establishing APEX 2.x as a clean, canonical platform built around the mature Cortex architecture, transitioning the primary interface into a native desktop application, and extending APEX beyond software-only context through purpose-built physical sensing systems.

Phase VI marks the point where APEX stops carrying forward transitional assumptions from its 1.x evolution. The platform is consolidated around its current runtime, persistence, Agent, world-model, execution, and operator-interface architecture before expanding into native and physical integrations.

[Back to Current Focus](#current-focus)

---

## v2.0.0 - Architectural Consolidation

**Status:** Planned

**Objective:**
Establish a clean APEX 2.x architectural baseline by removing obsolete 1.x compatibility layers, consolidating persistence and configuration, and ensuring the system is structured entirely around the capabilities and abstractions developed through the Cortex initiative.

This milestone should perform a comprehensive audit of the APEX database, configuration system, APIs, persistence paths, runtime abstractions, naming conventions, and legacy compatibility code.

Obsolete tables, columns, profile-era records, deprecated settings, unused telemetry structures, migration scaffolding, compatibility aliases, and superseded persistence mechanisms should be removed or migrated into their canonical replacements.

Useful operator data should be preserved wherever practical, including Cortex conversations, world-model knowledge, evidence, learned procedural skills, execution history, meaningful configuration, and audit records.

Fresh installations and installations upgraded continuously from APEX 1.x should converge on the same canonical schema, configuration structure, and runtime behavior.

This release may intentionally remove or change legacy internal contracts where preserving them would compromise the clarity or maintainability of the mature APEX architecture.

---

## v2.1.0 - Native Desktop Application

**Status:** Planned

**Objective:**
Transition the primary APEX HUD from its existing browser-oriented application model into a native desktop application using Tauri while preserving the separation between interface, runtime, API, and CLI established during APEX 1.x.

The Tauri application should act as a native operator surface over the existing APEX platform rather than embedding Cortex or backend logic directly into the desktop shell.

The milestone should preserve the ability to operate APEX independently through its CLI and backend interfaces while improving desktop lifecycle integration, startup and shutdown behavior, window management, local permissions, notifications, system integration, and distribution.

Where appropriate, native capabilities should be exposed through clearly defined platform services rather than accessed directly by Cortex or individual frontend components.

The migration should retain the established APEX HUD experience while providing a cleaner foundation for future desktop-specific capabilities.

---

## v2.2.0 - Tyto Environmental Node Integration

**Status:** Planned

**Objective:**
Integrate [Tyto-S3](https://github.com/edumarcano/Tyto-S3) as APEX's first purpose-built physical sensing node, allowing environmental measurements, device state, historical observations, and detected climate events to become part of Cortex's operational understanding while preserving Tyto as a fully independent standalone system.

APEX should connect to Tyto through a versioned and authenticated device interface rather than depending on firmware-specific implementation details.

The integration should support current environmental measurements, derived climate values, sensor and device health, historical observations, detected environmental events, firmware and protocol compatibility information, and clean handling of temporary network or device outages.

Cortex tools should be able to query Tyto's current state and relevant history, while significant observations may be reconciled into the Cortex world model with clear source provenance and timestamps.

Tyto-originated events should be able to enter the APEX event pipeline and participate in bounded Cortex workflows where appropriate, allowing environmental changes to contribute to briefings, context retrieval, anomaly detection, and future proactive behavior.

Tyto must remain operational when APEX is unavailable, and APEX should treat the device as an independently reliable source of physical-world evidence rather than as a peripheral that depends on Cortex for core functionality.

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

The long-term objective of APEX is to evolve through six distinct stages into a local-first personal intelligence and operations platform. Each phase builds upon the previous one, progressing from information aggregation and conversational intelligence toward a persistent system capable of maintaining an operational model of the user's world, retrieving relevant context, executing and verifying bounded actions, coordinating multi-step workflows, learning reusable procedures from experience, responding proactively to meaningful changes, and eventually extending those capabilities across distributed and physical interfaces.

## Current Focus

APEX is currently in **Phase IV: Interactive Intelligence**.

**Active milestone:**
[v1.19.0 - Apex Agents & Cortex Workspace](#v1190---apex-agents-cortex-workspace)
