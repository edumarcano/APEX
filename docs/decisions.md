# Engineering Decisions

This is the reasoning record behind APEX. The architecture reference explains how the current system works; this document explains why I chose its boundaries and which trade-offs I accepted for a single-user, local-first project.

Each entry leads with the decision, then the motivation and consequence. These are current decisions unless an entry explicitly describes historical hardware work or a compatibility path.

## Configuration

### Separate secrets from operator preferences

**Decision.** Credentials, tokens, private keys, and environment-only modes belong in `.env`. Committed non-secret defaults belong in `config.json`, while personal or machine-local runtime settings can live in gitignored `config.local.json`.

**Why.** Secrets should stay outside normal configuration files, while non-secret settings should live where APEX can validate and manage them. Machine-local settings such as llama.cpp executable and preset paths do not need to be environment variables as long as they remain untracked.

**Trade-off.** Configuration has several storage locations, so each setting needs a clear owner.

### Use `config.local.json` as a mutable overlay

**Decision.** Runtime Settings writes only to gitignored `config.local.json`, which overlays `config.json`.

**Why.** I want to change normal preferences from the HUD without modifying tracked defaults or restarting the process.

**Trade-off.** Invalid editable runtime settings reject the local layer as a unit, except MCP configuration: malformed optional MCP fields or providers fail closed independently so one integration cannot invalidate unrelated local preferences. Successful settings writes still use transactional replacement before the new snapshot is published.

## Backend and API

### Use SQLite for local durable state

**Decision.** SQLite stores APEX's local durable state, including run history, briefing history, the reminder cache and outbox, and the action ledger. Microsoft To Do remains authoritative for synced reminders.

**Why.** This data needs identity, ordering, transactions, or reliable recovery that would be awkward to maintain in JSON or text files. SQLite provides those properties without adding another service.

**Trade-off.** The database is not encrypted by APEX and still requires schema compatibility and transaction discipline.

### Keep full trigger execution synchronous

**Decision.** `POST /api/v1/trigger` remains one blocking full-run request while status observation uses a separate polling endpoint.

**Why.** One request owns the result and error contract, while polling can animate progress without streaming partial response state. For a single-user HUD, this is simpler than a job queue or websocket protocol.

**Trade-off.** The HTTP request stays open through collection and synthesis. The independent snapshot and briefing endpoints are preferable when the caller does not need the whole orchestration path.

### Separate runtime paths without removing the full pipeline

**Decision.** Activation, telemetry collection, briefing generation, Agent requests, and voice delivery have separate APIs and frontend owners. The full trigger remains supported.

**Why.** APEX became less useful when one environmental or provider failure blocked every capability. I want to inspect telemetry, ask a question, regenerate a briefing, or replay speech independently.

**Trade-off.** APEX now has more API and frontend paths to maintain. The older full trigger also remains supported, so the documentation has to make clear which paths are the normal ones.

### Keep telemetry snapshots process-local

**Decision.** The current typed telemetry snapshot lives in memory and is identified by an opaque `snapshot_id`.

**Why.** Snapshot state is temporary and tied to refreshes. Persisting every connector observation would add migrations, cleanup, and stale-record ambiguity without improving a single-process session.

**Trade-off.** Restarting FastAPI invalidates the snapshot. Snapshot-based briefing generation must reject missing or stale identifiers and require a refresh.

### Make operational preflight advisory before it is blocking

**Decision.** Network policy, power state, refresh frequency, and elevated resource use normally produce warnings. Hard blockers are reserved for conditions that prevent the selected operation.

**Why.** A Wi-Fi name or battery state is useful context, not authorization. The original hard gate made a personal local tool unavailable when the environment differed from expectations.

**Trade-off.** The user must make the final decision on advisory risk. Missing credentials, unavailable models, inference contention, failed resource gates, invalid input, and broken local configuration or database state remain non-overridable.

### Source speaker state from the backend

**Decision.** The HUD reads speaking state from the API instead of inferring completion from a frontend timer.

**Why.** Voice duration varies by engine, fallback, text length, and machine. The subsystem performing playback is the only reliable owner.

