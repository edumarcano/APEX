# APEX: Automated Personal Environment Xylem

<p align="center">
  <img
    src="docs/assets/apex-logo.png"
    alt="The APEX logo"
    width="180"
  >
</p>

APEX started as a small, fun experiment: could I build something that gave me a spoken daily briefing with a little of the Jarvis feeling from *Iron Man*? As it grew, it became a playground for a new interest in AI tools and software development, a place to experiment, learn, and find out what I could actually build.

Today, it is a local-first operational HUD that brings weather, schedules, reminders, news, markets, system health, and Apex Agent work into one deliberate workspace. It turns those signals into Home telemetry, concise briefings, and Agent queries while keeping the local machine, not a hosted account, at the center of the system.

APEX has two main workspaces: Home, which shows telemetry and briefings, and Cortex, which lets you work with configured Apex Agents. Telemetry means structured status collected from connected services; a briefing summarizes that status; and an Agent query is a request sent to one of the configured Agents.

<p align="center">
  <img
  src="docs/assets/apex-home.png"
  alt="APEX Home workspace delivering a briefing with static, non-personal demo telemetry"
  width="900"
>
</p>

<p align="center">
  <em>The Home workspace delivering a briefing with static, non-personal demo telemetry.</em>
</p>

## What APEX does

### Builds a live Home workspace

APEX collects enabled weather, calendar, inbox, news, sports, reminder, and market signals into typed telemetry. Each connector reports its own freshness and health, so missing data is visible rather than hidden inside generated prose.

### Produces briefings on my terms

A briefing can use a cloud Agent, a local Agent, or Structured Digest, a deterministic briefing that does not use a model. The cloud Agent falls back to the local Agent and then Structured Digest; an explicit local Agent request falls directly to Structured Digest. All routes receive the same sanitized, size-bounded facts, and a provider failure ends in a useful model-free result instead of a blank screen.

### Operates Apex Agents

Agent queries can use approved read capabilities for live data, briefing history, Gmail, Microsoft To Do, and optional MCP (Model Context Protocol) providers. Bounded Microsoft To Do create, update, completion, reopening, and deletion actions can be proposed, but each executes only after local operator approval and independent verification. Cloud and local Agents share one provider-neutral capability layer and one Tools selector; the selected names narrow Agent policy without changing MCP authorization.

<p align="center">
  <img
  src="docs/assets/apex-cortex.png"
  alt="APEX Cortex workspace showing an Agent response, tool trace, structured reminder results, effort selection, and context controls"
  width="900"
>
</p>

<p align="center">
  <em>The Cortex workspace using an Apex Agent to query approved reminder data and return a structured result.</em>
</p>

### Keeps runtime control visible

The HUD exposes connector health, CPU and memory use, active model state, briefing mode, voice delivery, preflight warnings, and machine-local settings. Activation, telemetry refresh, briefing synthesis, interactive Agent requests, and speech are independent operations rather than one mandatory pipeline.

## Engineering highlights

- **Local-first boundary** — FastAPI, the React HUD, SQLite, runtime settings, and the default Ollama endpoint stay on the machine and bind to loopback.
- **Independent runtime paths** — telemetry, briefing generation, Agent work, and voice delivery can succeed or fail without taking the entire HUD down.
- **Typed trust boundary** — connectors produce structured results; models receive only selected, sanitized facts marked as untrusted data.
- **Cloud, local, and deterministic execution** — cloud and local Agents support different execution paths, while Structured Digest provides the final model-free briefing fallback.
- **Explicit concurrency controls** — briefing execution, local inference, speech, settings writes, and telemetry refreshes use bounded ownership rather than silent queues.
- **Durable personal state** — SQLite persists reminders and the last 50 normal-mode briefings, while browser-held Agent conversations disappear on reload.
- **Inspectable failure behavior** — readiness probes, connector health, stable error categories, run IDs, and advisory preflight keep degraded states understandable.
- **Privacy-aware process isolation** — the backend receives credentials; the static server and browser receive a restricted child environment.

## Architecture at a glance

