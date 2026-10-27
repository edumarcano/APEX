# Documentation integrity

Judge a document by its purpose, audience, and authority before correcting it.
Specifications own intended behavior; implementation establishes current behavior;
setup and reference documents explain usable current contracts; decision records,
evaluations, and changelogs preserve dated observations. A specification is not
proof of implementation, and an old command in an accurate historical record is
not current drift.

Trace consequential claims to their appropriate owners. A mismatch may mean stale
documentation, a code defect, an unimplemented requirement, or a changed decision.
Establish the supported interpretation; do not edit a requirement to bless a bug
or describe a configured command as successfully executed.

## Coherence and the refactoring threshold

Maintain explanations as well as individual facts. Prefer one canonical owner
with useful pointers over competing descriptions. Retain adequate material;
editorial preferences are advisory.

Avoid **patch accumulation**—the tendency to append qualifications and historical
caveats onto stale descriptions. Apply the **documentation refactoring threshold**:
- **Patch:** Use targeted edits for isolated factual changes (a changed path, default,
or command flag).
- **Rewrite:** When an affected section accumulates multiple conditional caveats
("previously X, but now Y unless Z"), or when underlying architecture changes,
stop patching. Perform a **clean-room rewrite of that specific section in the
present tense**: explain how the software operates right now as if designed that
way from the start.
- **Relocate history:** Move historical observations, rejected alternatives, and
transition notes to dated decision records (`docs/decisions.md`) or changelogs.
Living documentation must not double as a chronological patch log.

## Anti-slop editorial standard

Technical documentation must be concise, dense, and immediately scannable:

1. **No preambles or throat-clearing:** Start directly with the technical subject.
Never begin sections with meta-announcements such as "In this section we will explore"
or "Below is a comprehensive overview".
2. **Punctuation and syntax hygiene:** Eliminate decorative em-dashes used as
conversational crutches or filler. Use clean colons, parentheses, or separate
sentences.
3. **Banned AI filler tropes:** Avoid marketing buzzwords and conversational padding
("delve", "tapestry", "seamless", "crucial", "testament to", "rich ecosystem").
4. **Scannable information hierarchy:** When documenting three or more structured
items (parameters, flags, configuration options, states), use a Markdown table
rather than prose paragraphs. Keep explanatory paragraphs short (3 to 4 sentences
maximum) and written in active voice.

## Contract boundaries and history

Assess the stated contract rather than properties an alternative implementation
could provide. A possible reading of an unpromised property is advisory uncertainty,
not a factual defect without supporting requirements or a concrete reader error.
Do not expand the contract merely to manufacture a finding.

Preserve accurate history unless its correction or restructuring is explicitly
requested. Do not remove it merely because current behavior differs. Distinguish
current behavior, approved intentions, proposals, and observations after every edit.

An audit can correctly find nothing to change. Inspection and supported file-link
checks do not prove that commands work, anchors resolve, external services behave
as described, or all semantic claims are correct. State the actual coverage and
remaining uncertainty.
