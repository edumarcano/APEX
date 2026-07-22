# Frontend Engineering Guidance

- Keep React components focused on presentation and interaction; place reusable state transitions, parsing, and effects in established hooks or utilities.
- Use `useApexData()` for boot configuration and reminders. Use the focused Branch 2 hooks for their respective concerns instead of adding to `useApexData()`: `useAppActivation()` for standby/activated lifecycle, `usePreflight()` for preflight warning/blocker dialog flow, `useTelemetrySnapshot()` for on-demand telemetry refresh, and `useBriefingPipeline()` for trigger/status polling and briefing/digest state.
- Preserve deliberately independent data flows such as `useMarketData()` when their lifecycle and polling cadence are separate from the briefing pipeline. Do not force unrelated state into `useApexData()` or into a hook that owns a different concern.
- Avoid duplicate fetch loops or competing sources of truth for the same backend resource.
- Model loading, empty, error, disabled, demo, and stale states explicitly. Use local progress indicators when a local action is independent; use shared status when the underlying operation is global.
- Preserve keyboard access, semantic structure, meaningful labels, visible focus, adequate contrast, and reduced-motion behavior.
- Build responsive layouts from content constraints and breakpoints. Fixed values are acceptable for bounded primitives such as borders, icons, focus rings, and minimum touch targets; avoid arbitrary fixed dimensions that prevent adaptation.
- Reuse established API constants, visual tokens, and shared components before introducing parallel abstractions.
- Follow `docs/design-system.md` for visual changes while allowing explicit product requirements to override defaults.
- Run `npm test`, `npm run lint`, and `npm run build` from `frontend/` after frontend changes.

