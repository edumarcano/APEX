# Configuration

Use Runtime Settings for everyday preferences and `.env` for credentials and environment-specific setup. This reference explains where settings live, how models and connectors are configured, and which limits apply. For a first run, start with [Getting Started](getting-started.md).

## Where settings live

| Location | Purpose |
|---|---|
| Resource `config.json` | Bundled or tracked defaults, Agent prompts, and file-only execution settings |
| Selected data directory `config.json` | Optional operator configuration, read when separate from resource defaults; defaults to the checkout in source runs or `%LOCALAPPDATA%\APEX` when frozen |
| Selected data directory `config.local.json` | Runtime Settings overrides, including local model paths and report-folder preferences |
| Selected data directory `.env` or process environment | Credentials, development/demo switches, and paths such as the Context vault destination |

The selected data directory is the checkout in source runs. Set `APEX_DATA_DIR` in the process environment before starting APEX to keep data elsewhere; the value must be absolute, and a relative nonempty value stops startup. A frozen Windows app defaults to `%LOCALAPPDATA%\APEX` and rejects a data directory inside the resources or executable installation directory. The selector is read before `.env` is loaded, so `.env` cannot change the active profile. Path selection does not copy or migrate existing data. Microsoft To Do's configured encrypted token-cache path, the Context vault destination, managed model executable and preset paths, and the external activity report folder remain operator-selected destinations.

Configuration layers apply in this order: resource `config.json`, data `config.json` when it is a different file, then data `config.local.json`. Later values override earlier values recursively. Missing optional files are skipped; unreadable or malformed optional files are ignored with a warning. Runtime Settings validates its editable values and writes only to `config.local.json`; an invalid local editable layer is discarded in favor of lower layers. File-only settings such as run limits and Ollama configuration remain read from the JSON layers.

APEX loads only the selected data directory's `.env`. Existing process environment values take precedence, including during variable interpolation. `PYTHON_DOTENV_DISABLED` disables `.env` loading. Restart after editing configuration files or `.env` directly.

### Browser and desktop shell origins

The loopback API allows the local web HUD origins by default and also allows `http://tauri.localhost`, the Windows desktop shell's webview origin. If `APEX_ALLOWED_ORIGINS` is set, its comma-separated list replaces all defaults. Include every origin the HUD should use, including `http://tauri.localhost` when the desktop shell needs access. An override that omits it will cause the shell's browser requests to be rejected by CORS. CORS does not authenticate callers or make a non-loopback API binding safe.

For example, this override keeps the default development origins and adds another local web HUD origin:

```dotenv
APEX_ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5173,http://localhost:5173,http://tauri.localhost,http://localhost:6000
```

The main writable paths follow the selected data directory:

| Data | Path |
|---|---|
| SQLite database | `apex_memory.db` |
| Backend ownership marker | `.apex-host.lock` (OS lock; marker retained after release) |
| Google OAuth files | `credentials.json` and `token.json` |
| Connector caches | `clients/.market_cache.json`, `clients/.f1_cache.json`, and `clients/.football_cache.json` |
| FastEmbed cache | `weights/fastembed/` |
| Kokoro weights | `core/weights/kokoro/` |

Documentation and demo fixtures remain under the resource directory, including `docs/` and `core/mock/`.

The retired `features.news` setting in an older `config.json` or `config.local.json` is ignored. It does not prevent other saved preferences from loading or being updated.

Runtime Settings changes apply in the running process. Keep credentials out of both JSON files, and keep machine-specific paths and model weights out of source control.

## Runtime Settings

Briefing and Cortex use the same APEX Agent model selection. The following `ask_apex` section shows the tracked model defaults:

```json
{
  "enabled": true,
  "selected_model": "z-ai/glm-5.3-flash",
  "sandbox_mode": false,
  "cloud": { "last_model": "z-ai/glm-5.3-flash", "effort": "low" },
  "local": { "last_model": "gemma-4-E2B-Q4_K_M.gguf", "context_window": 16384, "reasoning_mode": "none" }
}
```

