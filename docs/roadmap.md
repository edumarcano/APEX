# APEX Roadmap and Future Possibilities

APEX has completed its core foundational milestones through **v2.1.0** (the Native Desktop Foundation). There is no longer a rigid development schedule or committed sequence of versioned releases. Future work is exploratory and spontaneous; features may be picked up, changed, or set aside based on interest rather than a fixed timeline.

This document collects architectural ideas, potential workflows, and areas of exploration that may be explored in the future. See [Roadmap History](roadmap-history.md) for completed milestones from v0.1 through v2.1, and the [Changelog](../CHANGELOG.md) for detailed release notes.

## Completed Milestones

All planned foundation milestones through v2.1.0 are complete:

- **v1.0 - v1.20**: Foundational data ingestion, daily operations, and modernization (archived in [Roadmap History](roadmap-history.md)).
- **v2.0.0 - APEX 2.0**: Local-first personal intelligence foundation, persistent conversations, verified actions, external reports, context vault, and adaptive briefings.
- **v2.1.0 - Native Desktop Foundation**: Native Windows desktop shell powered by Tauri v2 with supervised background hosting, separate runtime profile, system tray integration, and per-user packaging.

---

## Potential Direction: Personal Context Portability

One significant area of interest is helping you bring your personal context to the AI services you choose, so that changing AI tools does not require explaining your projects, preferences, and decisions from scratch.

### Working Concept

APEX would keep the primary, trusted record of personal context on your computer. Outside AI services could receive selected copies or query allowed records when needed:

```text
APEX records -> scope and permissions -> Context Compiler
                                              |
                            live reads / file exports / copied text
                                              |
                                       chosen AI service
```

Key principles for this exploration:

- **Local ownership**: The desktop app and local database remain the primary record; outside services receive projections or copies.
- **Scoped sharing**: A named scope defines which records can be shared (e.g., an APEX project scope). Sensitive records require explicit permission.
- **Provenance and evidence**: Records retain their sources, timestamps, and history. Outside AI reports remain evidence to review rather than accepted facts.
- **Format independence**: Context should not depend on a proprietary format tied to a single AI vendor.

### Potential Capabilities to Explore

- **Local MCP Access**: A read-only Model Context Protocol (MCP) endpoint allowing local MCP clients (such as Claude Desktop or IDE tools) to query allowed records.
- **Context Capsules**: Bounded text packages that can be previewed and copied into any web chat when a direct connection is unavailable.
- **Machine-Readable Exports**: Structured exports (such as JSON) alongside the existing Markdown [Context Vault](context-vault.md).
- **Report Ingestion & Review**: Ingesting outside research reports into review proposals that link new claims, potential corrections, and conflicts back to their source before acceptance.

---

## Potential Direction: Remote Context Access

If local context sharing proves valuable, another possible exploration is allowing cloud AI apps to query current APEX context over a secure remote connection while the host machine is online.

### Ideas to Explore

- **Context Gateway**: A lightweight, separate endpoint that exposes only approved read operations for remote clients, keeping the main loopback API and background services inaccessible.
- **Zero-Cost Tunnels**: Evaluating free tunneling mechanisms (such as Tailscale Funnel) to avoid requiring paid infrastructure or public static IPs.
- **Scoped Client Authentication**: Identifying and restricting remote callers to specific pre-approved context scopes, with visible revocation controls.

---

## Potential Direction: Context-Centered Interface Rework

If context portability becomes the primary focus, the HUD layout could eventually be restructured around context management and interactions with Lynx:

### Ideas to Explore

- **Dedicated Context Workspace**: A workspace centered on exploring, filtering, and editing personal records, reviewing sources, and inspecting sharing scopes, potentially with an interactive relationship graph.
- **Unified Lynx Workspace**: Bringing Cortex conversations and saved Briefings together under Lynx, retaining spoken highlights and follow-up threads.
- **Integrated Inbox**: Moving Reports into an inbox or source rail within the context view, preserving summaries of outside work.

---

## Other Potential Ideas

These are unscheduled possibilities that may be explored if a concrete need arises:

- **Multilingual Support**: Supporting English and Spanish across interface text, Agent responses, briefings, and speech, while keeping source evidence in its original language.
- **Adaptive Speech**: Evaluating lighter TTS engines (such as Gemini Flash-Lite or newer ONNX models) alongside Google Cloud TTS and local engines.
- **Conversational Voice**: Exploring live voice interaction or voice commands for Lynx's context role while keeping text and CLI interfaces independent.
- **Note App Bidirectional Review**: Allowing edits made in Obsidian notes to be imported as review proposals rather than directly overwriting database records.
- **Reusable Skills / Procedures**: Adopting standardized skill formats for repeated tasks when warranted.
