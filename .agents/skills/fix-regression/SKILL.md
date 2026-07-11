---
name: fix-regression
description: Diagnose and repair an APEX defect with focused regression coverage. Use for crashes, incorrect runtime behavior, failing tests or builds, type errors, async failures, malformed payload handling, and bugs introduced by a recent change.
---

# Fix Regression

## Diagnose

1. Reproduce the failure or establish the strongest available evidence.
2. Trace the failing path across callers, contracts, state transitions, and runtime modes.
3. Identify the root cause separately from visible symptoms.
4. Record uncertainty when the environment cannot reproduce the issue.

## Repair

1. Make the smallest sufficient correction that preserves established architecture.
2. Avoid unrelated cleanup or speculative abstraction.
3. Add or update focused regression coverage for the failure and important edge conditions.
4. Preserve async cleanup, transaction integrity, secret boundaries, and offline behavior as applicable.

## Verify

1. Run the most focused relevant check first.
2. Run the broader validation required by `../../../AGENTS.md` for the affected subsystem.
3. Confirm the original failure is resolved and inspect the diff for unintended behavior changes.
4. Report the root cause, correction, verification, and remaining limitations.

