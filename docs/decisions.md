# Engineering Decisions

This is the reasoning record behind APEX. The architecture reference explains how the current system works; this document explains why I chose its boundaries and which trade-offs I accepted for a single-user, local-first project.

Each entry leads with the decision, then the motivation and consequence. These are current decisions unless an entry explicitly describes historical hardware work or a compatibility path.

## Configuration

### Separate secrets from operator preferences

**Decision.** Credentials, tokens, private keys, machine paths, and environment-only modes belong in `.env`. Committed non-secret defaults belong in `config.json`.

**Why.** The expected configuration shape should be visible and reviewable without risking secrets. Personal machine details should remain local.

**Trade-off.** APEX has more than one configuration surface, so ownership must remain explicit in [Configuration](configuration.md).

### Use `config.local.json` as a mutable overlay

**Decision.** Runtime Settings writes only to gitignored `config.local.json`, which overlays `config.json`.

**Why.** I want to change normal preferences from the HUD without modifying tracked defaults or restarting the process.

**Trade-off.** Invalid local configuration must fail as one layer rather than partially applying. The store validates the full overlay and publishes it only after a transactional file replacement succeeds.

## Backend and API

### Use SQLite instead of a flat file

**Decision.** Reminders, production runs, and briefing history use SQLite.

**Why.** The data has identity, ordering, lifecycle, and transactional requirements that outgrew ad hoc JSON or text files. SQLite keeps those properties local without adding a service.

**Trade-off.** The database is not encrypted by APEX and still requires schema compatibility and transaction discipline.

### Keep full trigger execution synchronous

**Decision.** `POST /api/v1/trigger` remains one blocking full-run request while status observation uses a separate polling endpoint.

**Why.** One request owns the result and error contract, while polling can animate progress without streaming partial response state. For a single-user HUD, this is simpler than a job queue or websocket protocol.

**Trade-off.** The HTTP request stays open through collection and synthesis. The independent snapshot and briefing endpoints are preferable when the caller does not need the whole orchestration path.

### Separate runtime paths without removing the full pipeline

**Decision.** Activation, telemetry collection, briefing synthesis, assistant access, and voice delivery have focused APIs and frontend owners. The full trigger remains supported.

**Why.** APEX became less useful when one environmental or provider failure blocked every capability. I want to inspect telemetry, ask a question, regenerate a briefing, or replay speech independently.

**Trade-off.** More explicit state owners and API workflows replace the simplicity of one global pipeline. The architecture reference must distinguish the primary independent model from compatibility orchestration.

### Keep telemetry snapshots process-local

**Decision.** The current typed telemetry snapshot lives in memory and is identified by an opaque `snapshot_id`.

**Why.** Snapshot state is ephemeral and refresh-oriented. Persisting every connector observation would add migrations, cleanup, and stale-record ambiguity without improving a single-process session.

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

## AI and speech

### Synthesize from typed facts instead of display prose

**Decision.** Connectors normalize into typed results, and briefing models receive a sanitized, bounded `SynthesisInput` marked as untrusted data.

**Why.** Raw display strings mix presentation, health state, and third-party content. An explicit schema creates a reviewable privacy and prompt-injection boundary shared by Gemini, Ollama, and deterministic output.

**Trade-off.** Every new synthesis-relevant fact requires deliberate schema work. That maintenance is preferable to silently expanding model disclosure.

### Keep deterministic synthesis as the final fallback

**Decision.** Every briefing mode terminates in Structured Digest when its selected model path cannot produce valid output.

**Why.** A personal briefing should remain useful when credentials, networks, providers, local models, or generated format fail.

**Trade-off.** Deterministic prose is less flexible, but its behavior is predictable and source-bounded.

### Share one Ollama lifecycle across briefings and assistant turns

**Decision.** Local briefing and assistant work share profile definitions, resource gates, the execution slot, model switching, and idle unload.

**Why.** Both workloads compete for the same CPU, RAM, and one resident-model budget. A second manager would hide rather than remove that contention.

