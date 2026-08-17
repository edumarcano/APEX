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

APEX has two main workspaces: Home, which shows telemetry and briefings, and Cortex, which is the workspace for interacting directly with Apex Panthera and Apex Felis. Telemetry means structured status collected from connected services; a briefing summarizes that status; and an Agent query is a request sent to the selected Agent.

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

### Produces briefings on user-defined terms

A briefing can use Panthera, Felis, or Structured Digest, a deterministic briefing that does not use a model. Panthera falls back to Felis and then Structured Digest; an explicit Felis request falls directly to Structured Digest. All routes receive the same selected, size-limited facts, and a provider failure ends in a useful model-free result instead of a blank screen.

### Operates Apex Agents

Agent queries can use approved read tools for live data, briefing history, Gmail, Microsoft To Do, and optional MCP (Model Context Protocol) providers. Reads run directly. Supported native writes create action proposals that require local approval and verification before they are considered complete.

After a Microsoft To Do list is selected, its incomplete tasks become the Home reminder source. SQLite keeps a small cache for stale display and an offline queue for local reminders that still need to sync. The Home Reminders panel can edit, complete, delete, reopen, and review completed tasks directly without adding the Agent approval step. Panthera and Felis use the same Tools selector, while each Agent's tool policy and MCP permissions remain separate.

<p align="center">
  <img
  src="docs/assets/apex-cortex.png"
  alt="APEX Cortex workspace showing an Agent response, tool trace, structured reminder results, reasoning selection, and context controls"
  width="900"
>
</p>

<p align="center">
  <em>The Cortex workspace using an Apex Agent to query approved reminder data and return a structured result.</em>
</p>

### Keeps runtime control visible

The HUD exposes connector health, CPU and memory use, active model state, briefing mode, voice delivery, preflight warnings, and machine-local settings. Activation, telemetry refresh, briefing generation, Agent requests, and speech are separate operations rather than one mandatory pipeline.

## Engineering highlights

- **Local-first:** FastAPI, the React HUD, SQLite, runtime settings, and the default Ollama endpoint stay on the machine and bind to loopback.
- **Independent features:** Telemetry, briefing generation, Agent work, and voice delivery can fail independently instead of taking the whole HUD down.
- **Safer model input:** Connectors produce structured results, and briefing models receive only selected facts marked as untrusted data.
- **Cloud, local, and model-free briefings:** APEX can use Panthera, Felis, or Structured Digest and always keeps Structured Digest as the final fallback.
- **One local model at a time:** APEX avoids hidden local-inference queues and keeps model loading visible.
- **Local storage:** SQLite keeps briefing history, the reminder cache and offline queue, and the durable action ledger. Browser-held Agent conversations disappear on reload.
- **Visible failures:** Readiness checks, connector health, stable errors, run IDs, and preflight warnings make degraded states easier to understand.
- **Credential isolation:** The backend receives credentials; the static server and browser receive a restricted child environment.

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
    B --> M["Panthera/OpenAI · Felis/llama.cpp · Structured Digest"]
    A --> P["Native and approved MCP capabilities"]
    API --> DB["SQLite"]
```

The browser owns the interactive session. FastAPI owns connector access, runtime coordination, model and tool execution, speech, and persistence. See the [architecture reference](docs/architecture.md) for the full system model and failure behavior.

## Technology

| Layer | Current stack |
|---|---|
| Backend | Python 3.14, FastAPI, Pydantic, uvicorn |
| Frontend | React 19, TypeScript 6, Vite 8, Tailwind CSS 4 |
| Persistence | SQLite |
| Cloud reasoning | Panthera through OpenAI, Google, or SpaceXAI; see Configuration for current model IDs |
| Local Agent infrastructure | Felis through Ollama development models or llama.cpp with Gemma and Qwen options |
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

## Use APEX without the HUD

When the backend is already running, the included CLI can inspect APEX, run one Agent turn, generate a briefing, and review or resolve durable actions:

```powershell
uv run apex status
uv run apex agents
uv run apex ask "What needs my attention?" --profile core_apex
uv run apex briefing --mode structured_digest
uv run apex actions list
```

The CLI talks only to APEX's loopback API at `127.0.0.1:8000`; it does not start the backend or provide remote access. See the [CLI reference](docs/cli.md) for the full command list and action behavior.

## Local trust boundary

APEX is local-first, not fully offline. Enabled connectors and selected cloud model or speech providers receive the data required for their operation. The API has no authentication and intentionally binds only to `127.0.0.1`; CORS is not an access-control boundary.

Use Felis or Structured Digest to avoid sending briefing data to a cloud model provider. Review [Privacy and Data Boundaries](docs/privacy.md) before enabling personal connectors or cloud processing.

## Documentation

| Document | Its one job |
|---|---|
| [Getting Started](docs/getting-started.md) | Install APEX, run a safe demo, launch the full system, and resolve common startup problems |
| [Configuration](docs/configuration.md) | Configure modes, settings, credentials, connectors, models, speech, and MCP providers |
| [Architecture](docs/architecture.md) | Understand processes, runtime paths, state ownership, data boundaries, concurrency, and failure behavior |
| [API](docs/api.md) | Use the public HTTP workflows and understand their behavioral contracts |
| [CLI](docs/cli.md) | Use the running local backend from a terminal without duplicating backend logic |
| [Engineering Decisions](docs/decisions.md) | Understand why important technical choices and trade-offs were made |
| [Identity and Naming](docs/identity-and-naming.md) | Understand the APEX name, logo symbolism, product vocabulary, and Apex Agent names |
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

APEX is a personal project. Local constraints, privacy boundaries, failure behavior, and the HUD's visual language are part of how I want the system to work, not afterthoughts.

## License

APEX is licensed under the [MIT License](LICENSE). Third-party software notices are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