**Trade-off.** Status polling continues while audio plays.

### Reset pipeline state after audio finishes

**Decision.** `_speak_and_cleanup` owns the final pipeline reset.

**Why.** Returning the briefing response before speech ends keeps the HUD responsive, but clearing state at response time would incorrectly report standby during delivery.

**Trade-off.** A worker thread must preserve run context and guarantee cleanup after success or failure.

### Isolate launcher child environments

**Decision.** FastAPI receives the backend environment; the static server and browser receive a restricted environment.

**Why.** Only the API owns connectors and providers. Passing API keys to processes that do not need them increases exposure without adding capability.

**Trade-off.** The launcher maintains an explicit allowlist of process-essential variables.

### Separate liveness and readiness

**Decision.** Liveness proves the process can answer; readiness also checks runtime settings and SQLite.

**Why.** The launcher should stop on broken required local state, but optional connector or model outages should not make the whole HUD unavailable.

**Trade-off.** Provider health appears in its own runtime surface rather than readiness.

### Write UTC while preserving legacy timestamp reads

**Decision.** New timestamps are timezone-aware UTC. Legacy timezone-naive run values are interpreted as local wall-clock time.

**Why.** UTC removes ambiguity for new records, while a destructive migration would add risk solely to normalize a SQLite text field.

**Trade-off.** Timestamp parsing permanently carries a compatibility branch.

### Keep `launch_apex.bat` as a hardware-trigger proxy

**Decision.** The Windows wrapper remains a single-action entry to `launcher.py`.

**Why.** APEX is meant to behave like a local appliance. The wrapper is a practical stand-in for a future physical trigger and makes failures visible in a retained terminal.

**Trade-off.** Shortcut setup must preserve the repository working directory.

### Use Microsoft To Do as the main reminder source

**Decision.** One selected Microsoft To Do list is the main source for APEX reminders. SQLite keeps a local copy of active reminders and stores pending local changes that still need to be synced.

**Why.** Microsoft To Do makes it easy to keep reminders in sync with my phone without APEX needing its own mobile app. Keeping a local copy in SQLite preserves APEX's local-first behavior, so reminders can still be shown and created when Microsoft To Do or the network is unavailable.

**Trade-off.** The local copy can become stale while offline, and locally created reminders may need to be synced later. APEX therefore has to keep the Microsoft list and its local state clearly separated instead of treating both as equal sources of truth.

### Keep the CLI as a client of the APEX API

**Decision.** The APEX CLI talks to the same local API as the HUD instead of calling backend services or the database directly.

**Why.** This keeps one path for Agent requests, briefings, reminders, actions, approval, and verification. The HUD and CLI therefore follow the same rules instead of slowly developing different behavior.

**Trade-off.** The APEX backend has to be running before the CLI can be used, and the CLI is intentionally limited to the local APEX instance.

## AI and speech

### Synthesize from typed facts instead of display prose

**Decision.** Connectors turn their data into typed results, and briefing models receive a bounded `SynthesisInput` marked as untrusted data.

**Why.** Display text mixes presentation, health state, and third-party content. Using a separate schema makes it clear which facts can be sent to a briefing model and keeps third-party text inside an explicit untrusted-data boundary.

**Trade-off.** Every new fact that should reach synthesis has to be added deliberately. That extra work is preferable to silently sending more data to a model.

### Keep deterministic synthesis as the final fallback

**Decision.** Every briefing mode ends in Structured Digest when its selected model path cannot produce valid output.

**Why.** A personal briefing should remain useful when credentials, networks, providers, local models, or generated format fail.

**Trade-off.** Deterministic prose is less flexible, but its behavior is predictable and limited to known facts.

### Share one local runtime lifecycle across briefings and Agent turns

**Decision.** Local briefings and Agent requests share the same model loading, resource checks, execution slot, model switching, and idle unload across Ollama and llama.cpp.

**Why.** Both workloads compete for the same CPU, RAM, and one resident-model budget. Separate managers would still compete for the same machine while making that contention harder to see and control.

**Trade-off.** One local operation can reject another instead of queuing. Briefing prompts and Agent context remain separate even though they share model lifecycle management.

