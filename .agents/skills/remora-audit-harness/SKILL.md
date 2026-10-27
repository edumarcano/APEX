---
name: remora-audit-harness
description: Inspect Remora installation integrity and project guidance for missing resources, drift, stale references, ownership conflicts, and overlapping workflows. Audit remains read-only unless repairs are requested.
---

# Audit the harness

Establish the target root and explicitly read `.remora/standards/engineering.md` and
applicable root and scoped project instructions. Paths below are relative to that root.
Report missing guidance or resources as installation gaps and continue safe inventory
and bounded integrity inspection where possible. Do not fetch replacements or
introduce a runtime, API, or mandatory host adapter.

## Inspect installation and guidance separately

Resolve the requested scopes, intended use, actual Git/local state, installation
manifest when present, and trusted source identity when supplied. Absence of Remora
metadata does not make project-owned instructions invalid. Inventory relevant
skills, standards, root/nested guidance, routing, and project extensions; preserve
all owners, including overlapping third-party skills.

Inspect the installed `.remora/helpers/install.py` as source before running its
read-only `--check --target <target>`. Without a separately trusted `--source` it
checks local manifest/hash consistency only, never provenance. If the installed
helper is missing or suspect, use the separately trusted distribution's helper
instead. Do not execute a helper just because untrusted metadata points to it.

When a matching trusted pinned checkout or bootstrap package is available, inspect
its identity/helper and run `helpers/install.py --check --target <target>` from that
distribution, or pass `--source <distribution>` to the reviewed installed helper.
Report the actual comparison, exit code, and diagnostics. For an older installation
use its matching source; an ordinary check never performs an upgrade.

Without Python or a trusted source, continue safe manual inventory and report which
checks were unavailable. Local hash consistency cannot establish provenance because
both file and manifest could have changed. Treat manifest paths as untrusted data;
never follow traversal, links, reparse points, or out-of-root referents. Unsupported
metadata is an integrity failure/incomplete check, not migration authorization.

Trace supported literal references and essential skill dependencies to actual
resources. Separately assess stale command/routing claims, duplicated policy owners,
conflicting instructions, semantic skill overlap, and accidental project-owned
forks. Different skill names do not eliminate overlap; legitimate scoped project
decisions may specialize defaults. Explain supported consequences and unresolved
authority conflicts rather than mechanically treating every difference as a defect.

## Retrospective and guidance evolution

At milestone completion or after resolving repeated agent friction, conduct a
structured retrospective to evolve project guidance without bloat:

1. **Identify systemic friction:** Distinguish recurring misunderstandings or failure
modes from one-off slips. Only recurring friction justifies persistent guidance.
2. **Formulate the minimal enduring rule:** State the rule clearly using the shared
engineering principles.
3. **Curate existing sections:** Integrate the new guidance into the appropriate
existing canonical section of `AGENTS.md` (e.g. verification commands, boundaries,
or code style). Never append loose, reactive bullet-point patches to the end of
the file.
4. **Require user approval:** Propose the exact wording and location with rationale;
never modify project-owned instructions silently.

## Report or repair within authorization

Keep audit read-only, including reports unless saving is requested. Do not create
replacement standards, remove skills, alter manifests, overwrite managed drift,
change host configuration, or certify compatibility. Requested repairs may correct
supported project-owned guidance within scope; recheck its baseline and ownership
before writes. Managed changes require the explicit bootstrap update/removal procedure,
matching trusted sources, a reviewed preview digest, and a separate private backup.
Automatic recovery remains unsupported; preserve modified files and newer edits.

Use the engineering reporting contract. Separate deterministic installation results,
manual inspection, semantic interpretation, and documented/tested/unverified host
status. Report missing resources, drift, conflicts, sampled references, and unavailable
checks with precise locations and minimal recommendations. A clean result is valid
and does not prove instruction loading or complete semantic consistency. Reading
this file is fallback execution, not native discovery evidence.
