---
name: remora-audit-tests
description: Audit sampled test protection through production paths, assertions, and distinct failure signals. Read-only by default, retaining coverage whose redundancy is uncertain.
---

# Audit test protection

Establish the target root and explicitly read `.remora/standards/engineering.md`
and `.remora/standards/testing.md`, plus applicable root/scoped instructions.
These are target-root paths, not relative to this skill. Follow those shared work,
evidence, and reporting procedures with the existing host agent. Missing resources
are an incomplete installation, not permission to fetch or invent replacements.

## Bound the assessment

Resolve the requested behavior, subsystem, test changes, or suite; actual revision
and included local changes; and available execution evidence. Select a meaningful
sample and name unexamined areas. Inspect configuration and commands as data before
permitted execution. Do not import application code as passive discovery or install
test tooling. A limited inspection can still be useful when execution is unavailable.

## Establish protection and missing signals

For each sampled behavior, trace a plausible defect through the production path to
an observable assertion. Explain what would fail and why it matters, identifying
established, inferred, and missing links. Inspect setup/fakes for reimplementation,
assertions for relevant wrong outcomes, and boundary/error/synchronization/cleanup
behavior where consequential. Judge mocks and representation assertions by the
contract they isolate or protect, not by blanket testing preferences.

Use the testing standard's evidence levels. A current passing run is not proof
that the relevant defect is detected. If explicitly authorized, use an isolated
disposable copy for a named controlled fault; preserve the active tree and compare
specific test signals before/after. Without that authorization, report inspection
or existing evidence without introducing faults. Do not add a mutation engine.

Compare similar tests by the distinct transformations, wiring, persistence, error,
or lifecycle boundaries they protect. Retain coverage whose redundancy is uncertain.
Recommend deletion only with evidence of preserved or obsolete protection; never
infer redundancy from test count, coverage overlap, or similar assertions alone.

## Hand off findings without automatic edits

Audit is read-only by default: no test generation, assertion changes, deletion,
source edits, or saved report. Explicitly requested corrections require rechecking
scope/ownership and preserving the identified protection; fault authorization is
separate. Recommend the smallest useful retention, improvement, missing case,
owning-layer change, or investigation with a concrete behavior and failure signal.

Report sample, evidence levels, precise sources, actual command outcomes, actionable
weaknesses versus retained protection, and unexamined areas. No weakness found is
valid; neither inspection nor fault samples prove suite completeness or test
equivalence. Reading this skill establishes fallback execution only.
