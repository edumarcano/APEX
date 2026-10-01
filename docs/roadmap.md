# APEX Roadmap

> [!NOTE]
> This roadmap records how APEX has changed, what each phase set out to solve, and where the project is heading next.
> Completed milestones provide historical context; [the changelog](../CHANGELOG.md) remains the detailed record of released changes.
> Planned milestones reflect current intent. Their order, scope, implementation details, and phase boundaries may change as development progresses.
> Planned milestones may include more detail while they are still being designed. Once completed, they are shortened to their final outcome while the changelog keeps the release details.

## Current Focus

**Current Phase:** [Phase VI: Native Platform & Interaction](#phase-vi-native-platform--interaction)  
**Next Milestone:** [v2.1.0 - Native Desktop Foundation](#v210---native-desktop-foundation)  
**Current Direction:** [APEX 2.0 Direction](#apex-20-direction)

### Navigation

[Phase I: Foundational](#phase-i-foundational) ·
[Phase II: Modernization](#phase-ii-modernization) ·
[Phase III: Cognitive Interface](#phase-iii-cognitive-interface) ·
[Phase IV: Interactive Intelligence](#phase-iv-interactive-intelligence) ·
[Phase V: APEX 2.0 Beta](#phase-v-apex-20-beta) ·
[Phase VI: Native Platform & Interaction](#phase-vi-native-platform--interaction)

---

# Roadmap Summary

APEX began as a collection of small Python automation scripts and has grown into a local-first personal context and operations platform.

Its development has moved through several stages:

* **Foundational automation:** Collect personal data, run scheduled tasks, and establish the first client-server version of APEX.
* **Modern interface architecture:** Move to the React and Vite HUD, make system activity visible, and establish the visual model used today.
* **Cognitive interaction:** Add conversational AI, cloud and local models, briefing generation, and the beginnings of Cortex.
* **Native assistance and verified actions:** Give APEX a built-in assistant that can use tools, work with personal context, and propose verified changes through both the HUD and CLI.
* **Trusted context and connected tools:** Keep a lasting, sourced understanding of the operator's environment and accept useful information from outside tools without giving those tools ownership of APEX.
* **Native platform and interaction:** Move APEX into a native desktop environment, improve how it presents information, and expand how the operator can interact with it without moving ownership of APEX state into the desktop shell.

APEX should become exceptionally good at understanding, protecting, connecting, and presenting the operator's personal environment.

It does not need to become the place where every task is performed. General-purpose AI products, coding Agents, research tools, workflow systems, automation platforms, and device hubs can keep their own interfaces and remain responsible for the work they already do well.

APEX should connect to those tools without becoming dependent on them. It should receive useful results, relate them to personal context, preserve their sources, and show what deserves attention.

The APEX Agent is the native assistant for this environment. It should be unusually good at working with APEX context, telemetry, connected services, briefings, reports, and verified actions. It does not need to compete with general-purpose Agent products.

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

## v1.19.0 - APEX Agents & Cortex Workspace

**Status:** Complete

**Objective:**
Establish APEX Agents as APEX's provider-neutral intelligence abstraction, unify cloud and local runtime behavior, expand local execution across multiple providers, and evolve the Cortex Workspace into the primary surface for Agent configuration, tool policy, runtime control, and interaction.

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

**Status:** Complete

**Core Focus:**
Build and stabilize the parts of APEX that should remain specific to the operator: personal context, source history, review, permissions, verified actions, attention, and a consistent interface.

APEX should not try to recreate production-grade tools for general-purpose Agent work, workflow execution, automation, system monitoring, remote networking, or device management.

When another project already solves one of those problems well, APEX should connect to it through a small, replaceable adapter. The outside tool should keep responsibility for its own execution and interface. APEX should keep only the information needed to understand, present, review, and safely use its results.

[Back to Current Focus](#current-focus)

---

## Cortex Initiative continued

The Cortex initiative established APEX's interactive foundation: model and provider support, tool use, runtime controls, persistent conversations, verified actions, and access from both the HUD and CLI.

Earlier versions explored a larger family of named Agents and later reduced it to separate cloud and local Agents. That structure was eventually consolidated into one APEX Agent.

APEX Agent is now APEX's built-in personal operations assistant. The selected model determines whether a request runs through a cloud provider or a local runtime.

This keeps the useful model, tool, and action infrastructure without treating every model or runtime as a separate Agent identity.

Phase V builds on this foundation with trusted personal context, bounded runs, outside activity reports, portable context, and a redesigned briefing experience.

Cortex should help the operator understand and work with their APEX environment without becoming another general-purpose Agent platform.

---

## APEX 2.0 Direction

APEX should become exceptionally good at understanding, protecting, connecting, and presenting the operator's personal environment.

It keeps accepted personal context and the evidence behind it. Conversations, connected-service records, outside reports, and model interpretations remain distinguishable, and important changes retain their history.

Outside tools should normally be used through their native interfaces. They can submit useful results through the Reports workspace without giving APEX responsibility for their sessions, task execution, or controls.

Trusted context can also travel in the other direction. APEX can maintain a selected, readable copy in a local folder, which the operator may sync through Google Drive, open in Obsidian, or use with an AI application. This does not require exposing the APEX backend to the internet.

The exported folder is a view of APEX context, not a second source of truth. APEX decides what it generates; the storage provider and receiving applications control access to the copies they receive.

APEX Agent remains the native assistant for this environment. It can explain records, compare connected information, prepare briefings, investigate relevant changes, and propose APEX-managed actions.

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
Unify models and runtimes under a single APEX Agent, and introduce bounded execution with APEX-enforced limits, a durable run ledger, live event streaming, an in-HUD activity inspector, OpenTelemetry GenAI tracing, and CLI run controls.

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

**Status:** Complete

**Objective:**
Publish selected trusted personal context as linked Markdown notes for Obsidian and sharing through synced folders.

---

## v2.0.0-beta.6 - Cortex: Adaptive Briefings & Attention

**Status:** Complete

**Objective:**
Rebuild briefings around a bounded, saved-session engine with Daily, Catch Up, and Deep profiles, grounded speech synthesis from saved artifacts, and dedicated Overview and Briefing workspaces.

---

## v2.0.0 - APEX 2.0 Stable

**Status:** Complete

**Objective:**
Consolidate the six beta milestones into a stable local-first foundation for personal context, verified actions, external reports, context sharing, and saved briefings.

---

# Phase VI: Native Platform & Interaction

**Status:** Planned

**Core Focus:**  
Move APEX from a browser-hosted local interface into a native desktop environment while preserving its independent backend and CLI, then improve how the system presents information and supports natural operator interaction.

The desktop application should remain a client of APEX rather than becoming the owner of Cortex, persistence, or personal context.

Native capabilities should be added through small platform services with clear boundaries so that desktop-specific behavior does not spread through Cortex or the frontend architecture.

[Back to Current Focus](#current-focus)

---

## v2.1.0 - Native Desktop Foundation

**Status:** Planned

**Objective:**  
Establish APEX as a native desktop application while preserving the backend, APIs, persistence, Cortex runtime, and CLI as independent platform components.

The main milestone should:

* package the existing React and Vite interface with Tauri;
* replace the current browser-window and static-server presentation path;
* define a clean lifecycle contract between the desktop application and the Python backend;
* keep the backend and CLI usable without the desktop shell;
* use Tauri and maintained plugins for desktop concerns such as application windows, startup, system tray behavior, notifications, permissions, deep links, updates, and distribution where useful;
* introduce a small platform-service boundary for native capabilities instead of calling desktop APIs directly from Cortex or scattered frontend components;
* provide permissioned shared device context, beginning with live location for features such as Weather;
* review idle resource use during the native transition and avoid keeping optional local models or heavyweight runtimes resident when they are not needed.

The existing Python launcher may remain useful for development or headless operation, but the packaged desktop application should no longer depend on launching a separate browser window.

The Tauri shell must not become the source of truth for personal context, conversations, briefings, actions, or Cortex runtime state.

Basic system-theme integration or shell-level appearance behavior may be added where useful, but a full theme editor should not block the native application.

The goal is to make APEX feel like a native application without tying the APEX platform to a single interface.

---

## v2.2.0 - Multilingual Foundation

**Status:** Planned

**Objective:**  
Make APEX fully usable in English and Spanish while establishing a localization architecture that can support additional languages without duplicating application logic.

APEX should have an explicit application-language preference, initially supporting English and Spanish. Native platform locale information may provide a sensible default, but the operator should remain in control of the selected language.

The milestone should:

* introduce a centralized localization system for user-facing frontend text;
* support English and Spanish throughout the primary APEX workspaces and settings;
* make APEX-owned Agent instructions, responses, status text, and interaction surfaces language-aware;
* generate briefings and spoken highlights in the selected language;
* establish language-aware speech configuration so TTS providers and voices can resolve appropriately;
* present dates, times, numbers, and other locale-sensitive information appropriately;
* define consistent behavior when source material or connected-service content is written in a language different from the selected APEX language.

Localization should remain primarily a presentation and interaction concern. Internal identifiers, API contracts, persistence schemas, tool names, logs, and original source evidence should not be translated merely because the interface language changes.

Stored evidence and external content should preserve their original meaning and provenance rather than being silently rewritten into the current application language.

The goal is to make English and Spanish first-class ways to use the same APEX system while creating a foundation that can support additional languages later.

---

## v2.3.0 - Adaptive Presentation

**Status:** Planned

**Objective:**  
Improve how APEX communicates information through both visual presentation and speech without changing the underlying Cortex or personal-context architecture.

Expand speech delivery with Gemini Flash-Lite TTS as a high-quality option for spoken briefing highlights while preserving Google Cloud TTS and local engines as independent choices.

Speech engines, voices, and delivery instructions should respect the selected APEX language. Spoken briefing delivery may use profile-aware, language-aware, or purpose-specific speaking instructions when they improve clarity and naturalness, while the saved briefing artifact remains the grounded source of truth.

Expand the visual presentation system beyond the current fixed dark atmosphere. Theme work may include light and dark presentation, additional curated themes, system-theme awareness, and an interactive theme configuration surface.

Presentation choices should remain preferences rather than changing the meaning, persistence, or structure of APEX data.

The goal is for APEX to adapt how it looks and sounds while keeping the underlying information and interaction model consistent.

---

## v2.4.0 - Conversational Voice

**Status:** Planned

**Objective:**  
Add a voice-first interaction mode that allows the operator to converse with and control APEX without requiring continuous keyboard and mouse interaction.

Voice interaction should support the languages established by APEX's multilingual foundation rather than introducing a separate language configuration or English-only interaction path.

The milestone should begin by evaluating the appropriate architecture rather than assuming a specific realtime model.

Possible approaches include:

* speech recognition feeding the existing APEX Agent, tool, context, action, and verification infrastructure, followed by normal speech synthesis;
* a realtime multimodal model such as Gemini Live or another compatible live provider, connected to APEX through bounded capabilities.

Voice interaction should reuse APEX's existing Agent, tool-policy, approval, context, and action boundaries wherever practical rather than creating a parallel assistant architecture.

The operator should remain able to inspect important actions and approvals through the normal interface. Voice interaction must not bypass existing verification or permission boundaries.

Voice mode should remain optional, and the existing text interface and CLI should continue to function independently.

The goal is to make APEX usable conversationally while preserving the same trusted operational model established by Cortex.

---

# Unscheduled Possibilities

These ideas are not requirements for the currently planned milestones. They should be scheduled only when an actual use case needs more than the existing local services, Reports, context vault, briefing system, or native application provides.

* **Live remote context access:** An authenticated MCP or API service may be considered if outside applications genuinely need fresh, interactive retrieval that exported files cannot provide. The existing local submission gateway should not be exposed publicly as a shortcut.
* **Edits from Obsidian or other note tools:** Changes to exported notes may eventually become proposals for APEX review. They should not silently overwrite accepted personal context.
* **External task delegation:** APEX may hand a bounded task to Hermes Agent or another isolated runtime when there is a practical reason to start that work from APEX.
* **Workflow tools and additional event sources:** A specific workflow, webhook, or external source may justify an adapter to an established tool. APEX should add the connection needed for that use, not build a general automation platform.
* **Portable procedural skills:** An existing skill format may be adopted when repeated APEX procedures justify it.
* **A cloud-hosted APEX service:** Live access or processing while the main machine is offline would require a separate design for hosting, security, synchronization, and data ownership. This is different from syncing a generated Markdown vault.

Custom replacements for the native interfaces of outside Agent products are not planned.

---

# Long-Term Vision

APEX is intended to be the trusted personal dashboard and context home around the tools the operator chooses to use.

It should understand the operator's environment, preserve where information came from, protect access to it, and make useful connections between projects, commitments, decisions, outside work, and current conditions.

Personal context should be useful both inside and outside APEX. A generated vault can make selected knowledge readable in a note application or available to an AI tool without moving ownership of that knowledge out of APEX.

APEX Agent is the native assistant for this environment. Its role is to help the operator understand their context, investigate relevant changes, prepare useful briefings, inspect outside reports, and carry out approved APEX actions.

Briefings should become configurable and interactive. Different needs may call for different sources, levels of detail, models, speaking styles, and delivery methods. The lasting value should come from how APEX relates information to the operator's environment, not from a particular model or a fixed collection of briefing modes.

The native desktop application should improve access to APEX without becoming the platform itself. Cortex, persistence, APIs, and the CLI should remain separable from the desktop shell so that future interfaces can be added without relocating APEX's source of truth.

Outside tools can continue to handle research, coding, browsing, terminal work, and long autonomous tasks through their own interfaces. APEX can receive the results that matter and share the context the operator chooses.

Interaction may expand beyond keyboard and mouse through speech and other native capabilities, but those interfaces should continue to use the same context, permission, verification, and action boundaries.

The local-first model remains the default. Core records and services stay under the operator's control, while selected exports may be copied into cloud storage. Public APEX hosting is not required.

Models, note applications, sync providers, speech providers, and outside AI products should remain replaceable. Changing those tools should not mean rebuilding APEX or losing the personal context accumulated within it.

## Current Focus

APEX is currently in **Phase VI: Native Platform & Interaction**.

**Next milestone:**  
[v2.1.0 - Native Desktop Foundation](#v210---native-desktop-foundation)