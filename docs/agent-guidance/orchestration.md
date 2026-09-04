# Agent Orchestration

For substantial implementation work, proactively use subagents when they improve context isolation, bounded execution, parallel exploration, or independent verification. Do not wait for the user to explicitly request delegation.

Keep the parent agent responsible for scope, integration, and final readiness.

Keep one active implementation owner per branch or worktree. Use isolated worktrees when multiple agents need to edit concurrently.

After substantive implementation, independently review the resulting diff and required validation against the requested outcome and acceptance criteria. Prefer a separate verification subagent when useful. Resolve actionable findings, repeat the review, and re-run affected validation before reporting completion.

For small or localized changes, prefer direct execution instead of unnecessary delegation. Do not delegate product or architectural decisions that genuinely require the user.
