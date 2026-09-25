# Privacy

APEX is local-first: durable settings, conversation history, retrieval data, context sources and history, review proposals, action evidence, external activity reports, the Cortex run ledger, and briefing history remain on the local machine unless a selected operation requires an enabled connector or model provider. APEX does not encrypt its local SQLite databases.

## Interactive models

The selected model determines the inference boundary. Cloud model requests may send the bounded prompt, active-branch history, explicitly selected APEX or MCP schemas, and any context allowed by the relevant runtime policy. Local model requests use the configured Ollama or llama.cpp endpoint. Personal-context retrieval is disabled by default for both runtimes.

Provider-hosted grounding is separate from APEX-managed tool calls. It is enabled only when the selected cloud model supports it and the corresponding Runtime Settings switch is enabled.

## Personal context

Original evidence, normalized claims, provenance, and append-only knowledge history are stored separately in the local SQLite database. APEX does not encrypt that database. Corrections and retractions preserve earlier evidence and history rather than erasing them, and pending review proposals remain outside normal retrieval.

Canonical claims have a persisted sensitivity classification. New sensitive captures retain that classification when their review is accepted; corrections and conflict resolution carry it forward if any predecessor is sensitive. Existing claims linked to an accepted sensitive review are backfilled as sensitive, and other existing claims start unclassified. Changing a record's classification requires a revision-checked operator mutation that adds a history event. Context vault selection is disabled with no selected records by default, and sensitive records remain excluded unless a scope explicitly opts in. When enabled, one lifespan-owned worker writes selected production claims under `APEX_CONTEXT_VAULT_PATH` and reconciles them after committed changes. Generated notes include canonical claim text and limited source metadata, but omit original evidence, source locators, and source URLs. Ownership hashes, pending paths, and operational state stay in local SQLite outside the vault. The publisher leaves handwritten files and `.obsidian/` alone, refuses to overwrite an unowned file at a generated path, and removes only files it tracks when asked. Demo and development sandbox modes cannot write to the production vault. A local export status does not confirm that another application or sync service copied or indexed the files.

When personal context is enabled for a model runtime, APEX can send selected current claims with concise provenance and effective-time labels as untrusted reference context. Full source evidence and knowledge history stay out of the prompt, and a pending proposal's replacement text is not sent as current knowledge. A cloud model provider receives the selected context included in that request; local models keep it on the configured local inference boundary.

The [Context vault guide](context-vault.md) explains how to select, share, and remove generated copies.

## External activity reports

External activity reports, including their structured findings and imported Markdown, are retained in local SQLite and may contain private content. They do not enter retrieval or model prompts automatically. When the operator explicitly generates a Daily briefing, APEX can select up to three relevant, non-dismissed reports from the newest 50 candidates and send bounded excerpts to the selected model as explicitly untrusted evidence. The excerpts identify the content as an external report; this does not promote it to accepted context. The optional mailbox leaves the original files in the operator-selected folder; if that folder is synced, its sync tool controls any external copies.

When the operator accepts a context review linked to a report, the resulting normalized claim enters personal-context retrieval with its external source provenance. If retrieval is enabled for a model runtime, selected claims can then enter model prompts, including cloud requests. Normal retrieval does not include the full report or original source evidence.

## Briefings

The Home Daily action uses the selected Apex Agent model and sends its bounded prompt to that model's configured provider, or to the configured local inference endpoint. A model that cannot fit a minimum useful Daily prompt is rejected before a session is created; Daily does not fall back to another model. A completed session and its canonical artifact and evidence snapshot are stored locally in the active production or sandbox partition. The conversation stores a rendered opening message linked to the artifact. Later turns in that conversation may send up to 500 estimated tokens of cited historical evidence to the model selected for that turn, including a cloud model. This is limited by the ordinary context budget and keeps source trust and snapshot-time labels. Saved accepted context, pending reviews, external reports, and action evidence are included only when personal-context retrieval is enabled for the selected runtime; the original artifact remains unchanged. Full saved evidence remains available through local inspection.

The legacy Focused, Flash, and Structured routes retain their fixed behavior: Focused uses OpenRouter DeepSeek V4 Flash, Flash uses the configured local Gemma route, and Structured calls no model.

Automatic voice delivery may speak short activation and briefing cues containing the saved user designation, briefing mode, and collection health. With Google Cloud TTS selected, that cue text may be sent to Google; local speech engines keep it on the machine. Manual and off voice modes do not speak contextual cues.

Calendar reads are limited to the calendars selected in Runtime Settings. Briefing and Agent calendar context can include selected event metadata, such as titles, times, and locations. When cloud briefing or model requests use that context, it is sent to the configured provider. Calendar labels are included by default; turn off **Show calendar names with events** in Runtime Settings to suppress labels from event attribution and model-visible calendar context. This does not remove the selected event metadata itself.

## Tools and actions

APEX tools pass only the arguments required for the requested operation. Tool output is treated as untrusted model data. Write operations are approval-gated, create local action evidence, and are not replayed automatically after ambiguous outcomes.

## Distributed tracing

OpenTelemetry tracing is optional and disabled by default. When an operator configures an OTLP export endpoint in `.env`, trace spans are sent to that destination. Tracing adheres to GenAI semantic conventions and preserves a zero-content privacy guarantee: spans capture run metadata, model names, token counts, timings, and status, but never include prompt text, model answers, or raw exception payloads.

## Development and demo

`DEV_MODE` masks email, calendar, and reminder content before briefing prompts or saved evidence; non-personal telemetry such as weather remains available. Sandbox uses a restricted non-personal tool allowlist and isolated history, and cannot refresh or remove copies in the production Context vault. Accepted Cortex runs retain their server-derived production or sandbox partition through execution and retrieval indexing, so changing the sandbox setting affects later requests without moving in-flight history or context. `DEMO_MODE` uses a deterministic Daily fixture, cannot write to the production vault, and does not contact configured connectors or model providers on demo paths.

Credentials belong in `.env` or the local environment, never in `config.json`, `config.local.json`, documents, or source control.
