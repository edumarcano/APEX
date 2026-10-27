---
name: remora-fix-regression
description: Diagnose a reported failure or repair a regression through reproduction-first evidence, an explicit fallback protocol, and proportional before/after verification. Diagnosis-only requests remain read-only.
---

# Diagnose or repair a regression

Establish the target root and explicitly read `.remora/standards/engineering.md` and
`.remora/standards/testing.md`, plus applicable root and scoped project instructions.
These are target-root paths. Follow shared procedures using host-native tools;
missing resources are installation gaps, not permission to fetch replacements or
use another inference runtime.

## Establish the failure and permitted action

Distinguish diagnosis-only from an authorized repair. Diagnosis makes no source,
test, configuration, or report edits. A repair request permits the smallest complete
fix and necessary test/documentation changes, without another routine approval.
Neutral continuations do not broaden that scope.

Identify observed failure, expected behavior and its authority, affected environment,
revision/local changes, and available reproduction. Inspect actual commands before
running them. Trace the production path, inputs, transformations, boundaries, and
observable failure; distinguish a supported cause from a hypothesis.

## Enforce reproduction-first

Never apply shotgun fixes (such as speculative null checks or empty exception catches)
without demonstrating the defect. Every repair requires **reproduction-first**:
construct an automated test or executable command that isolates the failure (turning
red) before touching production code. Historical revisions can be exercised in
disposable copies; do not reset the active tree.

### Explicit fallback protocol
If reproduction is genuinely blocked (such as unmocked UI interactions, specialized
hardware, or unavailable external credentials):
1. **Declare the reproduction gap:** Explicitly state what prevents reproduction.
2. **State root-cause hypothesis:** Explain the hypothesized cause backed by static
source and contract inspection.
3. **Present proposed plan:** Outline the intended fix and verification strategy for
user review and confirmation *before* modifying code.

## Repair when requested

Fix the supported cause while preserving unrelated behavior. Keep existing failure
signals and add a regression test to close the protection gap. Do not change the
approved specification or weaken expectations to agree with the defect. For
documentation impact, read `.remora/standards/documentation.md` and update its
existing owner only where necessary.

Run the reproduction and relevant checks after repair. Record failure before and
success afterward, naming the exact check and production behavior; otherwise explain
which evidence is unavailable. Explicitly review the actual diff and changed/untracked
inventory against scope using split-axis review (spec fulfillment vs. standards).
Correct supported in-scope issues and rerun affected checks, stopping at verified
repair or an explicit blocker.

Report cause/confidence, evidence, repair rationale, retained or added protection,
actual outcomes, and residual uncertainty. A diagnosis may finish with no change
and a concrete next diagnostic step.
