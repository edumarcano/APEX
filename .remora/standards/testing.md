# Test assurance

Explain what would have to go wrong for a test to fail and why that matters.
Trace a meaningful sample from requirement or behavior, through a plausible
defect and the production path, to an observable assertion and failure signal.
Mark each link as established, inferred, or missing; name the sample and omissions.

## Artifact proof and evidence levels

Keep evidence levels strictly separate:
- Static inspection supports a reasoned hypothesis.
- Running a test suite establishes execution in that environment, not user-facing behavior.
- Passing checks alone do not establish correctness; coverage measures lines touched, not assertion strength.
- Demonstrating completion requires **empirical artifact proof**: executing the real interface (CLI command, HTTP response payload, output file) and inspecting observable outputs and exit status.

### Paid and external API boundaries
Live third-party services, cloud deployments, and paid APIs (such as LLM calls) must never be triggered silently. When a change affects a paid or external boundary:
1. Explicitly mark that boundary as **unverified**.
2. State the reason (financial cost, rate limits, irreversible side effects).
3. Either request explicit user authorization to execute the live call, or provide copy-pasteable manual verification commands with expected outputs so the developer can verify independently.

## Test construction and boundaries

Inspect whether setup exercises production code or duplicates its implementation.
Mocks can isolate legitimate external boundaries; they can also replace the very
behavior under examination. Assertions must distinguish correct behavior from
relevant incorrect outcomes. Representation assertions are useful when that
representation is itself a stable contract. Check boundary/error cases,
synchronization, and cleanup where they affect the behavior.

Similar tests can protect different transformations, wiring, persistence, or
lifecycle boundaries. Overlapping coverage and similar wording do not establish
redundancy. Retain uncertain coverage. A deletion recommendation must identify
the lost protection and evidence that it is preserved or no longer required.
Never weaken expectations to agree with a defect.

## Defect reproduction and repairs

Repairs require **reproduction-first**: demonstrate the failing behavior via an
automated test or terminal command before editing production code. Prefer failure
before repair and verified success afterward; disclose when either is unavailable.

If reproduction is genuinely blocked (such as unmocked UI interactions, missing
hardware, or unavailable credentials), follow the **explicit fallback protocol**:
1. Declare the exact reproduction gap.
2. Explain the root-cause hypothesis supported by source inspection.
3. Propose the planned repair and test approach for user review *before* modifying code.

Auditing does not authorize test edits, deletion, generation, or fault injection.
Deliberate faults require explicit authorization and a disposable copy/worktree,
never the active user's tree. Do not install mutation tooling as an audit step.
Recommend retention, a stronger assertion, a missing case, a better owning layer,
or investigation only with a specific behavior and failure signal. No changes
needed is a valid conclusion.
