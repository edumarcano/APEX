# Privacy

APEX stores its settings and history locally, but connected services, cloud models, speech providers, and optional tracing can send data outside the machine. The settings you enable and the model you select determine those boundaries. Local storage is not encrypted by APEX.

## Local storage and credentials

`apex_memory.db` holds conversations, run records, briefing artifacts and speech, personal-context evidence and history, review proposals, external activity reports, reminder state, retrieval indexes, and action evidence. Runtime Settings saves non-secret preferences in `config.local.json`.

Windows desktop completion notifications are off by default. When enabled, they reveal only that an APEX run completed, using the fixed title `APEX` and body `An APEX run has completed.`; they omit prompts, answers, run identifiers, and provider details. Only successful committed Cortex and Briefing completions qualify, and each completion is notified at most once per app session. Notifications are shown only while the desktop window is hidden or minimized. The preference is stored locally with other Runtime Settings.

Credentials use separate storage:

- Provider keys and environment-specific paths belong in `.env` or the process environment.
- Google authorization reads `credentials.json` and writes a local `token.json`. The token file is not encrypted by APEX.
- Microsoft To Do uses an encrypted token cache outside the repository.
- MCP OAuth authorization uses the operating system credential manager. Other MCP credentials are read from the configured environment variables.

Keep credential files, tokens, databases, and local overrides out of source control. Files copied by backups or sync services are governed by those services, including copies of the database or exported notes.