### Expose explicit briefing modes

**Decision.** The HUD offers Panthera, Felis, and Structured Digest rather than choosing one automatically without showing the user.

**Why.** Cloud disclosure, local resource use, latency, and model-free output are meaningful personal choices. The selected mode should make that choice visible before execution.

**Trade-off.** More modes require more availability, fallback, configuration, and UI coverage. Legacy `cloud`, `local`, and `raw` values remain compatibility aliases.

### Use layered text-to-speech fallback

**Decision.** Google Cloud TTS falls back to pyttsx3. Kokoro also falls back to pyttsx3, but never to Google, so a local speech request does not silently become a cloud request.

**Why.** Speech should remain available when the selected engine fails while preserving the privacy choice between local and cloud speech.

**Trade-off.** Fallback can change voice quality. The resolved engine must remain visible.

### Keep Kokoro hardware-conditional

**Decision.** Kokoro remains supported but is only loaded when selected. Piper was removed.

**Why.** On the Intel Lunar Lake development machine, CPU ONNX execution took more than 40 seconds before speech for a 420-character briefing. Piper took about 16 seconds. Google delivered in under three seconds with no sustained local CPU load, while pyttsx3 began immediately.

Lazy Kokoro imports and warmup avoid idle memory and thread cost when it is not selected. Hardware with suitable ONNX acceleration can still opt in.

**Trade-off.** The default Google path requires network access and can disclose transcript text. pyttsx3 remains lower quality but provides immediate offline delivery.

## Local inference

### Consolidate the Agent family to Panthera and Felis

**Decision.** APEX exposes two Apex Agents: Panthera for cloud work and Felis for local work. Model, context, reasoning, effort, and hosted-tool settings live underneath those identities; each model profile determines its provider or local runtime.

**Why.** The earlier genus-based roster made every model/provider combination look like a separate product Agent. That was useful for experimentation, but the normal UI became broader than the roles APEX actually distinguishes today: cloud versus local.

**Trade-off.** Former Agent keys remain as migration and development-only model entries. Documentation, settings migration, and benchmarks must treat models as configuration rather than separate Apex Agents.

### Use named Agents instead of raw model IDs in the HUD

**Decision.** Cortex exposes Panthera and Felis rather than raw provider model IDs. Each Agent card shows the selected model and exposes the registered model catalog underneath it.

**Why.** The names communicate the cloud/local split while provider model IDs remain implementation details. An Agent identity can survive a model change as long as its role still makes sense.

**Trade-off.** Agent documentation must remain synchronized with current default model mappings, stability labels, and development-only model visibility.

### Separate development-only models from product Agents

**Decision.** Development-only models remain in the registered model catalog and appear in each Agent's `model_catalog` list only when `DEV_MODE` is active. They are not separate Apex Agents.

**Why.** I still need safe places to try alternate cloud and local models without expanding the normal product roster again.

**Trade-off.** Documentation and tests must distinguish durable Agent identities from replaceable model configuration.

### Keep Agent sessions stateless on the server

**Decision.** The browser sends bounded conversation history with every query; FastAPI stores no chat session.

**Why.** The browser tab already owns this single-user interaction. A server store would add expiry, cleanup, multi-tab conflicts, and another sensitive persistence surface.

**Trade-off.** Reloading loses the conversation, and each request resends retained history to the selected model.

### Enforce one resident model and non-blocking admission

**Decision.** APEX keeps one selected local model resident across Ollama and llama.cpp and rejects competing local execution rather than queueing it.

**Why.** Consumer hardware should remain responsive, and a hidden queue behind a slow generation gives poor feedback. CPU and RAM checks protect cold loads; a model that is already resident skips that check because loading it again would add no new model footprint.

**Trade-off.** I may need to retry a rejected request. Idle auto-unload returns memory without depending on manual cleanup.

### Talk to llama.cpp over HTTP with optional process supervision

**Decision.** APEX talks to llama.cpp over HTTP rather than embedding a Python binding. I can run the router myself, or let APEX start and stop a locally installed `llama-server` executable.

