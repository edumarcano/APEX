# Frontend Engineering Guidance

- Keep React components focused on presentation and interaction; place reusable state transitions, parsing, and effects in established hooks or utilities.
- Use `useApexData()` for briefing-pipeline state, trigger/status polling, reminders, boot configuration, and telemetry it already owns.
- Preserve deliberately independent data flows such as `useMarketData()` when their lifecycle and polling cadence are separate from the briefing pipeline. Do not force unrelated state into `useApexData()`.
- Avoid duplicate fetch loops or competing sources of truth for the same backend resource.
- Model loading, empty, error, disabled, demo, and stale states explicitly. Use local progress indicators when a local action is independent; use shared status when the underlying operation is global.
- Preserve keyboard access, semantic structure, meaningful labels, visible focus, adequate contrast, and reduced-motion behavior.
- Build responsive layouts from content constraints and breakpoints. Fixed values are acceptable for bounded primitives such as borders, icons, focus rings, and minimum touch targets; avoid arbitrary fixed dimensions that prevent adaptation.
- Reuse established API constants, visual tokens, and shared components before introducing parallel abstractions.
- Follow `docs/design-system.md` for visual changes while allowing explicit product requirements to override defaults.
- Run `npm test`, `npm run lint`, and `npm run build` from `frontend/` after frontend changes.

