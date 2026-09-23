---
name: implement-plan
description: Validate and execute an approved APEX implementation plan or one unit of a larger plan. Use when the user supplies or approves a plan, asks to implement a specific branch or stage, or hands off planned multi-file work that should be implemented, independently reviewed, corrected, and prepared for handoff.
---

# Implement Plan

## Establish the work

1. Inspect the current worktree, relevant code, tests, configuration, and documentation.
2. Identify the requested plan unit and verify any stated prerequisites or earlier work.
3. Reconcile material plan assumptions with the current repository. Correct stale implementation details without changing the intended outcome.
4. Stop when a missing product or architectural decision would materially change scope or behavior.

## Implement

1. Keep the parent agent responsible for scope, integration, and final readiness.
2. For substantive work, delegate implementation to one suitable configured worker in a fresh context. Honor an explicit worker choice from the user. For small or localized work, direct implementation is acceptable.
3. Give the worker the reconciled plan, acceptance criteria, relevant repository guidance, and required validation.
4. Keep one implementation owner for the active worktree. The worker should surface material conflicts with the plan rather than independently redesign the solution.
5. Implement complete behavior, including affected contracts, error paths, tests, and documentation, following the applicable guidance in `../../../AGENTS.md` and `../../../docs/agent-guidance/`.

## Review and correct

1. After implementation, the parent independently review the completed diff using the `review-change` skill against the reconciled plan and acceptance criteria. Do not treat the worker's self-review as sufficient.
2. Keep each review pass read-only. When actionable findings exist, return to this workflow and delegate the fixes to the implementation worker.
3. Re-run affected validation, then perform another `review-change` pass.
4. Repeat the fix → review cycle until no known actionable finding remains or a missing product or architectural decision blocks completion.

## Hand off

1. Run the broader validation required by `../../../AGENTS.md`.
2. Report validation that could not be completed and any residual risks.
3. If the user requested a pull request, use `prepare-release` Phase 1 to prepare and open it, then stop. Do not merge unless separately requested.
4. Otherwise report the completed implementation and stop.
