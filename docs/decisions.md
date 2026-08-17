# Engineering Decisions

This is the reasoning record behind APEX. The architecture reference explains how the current system works; this document explains why its boundaries were drawn and which trade-offs were accepted for a single-user, local-first project.

Each entry leads with the decision, then the motivation and consequence. These are current decisions unless an entry explicitly describes historical hardware work or a compatibility path.

## Configuration

### Separate secrets from user preferences

**Decision.** Credentials, tokens, private keys, and environment-only modes belong in `.env`. Committed non-secret defaults belong in `config.json`, while machine-local runtime settings can live in gitignored `config.local.json`.

**Why.** Secrets should stay outside normal configuration files. Non-secret settings should live where APEX can validate and manage them. Things like the llama.cpp executable path or preset location do not need to be environment variables as long as they are untracked.

**Trade-off.** Each setting needs a clear owner across multiple storage locations.

### Use `config.local.json` as a mutable overlay

**Decision.** Runtime Settings writes only to gitignored `config.local.json`, which overlays `config.json`.

**Why.** Normal preferences should be changeable from the HUD without touching tracked defaults or restarting the process.

**Trade-off.** Invalid editable runtime settings reject the local layer as a unit, except MCP configuration: malformed optional MCP fields or providers fail closed independently so one broken integration cannot invalidate unrelated preferences. Successful settings writes use transactional replacement before the new snapshot is published.

## Backend and API

### Use SQLite for local durable state

**Decision.** SQLite stores APEX's local durable state, including run history, briefing history, the reminder cache and outbox, and the action ledger. Microsoft To Do remains authoritative for synced reminders.

**Why.** This data needs identity, ordering, transactions, or reliable recovery that would be awkward to maintain in JSON or flat files. SQLite provides those properties without adding another service.

**Trade-off.** The database is not encrypted by APEX and requires schema compatibility and transaction discipline.

### Keep full trigger execution synchronous

**Decision.** `POST /api/v1/trigger` remains one blocking full-run request while status observation uses a separate polling endpoint.

**Why.** One request owns the result and error contract, while polling can animate progress without streaming partial state. For a single-user HUD, this is simpler than a job queue or websocket protocol.

**Trade-off.** The HTTP request stays open through collection and synthesis. The independent snapshot and briefing endpoints are preferable when the caller does not need the whole orchestration path.

### Separate runtime paths without removing the full pipeline

**Decision.** Activation, telemetry collection, briefing generation, Agent requests, and voice delivery have separate APIs and frontend owners. The full trigger remains supported.

**Why.** APEX became less useful when one environmental or provider failure blocked every capability. Telemetry inspection, agent queries, briefing regeneration, and speech replay should each work independently.

**Trade-off.** More API and frontend paths to maintain. The older full trigger also remains supported, so the documentation has to make clear which paths are the normal ones.

### Keep telemetry snapshots process-local

**Decision.** The current typed telemetry snapshot lives in memory and is identified by an opaque `snapshot_id`.

**Why.** Snapshot state is temporary and tied to refreshes. Persisting every connector observation would add migrations, cleanup, and stale-record ambiguity without improving anything in a single-process session.

**Trade-off.** Restarting FastAPI invalidates the snapshot, so snapshot-based briefing generation must reject missing or stale identifiers and require a refresh.

### Make operational preflight advisory before it is blocking

**Decision.** Network policy, power state, refresh frequency, and elevated resource use normally produce warnings. Hard blockers are reserved for conditions that prevent the selected operation.

**Why.** A Wi-Fi name or battery state is useful context, not authorization. The original hard gate made APEX unavailable whenever the environment differed from expectations, which was too aggressive for a personal local tool.

**Trade-off.** The user makes the final call on advisory risk. Missing credentials, unavailable models, inference contention, failed resource gates, invalid input, and broken local configuration or database state remain non-overridable.

### Source speaker state and reset the pipeline from the backend

**Decision.** The HUD reads speaking state from the API instead of inferring completion from a frontend timer, and `_speak_and_cleanup` owns the final pipeline reset after audio playback.

**Why.** Voice duration varies by engine, fallback, text length, and machine, so the subsystem performing playback is the only reliable owner. Returning the briefing response before speech ends keeps the HUD responsive, but clearing state at response time would incorrectly report standby during delivery.

**Trade-off.** Status polling continues while audio plays, and a background worker thread must preserve run context and guarantee cleanup after success or failure.

### Isolate launcher child environments

**Decision.** FastAPI receives the backend environment; the static server and browser receive a restricted environment.

**Why.** Only the API owns connectors and providers. Passing API keys to processes that do not need them increases exposure without adding capability.

**Trade-off.** The launcher maintains an explicit allowlist of process-essential variables.

