# APEX Design System

This reference defines the visual and interaction language for contributors working on the React HUD. It explains the design intent and reusable rules rather than individual component implementation; runtime ownership belongs in [Architecture](architecture.md), and frontend code conventions live in the [Frontend Guide](../frontend/README.md).

The meaning of the APEX mark and its relationship to the product and Agent names is documented in [Identity and Naming](identity-and-naming.md).

## Visual Direction

APEX uses a dark, cinematic operations look built around atmospheric lighting, metallic transitions, glass surfaces, and mission-control details. The background and identity effects should frame the interface without making telemetry or controls harder to read.

Prioritize clarity, accessibility, and information hierarchy over atmosphere. Visual effects should reinforce system state, depth, or interaction rather than compete with content.

## Color Families

APEX uses coordinated color families rather than a single flat accent palette. Representative colors define the visual language; lighter and darker shades may extend each family for gradients, contrast, and depth.

| Family | Representative colors | Primary meaning |
| --- | --- | --- |
| Blue | `#082F7A`, `#0F4DB8`, `#1F6FE5`, `#6EA8FF`, `#7EB3FF` | Platform identity, navigation, controls, selected content, and active attention |
| Emerald | `#047857`, `#10B981`, `#39FF88`, `#6EE7B7` | Processing, data collection, live status, and healthy availability |
| Purple | `#7E22CE`, `#A855F7`, `#C084FC`, `#D8B4FE` | Briefing investigation and synthesis, Agent reasoning, queries, and tool execution |
| Gold | `#D97706`, `#FBBF24`, `#FFD166`, `#FFF3B0` | Briefing persistence and prepared output, important highlights, and stale-data warning |
| Rust | `#C2410C`, `#F97316`, `#FB923C`, `#FDBA74` | Local-model loading and loaded local-runtime state |
| Cyan | `#22D3EE`, `#A5F3FC` | Reports workspace tab accent, active speech, voice waveform, and developer-mode indication |
| Red | `#991B1B`, `#DC2626`, `#F87171` | Errors, failed operations, and unavailable services |
| Bronze | `#451A03`, `#78350F`, `#92400E`, `#B45309` | Dormant identity core and inactive energy |
| Neutral | Near-black, zinc, slate, white alpha, and `#52525B` | Surfaces, secondary text, separators, pending state, and unknown module status |

Use established CSS properties, shared utilities, and semantic classes before introducing repeated raw values. Component-local colors remain appropriate for gradients, weather, charts, market movement, and other domain-specific visualization where a global token would obscure meaning.

## State Semantics

Color meaning depends on the state system in which it appears. Do not assume one color has a single meaning across every component.

### Session and activity

| State | Visual family |
| --- | --- |
| Before a usable telemetry snapshot is available in the current app session | Filled blue shell with a dormant core while idle |
| Telemetry refresh, or a briefing in preparation/collection | Emerald |
| Briefing investigation, synthesis, or Agent working | Purple |
| Briefing persistence or prepared output | Gold |
| Local model loading | Rust |
| Resident local model | Rust logo glow |
| Spoken-highlight playback | Cyan waveform and atmospheric glow over the gold core |
| Failure | Red |

### Module health

| State | Visual family |
| --- | --- |
| Live or available | Emerald |
| Stale | Gold |
| Loading or unknown | Neutral gray |
| Error or unavailable | Red |

Pair state color with text, icons, shape, motion, or an accessible label. Never rely on color alone.

On Launch, Overview, Briefing, and in the compact Cortex header, the shared logo uses the same app-wide reactive state. Briefing preparation and collection use a dim gold core between emerald surges, selection uses a steady emerald core, investigation and synthesis use a dim bronze core between purple surges, and persistence and completion use a steady gold core. Active stages use a traveling blue shell wave except investigation, which keeps the shell steady. The nebula and logo glow follow the core during active work; completed briefings return both glows to blue. Spoken-highlight preparation uses the purple surge and blue wave. During playback the core stays gold, the shell stays steady blue, and the glyph waveform and nebula glow cyan. Actual model loading temporarily adds an orange shell wave and orange glows while keeping the current core stage visible. A loaded local model keeps the logo glow orange while the nebula continues to follow briefing or speech activity. Telemetry collection shares the dim gold core between emerald surges and traveling blue wave. Reduced motion keeps the stage colors without running the surges or waves.