**Trade-off.** One local operation can reject another instead of queuing. Prompts and context remain separate even though lifecycle ownership is shared.

### Expose explicit briefing modes

**Decision.** The HUD offers Panthera, Mus, Sorex, and Structured Digest rather than one opaque automatic selector.

**Why.** Cloud disclosure, local resource use, latency, and model-free determinism are meaningful personal choices. The selected mode should communicate them before execution.

**Trade-off.** More profiles require more availability, fallback, configuration, and UI coverage. Legacy `cloud`, `local`, and `raw` values remain compatibility aliases.

### Use layered text-to-speech fallback

**Decision.** Google Cloud TTS is the normal cloud engine, pyttsx3 is the terminal local fallback, and Kokoro is an optional local neural engine that can fall through to Google and pyttsx3.

**Why.** Briefing delivery should survive network, credential, provider, or local-engine failure.

**Trade-off.** Fallback can change voice quality and disclosure boundary. The resolved engine must remain visible.

### Keep Kokoro hardware-conditional

**Decision.** Kokoro remains supported but is only loaded when selected. Piper was removed.

**Why.** On the Intel Lunar Lake development machine, CPU ONNX execution caused severe oversubscription: more than 40 seconds before speech for a 420-character briefing. Piper took about 16 seconds. Google delivered in under three seconds with no sustained local CPU load, while pyttsx3 began immediately.

Lazy Kokoro imports and warmup avoid idle memory and thread cost on hardware where it is not selected. Hardware with appropriate ONNX acceleration can still opt in.

**Trade-off.** The default Google path requires network access and can disclose transcript text. pyttsx3 remains lower quality but provides immediate offline delivery.

## Local inference

### Use named profiles instead of raw model IDs in the HUD

**Decision.** Assistant controls expose the Apex Profiles 2.0 family: Acinonyx, Panthera, Neofelis, Delphinus, Orcinus, Sorex, and Mus.

**Why.** The names communicate the intended intelligence profile while provider model IDs remain separate implementation details that can be audited in configuration and architecture references. The shared 2.0 version identifies the reworked profile contract; later profile changes can version independently.

**Trade-off.** Profile documentation must remain synchronized with current model mappings and stability labels.

### Keep assistant sessions stateless on the server

**Decision.** The browser sends bounded conversation history with every query; FastAPI stores no chat session.

**Why.** The browser tab already owns this single-user interaction. A server store would add expiry, cleanup, multi-tab conflicts, and another sensitive persistence surface.

**Trade-off.** Reloading loses the conversation, and each request resends retained history to the selected model.

### Enforce one resident model and non-blocking admission

**Decision.** APEX keeps one selected Ollama model resident and rejects competing local execution rather than queueing it.

**Why.** Consumer hardware should remain responsive, and a hidden queue behind a slow generation gives poor feedback. Profile-specific CPU/RAM gates prevent unsafe cold loads; a model already resident skips the gate because reselection adds no new model footprint.

**Trade-off.** Users may need to retry a rejected request. Idle auto-unload returns memory without depending on manual cleanup.

## Security

### Treat connector, HUD, and tool content as untrusted model data

**Decision.** Briefing facts, explicit HUD context, and tool results use separate untrusted-data markers with matching system instructions.

**Why.** Calendar titles, headlines, email content, tasks, and provider results are written outside APEX's control and can contain instruction-like text.

**Trade-off.** Prompt boundaries reduce risk but do not create a security boundary. Models cannot authorize actions, and higher-impact capabilities would require independent approval controls.

## Development process

### Keep one instruction source and load procedures on demand

**Decision.** Repository-wide agreements live in `AGENTS.md`, scoped engineering guidance lives under `docs/agent-guidance/`, and reusable workflows live under `.agents/skills/`.

**Why.** The older duplicated persona rules mixed project standards with task ceremony and drifted between editor surfaces. I prefer one canonical rule set and task-specific procedures that load only when relevant.

**Trade-off.** The system has less persona flavor and less automatic ceremony, but its expectations are easier to inspect and update. Historical changelog entries describing the earlier rule layout remain accurate as release history.