### Separate liveness and readiness

**Decision.** Liveness proves the process can answer; readiness also checks runtime settings and SQLite.

**Why.** The launcher should stop on broken required local state, but optional connector or model outages should not bring down the whole HUD.

**Trade-off.** Provider health appears in its own runtime surface rather than readiness.

### Write UTC while preserving legacy timestamp reads

**Decision.** New timestamps are timezone-aware UTC. Legacy timezone-naive run values are interpreted as local wall-clock time.

**Why.** UTC removes ambiguity for new records, and a destructive migration would add risk solely to normalize a SQLite text field.

**Trade-off.** Timestamp parsing permanently carries a compatibility branch.

### Use Microsoft To Do as the main reminder source

**Decision.** One selected Microsoft To Do list is the main source for APEX reminders. SQLite keeps a local copy of active reminders and stores pending local changes that still need to be synced.

**Why.** Microsoft To Do keeps reminders in sync across devices without APEX needing its own mobile app. Keeping a local copy in SQLite preserves local-first behavior, so reminders can still be shown and created when To Do or the network is unavailable.

**Trade-off.** The local copy can go stale while offline, and locally created reminders may need to be synced later. APEX has to keep the Microsoft list and its local state clearly separated instead of treating both as equal sources of truth.

### Keep the CLI as a client of the APEX API

**Decision.** The APEX CLI talks to the same local API as the HUD instead of calling backend services or the database directly.

**Why.** This keeps one path for Agent requests, briefings, reminders, actions, approval, and verification. The HUD and CLI follow the same rules instead of slowly developing different behavior.

**Trade-off.** The APEX backend has to be running before the CLI can be used, and the CLI is intentionally limited to the local APEX instance.

## AI and speech

### Synthesize from typed facts instead of display prose

**Decision.** Connectors turn their data into typed results, and briefing models receive a bounded `SynthesisInput` marked as untrusted data.

**Why.** Display text mixes presentation, health state, and third-party content. A separate schema makes it clear which facts can be sent to a briefing model and keeps third-party text inside an explicit untrusted-data boundary.

**Trade-off.** Every new fact that should reach synthesis has to be added deliberately. That extra work is preferable to silently sending more data to a model.

### Keep deterministic synthesis as the final fallback

**Decision.** Every briefing mode ends in Structured Digest when its selected model path cannot produce valid output.

**Why.** A personal briefing should remain useful when credentials, networks, providers, local models, or the generated format fail.

**Trade-off.** Deterministic prose is less flexible, but its behavior is predictable and limited to known facts.

### Share one local runtime lifecycle across briefings and Agent turns

**Decision.** Local briefings and Agent requests share the same model loading, resource checks, execution slot, model switching, and idle unload across Ollama and llama.cpp.

**Why.** Both workloads compete for the same CPU, RAM, and one resident-model budget. Separate managers would still fight over the same hardware while making that contention harder to observe and control.

**Trade-off.** One local operation can reject another rather than queue behind it. Briefing prompts and Agent context remain separate even though they share model lifecycle management.

### Expose explicit briefing modes

**Decision.** The HUD offers Panthera, Felis, and Structured Digest rather than choosing automatically.

**Why.** Cloud disclosure, local resource use, latency, and model-free output are meaningful personal choices. The selected mode should make that choice visible before execution.

**Trade-off.** More modes mean more availability, fallback, configuration, and UI coverage to maintain.

### Use layered text-to-speech fallback

**Decision.** Google Cloud TTS falls back to pyttsx3. Kokoro also falls back to pyttsx3, but never to Google, so a local speech request does not silently become a cloud request.

**Why.** Speech should stay available when the selected engine fails while preserving the privacy choice between local and cloud delivery.

**Trade-off.** Fallback can change voice quality, so the resolved engine needs to remain visible.

### Keep Kokoro hardware-conditional

**Decision.** Kokoro remains supported but is only loaded when selected. Piper was removed.

**Why.** On the Intel Lunar Lake development machine, CPU ONNX execution took over 40 seconds before speech for a 420-character briefing. Piper took about 16 seconds. Google delivered in under three seconds with no sustained local CPU load, while pyttsx3 began immediately.

Lazy Kokoro imports and warmup avoid idle memory and thread cost when it is not selected. Hardware with suitable ONNX acceleration can still opt in.

**Trade-off.** The default Google path requires network access and can disclose transcript text. pyttsx3 is lower quality but provides immediate offline delivery.

## Local inference

### Keep Panthera and Felis as the two Agent roles

**Decision.** APEX has two Apex Agents: Panthera for cloud work and Felis for local work. Models sit underneath those names, and the selected model determines the cloud provider or local runtime. The Agents do not have their own version numbers.

