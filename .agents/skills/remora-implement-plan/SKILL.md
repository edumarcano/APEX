---
name: remora-implement-plan
description: Implement an approved plan or clear scoped development request across phased work packets, including checkpoint verification, empirical artifact proof, and split-axis review.
---

# Implement the agreed outcome

Establish the target root and explicitly read `.remora/standards/engineering.md`,
plus root and applicable scoped project instructions. Follow its shared work and
reporting procedure. These paths are relative to the target root. Report missing
resources as an incomplete installation; do not invent or fetch them. Use the existing
host agent and project tools, without an independent runtime or API.

## Reconcile the request with the repository

An approved plan or clear implementation request is sufficient; a separately saved
plan is not mandatory. Establish outcome, boundaries, acceptance criteria, and actual
Git/local state. Recheck supplied paths, APIs, requirements, and dependencies against
current implementation. Preserve project decisions and unrelated changes. Surface
material contradictions before affected edits; resolve ordinary details yourself
and continue safe independent work.

## Execute across phased checkpoints

Follow the agreed plan dependencies and execute the work in sequential, verifiable
work packets. Supports both single-agent sequential execution and delegated subagents
according to project permissions:

- **Packet discipline:** Implement one work packet at a time. Settle foundational
types and contracts before procedural logic. Model state lifecycles explicitly;
reject loose boolean soup. Keep local logic proportionally minimal.
- **Checkpoint verification:** Stop at each phase checkpoint to run local checks
and confirm the packet works before modifying the next area. Report blocked acceptance
criteria explicitly rather than taking giant leaps.
- **Artifact proof:** Read `.remora/standards/testing.md`. Passing test suites are
necessary but not sufficient: execute the real interface (CLI command, HTTP payload,
diff inspection) and show empirical evidence. Never weaken a test to bless a defect.
- **External and paid boundaries:** Live third-party or paid APIs (such as LLM calls)
must never be triggered silently. Declare them unverified and supply clear manual
verification commands.

Read `.remora/standards/documentation.md` when changing explanations or contracts.
Update affected canonical documentation where needed; preserve adequate sections,
approved requirements, and accurate history. Assess surrounding examples and links.
Do not require a separate repository-wide documentation/test audit for a local edit.

## Split-axis diff review and handoff

Explicitly review the actual diff, including relevant staged, unstaged, and untracked
files, against requirements and acceptance criteria. Use the installed
`.agents/skills/remora-review-change/SKILL.md` for its procedure: evaluate
**Axis 1 (Spec Fulfillment)** and **Axis 2 (Standards & Anti-Slop)** independently.
Treat demonstrated blocking defects (correctness, security, data-loss, or contract
failures on either axis) as gates that must be corrected before handoff.
Correct supported in-scope findings and recheck affected behavior.

Finish with delivered behavior, actual checkpoint outcomes, artifact evidence,
remaining risks, and any unmet acceptance criteria. Do not automatically commit,
publish, or perform external operations.
