# Pull Request and Release Guidance

Follow this procedure for branch finalization, pull requests, milestone changelogs, annotated tags, and GitHub releases. Approval covers only the explicitly displayed external-action batch; revalidate immediately before execution.

## Phase 1: Feature PR and Squash Merge

1. Compare the feature branch with its target base (defaulting to `main`) from their merge base. Detect uncommitted work, secrets, generated files, documentation drift, and verification evidence.
2. Draft reviewer-facing PR artifacts following `.remora/standards/documentation.md` and `remora-prepare-pr`:
   - A conventional PR title.
   - A concise PR description with `Why`, `What changed`, `Verification` (highlighting artifact proof and local test commands), and `Risks and non-goals`.
   - A concise squash title and body describing the complete branch diff for permanent history.
3. Creating or updating a PR authorizes pushing the branch and opening or updating the PR via `gh pr create` or the GitHub API.
4. Squash merge is the repository default. Approval covers the final squash commit title, body, and merge action. Refresh PR head, base, reviews, conflicts, and CI status before merging. Stop if checks fail, conflicts exist, or the reviewed head changes.

## Phase 2: Milestone Changelog

1. Start when milestone features are complete. Compare the previous release tag through local `main` and merged PR evidence.
2. Verify remote `main` before preparation; never force-push or silently rewrite history.
3. Reconcile `CHANGELOG.md` following *Keep a Changelog* conventions (`### Added`, `### Changed`, `### Fixed`, `### Removed`). Exclude reverted or superseded intermediate work.
4. Use `## vX.Y.Z — Milestone Name` as the canonical changelog heading. This heading is authoritative for the later tag annotation and GitHub release title.
5. If explicitly requested to commit, validate the staged release diff and commit locally on `main` using `docs(release): reconcile vX.Y.Z changelog` or equivalent conventional commit title. Do not push `main`, tag, or publish in this phase.

## Phase 3: Tag and Publish Release

1. Require the finalized changelog commit to exist locally on `main`.
2. Confirm the previous release tag with `git describe --tags --abbrev=0`. Verify the new tag does not exist locally or remotely and that the target commit is synchronized with its remote state.
3. Derive both the annotated tag message and GitHub release title exactly from the canonical changelog heading without `## `: `vX.Y.Z — Milestone Name`.
4. Draft concise release notes. Begin the body with the release date. End the body with exactly these two lines and no trailing content:

```markdown
**Full Changelog**: [https://github.com/edumarcano/APEX/blob/main/CHANGELOG.md#<changelog-anchor>](https://github.com/edumarcano/APEX/blob/main/CHANGELOG.md#<changelog-anchor>)
**Code Diff**: [<previous-tag>...<new-tag>](https://github.com/edumarcano/APEX/compare/<previous-tag>...<new-tag>)
```

5. Derive `<changelog-anchor>` using GitHub heading-anchor rules (e.g. `## v1.14.0 — Central Command Atmosphere` -> `v1140--central-command-atmosphere`). Validate the anchor, repository URL, versions, tag range, and target commit.
6. Present the complete approval payload: local and remote `main` state, previous and new versions, target commit, changelog heading, tag annotation, full release title and body, and ordered external actions.
7. After explicit approval, push the changelog commit to `main`, create the annotated tag on the verified commit (`git tag -a vX.Y.Z -m "vX.Y.Z — Milestone Name"`), push the tag (`git push origin vX.Y.Z`), publish the release (`gh release create vX.Y.Z --title "vX.Y.Z — Milestone Name" --notes-file <file>`), and verify remote tag and links. Stop on any partial failure.

## Commit Text Conventions

- Use one of `feat:`, `fix:`, `docs:`, `refactor:`, or `chore:` for commit titles.
- Keep the title imperative, lowercase after the prefix, at most 72 characters, and without a trailing period.
- Use past-tense technical verbs for optional body bullets and describe only the staged diff.
