# APEX Design System

This reference defines the visual and interaction language for contributors working on the React HUD. It explains the design intent and reusable rules rather than individual component implementation; runtime ownership belongs in [Architecture](architecture.md), and frontend code conventions live in the [Frontend Guide](../frontend/README.md).

The meaning of the APEX mark and its relationship to the product and Agent taxonomy is documented in [Identity and Naming](identity-and-naming.md).

## Visual Direction

APEX uses a dark, cinematic operations look built around atmospheric lighting, metallic transitions, glass surfaces, and mission-control details. The background and identity effects should frame the interface without making telemetry or controls harder to read.

Prioritize clarity, accessibility, and information hierarchy over atmosphere. Visual effects should reinforce system state, depth, or interaction rather than compete with content.

## Color Families

APEX uses coordinated color families rather than a single flat accent palette. Representative colors define the visual language; lighter and darker shades may extend each family for gradients, contrast, and depth.

| Family | Representative colors | Primary meaning |
| --- | --- | --- |
| Blue | `#082F7A`, `#0F4DB8`, `#1F6FE5`, `#6EA8FF`, `#7EB3FF` | Platform identity, navigation, controls, selected content, and active attention |
| Emerald | `#047857`, `#10B981`, `#39FF88`, `#6EE7B7` | Processing, data collection, live status, and healthy availability |
| Purple | `#7E22CE`, `#A855F7`, `#C084FC`, `#D8B4FE` | Synthesis, Agent reasoning, queries, and tool execution |
| Gold | `#D97706`, `#FBBF24`, `#FFD166`, `#FFF3B0` | Delivery, prepared output, important highlights, and stale-data warning |
| Rust | `#C2410C`, `#F97316`, `#FB923C`, `#FDBA74` | Local-model loading and loaded local-runtime state |
| Cyan | `#22D3EE`, `#A5F3FC` | Active speech, voice waveform, and developer-mode indication |
| Red | `#991B1B`, `#DC2626`, `#F87171` | Errors, failed operations, and unavailable services |
| Bronze | `#451A03`, `#78350F`, `#92400E`, `#B45309` | Dormant identity core and inactive energy |
| Neutral | Near-black, zinc, slate, white alpha, and `#52525B` | Surfaces, secondary text, separators, pending state, and unknown module status |

Use established CSS properties, shared utilities, and semantic classes before introducing repeated raw values. Component-local colors remain appropriate for gradients, weather, charts, market movement, and other domain-specific visualization where a global token would obscure meaning.

## State Semantics

Color meaning depends on the state system in which it appears. Do not assume one color has a single meaning across every component.

### Pipeline and activity

| State | Visual family |
| --- | --- |
| Standby | Muted blue shell with dormant bronze core |
| Processing or collecting | Emerald |
| Synthesizing or Agent working | Purple |
| Delivering or ready output | Gold |
| Local model loading or loaded | Rust |
| Speaking | Cyan waveform within the current stage treatment |
| Failure | Red |

### Module health

| State | Visual family |
| --- | --- |
| Live or available | Emerald |
| Stale | Gold |
| Loading or unknown | Neutral gray |
| Error or unavailable | Red |

Pair state color with text, icons, shape, motion, or an accessible label. Never rely on color alone.

On Home and in the compact Cortex header, the shared logo keeps the outer blue shell and core independent: collection uses the blue outer wave with an emerald core, synthesis uses a fully lit blue shell while the core pulses purple, and local-model loading replaces the outer wave with a rust-metal wave over blue segments. Once the local model is resident, its nebula, center halo, and logo-wrapper glow remain rust while the shell returns to its normal blue behavior.

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

- Treat briefing generation as a global operation. Keep its selector, Refresh, and split Synthesize command together in the Home command rail beneath the logo while keeping the selected mode distinct from the engine that produced the last transcript.
- Organize briefing modes into Cloud and Local sections. Use shared Agent availability signals to disable unavailable model-backed modes; Structured Digest remains independent of model availability.
- Keep the briefing selector available in standby so Start with Briefing can use a session mode override. Hide Refresh and Synthesize until activation, disable current-snapshot generation when there is no telemetry snapshot, and disable briefing controls while collection, preflight, or generation is active.
- Treat Refresh All & Synthesize as one ordered action: a failed refresh must stop synthesis and leave its error visible.
- Show Speak / Replay as an icon action only on the Briefing tab when a transcript exists and voice mode permits manual delivery. Disable it while speech is active and present delivery failures as red text with an accessible status role.
- Keep provider, fallback, and delivery feedback with the transcript so the header selector continues to represent the next requested mode.
- When a local model is resident, show its compact icon-only unload control beside the Home synthesis action. Expose its model name through a hover-and-focus tooltip; keep lifecycle detail and the auto-unload countdown in Cortex's local-model inspector.

## Attention and Disclosure

Telemetry surfaces use four attention states:

```text
dormant -> pending -> active -> complete
```

- **Dormant:** Preserve settled glass and readable standby content.
- **Pending:** Reduce saturation and brightness while keeping the shell visible; mask body content when the pipeline has not unlocked it.
- **Active:** Apply blue catch-light and reveal the body as the surface becomes relevant.
- **Complete:** Return to settled glass while preserving completed content.

Use staggered curtain reveals to communicate pipeline order. Keep the shell spatially stable while content changes; do not move or resize the overall layout just to show attention.

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

## Domain-Specific Color

### Unified Tools selector

The Tools control is shared by cloud and local Agents. Its collapsed state shows the active profile or `Custom`, selected-tool count, and cumulative estimated schema tokens. Its expanded surface provides profile selection, search, APEX-family and MCP-server toggles, individual tool overrides, disabled availability reasons, group subtotals, select-all/clear actions, and the estimated next-request breakdown. Selection changes only which tools are offered to the Agent; MCP settings remain a separate permission boundary.

The local context meter uses monospace tabular numerals and displays used/available tokens. Neutral text is the default; amber is reserved for at least 80% utilization. Token estimates are diagnostics, not progress animation, and must remain readable without color.

### Cortex Agent catalog

The Cortex inspector is the detailed Agent-configuration surface. Show one selected `APEX <Agent>` card for Panthera or Felis; its popover presents catalog-provided names, descriptions, selected model metadata, available provider/runtime and model catalogs, ordered tags, availability, and compact pricing. The Home command rail may expose the same catalog through a compact Agent trigger, but it does not duplicate inspector-owned effort, grounding, local-tool, or lifecycle controls. The composer shows only the short Agent name and a send control. Agent marks, accent color, responsive card layout, and popover behavior are frontend presentation concerns; catalog content is backend-owned.

Treat `Configured` as credentials present but not provider-verified. Display verification and runtime-failure states with text and iconography, not color alone. `Verify access` remains a secondary action inside an expanded cloud card and must not be nested inside its Agent-selection button.

Stability is a reusable catalog treatment: **Preview** uses amber, **Experimental** uses cyan, and **Stable** has no stability badge. Apply these semantics wherever Agent catalog stability is shown; do not infer stability from the provider, runtime, or Agent mark.

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
