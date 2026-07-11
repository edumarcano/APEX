---
name: review-change
description: Perform a read-only review of APEX code, a branch diff, or a pull request. Use for correctness, security, async and concurrency safety, API or data-contract integrity, frontend behavior, operational risk, test adequacy, and identifying documentation impact caused by the reviewed change.
---

# Review Change

## Establish the review surface

1. Identify the requested base, branch, diff, files, or subsystem.
2. Inspect repository instructions and the applicable scoped guidance.
3. Treat the implementation and tests as evidence; do not infer behavior from titles or summaries alone.

## Review

Check the relevant dimensions:

- correctness and edge conditions;
- security, privacy, and credential boundaries;
- async execution, shared state, resource cleanup, and bounded retries;
- API, database, connector, and frontend data contracts;
- accessibility, state ownership, and responsive behavior;
- operational compatibility across normal, development, demo, and offline paths;
- test adequacy;
- documentation that must change because of the reviewed implementation.

Prioritize concrete defects over preferences. For every finding, provide severity, a tight file and line reference, impact, evidence, and a corrective direction. Separate confirmed findings from questions or optional improvements.

Keep documentation findings scoped to consequences of the reviewed change. Record affected files, changed behavior or configuration, removed behavior, and unresolved documentation decisions. Defer systematic change-range or repository-wide reconciliation to `audit-documentation`.

Remain read-only. Do not apply fixes, resolve review threads, or mutate external state unless the user explicitly changes the task from review to implementation.