The default model mapping is `apex` -> `z-ai/glm-5.3-flash`; `selected_model` chooses the model for new requests. Selecting a cloud or local model remembers that choice and its controls in the matching runtime section. Cloud and local personal-context preferences are independent. `tool_profiles.default_profile_by_runtime` selects the default tool profile for cloud and local requests. Fresh defaults are All APEX Tools for cloud and No APEX Tools for local; a per-turn model override uses its own runtime's default without changing saved settings.

Optional `user_designation` and `agent_display_name` are machine-local personalization fields stored only in `config.local.json`. An empty `agent_display_name` keeps the default visible name Lynx.

Overview collects telemetry without running a model. Briefing follow-ups use the selected model and its saved reasoning and context controls. Per-turn overrides do not change saved preferences.

## Models and credentials

The default model is OpenRouter GLM 5.3 Flash with Low reasoning. Configure the credential for the provider of the model you select:

| Provider | Environment variable |
|---|---|
| OpenRouter | `OPENROUTER_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |

Local models use Ollama or llama.cpp. Cortex reports availability for each model. APEX does not install these runtimes or download model weights.

Ollama model options are available only in `DEV_MODE`. Install and start Ollama, then pull the tags you want to use:

```powershell
ollama pull qwen3:1.7b
ollama pull qwen3:4b-instruct
```

Ollama host, idle-unload, and resource-gate settings live under `ollama` in `config.json`. For llama.cpp, see [External and managed router modes](#external-and-managed-router-modes).

Only one local generation may run at a time. APEX checks runtime reachability, installed models, resource gates, and residency before a cold load. The provider-neutral unload control releases the current local model.

## External and managed router modes

Copy the [llama.cpp preset example](examples/llama-cpp-apex-local-models.preset.ini) to a machine-local path and replace its GGUF placeholders. Keep the edited preset and weights untracked. Each alias exposes a model at a particular context size; use the aliases expected by APEX.

In **external mode**, start the router yourself. For example, from PowerShell, with paths adjusted for your installation:

```powershell
& "C:\path\to\llama-server.exe" --host 127.0.0.1 --port 8080 --models-preset "C:\path\to\apex-local-models.ini" --models-max 1 --no-models-autoload
```

Enable llama.cpp in Runtime Settings and set its host to `http://127.0.0.1:8080`, or the loopback address and port you chose. Leave **Manage server automatically** off.

In **managed mode**, enable llama.cpp and **Manage server automatically**, then set absolute executable and preset paths in Runtime Settings. APEX starts the router when the configured loopback URL is unreachable. These machine-local values are saved under `llama_cpp` in `config.local.json`:

```json
{
  "llama_cpp": {
    "enabled": true,
    "managed": true,
    "host": "http://127.0.0.1:8080",
    "executable_path": "C:\\path\\to\\llama-server.exe",
    "preset_path": "C:\\path\\to\\apex-local-models.ini"
  }
}
```

If the router requires a bearer token, set `LLAMA_CPP_API_KEY` in `.env` and configure the router to accept it. APEX requests `autoload=false`; keep automatic loading disabled. Local reasoning defaults to `none`; Cortex can select `focused` for supported llama.cpp models without unloading them. Hidden reasoning is discarded before display.

To check a running router manually:

```powershell
uv run python scripts/smoke_llama_cpp.py --host http://127.0.0.1:8080 --model gemma-4-e2b-16k --load --unload
```

## Briefing profiles

Briefing and `apex briefing` use the selected APEX Agent model. Daily is the CLI default; the interface lets you choose a profile:

- **Daily** provides orientation from current sources.
- **Catch Up** compares current sources with compatible evidence from completed briefings that were presented. Each source can use a different checkpoint. When comparable sources show no material changes, it saves a no-change result without calling a model.
- **Deep** adds a limited investigation with read-only tools allowed by the current connector, Agent, and MCP policies. It uses a curated tool selection rather than the saved Agent tool profile.

