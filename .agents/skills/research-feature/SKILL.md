---
name: research-feature
description: Research an APEX feature, integration, or rough product idea and turn it into an evidence-backed implementation handoff. Use for ambiguous proposals, external APIs or SDKs, architecture comparisons, unfamiliar data contracts, or requests to investigate and plan before implementation.
---

# Research Feature

## Establish intent

1. State the objective in observable terms.
2. Identify non-goals and constraints from the request.
3. Resolve repository facts through inspection before asking questions.
4. Ask only for product decisions that materially change the result.

## Build evidence

1. Inspect the current implementation, tests, configuration, and relevant documentation.
2. Verify unstable external facts with current primary sources.
3. Map affected APIs, data shapes, trust boundaries, runtime modes, UI surfaces, and documentation.
4. Compare viable approaches using project-specific benefits, costs, and failure modes.
5. Mark each conclusion as confirmed repository fact, externally sourced fact, or inference.

## Produce the handoff

Use the structure in `../../../docs/agent-handoffs/template.md`. Make the handoff decision-complete when the available evidence permits it. Include exact acceptance criteria and verification expectations without inventing file paths, tests, or behavior.

Remain read-only unless the user explicitly requests implementation or asks for the handoff to be saved as a repository artifact.

