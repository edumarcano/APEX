# APEX Roadmap

APEX will focus on helping you bring your personal context to the AI services you choose. Changing AI apps should not mean explaining your projects, preferences, and past decisions from scratch.

APEX 2.0 built the first version of that context system. This roadmap starts with v2.1, the desktop release already in progress. It replaces the old phase numbers with release milestones. See [Roadmap History](roadmap-history.md) for the completed work through v2.0 and the [Changelog](../CHANGELOG.md) for release details.

These milestones describe planned outcomes, not features that have all shipped. Each milestone gets its own implementation plan before work starts. That plan will choose the exact tools, screens, and branch order. Scope may change as we test what works.

## Direction

Personal context means the facts, goals, preferences, and decisions that help an AI understand you. For example, APEX could store why you chose a model for a project and which later decision replaced that choice.

APEX will keep the main record of that context under your control. Other AI services can receive selected copies or request allowed records when they need them. You should be able to change services without rebuilding your context.

Lynx, the default name of the APEX Agent, will help you maintain that record. It can inspect sources, prepare changes for review, answer questions, and give briefings. It does not need to replace the AI apps you use for research, coding, or general conversation. See [Identity and Naming](identity-and-naming.md) for the current names and roles.

The working rules are:

- **Keep ownership local.** Local-first means APEX keeps its main records on your computer. The desktop window, an AI provider, or a synced folder must not become the only place those records live.
- **Share only what you choose.** A scope is a named set of records allowed for sharing, such as an APEX project scope. Every sharing method must honor that choice. Sensitive records need separate permission.
- **Keep the evidence and history.** Records must keep their sources, dates, and changes. AI-written reports remain evidence to review, not accepted facts about you.
- **Keep connections replaceable.** APEX must not store its main records in a format tied to one AI service. Search indexes are copies that APEX can rebuild, not the original records.
- **Require no paid infrastructure.** Core sharing must not require a paid domain, hosted server, or sync subscription. An AI service may still charge for its own models or features.
- **Be clear about limits.** A receiving app must support the chosen sharing method. APEX cannot force it to use the context or erase copies it has already kept. Sending text to a cloud model sends that text outside your computer, even through a local connection.

## How context will move

Every way of sharing context will use the same rules to choose and protect records. A **Context Compiler** is the APEX component that selects allowed records and prepares them for a request. It must respect a size limit rather than send the whole context store to every AI.

It creates **projections**: selected views or copies of APEX records. The main record stays in APEX. A short copied summary and a live search result can contain different amounts of detail while following the same sharing rules.

```text
APEX records -> scope and permissions -> Context Compiler
                                              |
                            live reads / file exports / copied text
                                              |
                                       chosen AI service
```

Live access will first use **MCP (Model Context Protocol)**, a shared way for AI apps to request tools and data. MCP is one connection method, not APEX's storage format. Another method should be able to replace it without changing the records.

A **Context Capsule** is a short text package you can copy into an AI chat. It provides a fallback when an app has no live connection. The existing [Context Vault](context-vault.md), which exports selected records as linked Markdown text files, will remain another option.

Context must also travel back into APEX:

```text
External report -> proposed additions or corrections -> user review
                                                            |
                                                       APEX records
```

Imported text must retain its source. It must not silently replace accepted records or grant an outside AI permission to change them.

## Release plan

