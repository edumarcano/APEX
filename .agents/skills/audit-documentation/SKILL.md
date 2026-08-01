---
name: audit-documentation
description: Audit APEX documentation against current repository evidence. Use for milestone-end documentation reconciliation, documentation-heavy or architectural changes, audits across a commit or tag range, repository-wide drift checks, and verification after documentation updates.
---

# Audit Documentation

## Establish scope and evidence

1. Select change-scoped, repository-scoped, or post-edit verification mode from the request. Default milestone audits to the previous release tag through `HEAD`.
2. Inspect repository instructions, the selected diff or commit range, and the current implementation. Include relevant tests, schemas, configuration, examples, lockfiles, and user-visible behavior.
3. Treat documentation and implementation as competing evidence when they disagree. Do not assume either one defines the intended contract without corroboration.
4. Remain read-only unless the user explicitly requests documentation edits.

## Trace documentation impact

Compare documented claims with repository evidence, including:

- commands, paths, ports, dependencies, environment variables, defaults, and secrets;
- supported features, workflows, modes, integrations, limitations, and failure behavior;
- API routes, payloads, persistence, configuration, and frontend behavior;
- architecture, ownership boundaries, screenshots, examples, links, and version references.

Use the selected change range to find affected documentation, then inspect the current files rather than relying only on changed lines. For repository-scoped audits, inventory documentation and map important claims to their owning implementation surfaces.

## Assess structure and ownership

In addition to factual drift, assess whether the documentation remains easy to navigate and internally coherent:

- confirm that each public document has a distinct purpose and that repeated material links to a canonical owner;
- check that information-dense references provide a short orientation before their detailed material;
- check screenshots, captions, examples, and diagrams against the current behavior without overstating what is live, automatic, or guaranteed;
- distinguish an editorial preference from a documentation problem. Report unclear audience, duplicate ownership, missing orientation, or misleading framing only when it makes the documentation harder to use or maintain;
- preserve roadmap and changelog history unless the requested scope explicitly includes that history;
- when a provider, route, setting, persistence boundary, or integration changes, trace the related configuration, API, architecture, privacy, and fallback documentation as applicable;
- when a second model provider is added, verify that provider-profile documentation checks are generalized rather than duplicated as provider-specific rules.

## Report or verify

Classify each evidence-backed finding as incorrect, outdated, incomplete, ambiguous, orphaned, or unverified. Provide the documentation location, supporting implementation location, impact, and a precise corrective direction. Separate required corrections from optional editorial improvements and avoid reporting style preferences as drift.

In post-edit verification mode, recheck the updated claims against repository evidence and report only remaining drift or unsupported statements. Run the repository documentation checker when one is available, and distinguish checker failures from editorial findings.

Do not reconcile release history or draft changelog entries unless explicitly requested; `prepare-release` owns that workflow.
