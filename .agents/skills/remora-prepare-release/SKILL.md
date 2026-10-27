---
name: remora-prepare-release
description: Prepare a verified software release, updating CHANGELOG.md, proposing a semantic tag, and generating concise GitHub release notes under the anti-slop standard.
---

# Prepare a release

Establish the target root and explicitly read `.remora/standards/engineering.md`
and `.remora/standards/documentation.md`, plus applicable root and scoped project
instructions. Follow shared reporting rules. Paths are target-root relative.
Missing resources mean an incomplete installation; report the gap without fetching
replacements. Use native host tools without a separate service or runtime.

## Pre-flight hygiene and sanitization

Inspect the release branch (defaulting to `main`) and perform a pre-flight sanity
check before drafting release notes:

1. **Working tree clean:** Verify that `git status` has no uncommitted changes,
untracked files, or unfinished merges.
2. **Path and secret sanitization:** Verify that no private environment files
(`.env`), secrets, or absolute workstation paths (such as `C:\Users\...` or personal
home directories) are committed in documentation, configuration, or code.
3. **License check:** Confirm that an approved `LICENSE` file exists in the root.
4. **Verification status:** Confirm that test and content verification suites pass
cleanly before releasing.

## Inspect changes and determine version

Find the latest Git tag using `git describe --tags --abbrev=0` (or identify an initial
first release if no tags exist). Inspect all commits since that tag using
`git log <last_tag>..HEAD --no-merges`.

Analyze the changes and recommend the appropriate Semantic Versioning (SemVer) bump:
- **Patch (0.0.x):** Backwards-compatible bug fixes and documentation updates.
- **Minor (0.x.0):** New backwards-compatible capabilities or skills.
- **Major (x.0.0):** Breaking changes to public interfaces or workflows.

## Assemble the three release deliverables

Apply the anti-slop editorial standard from `.remora/standards/documentation.md`:
no celebratory fluff ("We are thrilled to announce"), no marketing jargon ("seamless",
"game-changing"), and no decorative em-dashes. Keep writing direct and active.

### 1. CHANGELOG.md update
Update `CHANGELOG.md` directly in the working tree following *Keep a Changelog* conventions:
- Use standard categories: `### Added`, `### Changed`, `### Fixed`, `### Removed`.
- Exclude internal churn, merge commits, and minor typos.
- Write punchy bullet points describing user-facing capabilities in the present tense.
- The detailed changelog edits live directly in the working tree diff and are verified
via `git diff` or in a PR, rather than duplicated as full text in chat.

### 2. Semantic Git tag
Present the proposed Git tag (e.g., `v0.1.0` or `v0.2.0`) and SemVer rationale directly
in chat.

### 3. GitHub release notes
Present the concise GitHub release notes directly in chat:
- Simpler and punchier than the detailed changelog.
- 1 to 2 sentences summarizing the release milestone.
- 3 to 4 key highlights.
- The 1-line installation or quick-start command.

## Safety and execution boundary

Preparing a release operates within clear boundaries:
- Preparing the release applies the structured `CHANGELOG.md` edits directly to the
working tree for inspection via `git diff`.
- Present only the pre-flight verification status, proposed tag, and GitHub release
notes in the conversation for review.
- Creating the actual Git tag (`git tag <version>`) or publishing via `gh release create`
requires explicit user confirmation.