## Material System

### Glass surfaces

- Use translucent near-black glass for primary telemetry panels and interactive shells.
- Use white-alpha borders and catch-lights to communicate material depth; do not paint every panel rim blue.
- Use the denser solid-glass treatment for overlays, Agent menus, diagnostics popovers, and surfaces that require stronger separation.
- Use inset near-black command surfaces for inputs, triggers, and operational controls.
- Preserve text contrast and visual containment when layered above nebula fields or the central logo.

### Lighting and elevation

- Use glow, gradients, blur, and layered shadows to reinforce hierarchy, activity, or state.
- Keep high-intensity glow concentrated on the active identity core, status indicators, and transient operational feedback.
- Allow hover and focus to brighten glass catch-lights, icon badges, dividers, and corner brackets without destabilizing layout.
- Avoid stacking multiple high-intensity effects where they obscure data or interaction targets.

## HUD Chrome

APEX uses a recurring mission-control vocabulary:

- Corner reticle brackets identify bounded operational modules.
- Icon badges anchor panel headings and controls.
- Header divider rails organize content and carry subtle accent light.
- Status LEDs communicate module freshness and availability.
- Monospace indexes, timestamps, and metrics suggest structured telemetry streams.
- Metric bars use inset tracks and state-aware fills.
- Command surfaces distinguish operator input from passive telemetry.

Reuse these established primitives instead of creating competing panel chrome.

### Briefing and voice controls

- Keep briefing controls in the Briefing rail. “Set up briefing” opens a responsive dialog with Daily, Catch Up, and Deep profile cards and one Apex Agent control. Its closed state keeps Model and Effort as separate segments showing the chosen model, provider, pricing, reasoning choice, and any stability or developer-mode badge. Each segment opens its own choices directly: Model lists Cloud/Local models with badges and prices, while Effort lists the selected model’s supported reasoning options. Draft choices stay local until Generate. For model-backed runs, the footer Generate action saves the selected Apex Agent model and reasoning settings before admitting a session; an error keeps the setup available for correction. Demo runs continue to use fixtures without saving a fixture model as the Agent selection. Cancel, saved sessions, source coverage, the resident local-model unload control, and speech controls stay in the rail. Saved sessions exclude archived Cortex conversations. “Repeat last briefing” uses the newest visible session and repeats its captured profile, model, and reasoning configuration against fresh context.
- Launch is the initial screen and contains the APEX identity, four workspace buttons, Settings, and an optional DEMO/DEVELOPER indicator. Launch uses the former standby hero mark and a gold APEX wordmark. Its workspace buttons stay neutral glass with zinc labels; only each button’s icon uses the peer accent (Overview blue, Briefing gold, Cortex purple, Reports cyan); Settings stays neutral. The APEX badge in workspace chrome returns to Launch without resetting app-level activity. Navigation never collects telemetry or requests a cue. Overview before collection shows its centered identity card and **Collect Telemetry** (emerald); the card keeps the large mark until the telemetry grid appears, then eases back to the grid mark, and reduced motion snaps that size change. Preflight cancellation leaves that card in place. After preflight proceeds, telemetry card shells appear with pending attention curtains; collection and briefing data gathering share the **Collecting data** glyph label. Reduced motion makes those reveals immediate. A usable snapshot opens the grid; failures without usable data show a centered error or no-data state with retry. A later refresh failure leaves an existing grid visible. The Briefing tab opens setup and generation without activation. Speech starts only after an explicit Prepare or Play action and never autoplays or regenerates on replay.
- Render a completed artifact as the opening message in the Briefing thread. Its heading marks the briefing as presented only after it has been visible.
- Summarize routine tool results compactly in the Briefing thread. Errors, action approvals, and trust labels always render in full.
- Share telemetry domain components between Overview cards and the Briefing telemetry rail rather than maintaining separate renderings. The rail is one bordered glass scroll panel; each domain renders as an internal section (heading, status LED, refresh controls, body) with generous vertical padding and hairline separators, without its own card chrome. Keep this section spacing scoped to the rail so Overview cards retain their existing chrome and compact layout.
- Collapse the artifact's other captured evidence into a closed disclosure that shows its count, matching the per-item Evidence disclosures.
- Present generation failures as red text with an accessible status role, and keep detailed local-model lifecycle information in Cortex.