| Release | Status | Outcome |
| --- | --- | --- |
| [v2.1.0 - Native Desktop Foundation](#v210---native-desktop-foundation) | In progress | Run APEX as a desktop app without tying its data to the window. |
| [v2.2.0 - Context Portability Foundation](#v220---context-portability-foundation) | Planned | Share selected context locally or as files and text; review context from reports. |
| [v2.3.0 - Remote Context Access](#v230---remote-context-access) | Planned | Let supported cloud AI apps read selected live context through a protected connection. |
| [v2.4.0 - Context-Centered Interface](#v240---context-centered-interface) | Planned | Rework the app around managing context and working with Lynx. |

## v2.1.0 - Native Desktop Foundation

**Status: In progress.** Keep the existing desktop milestone in this roadmap. Its scope does not change because of the new direction.

Use **Tauri**, a tool for packaging web interfaces as desktop apps, to host the existing React and Vite interface. The packaged app must not need a separate browser window or static web server.

The **backend**, which runs APEX's services and stores its data, must stay independent of the desktop window. So must the **API**, the interface other programs call, and the **CLI**, the command-line tool. Define how the desktop app starts and stops the Python backend. Define what happens if either process fails. The desktop app must not take ownership of context, conversations, briefings, actions, or the Cortex Engine.

This milestone also covers:

- Use Tauri and maintained plugins for windows, startup, tray controls, notifications, and permissions. Use them for app-opening links, updates, and distribution where needed.
- Keep desktop-only code behind a small shared interface. Do not spread it through the Agent or screen code.
- Add device information with permission, starting with current location for Weather.
- Check memory use while idle. Do not keep optional local models or other large processes loaded without a reason.
- Keep the Python launcher useful for development or use without a window. Basic system-theme support is allowed; a full theme editor is not required.
- Remove the GNews-backed News feed and adjust Overview for the remaining services. Do not add a replacement feed. Keep evidence from saved briefings available.

## v2.2.0 - Context Portability Foundation

**Status: Planned.** Make selected context usable outside APEX before adding public internet access.

Build the Context Compiler on the existing records, review system, and scopes. Change the stored data only where sharing reveals a real gap. Give the local MCP server, capsules, and exports the same rules for permissions, sources, and current records. Old or retracted claims must not return as current facts.

Deliver:

- Read-only local MCP access for apps that can run a local connection.
- Context Capsules with a size limit and a preview before copying.
- A machine-readable export, such as JSON, a common text format for data. Keep the Markdown Context Vault and reuse shared rules where practical.
- A report-import workflow that finds new claims, possible corrections, conflicts, and facts already stored. Group proposed changes for review and keep each claim linked to its source.
- Controls in the existing interface for scopes, previews, exports, local connection status, and report review.

The report workflow addresses the need raised in [issue #577](https://github.com/edumarcano/APEX/issues/577). Lynx should process a report as a batch. It should not need a separate chat loop for every claim. Keep work bounded and report partial results clearly. The implementation plan should decide whether any run limits also need to change. This roadmap does not settle that by removing them.

The completion test should use a report like the one exported from Gemini. Review its proposed changes, save accepted records, then retrieve the allowed subset through a local MCP client and a capsule. Check sources, excluded sensitive records, and corrections, not just a successful read.

Public access, automatic two-way sync, imports from every AI service, and the workspace redesign are outside this milestone. Reports, Cortex, Briefing, and Overview remain in place.

## v2.3.0 - Remote Context Access

**Status: Planned.** Let a supported cloud AI app read current APEX context while the APEX computer is online.

Reuse v2.2's context services. Add a **context gateway**, a separate entry point that exposes only the approved read operations. Do not publish the main backend on port 8000 or reuse the existing report-submission gateway as a public shortcut.

Evaluate a free connection method, such as Tailscale Funnel, during implementation planning. A **tunnel** carries requests between an outside service and a local service. Some methods make the gateway reachable on the public internet; others may use a provider's private connection. Either way, the gateway must check who is calling and what they may read. A tunnel alone does not grant access.

This milestone must include:

- A supported way to identify each remote client and limit it to chosen scopes.
- Read-only access, request size and rate limits, and a record of access that avoids logging private content unnecessarily.
- Visible controls to enable or disable sharing, inspect connection status, change permissions, and revoke a client's access.
- Clear behavior when APEX goes offline or the connection fails. Revocation stops future reads; it cannot recall copies already sent.
- An end-to-end test in at least one real consumer AI app using an account that supports the connection.

Keep mandatory infrastructure cost at $0. Verify the chosen service's terms and the receiving app's account requirements during planning. A connection that works in a developer API may not work in the consumer chat app. Do not promise compatibility with every AI service.

The completion test is a current, source-linked answer from a cloud AI app on another device. It must use only its allowed APEX context and require no public access to the main backend. Also test denied and revoked access. Hosting a copy that stays live while the APEX computer is off remains later work.

## v2.4.0 - Context-Centered Interface

**Status: Planned.** Make context management the center of the app once local and remote sharing work.

Plan a dedicated Context workspace and a Lynx workspace. Bring Cortex conversations and Briefing access together under Lynx. Keep saved briefings, their evidence, spoken highlights, and follow-up conversations. This changes how users reach those features; it does not require replacing the Cortex Engine.

Move Reports into an appropriate source or inbox area within Context. Keep reports useful as records of outside work even when none of their findings become personal context. Plan to retire Overview as a separate workspace. Keep connector data and controls where Context or Lynx still needs them.

Context should support finding and editing records, reviewing sources and history, resolving conflicts, and managing sharing. Add an interactive relationship graph alongside search and list views. Keep APEX's space-inspired visual style, but leave graph layout, animation, screen structure, and navigation details to implementation planning.

Evaluate access to selected source files without turning APEX into a general file-storage service. File access must follow the same permission rules as other context.

Lynx should focus on helping you maintain and use your context. Keep Calendar, Gmail, web search, and other connectors when they serve that role. Do not expand its tools just to match a general-purpose AI assistant.

The controls added in v2.2 and v2.3 must remain usable throughout this change. Those releases add the controls their features need; v2.4 owns the wider interface redesign.

## Later work

The former v2.2-v2.4 plans move here without release numbers. They are deferred, not cancelled. Schedule them only when they support the context-focused direction.

- **Multilingual Foundation:** Support English and Spanish with a user-controlled language setting. Cover interface text, Agent responses, briefings, speech, dates, times, and numbers. Keep original evidence in its source language. Do not translate internal names, data formats, or API fields with the interface.
- **Adaptive Presentation:** Evaluate Gemini Flash-Lite text-to-speech while keeping Google Cloud TTS and local engines as choices. Match voices and delivery to the selected language and briefing purpose. Keep speech based on saved briefing content. Consider light and dark themes, system-theme support, and theme controls without changing stored data.
- **Conversational Voice:** Revisit voice control for Lynx's context role. Compare speech recognition plus existing tools with a live voice model. Reuse the same languages, permissions, approvals, and action checks. Keep text and CLI access independent.
- **More import and export formats:** Add AI memory formats when a real service needs them. Keep adapters small and leave APEX's own records independent of those formats. Do not invent a new industry standard.
- **Edits from note apps:** Let changes made in Obsidian or another note app become review proposals, not silent replacements for APEX records.
- **News reports and outside tasks:** Accept useful research with sources, dates, and clear freshness. Test delivery and briefing selection. Do not treat Reports as an automatic replacement for the removed News feed. Delegate tasks or add workflow connections only for a concrete need, not to build another agent platform.
- **Reusable procedures:** Adopt an existing skill format when repeated APEX tasks justify it.
- **Access while the main computer is off:** Design hosting, sync, security, and data ownership separately. A synced export is not a live APEX service. Paid hosting may be optional, but it must not become a requirement for core context sharing.
