---
name: remora-plan-change
description: Investigate and plan a scoped development change into phased, verifiable work packets using repository evidence, requirements, and acceptance criteria. Planning remains read-only unless saving a plan is requested.
---

# Plan a change

Establish the target root and explicitly read `.remora/standards/engineering.md`,
plus root and applicable scoped project instructions. Follow its shared work and
reporting procedure. These are target-root paths, not relative to this skill. Missing
resources mean an incomplete installation: report the gap without fetching or
inventing replacements. The host agent performs the work; no separate API or
runtime is required.

## Investigate before deciding

Identify the desired outcome, constraints, approved requirements, current behavior,
and acceptance criteria. Read relevant implementation, tests, configuration, and
canonical documentation. Treat details supplied by an external planning conversation
as hypotheses until checked locally. Separate proposals from established decisions.

Apply the Senior Technical Mentor interaction rules:
- **Resolve discoverable facts yourself:** Inspect code, configuration, and Git
state before asking questions. Never ask about discoverable facts.
- **Adaptive grilling:** For routine changes (Tier 1), proceed autonomously with
sensible defaults grounded in repository evidence, clearly summarizing assumptions.
For high-impact changes (Tier 2)—such as new persistence schemas, public contract
modifications, destructive operations, or fundamental ambiguity—pause and ask
targeted alignment questions before planning or editing.
- **Explain the rationale:** Explain the engineering "why" behind non-trivial
choices in plain language, present practical tradeoffs, and make a clear recommendation.

Inspect actual Git state and relevant local changes. Define the complete requested
scope, not merely the next editing step. Account for functionality already present.
Do not execute discovered tooling as passive inspection. Safe diagnostic checks
must fit the request and project permissions; report execution limits.

## Structure into phased work packets

Decompose the change into sequential, independently verifiable work packets (or PR
seams) that an agent can execute incrementally:

- **Foundational thinking:** Settle core types, data models, public interfaces, and
packet boundaries first.
- **Model the domain:** Define explicit state representations or lookup tables;
reject loose boolean soup for lifecycles or workflows. Keep simple local logic minimal.
- **Proportional simplicity:** Implement the smallest complete solution satisfying
requirements (YAGNI). Avoid speculative wrappers or unneeded dependencies.
- **Define checkpoints:** For each packet, state the affected interfaces, files,
acceptance criteria, and specific verification commands. Each phase must be verifiable
before the next begins.

Read `.remora/standards/testing.md` when assessing test protection, and
`.remora/standards/documentation.md` when documentation decisions need its ownership
rules. Reuse existing checks and canonical owners; new tests/documents are not
automatic deliverables. Paid API calls or live external operations must be planned
with explicit unverified declarations and manual verification steps.

Deliver a decision-complete brief. Plans remain in the chat conversation or native
plan tool by default; write plan files to disk only when explicitly requested,
compacting context, or crossing environments. If a material decision prevents
completion, identify its consequences and concrete alternatives. Finish with the
plan or explicit decision blocker, checks actually run, and uncertainty.