## Attention and Disclosure

Telemetry surfaces use four attention states:

```text
dormant -> pending -> active -> complete
```

- **Dormant:** Preserve settled glass and readable standby content.
- **Pending:** Reduce saturation and brightness while keeping the shell visible; show a local loading or unavailable state when that resource has not arrived.
- **Active:** Apply blue catch-light and reveal the body as the surface becomes relevant.
- **Complete:** Return to settled glass while preserving completed content.

Use staggered transitions when a workspace opens to guide attention. Telemetry, briefing generation, Cortex, and speech can progress independently; keep the shell spatially stable as their own status changes.

## Atmospheric Layering

Build the HUD as a deliberate depth stack:

```text
Space gradient
-> celestial stars
-> reactive nebula and ambient glow
-> central metallic identity mark
-> bento HUD and console surfaces
-> solid overlays and popovers
```

- Keep the vignette strong enough to contain the composition and preserve edge contrast.
- Use slow, continuous atmospheric motion rather than fast decorative movement.
- Allow reactive glow to follow pipeline and runtime state without overwhelming the glass foreground.
- Keep decorative atmospheric layers non-interactive and outside the accessibility tree.

## Typography

Use three typographic roles:

- **Exo 2:** Default interface copy, readable body content, descriptions, and conversational output.
- **Orbitron:** Panel titles, state labels, compact controls, identity text, and short operational headings.
- **Monospace:** Telemetry, timestamps, symbols, diagnostic values, indexes, Agent metadata, and machine-oriented labels.

Use uppercase text and wide tracking primarily for short operational labels. Avoid long uppercase body copy. Use tabular numerals for values that update or align vertically.

## Layout and Responsiveness

- Build structural layout from flexible tracks, content constraints, and bounded min/max sizing.
- Preserve fullscreen containment on wide desktop viewports where the bento HUD is designed to fit within the viewport.
- Switch to natural-height, vertically scrollable composition below `1280px` width or `821px` height.
- Apply additional compact spacing and scale adjustments below `768px` width.
- Preserve intentional internal scrolling for panels, trays, and telemetry streams.
- Use fixed pixel values when appropriate for borders, icons, focus rings, minimum interaction targets, deliberate maximum widths, and other bounded primitives.
- Avoid arbitrary fixed structural dimensions that prevent content from adapting.
- Workspace chrome shows four peer buttons in order: Overview, Briefing, Cortex, and Reports. Each uses its peer accent when selected (Overview blue, Briefing gold, Cortex purple, Reports cyan); on Launch, those buttons stay neutral glass with peer-colored icons only while header tabs still use the accent when selected, and Settings stays neutral. Launch also uses a gold APEX wordmark and the former standby hero-sized identity mark. The APEX name returns to Launch. On Launch, Settings and the optional mode indicator remain visible without diagnostics chrome. In workspaces, the left header flank collapses CPU and RAM into one expandable system pill (disk appears only when expanded); connector health keeps the same hover, click, and pin inspector. Overview arranges telemetry in a six-column grid around a central identity card: Weather and Events, then News, identity, and Reminders, then Market and Email. Below the compact breakpoint, the identity card comes first and cards stack. Briefing shows profile and selected-model controls, the current or saved session with its linked conversation, and the telemetry rail in three columns. Before an artifact exists, the conversation area shows the session state; after completion, it renders the canonical artifact and supports follow-up. Below the compact breakpoint, Briefing stacks the conversation and exposes controls and telemetry through toggles.
- Overview and Briefing layout transitions use a short enter animation that is disabled under `prefers-reduced-motion`, and the Overview mark size change does not ease under reduced motion.

