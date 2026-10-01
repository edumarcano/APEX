# Architecture

APEX is a local-first personal intelligence workspace. React provides the interface, FastAPI owns application services and execution, and SQLite stores durable application records. Optional connectors, model providers, and speech services can send data outside the local process; [Privacy](privacy.md) describes those boundaries.

This document explains how collection, conversations, briefings, and personal context fit together. Use [Configuration](configuration.md) for settings, [API](api.md) for HTTP behavior, and the [frontend guide](../frontend/README.md) for browser state and presentation loading.

## System components

The browser opens on Launch and provides four peer workspaces: Overview, Briefing, Cortex, and Reports. Navigation does not start telemetry collection or briefing generation. The shared conversation runtime and app-level state owners stay mounted while workspace presentations load on demand. Loading and retry states remain within the requested workspace; see [Presentation loading](../frontend/README.md#presentation-loading).

FastAPI owns connectors, telemetry snapshots, settings, conversations, runs, tools, actions, knowledge, retrieval, briefing sessions, and speech. Its lifespan initializes services, recovers interrupted work, starts background workers, and drains work before closing dependencies.

The **APEX Agent** is the single built-in assistant, identified internally as `apex`. The **Cortex Engine** runs its model turns and tool loops. A model choice determines the provider or local runtime, context limits, reasoning controls, pricing, availability, and supported hosted tools. It does not change the Agent's identity. Naming and workspace definitions belong in [Identity and naming](identity-and-naming.md).

## Telemetry collection

Telemetry collection gathers status from enabled connectors without requiring model inference. Overview begins with Collect Telemetry; preflight and an explicit refresh precede the first usable grid. A failed or unusable first collection leaves a retry or no-data state. Briefing can also collect telemetry without leaving its workspace.

```text
Explicit collection request
    -> connector refresh lifecycle
    -> shared snapshot with source health and freshness
    -> Overview display or briefing evidence selection
```

Connector refreshes run sequentially. The shared snapshot records usable data and source limitations, so one unavailable connector need not hide the others. Cached values retain freshness labels rather than being treated as live observations.

Market uses a separate file-backed cache owned by its client. Collection can fetch Alpha Vantage data; the Market API only reads the cache. Per-symbol request gates handle successful daily fetches, throttling, quota exhaustion, and failure backoff. The frontend reloads Market data when telemetry publishes a collection revision. Charts use daily OHLCV history, while briefings use bounded ticker snapshots and price moves. See [Market data](configuration.md#market-data) for cache and request settings.

## Conversations and model execution

Conversation requests resolve their model and effective controls before entering the Agent loop:

```text
Conversation turn
    -> resolved model, controls, and partition
    -> permitted context and tools
    -> Cortex Engine bounded model/tool loop
    -> provider or local runtime
    -> saved answer, execution metadata, and action evidence
```

Conversation storage owns prompts and answers. Request metadata records the model, provider, runtime, controls, and accepted production or sandbox partition. Idempotent replay uses those choices as well as the Agent identity. Once an asynchronous run is accepted, later settings changes affect subsequent requests rather than changing that run's execution choices.

Provider profiles, tool defaults, hosted capabilities, and schema projections follow the effective request model, including an explicit override. Gemini, OpenAI Responses, and llama.cpp consume native streams even without a live browser observer. Providers own stream cleanup and bounded retries. Gemini can recover an empty non-structured STOP result with one bounded unary call. OpenAI requests use `store=False` and send bounded APEX history instead of relying on provider-owned conversation state.

### Tools and actions

Tool exposure depends on user selection, Agent policy, runtime availability, sandbox restrictions, risk controls, and MCP allowlists. An empty selection exposes no APEX-managed tools. Provider-hosted grounding is controlled separately from APEX and MCP tool schemas.

Write-capable tools create action proposals for operator approval before execution. New proposals use `agent_key="apex"`; historical action records retain their original provenance and checksums. Execution and verification belong to the action service, which records outcomes for later inspection.

### Local inference

One coordinator permits a single local inference execution across Ollama and llama.cpp. Before loading a model, it checks reachability, resident models, installed aliases, and resource gates. Context and reasoning changes apply to the next relevant request. Loading, switching, and unloading share the coordination boundary with inference.

### Runs and activity

The `CortexRunCoordinator` executes asynchronous work in a bounded thread pool. It permits one active run per conversation, returns `409` for overlap and `429` when the pool is full, and reuses an existing run for an identical turn request without taking another slot. [Bounded run limits](configuration.md#bounded-run-limits) defines the settings.

SQLite stores run limits, token accounting, turn and tool counts, timings, stop reasons, and completion evidence in a ledger separate from message text. Unfinished runs become `interrupted` on startup. Cancellation is cooperative: execution checks for it at model-turn and tool boundaries.

Server-Sent Events carry live status, answer deltas, tool activity, and measurements. Bounded process-local buffers support reconnect replay; disconnecting the browser does not cancel the run. These buffers do not survive a server restart.

Completed conversation messages also retain a bounded, sanitized activity timeline. Saved history can show model and tool progress without reconstructing the live event stream. Activity excludes model reasoning and tool argument or result bodies; answer content and tool outputs have their own presentation paths.

## Briefing routes

Briefings create durable sessions through a shared collection, comparison, synthesis, and artifact pipeline:

```text
Profile and explicit model choice
    -> current telemetry and permitted personal evidence
    -> comparison with presented source checkpoints
    -> bounded investigation for Deep
    -> synthesis and validation, or a no-change Catch Up result
    -> canonical artifact, saved evidence, and linked conversation
```

Daily selects current evidence for an orientation. Catch Up compares current source state with compatible checkpoints from completed, presented sessions; different sources can use different prior sessions. Showing an artifact marks it as presented, which is separate from completing generation. When comparison finds no material changes and no synthesis candidates, Catch Up can save a no-change result without a model call.

Accepted context, pending reviews, relevant external reports, and verified action outcomes enter evidence selection only when the selected runtime permits personal context and development mode is off. Pending proposals and reports keep their distinct trust labels. They do not become accepted knowledge by appearing in a briefing.

The session stores the canonical artifact, observed evidence, coverage, comparison, model configuration, and limitations. Its opening conversation message is a rendered copy linked to that artifact. Follow-ups use normal conversation history and context policy, with a small, relevance-ranked slice of cited saved evidence inside the untrusted reference boundary and context budget. Personal-context-derived snapshots remain subject to the selected runtime's retrieval setting. The evidence inspector reads full saved snapshots on demand.

Briefings do not silently switch models when the requested model is unavailable or cannot fit a useful prompt. Cancellation, global execution limits, invalid synthesis after repair, and persistence errors do not produce a completed artifact. Demo mode supplies deterministic Daily and Catch Up fixtures; Deep is unavailable.

### Deep investigation

Deep inserts an investigation before synthesis using the shared Agent loop. It selects up to eight relevant read capabilities from current evidence, separately from the saved Agent tool profile. Policy, partition, connector availability, and MCP permissions are checked at selection and invocation. Write, destructive, and provider-hosted tools are excluded.

The investigation prompt includes bounded current evidence and paired historical records with source roles, trust labels, and capture times. It permits at most four calls, 1,024 generated tokens per turn or the lower session output limit, and 180 seconds or half the remaining run time. Model and run limits reserve at least two turns for synthesis, including one repair. Local investigation releases its inference slot before synthesis acquires one.

Selected read results become labeled evidence. The artifact records investigation status and limitations, while the raw investigation transcript is not persisted.

### API and history

The briefing API consists of `GET /api/v1/briefing-profiles` and the `/api/v1/briefing-sessions` routes. The CLI uses the same asynchronous API with origin `cli`; it does not call services or SQLite directly.

The Agent's `get_briefing_history` tool reads at most five newest completed sessions with canonical artifacts from the active partition. It returns bounded content, profile and model identity, timestamps, presentation status, and limitations. Failed or incomplete sessions are excluded before applying the limit. The retired transcript-based briefing pipeline and routes are not supported.

### Speech derived from briefings

Speech preparation starts from a completed canonical artifact. A separate worker makes a bounded adaptation call using the session's model and artifact, validates the resulting highlights, and synthesizes audio through the selected voice engine. It does not collect fresh evidence or run an independent investigation.

The session stores the speech script and references to local audio chunks, tied to the artifact's hash. Playback reuses prepared audio on the APEX host without another model or synthesis call. One speech worker serializes preparation and playback, with explicit stop and shutdown cancellation. Speech failure leaves the canonical briefing available. See the [Speech runtime guide](speech-runtime.md) for delivery behavior and [Privacy](privacy.md#speech) for data sent to voice services.

## Personal context and review

The knowledge store separates immutable source evidence from normalized claims. Sources record origin, occurrence time when known, and capture time. Claim-to-source links distinguish direct statements, model interpretations, and unknown derivation; approval does not change how the evidence originated.

Knowledge history records status changes, evidence links, corrections, conflict decisions, and entity reconciliation. Existing `migration_baseline` entries remain historical records; bootstrap does not create new baselines.

Review proposals freeze source evidence, the proposed mutation, reason codes, and affected record, entity, and alias snapshots. Pending proposals stay outside retrieval. Acceptance uses the action executor and verifier, committing the knowledge mutation, history, retrieval synchronization, and decision in one SQLite write transaction. A stale decision must be refreshed before the operator decides again.

Context assembly reloads retrieved records from the knowledge store before adding them to a prompt. Only active or explicitly conflicting records are eligible, so stale retrieval entries cannot restore superseded or retracted claims. Claims carry provenance, effective-time labels, and inspection references. A pending review marks the current claim as uncertain without inserting its proposed replacement into retrieved context. Briefing selection can include pending proposals separately, as described above.

Retrieved context remains untrusted reference material and counts against the cloud or local context budget. Cortex's Context inspector exposes current wording, original evidence, history, and review decisions separately.

## Context vault publication

The knowledge store remains canonical; the configured vault is a generated Markdown copy. A worker owned by the FastAPI lifespan coalesces committed production changes and publishes selected scopes off the event loop. Manual refresh and managed-copy removal use the same serialization boundary.

Each source transaction advances the production knowledge revision. The worker checks revisions before and after snapshots and publication. If knowledge or the saved selection changes during a refresh, it keeps the state dirty and reconciles again.

SQLite retains ownership hashes, interrupted work, revisions, counts, timestamps, and sanitized errors. Startup recovers pending publication. Failures keep dirty state, receive bounded retries, and then wait for a new change or manual refresh. Disabling publication keeps existing copies; explicit removal deletes tracked files without pruning the destination tree. Completion means files were published locally, not that another application synced or indexed them. See the [Context vault guide](context-vault.md) for selection and cleanup.

## External activity reports

External reports are immutable input, separate from accepted knowledge. Their store records receipt identity, partition, caller-claimed source label, and idempotency key. The separate `new`, `reviewed`, or `dismissed` disposition can change without modifying the report. Valid source-label syntax does not authenticate the caller.

Reports are not indexed for general personal-context retrieval or promoted automatically. When personal-context policy permits, briefing selection can include at most three relevant, non-dismissed reports from the newest 50 candidates as untrusted evidence.

An operator can select a finding for a pending context review. The server freezes its text, evidence locator, external origin, and occurrence time. Locators identify `/findings/<index>`, or `/outcome` and `/markdown_body` when no structured finding exists. A declared `model_interpretation` remains an interpretation; otherwise derivation is `unknown`. Only acceptance creates a knowledge record eligible for retrieval.

The Reports workspace reads a bounded list and exact details, changes disposition, and opens linked reviews in Cortex. It retains the selected partition. Report text and external references remain untrusted display data: Markdown renders without raw HTML and links are limited to HTTP(S).

The opt-in loopback gateway exposes submission through JSON HTTP and Streamable HTTP MCP. It shares the activity store with CLI and file import, uses the local `operator` principal, and derives the partition server-side. It does not expose report reads, main application routes, Agent execution, actions, or proxy access. Its process-wide limit is 30 combined JSON and MCP attempts per minute. Because it does not authenticate remote callers, it must not be exposed through a tunnel or reverse proxy. Setup belongs in [Configuration](configuration.md#external-activity-gateway).

## Persistence and lifecycle

SQLite owns conversations, runs, briefing sessions, knowledge and review history, actions, external reports, and derived retrieval records. The browser owns presentation state; vault notes, retrieval indexes, and speech output are derived from application records rather than replacing them.

On shutdown, FastAPI signals speech cancellation and closes run admission. It drains active runs and application-owned tasks, then the speech worker, before releasing stores, connectors, and other dependencies. A bounded shutdown window reports failure and leaves dependencies open if work remains active, avoiding cleanup underneath a running worker.

### Persistence compatibility

The v2.0.0-beta.6 database schema is the supported upgrade floor. Before bootstrap or recovery, startup checks core persistence versions and required table shapes through a read-only connection. Fresh databases receive the current schema. Unsupported core schemas stop startup without rewriting data or deleting tables; APEX does not automatically migrate older schemas.

Fresh `cortex_runs` tables no longer allow `max_total_tokens` as a stop reason. Existing databases may retain that older table constraint; this does not block startup, and APEX does not rebuild it automatically. To normalize an existing database, stop APEX and run `uv run python scripts/normalize_run_constraint.py --database path\to\apex_memory.db --apply`. Without `--apply`, the command checks eligibility without changing the database. It refuses unsupported table shapes and rows that use the retired stop reason. On an eligible apply, it takes a uniquely named adjacent SQLite backup, then rebuilds only the `cortex_runs` table and validates its rows, indexes, triggers, foreign keys, and database integrity before committing. The `RunLimitSnapshot` reader still accepts historical snapshots containing `max_total_tokens`.

Unsupported retrieval persistence disables retrieval for that run while canonical knowledge writes continue without derived synchronization. Conversation deletion and archived-conversation retention are also deferred because message deletion triggers can update retrieval rows. Manual deletion returns `409 Conflict`; retention logs the failed sweep and retries on its next scheduled pass.

Initialization leaves any residual retired `briefings` table untouched. See [Configuration](configuration.md#briefing-profiles) for ignored legacy preferences and [Privacy](privacy.md#retention-and-deletion) for retained data and deletion boundaries.

## Distributed tracing

When configured, OpenTelemetry exports failure-isolated traces for the root run (`invoke_agent`), model calls, and tool execution using GenAI semantic conventions. Explicit attributes contain model identifiers, tokens, counters, and timings without adding prompt or answer content. Exceptions escaping tracing contexts can still record messages and stack traces. See [Configuration](configuration.md#opentelemetry-genai-tracing) for setup and [Privacy](privacy.md#distributed-tracing) for that limitation.