The Windows desktop Import flow copies a selected source profile into its private data folder and leaves the source unchanged. Its preview shows managed file categories and safe labels, not credential values or external absolute paths. Some files stay at external destinations, including the Context vault, report folder, and configured model locations; Microsoft To Do's encrypted token cache uses the existing same-user Windows storage. Later backup or sync copies follow those services' retention and access controls. See [Configuration](configuration.md#desktop-first-run-and-import) for import and recovery behavior.

## Device location

Device location is off by default and requires a saved opt-in plus an explicit foreground Windows permission check in each native app session. Only actual Weather requests acquire a fix. Settings, status reads, preflight checks, tool catalogs, and background workers do not request permission. APEX does not subscribe to continuous position updates or store a location history.

Raw coordinates travel over private process pipes and are sent to Open-Meteo as forecast request parameters. They stay out of the frontend, HTTP status responses, logs, model context, Cortex tool records, and saved Briefing evidence. APEX retains fixes only in memory for at most 15 minutes and clears them when location is disabled, permission is revoked, or the session shuts down. Weather results expose a safe **Current area** label and device source attribution; configured and explicit locations keep their ordinary labels.

## Models and connected services

A cloud model request can include your message, selected conversation history, tool definitions, and the evidence allowed for that request. Local models receive those inputs at the configured llama.cpp endpoint. Choosing a local model does not make connected services local: a connector or MCP tool can still contact its external service.

Provider-hosted grounding is separate from APEX tool calls. It is available only when the cloud model supports it and its Runtime Settings switch is enabled. Search or map grounding can send information from the request to the provider's hosted service.

Calendar reads use only the calendars selected in Runtime Settings. Event titles, times, locations, and calendar labels can enter briefing or Agent prompts. Turning off **Show calendar names with events** removes calendar attribution labels from model-visible context; it does not remove the event metadata.

Tools send the arguments needed for their operation to the relevant service, and their results can be returned to the selected model as untrusted data. Native write operations require local approval and create action evidence. Ambiguous outcomes are not replayed automatically.

## Personal context

Cloud and local personal-context retrieval are independently disabled by default. When enabled, selected current claims can enter model prompts with concise provenance and effective-time labels. Normal claim retrieval excludes full source evidence, knowledge history, and pending replacement text as current knowledge.

Briefings have an additional evidence path. When personal context is enabled, they can include pending review text, selected external report excerpts, and verified action outcomes alongside accepted claims. Pending proposals remain labeled as pending; external reports remain untrusted. Neither becomes accepted knowledge merely because it was included in a briefing.

Original evidence, normalized claims, provenance, and knowledge history are stored locally. Corrections and retractions preserve earlier evidence and history. Records have a sensitivity classification, which carries forward through corrections and conflict resolution when a predecessor is sensitive. Changing that classification adds a history event. The Context vault uses sensitivity to control export; its opt-in is separate from the runtime switches that permit model retrieval.

## External activity reports

Importing a report stores its findings and Markdown locally without accepting them as personal knowledge. When personal context is enabled, APEX can select relevant, non-dismissed report excerpts for briefing evidence and send them to the chosen model. Cloud models receive the excerpts included in their requests.

Cortex can discover and read received reports when the report tools are selected and the chosen runtime's personal-context setting is enabled. Reads are unavailable in demo, development, and sandbox execution. Cloud models receive the report content returned by these tools, including Markdown, findings, and external references when read. Responses are bounded and long reports require continuation reads; an exact read can include a dismissed report. Reading does not authenticate a source, accept its claims, or follow its references.

The run retains its admitted partition and effective model for report access. Turning off personal context blocks subsequent report reads; it cannot retract content already sent to the model.

Accepting a context review linked to a report creates a normalized claim with external source provenance. That claim can later enter ordinary personal-context retrieval when enabled. Normal claim retrieval does not include the full report or its original evidence.

The optional report folder leaves imported files in place. If the folder is synced, its sync service controls the external copies. The separate local submission gateway accepts caller-declared source labels; those labels do not authenticate the submitting program. See [Configuration](configuration.md#external-activity-gateway) for its loopback boundary.

## Briefings

Daily, Catch Up, and Deep use the selected APEX Agent model. Their requests can include current telemetry and selected contextual evidence. Catch Up and Deep can also include historical evidence from previously presented briefings. Cloud providers receive the evidence included in these calls; local inference uses the configured endpoint. APEX does not silently fall back to another model.

Catch Up compares compatible checkpoints separately for each source. It can save a deterministic no-change result without calling a model. Saved artifacts and evidence remain available for local inspection. Follow-up conversation turns can send a limited selection of cited briefing evidence to the model chosen for that turn, including a cloud model.

Deep offers a curated set of permitted read-only tools, separate from the saved Agent tool profile. A model may request reads from enabled connectors or allowlisted MCP services, and bounded results are returned to it. Write, destructive, and provider-hosted tools are excluded. Selected read results are saved with their source trust and capture time; the raw investigation transcript is not persisted. See [Architecture](architecture.md#briefing-routes) for execution and evidence limits.

## Speech

Preparing spoken highlights makes a separate model call using the saved briefing artifact and the original session's model. The saved user designation may also be sent so the script can address the user. That call has no tools, retrieval, conversation history, or fresh telemetry. The validated script and audio chunks are stored locally. Playback uses the stored chunks without another model or speech-synthesis call, and audio is played on the host machine rather than streamed to the browser.

Google Cloud Text-to-Speech receives the text it synthesizes. Kokoro and pyttsx3 synthesize locally. This applies both to prepared briefing speech and short contextual cues. Automatic voice mode can speak cues during collection, briefing generation, and speech preparation; manual and off modes suppress those cues. Prepared briefing speech is played only through explicit controls.

See [Speech Runtime](speech-runtime.md) for installation, fallback, and caching behavior.

## Context vault copies

Context vault export is disabled by default and starts with no selected records. Enabling it writes selected production claims as Markdown under `APEX_CONTEXT_VAULT_PATH`. Sensitive records require a scope's explicit opt-in. Demo and development sandbox sessions cannot publish to the production vault.

Generated notes contain canonical claim text and limited source metadata, but omit original evidence, source locators, and source URLs. Export status confirms local publication only; it does not confirm that another application or sync service copied or indexed the files.

Disabling export retains existing copies. Deselecting a record while export is enabled removes its managed copy on refresh. Changing the destination leaves copies at the previous location for deliberate cleanup. Managed-copy removal affects only files tracked as APEX-owned, leaving handwritten files and `.obsidian/` alone. Copies made by other applications must be managed there.

See [Context Vault](context-vault.md) for selection and cleanup procedures.

## Retention and deletion

Archived Cortex conversations are eligible for permanent deletion after 30 days by default. The configurable minimum is 14 days. Checks run at startup and about every 24 hours, and skip conversations with pending turns or active runs. Deleting a conversation also removes its linked briefing session and speech data. Separately accepted personal-context sources keep their own lifecycle.

Retracting personal knowledge preserves its earlier evidence and history; it is not an erasure operation. Imported report-folder files and copies held by backups, sync services, or external providers are outside conversation deletion.

An existing retired `briefings` table is left untouched. Its contents are not read or migrated into saved-session history and can remain private data in the database. See [Configuration](configuration.md#archived-conversation-retention) for retention settings and [Persistence compatibility](architecture.md#persistence-compatibility) for database startup checks.

## Distributed tracing

Tracing is optional. With the tracing dependencies installed and an OTLP endpoint configured, APEX exports spans to that destination. Its explicit span attributes record identifiers, models, token counts, timings, and status without adding prompt, answer, or tool-result content.

The current tracing contexts can also record exceptions that escape them, including exception messages and stack traces. Error text can contain private information, so exported traces do not have a zero-content guarantee. The collector controls retention and access to exported copies. See [Configuration](configuration.md#opentelemetry-genai-tracing) for setup.

## Development and demo

`DEV_MODE` masks email, calendar, and reminder content before briefing prompts and saved evidence. It does not make every operation offline. The development sandbox uses restricted non-personal tools and separate history. An accepted Cortex run keeps its original production or sandbox partition even if the setting changes while it is running.

`DEMO_MODE` uses temporary storage and deterministic Daily and Catch Up fixtures. Demo paths skip live connectors and model providers, and cannot write to the production Context vault. Optional speech is adapted from the fixture artifact and uses `DEMO_TTS`; selecting Google speech can still send spoken text to Google. The default demo speech engine is local pyttsx3.
