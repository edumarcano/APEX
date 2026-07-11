---
name: prepare-release
description: Prepare and, after explicit approval, execute evidence-based APEX pull requests, squash merges, milestone changelogs, annotated tags, and GitHub releases. Use when finalizing a feature branch, drafting or creating a PR, preparing or performing a squash merge, reconciling and committing a milestone changelog, or drafting and publishing a tagged release.
---

# Prepare Release

## Establish evidence and authority

1. Select exactly one phase: feature PR and merge, milestone changelog, or tag and release. Infer it only when unambiguous; do not advance to another phase without an explicit request.
2. Confirm the comparison base or previous tag and inspect the complete diff, commits, dirty files, changed contracts, affected documentation, and validation evidence. Use commit messages as supporting context, not proof of behavior.
3. Separate completed behavior from reverted work, plans, local-only state, and unsupported claims. Never claim tests or compatibility that repository evidence does not establish.
4. Treat local drafting, requested documentation edits, and explicitly requested local commits as authorized. Before any push, PR creation, merge, tag push, or GitHub release publication, show the exact payload and actions and obtain explicit approval.
5. Approval covers only the displayed external-action batch. Revalidate immediately before execution and request renewed approval if the branch, PR head, checks, target commit, tag state, release content, or requested actions change.

## Phase 1: Prepare a feature PR or squash merge

1. Compare the feature branch with the selected base from their merge-base. Detect uncommitted or untracked work that would be omitted, secrets or generated files, documentation drift, and missing verification evidence.
2. Draft distinct artifacts:
   - A conventional PR title.
   - A reviewer-facing PR body with Summary, Changes, Contract or Architecture Impact, Verification, Risks or Limitations, and Documentation. Omit empty sections rather than inventing content.
   - A concise squash title and optional body describing the complete branch diff for permanent history.
3. Before pushing a branch or creating a PR, present the branch, base, commits, title, body, and exact actions for approval.
4. Treat later merging as a separate batch. Refresh the PR head, base, reviews, conflicts, and required checks; present the final squash message and merge action for approval.
5. Perform only a squash merge. Stop when checks fail, conflicts exist, required review is missing, or the reviewed head changes. Verify the resulting base-branch commit after merging.
6. Do not prepare a milestone changelog, tag, or release in this phase.

## Phase 2: Draft and commit the milestone changelog

1. Start only when the user indicates that the milestone features are complete. Use the previous release tag through local `main`, the aggregate diff, and merged PR evidence to establish release contents.
2. Preserve unrelated work and require a safe transition to `main`. Inspect remote `main` before preparation; never force-push or silently rewrite divergent history.
3. Reconcile `CHANGELOG.md` and other release-relevant documentation with implemented behavior. Exclude reverted, superseded, or unsupported intermediate work.
4. Use `## vX.Y.Z — Milestone Name` as the canonical changelog heading. It is authoritative for the later tag annotation and GitHub release title.
5. If asked for a draft, stop after presenting or editing the changelog. If explicitly asked to commit it, validate the staged release diff and commit it locally on `main` using the repository commit convention.
6. Do not push `main`, create a tag, or publish a release in this phase.

## Phase 3: Tag and publish the release

1. Require the finalized changelog commit to exist locally on `main`. Default the release target to that commit; accept another explicit target only after warning and verifying that it contains the finalized changelog.
2. Determine the previous tag. Verify the new tag does not already exist locally or remotely and that the selected target is synchronized with its intended remote state.
3. Derive both the annotated tag message and GitHub release title exactly from the canonical changelog heading without `## `: `vX.Y.Z — Milestone Name`.
4. Draft concise, user-facing release notes from the finalized changelog. End the body with exactly these two lines and no content after them:

```markdown
**Full Changelog**: [https://github.com/edumarcano/APEX/blob/main/CHANGELOG.md#<changelog-anchor>](https://github.com/edumarcano/APEX/blob/main/CHANGELOG.md#<changelog-anchor>)
**Code Diff**: [<previous-tag>...<new-tag>](https://github.com/edumarcano/APEX/compare/<previous-tag>...<new-tag>)
```

5. Derive `<changelog-anchor>` using GitHub heading-anchor behavior. For `## v1.14.0 — Central Command Atmosphere`, use `v1140--central-command-atmosphere`. Validate the anchor, repository URL, versions, tag range, and target commit.
6. Present one approval payload containing local and remote `main` state, previous and new versions, exact target commit, changelog heading, tag annotation, complete release title and body, and the ordered external actions.
7. After approval, revalidate and then push the changelog commit to `main`, create the annotated tag on the verified commit, push the tag, publish the GitHub release, and verify the remote tag, release target, title, and footer links.
8. Stop after any partial failure. Report the exact resulting state and obtain renewed approval before retrying the remaining external actions.

## Commit text

- Use one of `feat:`, `fix:`, `docs:`, `refactor:`, or `chore:` for commit-style titles.
- Keep the title imperative, lowercase after the prefix, at most 72 characters, and without a trailing period.
- Use past-tense technical verbs for optional body bullets and describe only the staged or reviewed diff.
