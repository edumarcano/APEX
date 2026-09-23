---
name: plan-change
description: Research and plan an APEX feature, milestone, integration, architectural change, or product idea into an implementation-ready handoff. Use for roadmap reconciliation, new or unplanned changes, unfamiliar APIs or contracts, architecture comparisons, and requests to investigate the repository before deciding how work should be implemented.
---

# Plan Change

## Establish the change

1. Define the requested outcome, constraints, and non-goals in observable terms.
2. Inspect the current repository, tests, configuration, and relevant documentation before making implementation assumptions.
3. Reconcile the request with any relevant product source, such as the roadmap, an issue, existing documentation, or user-provided requirements.
4. Ask only for decisions that materially affect behavior, architecture, or scope.

## Research and decide

1. Verify unstable external facts with current primary sources when needed.
2. Trace affected systems, contracts, data shapes, runtime modes, UI surfaces, configuration, and documentation.
3. Compare materially different approaches using APEX-specific benefits, costs, risks, and failure modes.
4. Prefer the smallest coherent design that satisfies current requirements. Avoid speculative infrastructure, abstraction, generalization, or future-proofing that is not justified by the present change.
5. Distinguish repository facts, externally verified facts, and inference.

## Produce the plan

1. Make the plan decision-complete enough for `implement-plan` to execute without rediscovering the architecture.
2. For substantial work, divide it into ordered implementation units or feature branches when that improves isolation, sequencing, or reviewability. State dependencies between them.
3. Use `../../../docs/agent-handoffs/template.md` for the handoff. Include requirements, decisions, affected systems, acceptance criteria, verification, risks, and only genuinely unresolved questions.
4. Do not invent exact paths, tests, contracts, or behavior that repository evidence does not support.

Remain read-only unless the user explicitly requests implementation or asks for the plan to be saved as a repository artifact.
