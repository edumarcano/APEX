---
name: remora-review-change
description: Review a named implementation, diff, or revision range using independent split-axis analysis with consequence-based blocking. Read-only review never applies repairs.
---

# Review the declared change

Establish the target root and explicitly read `.remora/standards/engineering.md`,
plus applicable root and scoped project instructions. Follow its shared procedure and
reporting rules. Paths are target-root relative. Missing resources are an incomplete
installation; do not fetch replacements or silently install/update Remora. Use the
host agent without a separate API or runtime.

## Resolve the review surface

Identify the named implementation or actual base/head range, relevant requirements,
and whether staged, unstaged, and untracked changes are included. Do not guess a
branch or release. If surface identity/base is materially ambiguous, ask before
claiming a completed review. An explicitly named implementation can be reviewed
without history; report that limitation. Account for renames, removed paths, and
applicable scoped instructions beyond edited lines.

## Execute split-axis review

Read the actual code and affected callers/contracts, not only summaries or changed
lines. Formally evaluate the diff across two strictly independent axes:

### Axis 1: Specification and requirement fulfillment
- **Outcome verification:** Did the change deliver the agreed outcome and satisfy
  all stated acceptance criteria?
- **Contract & edge-case compliance:** Are public interfaces, boundary conditions,
  and error handling respected? Are defined non-goals preserved?
- **Scope discipline:** Does the diff remain within authorized boundaries, avoiding
  unrelated edits or unrequested features?

### Axis 2: Engineering standards, architecture and anti-slop
- **Foundational thinking & security:** Are data structures, types, error boundaries,
  and module seams sound? Is the change free of security vulnerabilities (injections,
  unsafe path traversal, auth/secret exposure)?
- **Model the domain:** Is the logic free of boolean soup? Are state lifecycles
  modeled cleanly with explicit states or lookup tables?
- **Proportional simplicity (anti-slop):** Is the code free of unnecessary wrappers,
  speculative abstractions, dead code, or redundant comments that merely restate code?
- **Test assurance:** Read `.remora/standards/testing.md`. Does testing include
  meaningful assertions and real artifact proof rather than shallow mocks?
- **Paid & external boundaries:** Are external/paid calls properly protected or
  declared unverified?

## Consequence-based blocking criteria

Blocking severity depends on **demonstrated consequences**, not which axis identifies
the issue:

| Severity | Definition & Examples | Review Action |
| :--- | :--- | :--- |
| **Blocking** | Serious correctness defects (wrong calculation, unmet acceptance criteria, silent data corruption), security vulnerabilities, resource leaks, deadlocks, or breaking regressions on either axis. | **Blocks approval.** Requires resolution before merging. Must cite concrete evidence and demonstrated failure modes. |
| **Non-blocking (Advisory)** | Minor maintainability concerns, stylistic preferences, naming nits that do not obscure meaning, or speculative optimization ideas. | **Does not block approval.** Reported as optional observations for future consideration. |

Reviewers must **never manufacture blockers** or turn code reviews into open-ended
improvement exercises. Every blocking finding requires verifiable evidence: an exact
reproduction trace, a concrete failing input, or a demonstrated violated requirement.

## Report findings and boundaries

Review is read-only: do not repair source, tests, guidance, or documentation, save
reports unless requested, or automatically invoke implementation. A supplied plan
does not expand review authorization.

Structure the review report with findings clearly categorized by Axis 1 and Axis 2,
labeling each finding as **Blocking** or **Non-blocking**:
- State the exact file location, trigger, concrete evidence, and consequence.
- Conclude with a clear verdict:
  - **Blocked:** Contains one or more demonstrated blocking defects that must be resolved.
  - **Approved with observations:** No blocking defects; minor advisory suggestions noted.
  - **Approved:** Fully satisfies both axes with zero blocking or advisory findings.

No findings is valid; it does not mean exhaustive proof.