```mermaid
flowchart LR
    L["launcher.py"] --> API["FastAPI · 127.0.0.1:8000"]
    L --> HUD["React HUD · 127.0.0.1:5500"]
    HUD --> T["Telemetry snapshots"]
    HUD --> B["Briefing synthesis"]
    HUD --> A["Agent queries"]
    HUD --> V["Voice delivery"]
    T --> C["Local and external connectors"]
    B --> M["Cloud Agent/OpenAI · Local Agent/llama.cpp · Structured Digest"]
    A --> P["Native and approved MCP capabilities"]
    API --> DB["SQLite"]
```

The browser owns the interactive session. FastAPI owns connector access, runtime coordination, model/provider boundaries, speech, and persistence. See the [architecture reference](docs/architecture.md) for the state owners, request flows, and failure model.

## Technology

| Layer | Current stack |
|---|---|
| Backend | Python 3.14, FastAPI, Pydantic, uvicorn |
| Frontend | React 19, TypeScript 6, Vite 8, Tailwind CSS 4 |
| Persistence | SQLite |
| Cloud reasoning | OpenAI, Google, and SpaceXAI Apex Agents; see Configuration for current model IDs |
| Local Agent infrastructure | Ollama with Qwen3 development Agents; llama.cpp with the Apodemus stable local Agent and Neotoma preview local Agent |
| Voice | Google Cloud TTS, pyttsx3, optional Kokoro ONNX |
| Tool integrations | Native connectors plus allowlisted MCP clients |
| Validation | unittest, Vitest, ESLint, TypeScript, Vite build |

## Try it safely

The quickest evaluation path uses static demo data and needs no external credentials:

```powershell
copy .env.example .env
# Set DEMO_MODE=true in .env

uv sync --locked
cd frontend
npm ci
npm run build
cd ..
uv run python launcher.py
```

Demo mode bypasses live connectors and model calls, does not write briefing history, and uses the configured demo voice path. For the complete Windows setup, optional providers, manual launch commands, and troubleshooting, see [Getting Started](docs/getting-started.md).

## Local trust boundary

APEX is local-first, not fully offline. Enabled connectors and selected cloud model or speech providers receive the data required for their operation. The API has no authentication and intentionally binds only to `127.0.0.1`; CORS is not an access-control boundary.

Use a local Agent or Structured Digest to avoid sending briefing data to a cloud provider. Review [Privacy and Data Boundaries](docs/privacy.md) before enabling personal connectors or cloud processing.

## Documentation

| Document | Its one job |
|---|---|
| [Getting Started](docs/getting-started.md) | Install APEX, run a safe demo, launch the full system, and resolve common startup problems |
| [Configuration](docs/configuration.md) | Configure modes, settings, credentials, connectors, models, speech, and MCP providers |
| [Architecture](docs/architecture.md) | Understand processes, runtime paths, state ownership, data boundaries, concurrency, and failure behavior |
| [API](docs/api.md) | Use the public HTTP workflows and understand their behavioral contracts |
| [Engineering Decisions](docs/decisions.md) | Understand why important technical choices and trade-offs were made |
| [Identity and Naming](docs/identity-and-naming.md) | Understand the APEX name, logo symbolism, product vocabulary, and Apex Agent taxonomy |
| [Privacy](docs/privacy.md) | See what stays local, what can leave the machine, and what is persisted |
| [Design System](docs/design-system.md) | Preserve the HUD's visual language, state semantics, responsiveness, and accessibility |
| [Roadmap](docs/roadmap.md) | Follow APEX's product and architectural evolution and its planned direction |
| [Changelog](CHANGELOG.md) | Review the detailed record of released changes |
| [Frontend Guide](frontend/README.md) | Work specifically in the React/TypeScript application |
| [Local Model Benchmarking](benchmarks/README.md) | Compare local Agents and one-off llama.cpp candidates with the developer benchmark utility |

Run the documentation consistency check after editing public docs:

```powershell
uv run python scripts/check_docs.py
```

APEX is a personal project, but the engineering is intentionally explicit: local constraints, privacy boundaries, failure modes, and visual behavior are part of the product rather than afterthoughts.