## Domain-Specific Color

### Unified Tools selector

The Tools control belongs to Apex Agent and is scoped to the selected runtime. Its collapsed state shows the active profile or `Custom`, selected-tool count, and cumulative estimated schema tokens. Its expanded surface provides profile selection, search, APEX-family and MCP-server toggles, individual tool overrides, disabled availability reasons, group subtotals, select-all/clear actions, and the estimated next-request breakdown. Selection changes only which tools are offered to the Agent; MCP settings remain a separate permission boundary.

The local context meter uses monospace tabular numerals and displays used/available tokens. Neutral text is the default; amber is reserved for at least 80% utilization. Token estimates are diagnostics, not progress animation, and must remain readable without color.

### Cortex Agent and model selector

Cortex shows the Apex Agent (or a local display name when set) with one model selector grouped by Cloud and Local. Model-supported controls appear below the selected model. The Agent card can show provider or local runtime, availability, and compact pricing, while the catalog stays in the model selector. Provider and runtime are information derived from the model, not separate routing controls.

Keep the Cortex heading visible when opening a conversation. The conversation rail keeps its heading, New Conversation button, and Active/Archived tabs in place while the list scrolls independently; the compact panel bounds that list rather than stretching the workspace. Programmatic message scrolling stays within the chat viewport.

The selected model determines which reasoning controls, hosted tools, local context options, and lifecycle controls make sense. Overview and Briefing may offer a smaller Agent trigger, but those detailed model controls stay in Cortex. The composer shows only the short Agent name and a send control.

Treat `Configured` as credentials present but not provider-verified. Display verification and runtime-failure states with text and iconography, not color alone. `Verify access` remains a secondary action for the selected cloud model and must not be nested inside its model-selection button.

Stability belongs to the model. **Preview** uses amber, **Experimental** uses cyan, and **Stable** has no stability badge. Do not infer model stability from the provider, runtime, or Agent name.

Weather conditions, market trends, provider badges, tool-result cards, demo/developer indicators, and data visualizations may use local palettes beyond the global state families.

- Keep local colors subordinate to global operational state.
- Do not reuse a global state treatment when the domain meaning conflicts with it.
- Use green and red for market movement only within an explicit financial context.
- Preserve sufficient contrast and provide text or iconographic meaning alongside domain color.
- Do not promote every local shade into a global design token.

## Motion and Accessibility

- Keep animation purposeful and tied to atmosphere, state transition, data activity, or direct interaction.
- Prefer slow breathing, staged flow, curtain reveal, and material response over arbitrary bouncing or continuous high-frequency motion.
- Respect `prefers-reduced-motion` across every animation family, including atmosphere, weather, logo breathing and surges, status LEDs, border rotation, signal flow, speech waveform, and attention transitions.
- Preserve visible keyboard focus, semantic structure, meaningful labels, adequate contrast, and minimum interaction targets.
- Ensure content remains available and understandable when motion and glow are disabled.

## Decision Priority

1. Clarity
2. Readability and accessibility
3. Information hierarchy
4. Consistency with existing components and tokens
5. Effective state communication
6. Material and atmospheric quality
7. Explicit product intent

Explicit feature requirements may override default treatments, but deviations should preserve accessibility and avoid creating conflicting state semantics.

When a visual change introduces a new runtime state, update the state semantics here only if that meaning is reusable across the HUD. Keep feature-local behavior in the owning component and its tests.
