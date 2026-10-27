---
name: remora-remediate-project
description: Orchestrate repository onboarding and cleanup across grounding, documentation sanitization, test protection, and scoped debt remediation through checkpointed review gates.
---

# Remediate a repository

Establish the target root and explicitly read `.remora/standards/engineering.md`,
`.remora/standards/documentation.md`, and `.remora/standards/testing.md` from that root,
plus applicable root and scoped project instructions. Paths are target-root relative.
Missing resources mean an incomplete installation; report the gap without inventing
replacements. Use native host tools without a separate service, daemon, or runtime.

Remediation brings an existing codebase up to Remora's engineering standards through a
disciplined, four-phase sequence. This workflow **orchestrates Remora's specialist skills**;
it does not duplicate their procedures. Each phase coordinates the appropriate specialist
workflow, establishes explicit authorization before mutating files, and stops at a
mandatory **Review Gate** to verify outcomes before advancing.

## Read-only initial assessment and punch list

Perform a safe, read-only reconnaissance across the four remediation axes without
requiring approval ceremonies:

| Axis | Focus | Specialist Procedure |
| :--- | :--- | :--- |
| **1. Grounding** | Instructions, routing, verified commands | `.agents/skills/remora-audit-harness/SKILL.md` |
| **2. Documentation** | Ownership, refactoring threshold, anti-slop | `.agents/skills/remora-audit-documentation/SKILL.md` |
| **3. Test Protection** | Protection chains, failure signals, boundaries | `.agents/skills/remora-audit-tests/SKILL.md` |
| **4. Technical Debt** | Defect backlog, architectural debt, regressions | `.agents/skills/remora-review-change/SKILL.md` |

Deliver the assessment as a prioritized Remediation Punch List directly in chat. Do not
modify target files during assessment. Request authorization to begin Phase 1.

## Phase 1: Grounding and orientation

Coordinate root instruction alignment by following `.agents/skills/remora-audit-harness/SKILL.md`:

1. **Authorization:** Confirm user approval for proposed project instruction updates.
2. **Procedure:**
   - Execute and verify build, test, and lint commands locally; distinguish verified commands
     from configured manifest entries.
   - Remove discoverable trivia, tool tutorials, and obvious syntax explanations.
   - Establish concise project non-goals, reproduction rules, and operational boundaries.
   - Ensure root guidance references `.remora/standards/engineering.md` and installed skills.
3. **Review Gate 1:** Present the proposed `AGENTS.md` diff and local verification results.
   Verify that existing project-owned instructions outside the agreed scope remain intact.
   Obtain user approval before transitioning to Phase 2.

## Phase 2: Documentation sanitization

Coordinate documentation reconciliation by following `.agents/skills/remora-audit-documentation/SKILL.md`:

1. **Authorization:** Agree on the target documents or range authorized for reconciliation.
2. **Procedure:**
   - Assess document roles and enforce single canonical ownership.
   - Apply the documentation refactoring threshold from `.remora/standards/documentation.md`:
     use surgical patches for small factual updates; perform clean-room present-tense section
     rewrites when caveats accumulate; relocate dated observations to `docs/decisions.md`.
   - Enforce anti-slop editorial hygiene: strip preambles, decorative em-dashes, and buzzwords;
     convert structured lists of 3 or more items into Markdown tables.
3. **Review Gate 2:** Run local Markdown link and formatting checks. Present the documentation
   diff. Confirm coherence and obtain user approval before transitioning to Phase 3.

## Phase 3: Test protection audit

Coordinate test suite evaluation by following `.agents/skills/remora-audit-tests/SKILL.md`:

1. **Authorization:** Auditing test protection remains read-only by default. Deliberate fault
   injection requires separate explicit authorization and an isolated disposable environment.
2. **Procedure:**
   - Sample production behavior to distinguish empirical artifact proof from test proxies.
   - Identify brittle mocks, tautological assertions, and untested failure paths.
   - Isolate external and paid API boundaries, confirming deterministic tests exist alongside
     documented manual reproduction steps.
   - Verify that regression tests produce distinct failure signals when underlying logic fails.
3. **Review Gate 3:** Present the prioritized Test Protection Gap Report. Confirm identified
   gaps and obtain user authorization before implementing repairs in Phase 4.

## Phase 4: Scoped technical debt and defect remediation

Address approved gaps by delegating to Remora's implementation and review skills:

1. **Work packet formulation:** Deconstruct approved technical debt and test gaps into
   small, independent work packets using `.agents/skills/remora-plan-change/SKILL.md`.
2. **Execution:**
   - For planned improvements and missing tests, follow `.agents/skills/remora-implement-plan/SKILL.md`.
   - For defects and regressions, follow `.agents/skills/remora-fix-regression/SKILL.md`,
     adhering to reproduction-first and verified test-first repairs (writing the failing
     test before implementing the production fix).
   - Never weaken or delete existing assertions without empirical proof of obsolete contracts.
3. **Review Gate 4:** For each completed packet, conduct a split-axis review using
   `.agents/skills/remora-review-change/SKILL.md` (evaluating Specification Fulfillment and
   Standards Compliance separately). Review the diff and verify all local checks pass.

## Operational boundaries

- **Preserve unrelated project content:** Never modify unrelated source files, tests, docs,
  or custom project skills.
- **No unmonitored batch execution:** Never chain phases autonomously without stopping at
  review gates.
- **Conflict resolution:** If code conflicts with an approved specification, surface the
  contradiction to the user rather than silently modifying either to match the other.
- **Handoff:** Conclude with a clean audit report and verified Git working state ready for
  pull request creation.
