# Agent Orchestration

For non-trivial work, proactively use subagents when they improve context isolation, parallel exploration, or independent verification. Do not wait for the user to explicitly request delegation.

Keep the parent agent responsible for scope, integration, and final readiness.

Keep one active implementation owner per branch or worktree. Use isolated worktrees when multiple agents need to edit concurrently.

After substantive implementation, independently review the resulting diff and required validation. Prefer an independent verification subagent when useful, resolve actionable findings, and re-check before reporting completion.

Do not spawn subagents for trivial work or delegate product or architectural decisions that genuinely require the user.
