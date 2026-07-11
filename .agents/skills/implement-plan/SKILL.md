---
name: implement-plan
description: Validate and implement an approved APEX plan completely. Use when the user supplies or approves an implementation plan, asks for autonomous multi-file work, or hands off research that must be reconciled with the current repository before coding.
---

# Implement Plan

## Reconcile the plan

1. Inspect the current worktree, relevant code, tests, configuration, and documentation.
2. Check every material plan assumption against repository evidence.
3. Correct stale paths, symbols, contracts, or validation commands while preserving the requested outcome.
4. Stop only when a missing product decision would materially change behavior or expand scope.

## Implement

1. Treat the explicit implementation request as authorization for in-scope edits.
2. Preserve unrelated changes and maintain one implementation owner for the active worktree.
3. Implement complete vertical behavior, including callers, contracts, error paths, tests, and affected documentation.
4. Avoid placeholders, unrelated refactors, and silent changes to established runtime modes.
5. Follow the applicable guidance in `../../../AGENTS.md` and `../../../docs/agent-guidance/`.

## Verify and hand off

1. Run focused checks during implementation, then the broader commands required by `AGENTS.md`.
2. Inspect the final diff for accidental scope, secret exposure, and documentation drift.
3. Report the outcome, files or systems changed, validation actually run, and residual risks.

