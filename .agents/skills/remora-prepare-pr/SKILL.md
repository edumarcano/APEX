---
name: remora-prepare-pr
description: Prepare a concise, reviewer-friendly pull request brief adhering to the anti-slop standard, emphasizing artifact proof and reviewer verification over redundant CI logs.
---

# Prepare a pull request

Establish the target root and explicitly read `.remora/standards/engineering.md`
and `.remora/standards/documentation.md`, plus applicable root and scoped project
instructions. Follow shared reporting rules. Paths are target-root relative.
Missing resources mean an incomplete installation; report the gap without fetching
replacements. Use native host tools without a separate service or API.

## Resolve the branch change surface

Identify the current branch, target base branch (defaulting to `main` or repository
default), and actual revision range. Inspect the full diff, including staged,
unstaged, and untracked changes, using `git diff <base>...HEAD` or equivalent range
commands. Do not guess commit history.

Reconcile the actual diff with the original requirements, acceptance criteria, and
plan. Verify that all in-scope work packets are complete and that split-axis review
has been satisfied. If uncommitted changes exist, ask whether they belong in the PR
or should be stashed.

## Assemble the fast-to-review brief

Apply the anti-slop editorial standard from `.remora/standards/documentation.md`:
- Eliminate throat-clearing preambles, marketing buzzwords, and decorative em-dashes.
- Never recite commits or file edits line by line. Focus on architectural intent.
- Keep the entire PR description under 20 lines total, scannable in 60 seconds.

Structure the PR description using four concise sections:

### 1. Why
State the underlying problem or motivation in 1 to 2 direct sentences.

### 2. What changed
Summarize key architectural and functional changes in 3 to 5 tight bullet points
(maximum 2 lines per bullet).

### 3. Verification
Do **not** dump raw logs of standard test runners (`pytest`, `npm test`) or linters
that CI already runs automatically. Focus proof on what CI cannot show:
- **Artifact proof:** Show the actual interface output (CLI stdout snippet, response
payload, or visual change).
- **Local test command:** Provide the exact 1-line command for the reviewer to run
and inspect locally.
- **Unverified boundaries:** Disclose any boundary CI cannot test (e.g., live paid
APIs like LLM calls, private hardware), including manual test instructions.

### 4. Risks and non-goals
State in 1 to 2 bullet points:
- What was intentionally excluded from scope to prevent scope creep.
- Any breaking contract changes, schema migrations, or operational risks.

## Safety and boundaries

Preparing a pull request description is **read-only**:
- Do not automatically create commits, push branches, open GitHub pull requests via
API, or merge code unless explicitly authorized covering those actions.
- Present the prepared PR description directly in the chat conversation (or save
to an approved file location only when requested).
- Review remaining risks and ask the user for confirmation before any subsequent Git
operations.
