# APEX Roadmap

> [!NOTE]
> This roadmap records how APEX has changed, what each phase set out to solve, and where the project is heading next.
> Completed milestones provide historical context; [the changelog](../CHANGELOG.md) remains the detailed record of released changes.
> Planned milestones reflect current intent. Their order, scope, implementation details, and phase boundaries may change as development progresses.
> Planned milestones may include more detail while they are still being designed. Once completed, they are shortened to their final outcome while the changelog keeps the release details.

## Current Focus

**Current Phase:** [Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta)
**Active Milestone:** [v2.0.0-beta.5 - Context Vault & Sharing](#v200-beta5---context-vault--sharing)
**Current Direction:** [APEX 2.0 Direction](#apex-20-direction)

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

Phase V builds on this foundation with trusted personal context, bounded runs, outside activity reports, portable context, and a redesigned briefing experience.

Cortex should help the operator understand and work with their APEX environment without becoming another general-purpose Agent platform.

---

## APEX 2.0 Direction

APEX should become exceptionally good at understanding, protecting, connecting, and presenting the operator's personal environment.

It keeps accepted personal context and the evidence behind it. Conversations, connected-service records, outside reports, and model interpretations remain distinguishable, and important changes retain their history.

Outside tools should normally be used through their native interfaces. They can submit useful results through the External Activity Inbox without giving APEX responsibility for their sessions, task execution, or controls.

Trusted context can also travel in the other direction. APEX can maintain a selected, readable copy in a local folder, which the operator may sync through Google Drive, open in Obsidian, or use with an AI application. This does not require exposing the APEX backend to the internet.

The exported folder is a view of APEX context, not a second source of truth. APEX decides what it generates; the storage provider and receiving applications control access to the copies they receive.

Apex Agent remains the native assistant for this environment. It can explain records, compare connected information, prepare briefings, investigate relevant changes, and propose APEX-managed actions.

Adding or removing an outside tool should usually be a configuration or sharing decision. The personal context and its meaning should not depend on which AI products the operator happens to use.

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

**Status:** Complete

**Objective:**
Make personal context inspectable and safe to change. SQLite now keeps original evidence, provenance, effective time, normalized claims, and append-only history as separate records. Clear operator input can save directly, while sensitive, conflicting, and model-interpreted changes remain outside retrieval until a durable, revision-aware review is accepted.

The Cortex Records and Review views and the CLI expose current claims, evidence, related records, history, corrections, retractions, and review decisions. Prompt assembly reloads canonical records and labels their trust and provenance, so stale retrieval entries and pending replacement text cannot silently become current context.

---

## v2.0.0-beta.4 - External Activity Inbox

**Status:** Complete

**Objective:**
Give outside tools a local inbox for completed work, findings, evidence, and follow-up items.

---

## v2.0.0-beta.5 - Context Vault & Sharing

**Status:** In Progress

**Objective:**  
Maintain a portable Markdown copy of selected, trusted APEX context that can be opened in Obsidian and shared with AI applications through a synced folder.

APEX remains the source of truth. The vault is generated from accepted records and can be rebuilt without changing or losing the underlying personal context.

The vault should contain small, focused notes about the subjects APEX already knows, such as projects, people, decisions, preferences, and commitments. A short index should help readers find their way around. It should not become one large export that every application has to read in full.

Notes should use ordinary Markdown, readable metadata, and internal links. Related records should link to one another so the vault is useful in Obsidian's graph view, while the meaning of each relationship remains clear in the text. Stable record identifiers, source references, and update times should make it possible to trace an exported note back to APEX.

The operator should choose the destination folder and what context is included. A project-specific export or a small set of useful personal defaults should be possible without sharing everything else. Raw conversations, private source documents, pending reviews, and external reports should not be exported merely because APEX stores them.

Google Drive should be the first reference setup for synchronization. APEX writes local files and leaves synchronization to the existing Drive application. The same locally available folder should be usable as an Obsidian vault, without requiring Obsidian plugins, Obsidian Sync, or a Google-specific storage implementation inside APEX.

The initial direction is one-way: APEX writes the generated notes. Editing those notes in Obsidian does not change accepted APEX context. Handwritten notes may live in a separate area of the vault, and APEX must leave that area and Obsidian's settings alone. Anything placed in a shared folder is still subject to that folder's sharing permissions, including handwritten material.

When trusted context changes, APEX should update the affected notes and remove or clearly supersede generated content that is no longer current or allowed in the export. Updates should preserve links and avoid unnecessary rewrites. The operator should be able to see what was exported, when it was last refreshed, and whether an update failed.

Sharing should be explicit. APEX can stop exporting a record and remove its managed copy, but it cannot guarantee deletion from another application's history, index, or previously downloaded files. Disabling an export is not the same as recalling information already shared.

Validation should include browsing the linked notes in Obsidian and using the exported context in at least one actual Drive-connected AI workflow. Folder selection and retrieval behavior should be checked in that application rather than assumed to work identically everywhere.

This milestone does not add bidirectional note editing, a live remote context gateway, a cloud database replica, or a custom synchronization service.

---

## v2.0.0-beta.6 - Cortex: Adaptive Briefings & Attention

**Status:** Planned

**Objective:**  
Redesign briefings as a configurable, interactive way to understand the personal environment, using the context, review, run, and external-activity foundations established by the earlier betas.

The redesign should begin with the operator's real briefing needs rather than preserving the current modes unchanged. Specialized briefings may serve different purposes, such as starting the day, reviewing a project, or catching up on outside work. The first version should support a useful, manageable set of experiences without trying to anticipate every possible mode.

A briefing's purpose should be separate from the model that generates it. Configuration should describe the subjects, sources, time range, level of detail, and presentation the operator wants. Model selection and generation settings should be separate choices, with capability checks where needed. A mode should not require a particular named model simply because that was its original implementation.

Briefings should combine relevant accepted context, current connector data, pending reviews, verified-action state, and selected external activity. They should help explain what changed, why it matters, what needs a decision, and what can wait. APEX should continue reading its own services directly; the exported vault is for outside consumers, not a replacement for internal context retrieval.

External reports need to retain their status as reports. A briefing can say that an outside tool found something or that a finding needs review without presenting it as an accepted fact. Reading or dismissing an Inbox item must not silently promote its contents into trusted knowledge.

Attention should persist between briefings. A small set of attention records should prevent the same item from being presented as new every time and let the operator review, dismiss, or resolve it where appropriate. These records should point back to existing tasks, reports, reviews, or actions rather than create another task-management system.

The experience should support follow-up. The operator should be able to ask why an item matters, inspect its evidence, narrow the briefing to a subject, request more detail, or move into an approved action. Existing Cortex conversation and run capabilities should support this interaction.

More agentic briefing generation should reuse the bounded-run system. Apex Agent may retrieve additional relevant context or check an approved source when needed, while APEX enforces the allowed tools, input limits, time and token budgets, cancellation, and action permissions. Briefings should not introduce a second Agent runtime.

Proactive behavior should begin with a few concrete, opt-in uses. Existing refreshes, newly received reports, or a configured schedule may update attention or prepare a briefing when that is useful. The operator should control when this happens, whether a model may be called, and whether it produces a notification. Repeated or unchanged information should not generate unnecessary work or interruptions.

Only the hooks needed for these uses belong in this milestone. A general webhook platform, workflow engine, always-on autonomous assistant, and broad automation integrations are outside its scope.

A useful non-model view should remain available when generation is unavailable or unnecessary. Briefings should make missing or stale sources clear, and fallback behavior should not silently turn a requested experience into a different one.

This is the final feature beta before v2.0.0. Its scope should settle the briefing configuration, attention state, interaction model, and relationship with existing APEX services. Additional modes and integrations can follow later without holding the stable release open indefinitely.

---

## v2.0.0 - APEX 2.0 Stable

**Status:** Planned

**Objective:**  
Consolidate the six beta milestones into a stable APEX 2.0 release without adding another major feature area.

The release should settle the contracts for personal context and evidence, review decisions, Apex Agent runs, verified actions, external activity, generated context vaults, briefing configuration, and persistent attention.

Migration work should preserve useful operator data, including conversations, accepted context, source history, reviews, actions, run summaries, reports, and existing briefing history. Remaining obsolete settings and compatibility code should be removed where they are no longer needed.

Vault testing should cover export selection, retractions, obsolete generated files, broken links, regeneration, and protection of handwritten notes. Documentation should clearly distinguish local APEX records from copies shared through cloud storage or other applications.

Briefing testing should cover normal use, missing or stale sources, unreviewed external findings, unavailable models, cancellation, repeated attention items, and opted-in background generation.

APEX should remain usable without Google Drive, Obsidian, an outside AI application, or an optional tracing service. A missing external service must not prevent access to locally stored personal context.

Fresh and upgraded installations should reach the same current schema and configuration. Documentation should explain data ownership, privacy boundaries, export behavior, model selection, and the limits of any proactive features.

Stable v2.0.0 should mark a reliable foundation for future improvements, not require every possible briefing mode, connection, or automation to be finished.

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

Cortex should be able to answer questions about current conditions, use recent history in briefings, and explain important changes. Selected observations may update attention or support an opted-in briefing. Any Tyto-specific event handling should be added in this milestone and reuse existing APEX services where practical.

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

These ideas are not requirements for stable v2.0.0. They should be scheduled only when an actual use case needs more than the existing local services, Inbox, context vault, or briefing system provides.

* **Live remote context access:** An authenticated MCP or API service may be considered if outside applications genuinely need fresh, interactive retrieval that exported files cannot provide. The existing local submission gateway should not be exposed publicly as a shortcut.
* **Edits from Obsidian or other note tools:** Changes to exported notes may eventually become proposals for APEX review. They should not silently overwrite accepted personal context.
* **External task delegation:** APEX may hand a bounded task to Hermes Agent or another isolated runtime when there is a practical reason to start that work from APEX.
* **Workflow tools and additional event sources:** A specific workflow, webhook, or device connection may justify an adapter to an established tool. APEX should add the connection needed for that use, not build a general automation platform.
* **Portable procedural skills:** An existing skill format may be adopted when repeated APEX procedures justify it.
* **A cloud-hosted APEX service:** Live access or processing while the main machine is offline would require a separate design for hosting, security, synchronization, and data ownership. This is different from syncing a generated Markdown vault.

Custom replacements for the native interfaces of outside Agent products are not planned.

---

# Long-Term Vision

APEX is intended to be the trusted personal dashboard and context home around the tools the operator chooses to use.

It should understand the operator's environment, preserve where information came from, protect access to it, and make useful connections between projects, commitments, decisions, outside work, and current conditions.

Personal context should be useful both inside and outside APEX. A generated vault can make selected knowledge readable in a note application or available to an AI tool without moving ownership of that knowledge out of APEX.

Apex Agent is the native assistant for this environment. Its role is to help the operator understand their context, investigate relevant changes, prepare useful briefings, and carry out approved APEX actions.

Briefings should become configurable and interactive. Different needs may call for different sources, levels of detail, models, and delivery styles. The lasting value should come from how APEX relates information to the operator's environment, not from a particular model or a fixed collection of briefing modes.

Outside tools can continue to handle research, coding, browsing, terminal work, and long autonomous tasks through their own interfaces. APEX can receive the results that matter and share the context the operator chooses.

The local-first model remains the default. Core records and services stay under the operator's control, while selected exports may be copied into cloud storage. Public APEX hosting is not required.

Models, note applications, sync providers, and outside AI products should remain replaceable. Changing those tools should not mean rebuilding APEX or losing the personal context accumulated within it.

## Current Focus

APEX is currently in **Phase V: APEX 2.0 Beta**.

**Next milestone:**
[v2.0.0-beta.5 - Context Vault & Sharing](#v200-beta5---context-vault--sharing)