Sessions retain their model selection and saved artifact and can be continued in a linked Cortex conversation. APEX does not silently substitute another model. Insufficient context or execution capacity is rejected before generation; Deep also requires an eligible read capability. Demo mode supplies Daily and Catch Up fixtures and does not offer Deep.

See [Architecture](architecture.md#briefing-routes) for evidence selection and investigation limits, and [Privacy](privacy.md#briefings) for what reaches the model.

The retired Flash, Focused, and Structured briefing engine and routes are not supported. Existing `briefing` entries in `config.local.json` are ignored; APEX does not map their settings or model choices into profile or APEX Agent preferences. See [Persistence compatibility](architecture.md#persistence-compatibility) for database validation and legacy-table behavior.

## Connector credentials

Enable only the services you intend to use. Disabled telemetry connectors do not make network or authentication attempts.

| Capability | Setup |
|---|---|
| Weather | `TARGET_LOCATION` in `.env`; Open-Meteo needs no API key |
| Football | `FOOTBALL_API_KEY` in `.env` and followed teams in Runtime Settings |
| Gmail and Google Calendar | Desktop OAuth `credentials.json` in the selected data directory; first authorization creates `token.json` there |
| Microsoft To Do | `MICROSOFT_TODO_CLIENT_ID`, optional tenant and token-cache path; a public/native Entra app with device-code flow and delegated `Tasks.ReadWrite` |
| Google Cloud speech | Service-account key with its absolute path in `GOOGLE_APPLICATION_CREDENTIALS` |
| MCP services | Enable MCP and the chosen server preset, then configure its environment credential or OAuth authorization |

The tracked MCP presets cover GitHub, Brave Search, and Alpha Vantage. GitHub uses `GITHUB_PERSONAL_ACCESS_TOKEN`, Brave uses `BRAVE_API_KEY`, and Alpha Vantage MCP uses browser OAuth. Alpha Vantage market telemetry uses the separate API key described below.

APEX no longer collects headlines through a News telemetry connector, so `GNEWS_API_KEY` is not required. Existing copies of that variable have no effect. News search tools available through Brave Search or Alpha Vantage are separate from Overview telemetry.

Google authorization uses shared Gmail and Calendar scopes. If those scopes change, remove the local `token.json` and authorize again. Keep credential files and tokens out of source control.

## Google Calendar selection

When Calendar is enabled, Runtime Settings lists readable primary, secondary, subscribed, and hidden Google calendars. APEX reads only the selected IDs; a fresh configuration selects `primary`, but it may be unchecked and an empty selection remains empty. Calendar labels are shown with events by default in Overview, briefings, and Agent tool results. Turning off `calendar.show_calendar_names` suppresses those event labels without changing the picker.

Calendar IDs and this display preference are local runtime settings:

```json
{
  "calendar": {
    "selected_calendar_ids": ["primary"],
    "show_calendar_names": true
  }
}
```

APEX keeps unavailable saved IDs so they can be removed deliberately. It reads selected calendars independently: events from calendars that succeed remain available when another selected calendar fails, and Sync Health reports the partial failure. It does not create events, alter Google Calendar visibility, or use webhooks or a remote cache.

## Market data

Enable `features.market`, add one to eight `market.symbols`, and place `ALPHA_VANTAGE_API_KEY` in `.env`. Market reads daily closing data, and each symbol can contact Alpha Vantage at most once per UTC calendar day after a successful response. A successful response remains fresh cached data for that UTC day even when the latest close came from an earlier trading day. Temporary provider throttling retries after a short same-day cooldown, and daily quota exhaustion waits for the next UTC day. Other failed symbols retry on a later date with exponential backoff. An enabled connector without symbols or an API key reports unavailable in Sync Health but does not prevent APEX activation.
## Context vault selection

Context vault export is disabled by default, with no selected records. Set `APEX_CONTEXT_VAULT_PATH` in `.env` to an absolute destination directory, then use Cortex → Context → Vault to choose records and enable export.

`context_vault.enabled` controls publication. Each scope has a name, enable flag, selected entity and record IDs, excluded record IDs, and an `include_sensitive` opt-in. Only active production records without pending challenges are eligible; sensitive records require that scope's explicit opt-in.

Disabling export keeps existing copies. Changing the destination leaves copies at the previous location for deliberate cleanup. See [Context Vault](context-vault.md) for selection, preview, refresh, and removal procedures, and [Privacy](privacy.md#context-vault-copies) for what exported notes contain.

## Privacy and development modes

Cloud and local personal-context switches are independent and off by default. They allow selected saved claims and, for briefings, pending reviews, external reports, and verified action evidence to enter model prompts. Cortex report tools also require the effective model runtime's personal-context switch; selecting a report tool alone does not enable report access. See [Privacy](privacy.md#personal-context).

Sandbox mode is available only in `DEV_MODE`, uses a restricted non-personal tool allowlist, and stores conversation history in the sandbox partition. `DEMO_MODE` takes precedence for demo paths and does not contact configured providers.

## Voice settings

Runtime Settings configures text-to-speech engine selection, voice gender, and delivery mode:

```json
{
  "tts_settings": {
    "primary_tts": "pyttsx3",
    "voice_gender": "female",
    "voice_mode": "automatic"
  }
}
```

This example selects local speech; the tracked default engine is Google. Install the optional dependencies for Google or Kokoro before selecting them. The settings API exposes these under `voice` with `engine` (`google`, `pyttsx3`, or `kokoro`), `gender` (`female` or `male`), and `mode` (`automatic`, `manual`, or `off`). In automatic mode, APEX can speak short contextual cues for telemetry collection and for briefing and spoken-highlights progress; manual mode suppresses cues while allowing explicit speech and briefing highlights. Off mode also blocks speech preparation and playback. For installation, fallback behavior, Kokoro hardware gates, and speech caching, see the [Speech runtime guide](speech-runtime.md).

## External activity intake

Local activity intake accepts caller-declared source IDs. Use a nonempty lowercase ID matching `^[a-z][a-z0-9_-]{0,63}$`, such as `codex` or `grok-bot`. The ID is stored as source attribution; it does not identify or authenticate the software that submitted the report. The server assigns the local `operator` principal and the current production or development sandbox partition.

### Optional local report folder

The main APEX backend can poll one operator-selected folder for completed report files. The report folder is disabled by default. Its enabled flag and absolute folder path are machine-local Runtime Settings stored in the gitignored `config.local.json`; keep credentials in `.env`.

```json
{
  "activity_report_folder": {
    "enabled": true,
    "folder_path": "/absolute/path/to/activity-report-folder"
  }
}
```

On Windows, use an absolute path such as `C:\\Users\\<you>\\AppData\\Local\\APEX\\activity-report-folder`. Create the folder in a private local or synced location and grant access only to the operator and the sync tool. APEX scans it at startup and about every 60 seconds; Reports **Refresh** requests an immediate scan. A missing folder remains configured and is retried. Runtime setting changes take effect without restarting APEX.

Place only completed, top-level `.json` files in the folder; the extension is case-insensitive, and the filename does not need to match the report's `submission_key`. Each file must contain a version-one submission envelope and be at most 256 KiB. For example:

```json
{
  "client_id": "grok-bot",
  "report": {
    "version": "1",
    "submission_key": "run-2026-09-23",
    "title": "Completed review",
    "task_status": "completed",
    "outcome": "The requested checks passed."
  }
}
```

The `report` object uses the same version-one fields described in [the API activity contract](api.md#external-activity-reports); a bare report object is invalid here. Write to a temporary filename and rename it to a `.json` filename only after the file is complete. APEX leaves source files in place; identical reports reuse the original receipt, while changed content with the same source ID and key follows the normal conflict behavior.

The envelope's `client_id` is the source label claimed by the file producer; the `report` cannot choose a partition or principal. Report-folder intake enters the same untrusted Reports workspace as CLI, JSON/MCP gateway, and API submissions. The report folder uses no provider API and adds no remote endpoint.

## External activity gateway

The submission gateway is separate from the normal APEX launcher. Start it only when another local program needs HTTP or MCP submission:

```powershell
uv run python -m core.activity.gateway
```

The gateway binds to `127.0.0.1:8001` unless `--host` and `--port` select another loopback address and port. Requests must use that selected host and port; the default also accepts the standard loopback aliases. It exposes `GET /healthz`, `POST /v1/activity/reports`, and Streamable HTTP MCP at `/mcp/`. The JSON route accepts `application/json`; MCP exposes only `submit_activity`. Both adapters accept caller-declared source IDs, use the local `operator` principal and current production or development sandbox partition, and share the `apex_memory.db` activity table used by the local API and CLI.

The gateway rejects non-loopback bindings, unexpected Host headers, cross-origin browser requests, request bodies above 256 KiB, and more than 30 combined JSON and MCP submission attempts per minute across the process. It does not start Cortex, connectors, the main API, or a second database. `DEMO_MODE` keeps its storage in memory and rejects submissions.

Keep this listener on loopback. Do not place it behind a tunnel, reverse proxy, or public endpoint; the gateway does not authenticate remote callers.

## Bounded run limits

`config.json` sets execution ceilings for asynchronous Cortex runs:

```json
{
  "cortex_runs": {
    "max_concurrent_runs": 2,
    "max_elapsed_seconds": 600,
    "max_retries": 4,
    "max_model_turns": 6,
    "max_tool_calls": 10,
    "event_replay_limit": 512,
    "shutdown_drain_seconds": 30
  }
}
```

`max_concurrent_runs` limits active execution slots before the API returns `429`. `event_replay_limit` sets the in-memory event buffer size per run for Server-Sent Events reconnects. `shutdown_drain_seconds` bounds the application drain for cancelled run workers, application-owned tasks, report-folder work, and speech. If work remains active, APEX reports shutdown failure and leaves its dependencies open. The backend host advertises and enforces a total shutdown timeout of this interval plus thirty seconds, including HTTP-task shutdown, dependency cleanup, and forced exit (sixty seconds with the default). A managed parent waits through that advertised timeout before forced fallback. The remaining fields define the immutable stop-limit snapshot applied to each run.

`total_tokens` remains cumulative usage accounting for every provider turn. It does not stop a run: multi-turn requests may resend conversation context, while the provider's context-window checks still protect each individual request. Historical run snapshots retain their recorded token ceiling for history inspection; new snapshots have no cumulative-token limit.

## Archived conversation retention

`config.json` sets how long Cortex keeps an archived conversation before permanent deletion:

```json
{
  "cortex_conversations": {
    "archived_retention_days": 30
  }
}
```

The minimum is 14 days. The period starts when the conversation is archived, not when it was last edited. Repeating Archive does not restart it; restoring and later archiving does. APEX checks at startup and about every 24 hours, so deletion may happen after the exact cutoff. It skips conversations with a pending turn or active run and retries them at a later check. The sweep covers production and development sandbox history; demo mode has no durable history to purge. The existing archived-only Delete action still removes a conversation immediately.

Archived Briefing conversations disappear from Saved sessions and Repeat last but remain available to Catch Up and Agent history until deletion. Permanent deletion also removes their linked Briefing session and speech data. Separately accepted personal-context sources keep their own lifecycle.

## OpenTelemetry GenAI tracing

Install the optional tracing dependencies before configuring export:

```powershell
uv sync --locked --extra tracing
```

Set the following values in `.env` and restart APEX:

- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`: Destination URL for OTLP HTTP trace export (such as a local Arize Phoenix or OpenTelemetry collector).
- `OTEL_EXPORTER_OTLP_TRACES_HEADERS` or `OTEL_EXPORTER_OTLP_HEADERS`: Optional comma-separated `key=value` headers.
- `OTEL_SERVICE_NAME`: Service name attribute, defaulting to `apex`.

Without an endpoint, APEX does not configure trace export. If the SDK or exporter is missing, it logs a warning and leaves export disabled. Spans record run identifiers, models, token counts, timings, and status. Exceptions escaping a tracing context can also be recorded with their message and stack trace; see [Privacy](privacy.md#distributed-tracing).