**Why.** Process isolation, independent upgrades, and existing OpenAI-compatible tooling matter more than in-process convenience for a personal HUD. Managed mode removes a manual startup step without bundling binaries or model weights.

**Trade-off.** APEX never installs, bundles, or updates llama.cpp and never downloads model weights. Managed mode accepts only loopback hosts, stops only processes APEX launched, and does not expose local filesystem paths outside Runtime Settings.

### Use stable runtime aliases for llama.cpp models

**Decision.** Felis loads llama.cpp models through stable model-based aliases such as `gemma-4-e2b-16k` instead of exposing raw GGUF paths or an arbitrary context slider. Legacy Agent-based alias names still resolve for existing presets.

**Why.** I want a small set of tested context sizes so loading, memory checks, and documentation stay predictable while model paths remain behind stable aliases.

**Trade-off.** Adding a new context requires a router preset and settings migration work. High-resource presets such as `gemma-4-e2b-132k` and `gemma-4-e4b-64k` are explicitly marked as such. A model can support a larger maximum context than APEX chooses to expose.

### Make local reasoning capability-driven and private

**Decision.** Felis reasoning preferences default to `none`. llama.cpp models that support reasoning expose `none` and `focused`; Ollama development models expose only `none`. For llama.cpp, `none` sends `reasoning_effort: "none"`, while `focused` lets the model use its native reasoning behavior. Hidden reasoning fields and think-style tags are removed before display.

**Why.** Local models do not all support the same reasoning controls as cloud models. The HUD only shows reasoning options that the selected Felis model actually supports, and hidden reasoning stays out of the visible response.

**Trade-off.** Focused mode has no separate APEX reasoning-token budget or telemetry. llama.cpp runtime data only gives conservative completion headroom, and model-specific sampling stays unchanged until benchmarks justify tuning it.

### Keep Felis as an explicit briefing mode

**Decision.** Felis is an explicit briefing mode and Panthera's only local fallback before Structured Digest.

**Why.** Choosing Felis should mean using Felis, not silently replacing it with another local model. Cold loads use a 16K context, while an already loaded compatible llama.cpp alias can be reused.

**Trade-off.** If the configured local runtime is unavailable or blocked by resource checks, an explicit Felis request falls directly to Structured Digest.

## Security

### Treat connector, HUD, and tool content as untrusted model data

**Decision.** Briefing facts, explicit HUD context, and tool results use separate untrusted-data markers with matching system instructions.

**Why.** Calendar titles, headlines, email content, tasks, and provider results are written outside APEX's control and can contain instruction-like text.

**Trade-off.** Prompt boundaries reduce risk but do not authorize actions. Supported native writes go through the action system, while MCP write and destructive capabilities remain unavailable.

### Prove the action flow with Microsoft To Do

**Decision.** Microsoft To Do changes go through APEX's action flow: propose the change, ask for approval when needed, execute it, verify the result, and record what happened. To Do is the first real use of this system and serves as a test case for future Cortex actions.

**Why.** Task changes are simple enough to test the full flow without much risk. The approval flow applies to Agent-requested changes, where APEX needs a clear boundary between a model suggestion and an external write. Direct reminder management in the Home workspace stays simpler and does not add approval steps just to edit a task. This gives APEX a place to work through approval, failed or uncertain writes, restart recovery, verification, and history before the same ideas are used for more important workflows.

**Trade-off.** This is more machinery than Microsoft To Do alone needs. For now, that extra complexity is intentional because the goal is to prove the action flow, not just build task editing.

## Development process

### Keep one instruction source and load procedures on demand

**Decision.** Repository-wide agreements live in `AGENTS.md`, scoped engineering guidance lives under `docs/agent-guidance/`, and reusable workflows live under `.agents/skills/`.

**Why.** The older setup repeated persona and workflow rules in several places, which made them easier to drift. I prefer one main rule set with extra guidance and procedures loaded only when they are relevant.

**Trade-off.** The system has less persona flavor and less automatic ceremony, but its expectations are easier to inspect and update. Historical changelog entries describing the earlier rule layout remain accurate as release history.
