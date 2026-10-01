# Engineering Decisions

This document records why APEX uses its current boundaries and which trade-offs it accepts as a single-user, local-first project. [Architecture](architecture.md) explains how those choices fit together; the linked guides own settings, API behavior, and operational details.

The current decisions are grouped by concern. Each states the choice, its motivation, and its cost. [Earlier designs](#earlier-designs) preserves the reasoning behind retired approaches and links to their replacements.

## Configuration and storage

### Separate secrets, tracked defaults, and local preferences

**Decision.** Keep secrets out of configuration JSON. Provider keys and environment-only switches use `.env` or the process environment; OAuth credentials and tokens use their connector's file, encrypted cache, or operating system credential store. `config.json` holds committed non-secret defaults, and gitignored `config.local.json` holds supported local overrides.

**Why.** Credentials, shared defaults, and personal settings have different lifecycles. Separating them lets APEX manage preferences without rewriting secrets or committing machine-specific values.

**Trade-off.** There are several storage locations to understand and protect. Neither an untracked file nor local storage implies encryption. See [Configuration](configuration.md#where-settings-live) and [Privacy](privacy.md#local-storage-and-credentials).

### Use a mutable overlay for Runtime Settings

**Decision.** Runtime Settings writes supported changes to `config.local.json`, overlays them on tracked defaults, and publishes the new snapshot after the file has been replaced successfully.

**Why.** Preferences should be editable from the interface without modifying the repository's defaults or restarting for each change.

**Trade-off.** File-only settings still need a restart, and invalid overrides need a clear fallback to defaults. Validation and persistence must agree before a new snapshot becomes visible. See [Runtime Settings](configuration.md#runtime-settings).

### Use SQLite for durable application state

**Decision.** SQLite owns local application records, including conversations, runs, briefings, personal context, reviews, reports, reminders, and actions.

**Why.** These records need identity, ordering, transactions, and recovery. SQLite supplies those properties without requiring a separate database service.

**Trade-off.** APEX must manage schema compatibility, transaction boundaries, and retention. It does not encrypt the database. External services can remain authoritative for synced data, as with [Microsoft To Do reminders](#use-microsoft-to-do-as-the-reminder-authority).

### Validate persistence before changing it

**Decision.** The v2.0.0-beta.6 schema is the supported upgrade floor. Startup checks core persistence through a read-only connection before bootstrap or recovery and rejects unsupported schemas. Unsupported retrieval persistence disables retrieval for the run while canonical knowledge writes continue without derived synchronization.

**Why.** Conversation and knowledge records are harder to replace than a derived search index. Startup should establish that it understands existing data before writing to it.

**Trade-off.** APEX does not automatically upgrade every older database. Retrieval degradation also defers conversation deletion and retention where deletion triggers could touch unsupported retrieval tables. See [Persistence compatibility](architecture.md#persistence-compatibility).

### Write timezone-aware UTC timestamps

**Decision.** Application-generated record timestamps use timezone-aware UTC.

**Why.** A shared time basis keeps ordering and comparisons independent of the host's current time zone and avoids ambiguous local wall-clock values.

**Trade-off.** Presentation must convert timestamps to the user's local time where appropriate. The retired reader for legacy cooldown records is described under [Earlier designs](#legacy-cooldown-timestamp-reads).

## Execution and model ownership

### Give operations independent lifecycles

**Decision.** Activation, telemetry collection, briefing generation, Agent turns, and speech have separate service and interface owners.

**Why.** A provider or speech failure should not prevent telemetry inspection or make an already saved briefing unreadable. Each operation needs its own progress, failure, and retry behavior.

**Trade-off.** More independent paths require coordination and explicit state ownership. There is no full-trigger request that owns every operation. See [Architecture](architecture.md).

### Use one APEX Agent with model-routed execution

**Decision.** APEX has one built-in Agent. The selected model determines its provider or local runtime, capabilities, controls, and availability. Experimental models remain in that catalog but are exposed only in development mode.

**Why.** The assistant's role should remain consistent when its model changes. A development-only catalog gives the project room to experiment without introducing another Agent identity for each runtime.

**Trade-off.** Model metadata, settings, and capability checks still need to agree. A consistent Agent identity does not imply identical behavior across models. See [Identity and naming](identity-and-naming.md#apex-agent-and-lynx) and [Models and credentials](configuration.md#models-and-credentials).

### Keep conversation state in APEX

**Decision.** APEX stores the conversation tree and rebuilds a bounded active-branch history for each run rather than relying on a persistent provider-owned model session.

**Why.** Branching, history, and recovery should remain under application control when the selected model or provider changes.

**Trade-off.** APEX must select history within the model's context budget and reconcile browser thread state with the saved active branch. Conversation text remains in unencrypted local storage. See [Conversations and model execution](architecture.md#conversations-and-model-execution).

### Share local inference admission and model lifecycle

**Decision.** Briefings, Agent turns, and speech adaptation share local model loading, switching, execution admission, and idle unloading across Ollama and llama.cpp. APEX coordinates one resident model among its known models and rejects competing local execution rather than adding a hidden queue.

**Why.** These workloads use the same CPU and memory. One coordinator makes contention visible and prevents separate APEX managers from loading competing models. Cold-load resource checks protect the host; a verified resident model does not need another loading gate.

**Trade-off.** Busy requests require a retry, and idle unloading adds another lifecycle to manage. This coordination does not control unrelated processes or every model loaded outside APEX. See [Local inference](architecture.md#local-inference).

### Expose supported reasoning controls and keep reasoning private

**Decision.** Reasoning controls follow the selected model's capabilities. Local reasoning defaults to `none`. Hidden reasoning fields and think-style tags are removed before response display, and activity records exclude model reasoning.

**Why.** Provider controls differ, and an unsupported setting should not appear to work. Progress visibility should explain what the Agent is doing without exposing hidden reasoning.

**Trade-off.** Equivalent control names do not guarantee equivalent behavior across models. APEX does not set a separate local reasoning-token budget or report local reasoning-token usage. See [Models and credentials](configuration.md#models-and-credentials) and [Runs and activity](architecture.md#runs-and-activity).

### Bound execution and drain workers before closing dependencies

**Decision.** Run admission and execution are bounded. Cancellation is cooperative. Shutdown closes admission and drains active work before closing the stores, connectors, and runtimes it uses.

**Why.** Long model and tool operations need limits, while dependencies must remain available until their workers stop using them.

**Trade-off.** Cancellation can wait for a model or tool boundary. If work outlasts the shutdown window, shutdown reports failure and leaves dependencies open rather than closing them beneath a running worker. See [Bounded run limits](configuration.md#bounded-run-limits) and [Persistence and lifecycle](architecture.md#persistence-and-lifecycle).

### Keep operational preflight advisory where possible

**Decision.** Network policy, power state, refresh frequency, and high-resource model selection normally produce warnings. Conditions that prevent the chosen operation remain blockers.

**Why.** A Wi-Fi name or battery state provides context, not proof of safety or permission. A personal tool should let the operator decide whether to proceed through an advisory warning.

**Trade-off.** The operator must judge those warnings. Missing required credentials, unavailable models, inference contention, failed resource gates, and invalid required local state cannot be overridden. See [Telemetry and preflight](api.md#telemetry-and-preflight).

### Stream live activity without persisting every event

**Decision.** Live run updates use Server-Sent Events with bounded process-local replay buffers. SQLite records run state from admission onward, and completed messages retain a bounded, sanitized activity timeline.

**Why.** Unidirectional HTTP streaming supports live progress and reconnects without a WebSocket protocol or a database write for every answer delta. Saved status and activity can remain useful after the live stream is gone.

**Trade-off.** Replay covers only the retained buffer and cannot survive a backend restart. Unfinished durable runs become interrupted on startup. Disconnecting a client does not cancel its run. See [Runs and activity](architecture.md#runs-and-activity).

## Briefings and speech

### Keep live telemetry snapshots process-local

**Decision.** The current typed telemetry snapshot stays in memory and is identified by an opaque `snapshot_id`. Briefing sessions persist the evidence they use.

**Why.** Live observations serve refresh and inspection. Saving every observation would introduce another retention and compatibility lifecycle; saved briefing evidence provides history for the generation that needs it.

**Trade-off.** Restarting the backend invalidates explicit live snapshot references. APEX does not provide a durable history of every connector observation. See [Telemetry collection](architecture.md#telemetry-collection).

### Save a canonical briefing artifact with its evidence

**Decision.** Each completed briefing session saves a canonical artifact, selected evidence, and execution metadata. Presentation is recorded separately from generation. The linked conversation starts with a rendered copy of the artifact.

**Why.** A briefing should remain inspectable after its source data changes. Separating evidence from display prose also makes the information sent to synthesis deliberate. Catch Up needs to distinguish a generated briefing from one actually presented to the operator.

**Trade-off.** Evidence selection, provenance, and presentation checkpoints require their own contracts and storage. A saved artifact records what APEX produced; it does not guarantee that every model claim is correct. See [Briefing routes](architecture.md#briefing-routes).

### Separate briefing profiles from model selection

**Decision.** Daily, Catch Up, and Deep define the briefing workflow and use the explicitly selected Agent model. An unavailable or failed selected model does not silently switch to another model or synthesis route.

**Why.** The kind of briefing and the model executing it are separate choices. Keeping them separate makes provider use, local resource use, and failure behavior easier to understand.

**Trade-off.** Some failures leave the session without a completed artifact. Catch Up can produce a deterministic no-change result when its comparison warrants one, but that is profile behavior rather than a model fallback. See [Briefing profiles](configuration.md#briefing-profiles).

### Derive speech separately and reuse prepared audio

**Decision.** Speech preparation adapts a completed artifact using the session's saved model, then validates the script and caches audio tied to that artifact. Playback uses the saved chunks on the APEX host. The backend owns actual preparation and playback state.

**Why.** Speech should not collect new evidence or change a saved briefing. Separating preparation from playback avoids repeated model and synthesis calls, and speech failure leaves the briefing available. Backend state reflects delivery more reliably than a browser timer.

**Trade-off.** Preparation adds a model call, audio storage, cache invalidation, and worker coordination. Validation catches specified mismatches rather than proving every factual claim, and host playback depends on working local audio. See [Saved briefing highlights](speech-runtime.md#saved-briefing-highlights) and [Speech privacy](privacy.md#speech).

### Keep speech fallback local

**Decision.** Google Cloud TTS and Kokoro attempt local pyttsx3 fallback when synthesis fails. Kokoro never falls back to Google Cloud TTS.

**Why.** A failed local engine should not silently send its text to a cloud speech service. A lighter local engine can still offer delivery when the selected engine is unavailable.

**Trade-off.** Fallback can change the voice or fail too. The saved speech state records the resolved engine. Local audio synthesis is separate from script preparation, which may use a cloud model. See [Engine behavior](speech-runtime.md#engine-behavior).

### Load Kokoro only when selected

**Decision.** Kokoro is optional, initializes only when selected, and has speech-specific resource admission checks.

**Why.** Its imports, warmup, and inference consume resources even when another voice engine is preferred. Earlier measurements on the development machine showed enough startup latency to justify keeping it optional.

**Trade-off.** Selecting Kokoro requires local assets and may incur warmup or resource-related fallback. Performance depends on the host; the historical observations below are not current latency guarantees. See [Installation](speech-runtime.md#installation) and [Kokoro resource checks](speech-runtime.md#kokoro-resource-checks).

## Context and actions

### Keep source evidence separate from current claims

**Decision.** Personal context separates immutable source evidence from normalized claims and preserves changes in append-only history. Clear direct operator input can save immediately; sensitive, conflicting, or model-interpreted changes use durable review. Pending replacement claims stay out of ordinary retrieval.

**Why.** APEX needs to distinguish what was supplied, how it was interpreted, and what it currently treats as true. Frozen evidence and revision checks prevent a stale proposal from silently replacing current knowledge.

**Trade-off.** Review and history add schema and lifecycle work, and correction or retraction does not erase earlier evidence. Review acceptance commits the mutation, history, decision, and supported retrieval synchronization together. See [Personal context and review](architecture.md#personal-context-and-review) and [Privacy](privacy.md#personal-context).

### Publish selected context as a derived copy

**Decision.** The knowledge store remains canonical. Context vault publication is opt-in and writes selected production claims as generated Markdown, with a separate sensitive-data opt-in and managed-file ownership.

**Why.** External applications can read useful context without becoming the knowledge store or receiving all source evidence. Explicit selection keeps publication separate from permission to retrieve context for model prompts.

**Trade-off.** Publication needs revision tracking, recovery, and cleanup. Disabling it retains existing copies, and local publication cannot confirm another application's sync or indexing. Copies outside APEX's ownership have their own lifecycle. See [Context Vault](context-vault.md).

### Keep external reports outside accepted knowledge

**Decision.** External activity reports are immutable input with a separately editable disposition. Findings become accepted knowledge only through review. Reports are excluded from general personal-context retrieval, though permitted briefings can select excerpts as untrusted evidence.

**Why.** Receiving a report or marking it reviewed does not establish the truth of its claims. A separate review preserves external provenance and gives the operator control over promotion into personal context.

**Trade-off.** Reports and knowledge need separate storage and review paths. Caller-declared source labels do not authenticate origin, and permitted report excerpts may reach the selected model before knowledge acceptance. See [External activity reports](architecture.md#external-activity-reports) and [Privacy](privacy.md#external-activity-reports).

### Treat connector and tool content as untrusted data

**Decision.** Connector evidence, retrieved context, and tool results enter prompts within explicit untrusted-data boundaries. Native write capabilities use the action system; MCP write and destructive capabilities remain unavailable.

**Why.** Calendar titles, messages, reports, and provider results can contain instructions written outside APEX's control. Their content should inform an answer without granting authority to act.

**Trade-off.** Prompt markers reduce risk but cannot prove that a model will ignore every embedded instruction. Execution policy and approval must enforce the action boundary independently. See [Tools and actions](architecture.md#tools-and-actions).

### Prove the action flow with Microsoft To Do

**Decision.** Agent-requested To Do changes use proposals, approval, execution, verification, and an action record. Direct reminder management remains an operator action without an added model-approval step.

**Why.** Task changes provide a manageable way to explore approval, uncertain writes, restart recovery, verification, and history before applying the same ideas to more consequential workflows.

**Trade-off.** This is more machinery than task editing alone requires. That complexity is intentional: APEX is a place to learn and experiment with development using AI tools, including the boundaries around model-requested actions. See [Actions](api.md#actions).

## Integrations and interface boundaries

### Use Microsoft To Do as the reminder authority

**Decision.** One selected Microsoft To Do list is authoritative for synced reminders. SQLite keeps local reminder state and an outbox for pending changes.

**Why.** To Do supplies cross-device synchronization without APEX needing a mobile application. Local records preserve reminder visibility and allow local creation during an outage.

**Trade-off.** Cached reminders can become stale, and pending changes need later synchronization. Local state and confirmed external state must remain distinguishable. See [Reminders](api.md#reminders).

### Keep the CLI as an API client

**Decision.** The CLI uses the same local API as the browser rather than calling backend services or SQLite directly.

**Why.** One service boundary keeps validation, approval, execution, and verification consistent across interfaces.

**Trade-off.** The backend must be running, and the CLI is limited to the local APEX instance. See [CLI](cli.md).

### Restrict launcher child environments

**Decision.** FastAPI receives the backend environment; the static server and browser receive a restricted environment.

**Why.** Those presentation processes do not need connector or provider credentials. Restricting inheritance reduces unnecessary credential exposure.

**Trade-off.** The launcher must maintain an allowlist of process-essential variables. See [Getting Started](getting-started.md) for the launch workflow.

### Separate liveness from readiness

**Decision.** Liveness checks that the process can answer. Readiness also checks required settings and SQLite, while optional connector and model availability have their own status surfaces.

**Why.** Broken required local state should prevent normal startup, but an optional provider outage should not make the whole application unavailable.

**Trade-off.** A ready backend does not mean every capability is ready. Clients must inspect operation-specific availability. See [Service and configuration](api.md#service-and-configuration).

### Keep assistant-ui behind an APEX adapter

**Decision.** Cortex uses assistant-ui for browser thread state and low-level interface primitives through an APEX-owned adapter. APEX retains conversation persistence, execution, policy, tools, and actions.

**Why.** The interface library can supply editing and branch interactions without becoming a second durable conversation system.

**Trade-off.** The adapter must translate identifiers and history correctly, with focused coverage when the pinned dependency changes. See [Frontend state ownership](../frontend/README.md#state-ownership).

### Use llama.cpp over HTTP with stable model aliases

**Decision.** APEX talks to llama.cpp over HTTP and selects models through configured aliases rather than raw GGUF paths. The router can run externally or be supervised by APEX using a locally installed executable.

**Why.** Process isolation and independent upgrades are useful for experimentation. Aliases separate model selection from machine-specific files and give context presets a predictable configuration boundary.

**Trade-off.** Router presets and APEX model configuration must agree. APEX does not install llama.cpp or download its weights. Managed mode accepts loopback hosts and stops only processes APEX launched. See [External and managed router modes](configuration.md#external-and-managed-router-modes).

### Export optional traces instead of maintaining a tracing platform

**Decision.** Optional tracing uses OpenTelemetry GenAI attributes and standard OTLP HTTP export. APEX does not maintain a tracing interface or observability store.

**Why.** An external collector can support inspection and evaluation without adding another application subsystem. Explicit attributes record identifiers, usage, timings, and status while omitting prompt, answer, and tool-result content.

**Trade-off.** Inspection requires an external collector with its own access and retention policies. Exceptions escaping tracing contexts can include messages and stack traces, so exports have no zero-content guarantee. Disabled tracing does not initialize an exporter. See [Tracing configuration](configuration.md#opentelemetry-genai-tracing) and [Tracing privacy](privacy.md#distributed-tracing).

## Earlier designs

These approaches are retired. Their reasoning is preserved here to explain the transitions, not to describe supported workflows.

### The blocking full-run pipeline

The original trigger kept collection and synthesis in one blocking request, with separate progress polling. A single result and error contract was simpler than coordinating asynchronous work. Later, operations gained independent APIs while the full trigger remained available, increasing the number of paths to maintain.

The v2.0.0-beta.6 saved-session engine retired the full trigger and its pipeline status routes. The current decisions are [independent operation lifecycles](#give-operations-independent-lifecycles) and [saved briefing artifacts](#save-a-canonical-briefing-artifact-with-its-evidence).

### Global speaker state and pipeline cleanup

The earlier pipeline read speaking state from the backend and reset global pipeline state after playback. This avoided assuming that a browser timer or an HTTP response meant speech had finished, but coupled delivery to full-run cleanup.

Session-scoped speech retired that reset path. [Backend-owned speech preparation and playback](#derive-speech-separately-and-reuse-prepared-audio) retains the state-ownership principle.

### Legacy cooldown timestamp reads

Earlier cooldown handling interpreted timezone-naive values in the legacy `runs` table as local wall-clock time while writing new values in UTC. This avoided rewriting old records solely to normalize a text field, at the cost of a compatibility parser.

Stable persistence cleanup retired that cooldown reader and parser while leaving existing legacy rows untouched. [Timezone-aware UTC writes](#write-timezone-aware-utc-timestamps) remain the current choice.

### Earlier briefing modes and deterministic fallback

Flash, Focused, and Structured combined execution choices with different synthesis paths. Their typed `BriefingFacts` projections kept model input separate from display prose, and Structured supplied deterministic output when model paths failed. This favored availability but required separate mode, projection, and fallback behavior.

v2.0.0-beta.6 replaced those paths with Daily, Catch Up, and Deep profiles using an explicit model selection. The [canonical artifact and evidence](#save-a-canonical-briefing-artifact-with-its-evidence) retain the separation between evidence and presentation; [profiles separate from model selection](#separate-briefing-profiles-from-model-selection) replace silent synthesis fallback.

During that cutover, the retired `briefings` table was transactionally dropped without migrating its rows into session history; `briefing_sessions` and unrelated records were preserved. Current initialization leaves any residual retired table untouched. See [Persistence compatibility](architecture.md#persistence-compatibility).

### Earlier speech-engine measurements

The original decision log recorded time before speech on an Intel Lunar Lake development machine: over 40 seconds for Kokoro CPU ONNX on a 420-character briefing, about 16 seconds for Piper, under three seconds for Google, and immediate pyttsx3 delivery. These were observations from that setup, not reproducible benchmarks or guarantees for current versions.

They motivated removing Piper and keeping Kokoro optional. [Load Kokoro only when selected](#load-kokoro-only-when-selected) retains that resource choice; [local speech fallback](#keep-speech-fallback-local) records the current delivery boundary.
