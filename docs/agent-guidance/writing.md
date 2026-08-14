# Writing Guidance

Write in plain, natural language for the intended audience. Prefer concrete verbs, specific claims, and direct explanations. Avoid unnecessary technical jargon, corporate language, marketing claims, filler, and exaggerated wording.

Avoid AI-shaped prose: unnecessary modifiers, abstract nouns, inflated phrasing, repetitive sentence patterns, and generic claims such as “robust,” “streamlined,” “structured,” “comprehensive,” or “enhanced” unless they convey specific information. Prefer the simplest wording that accurately describes the change.

Vary sentence structure naturally. Do not force parallel bullet phrasing, repeated “X now Y” constructions, or polished-sounding transitions when plain prose is clearer.

Use technical terminology when it improves precision. Explain unfamiliar terms when the audience may not know them, but do not replace accurate engineering language with vague simplifications. Preserve the established voice of an existing document instead of rewriting it into a generic style.

Distinguish verified behavior from inference, proposals, limitations, and unresolved questions. Do not present expected, planned, or unverified behavior as implemented fact.

## Documentation Audience and Voice

Write project documentation for the project owner's future reference first, and for external engineers who want to understand or run APEX second. Make the project understandable through concrete motivation, working behavior, and honest trade-offs, not evaluative or promotional framing.

Use first person only where it adds useful context about personal motivation, constraints, or a decision. The README, roadmap framing, and engineering decisions may use that voice. Technical references should remain neutral, direct, and specific.

Prefer ordinary engineering language over abstract or inflated phrasing. Avoid unnecessary modifiers, stacked abstractions, and formulaic wording when a simpler sentence would be equally precise.

## Documentation Structure and Ownership

- Give every document a distinct job. Keep a topic's full explanation in its canonical document and link to it elsewhere rather than maintaining parallel versions.
- Start information-dense references with a short orientation section that explains the reader's likely question, the current model, and how to use the rest of the document.
- Keep onboarding focused on reaching a first successful run. Keep configuration focused on settings and credentials. Keep architecture focused on the current system model and boundaries. Keep API documentation focused on behavior and usage, with generated schemas owning exhaustive contracts.
- Prefer durable concepts, workflows, and ownership boundaries over source-tree inventories or implementation walkthroughs that quickly become stale.
- Preserve historical records. The roadmap explains evolution and direction; the changelog records released changes. Do not rewrite their substantive history during an ordinary documentation pass.
- Keep product identity, canonical terminology, logo meaning, and Apex Agent naming rationale in `docs/identity-and-naming.md`. Other documents should define operational behavior where needed and link to that reference rather than repeating the naming history or symbolism.

## Documentation Scannability

- Lead each section with its main point or user outcome.
- Use descriptive headings that communicate the section's content.
- Keep paragraphs focused and reasonably short.
- Use lists, tables, examples, and code blocks when they make information easier to locate, compare, or apply.
- Keep formatting proportional to the material. Avoid fragmented prose, excessive headings, deeply nested lists, and walls of bullets.
- Place prerequisites, warnings, commands, and next actions where readers need them.
- Avoid duplicating the same explanation across multiple sections; link to the canonical source when appropriate.

Scannability means making information easy to locate and understand. It does not mean maximizing bullets or minimizing all prose.

## Documentation Maintenance

When a route, setting, provider, persistence boundary, integration, or privacy behavior changes, review the canonical documentation owner and any affected cross-links, examples, screenshots, and checks. When adding a second model provider, evolve provider-specific documentation validation into a shared provider-profile check rather than adding another one-off rule.

## Artifact Expectations

- **Documentation:** Make it durable, navigable, and explanatory.
- **Pull requests:** Write like an engineer explaining the change to another engineer, not like release marketing or generated documentation. State what changed and why in ordinary language. Avoid filler adjectives, unnecessary categorization, and formulaic AI phrasing.
- **Changelog entries:** Record what changed in plain language, with enough technical detail to remain a useful engineering history. Describe behavior before implementation, avoid unnecessary architectural labels and modifiers, and reserve file names, contracts, routes, and internal structures for sections where they add useful precision.
- **Release notes:** Summarize the milestone in terms of the most important changes and their practical effect. Keep implementation detail lighter than the changelog and avoid architecture-inventory language.
- **Interface copy:** Keep it brief, direct, and actionable. State what happened and what the user can do next.