**Why.** The earlier Agent roster grew alongside the model list, which made model choices look like permanent product identities. The distinction that matters is simpler: Panthera is the cloud role and Felis is the local role.

**Trade-off.** The model catalog can grow without adding Agents, but model metadata, settings, and documentation still need to stay in sync.

### Separate development-only models from product Agents

**Decision.** Development-only models remain in the registered model catalog and appear in each Agent's `model_catalog` list only when `DEV_MODE` is active. They are not separate Apex Agents.

**Why.** There needs to be a safe place to try alternate cloud and local models without expanding the normal product roster.

**Trade-off.** Documentation and tests must distinguish Agent roles from replaceable model configuration.

### Keep Agent sessions stateless on the server

**Decision.** The browser sends bounded conversation history with every query; FastAPI stores no chat session.

**Why.** The browser tab already owns this single-user interaction. A server store would add expiry, cleanup, multi-tab conflicts, and another sensitive persistence surface.

**Trade-off.** Reloading loses the conversation, and each request resends retained history to the model.

### Enforce one resident model and non-blocking admission

**Decision.** APEX keeps one selected local model resident across Ollama and llama.cpp and rejects competing local execution rather than queueing it.

**Why.** Consumer hardware should stay responsive, and a hidden queue behind a slow generation gives poor feedback. CPU and RAM checks protect cold loads; a model that is already resident skips that check because loading it again would add no new footprint.

**Trade-off.** Rejected requests require a retry. Idle auto-unload returns memory without depending on manual cleanup.

### Talk to llama.cpp over HTTP with optional process supervision

**Decision.** APEX talks to llama.cpp over HTTP rather than embedding a Python binding. The router can be run externally, or APEX can start and stop a locally installed `llama-server` executable.

**Why.** Process isolation, independent upgrades, and the existing OpenAI-compatible tooling matter more than in-process convenience for a personal HUD. Managed mode removes a manual startup step without bundling binaries or model weights.

**Trade-off.** APEX never installs, bundles, or updates llama.cpp and never downloads model weights. Managed mode accepts only loopback hosts, stops only processes APEX launched, and does not expose local filesystem paths outside Runtime Settings.

### Use stable runtime aliases for llama.cpp models

**Decision.** Felis loads llama.cpp models through stable model-based aliases such as `gemma-4-e2b-16k` instead of exposing raw GGUF paths or an arbitrary context slider.

**Why.** A small set of tested context sizes keeps loading, memory checks, and documentation predictable while model paths remain behind stable aliases.

**Trade-off.** Adding a new context requires a router preset and matching model configuration. High-resource presets such as `gemma-4-e2b-132k` and `gemma-4-e4b-64k` are explicitly marked as such. A model can support a larger maximum context than APEX chooses to expose.

### Make local reasoning capability-driven and private

**Decision.** Felis reasoning preferences default to `none`. llama.cpp models that support reasoning expose `none` and `focused`; Ollama development models expose only `none`. For llama.cpp, `none` sends `reasoning_effort: "none"`, while `focused` lets the model use its native reasoning behavior. Hidden reasoning fields and think-style tags are removed before display.

**Why.** Local models do not all support the same reasoning controls as cloud models. The HUD only shows options the selected Felis model actually supports, and hidden reasoning stays out of the visible response.

**Trade-off.** Focused mode has no separate reasoning-token budget or telemetry in APEX. llama.cpp runtime data only gives conservative completion headroom, and model-specific sampling stays unchanged until benchmarks justify tuning it.

## Security

### Treat connector, HUD, and tool content as untrusted model data

**Decision.** Briefing facts, explicit HUD context, and tool results use separate untrusted-data markers with matching system instructions.

**Why.** Calendar titles, headlines, email content, tasks, and provider results are written outside APEX's control and can contain instruction-like text.

**Trade-off.** Prompt boundaries reduce risk but do not authorize actions. Supported native writes go through the action system, while MCP write and destructive capabilities remain unavailable.

### Prove the action flow with Microsoft To Do

**Decision.** Microsoft To Do changes go through APEX's action flow: propose the change, ask for approval when needed, execute it, verify the result, and record what happened. To Do is the first real use of this system and serves as a test case for future Cortex actions.

**Why.** Task changes are simple enough to test the full flow without much risk. The approval flow applies to Agent-requested changes, where APEX needs a clear boundary between a model suggestion and an external write. Direct reminder management in the Home workspace stays simpler and does not add approval steps just to edit a task. This gives APEX a place to work through approval, failed or uncertain writes, restart recovery, verification, and history before the same ideas are used for more important workflows.

**Trade-off.** This is more machinery than Microsoft To Do alone needs. For now, that extra complexity is intentional because the goal is to prove the action flow, not just build task editing.
