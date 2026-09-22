# Configuration

APEX keeps portable defaults in `config.json` and machine-specific settings, credentials, local paths, and model runtime details in `config.local.json` and `.env`. Do not commit secrets or GGUF paths.

## Runtime Settings

Runtime Settings persist the editable parts of the resolved configuration. `ask_apex` uses schema version 20 and has one native identity plus model-based routing:

```json
{
  "enabled": true,
  "selected_model": "deepseek/deepseek-v4-flash-0731",
  "sandbox_mode": false,
  "cloud": { "last_model": "deepseek/deepseek-v4-flash-0731", "effort": "low" },
  "local": { "last_model": "gemma-4-E2B-Q4_K_M.gguf", "context_window": 16384, "reasoning_mode": "none" }
}
```

Current default model mapping is `apex` -> `deepseek/deepseek-v4-flash-0731`; `selected_model` is authoritative. Selecting a cloud or local model remembers that choice and its controls in the matching runtime section. Cloud and local personal-context preferences are independent. Cloud tool profiles default to All APEX Tools; local profiles default to No APEX Tools.

Home and Cortex share this model selection. Home applies per-turn overrides: the lowest supported cloud effort, or a 16K local context with reasoning disabled. Those overrides never change saved Cortex preferences.

## Google Calendar selection

When Calendar is enabled, Runtime Settings lists readable primary, secondary, subscribed, and hidden Google calendars. APEX reads only the selected IDs; a fresh configuration selects `primary`, but it may be unchecked and an empty selection remains empty. Calendar labels are shown with events by default in Home, briefings, and Agent tool results. Turning off `calendar.show_calendar_names` suppresses those event labels without changing the picker.

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

## External activity registrations

`external_activity.clients` in `config.json` declares report sources. Each registration has a stable `id`, display name, explicit enabled flag, allowed principals, a bounded `permissions` list, and fixed partition. The only current permission is `activity:submit`; an empty list denies submission. The local CLI uses principal `operator`; its client name is declared source attribution, not proof that a particular program submitted the report.

```json
{
  "external_activity": {
    "clients": [{
      "id": "codex",
      "display_name": "Codex",
      "enabled": true,
      "allowed_principals": ["operator"],
      "permissions": ["activity:submit"],
      "partition": "production"
    }]
  }
}
```

A registration is checked for every submission. Disabling or removing it preserves reports already received, while new submissions under that ID fail. Report content cannot choose a partition; configure distinct registrations when both production and sandbox submissions are needed. Missing required registration fields and invalid permission values deny submission. Duplicate IDs are unavailable, regardless of their array order. Invalid registration entries are ignored with a startup warning.

## External activity gateway

The submission gateway is separate from the normal APEX launcher. Start it only when another local program needs HTTP or MCP submission:

```powershell
uv run python -m core.activity.gateway --mode local
```

Local mode binds to `127.0.0.1:8001` unless `--host` and `--port` select another loopback address and port. Requests must use that selected host and port; the default also accepts the standard loopback aliases. It exposes `GET /healthz`, `POST /v1/activity/reports`, and Streamable HTTP MCP at `/mcp/`. The JSON route accepts `application/json`; MCP exposes only `submit_activity`. Both adapters use the configured registration, local `operator` principal, current production or development sandbox partition, and the same `apex_memory.db` activity table used by the local API and CLI.

The gateway reloads external activity registrations before every submission, so disabling or removing a client takes effect for existing MCP sessions. It rejects non-loopback local bindings, unexpected Host headers, cross-origin browser requests, request bodies above 256 KiB, and more than 30 attempts from one client in a minute. It does not start Cortex, connectors, the main API, or a second database. `DEMO_MODE` keeps its storage in memory and rejects submissions.

`--mode cloudflare` keeps the same loopback listener but replaces local header checks with Cloudflare Access assertion verification. Configure `external_activity.cloudflare` alongside the clients before starting it. The issuer, JWKS URL, Access application audiences, and allowed Access subjects are non-secret configuration. The gateway validates an `RS256` `Cf-Access-Jwt-Assertion` against the configured issuer, expiry, and cached signing keys; it fails closed if keys cannot refresh. A binding derives both the APEX client ID and generic principal, so a submitted `client_id` must match the verified Access application.

```json
{
  "external_activity": {
    "clients": [{
      "id": "spark",
      "display_name": "Spark",
      "enabled": true,
      "allowed_principals": ["cloudflare:spark"],
      "permissions": ["activity:submit"],
      "partition": "production"
    }],
    "cloudflare": {
      "issuer": "https://your-team.cloudflareaccess.com",
      "jwks_url": "https://your-team.cloudflareaccess.com/cdn-cgi/access/certs",
      "bindings": [{
        "client_id": "spark",
        "audience": "the-distinct-access-application-audience",
        "allowed_subjects": ["the-operator-access-subject"]
      }]
    }
  }
}
```

The Access subject is the signed `sub` claim, not a display name or source label. Each remote client needs its own Access application, audience, hostname, binding, and registration. APEX does not store Cloudflare headers or claims with a report. Recheck the complete [Cloudflare Access deployment guide](cloudflare-access.md) before exposing the gateway. Do not tunnel local mode: a tunnel reaches the same loopback listener and does not make its callers local.

## Models and credentials

The fresh interactive default is OpenRouter DeepSeek V4 Flash with Low reasoning. Cloud models require their documented provider credential: `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`. Local models run through Ollama or llama.cpp and their availability is reported per model in Cortex.

Only one local generation may run at a time. APEX checks runtime reachability, installed models, resource gates, and residency before a cold load. The provider-neutral unload control releases the current local model.

## Briefing modes

Briefings are fixed routes, independent of the interactive model. Focused uses OpenRouter DeepSeek V4 Flash with High reasoning; Flash uses Gemma E2B through llama.cpp at 16K with reasoning disabled; Structured is deterministic. Fallback order is Focused, Flash, then Structured.

## External and managed router modes

Configure llama.cpp aliases with one preset per exposed context size. A tracked placeholder is [`docs/examples/llama-cpp-apex-local-models.preset.ini`](examples/llama-cpp-apex-local-models.preset.ini). Copy it to a machine-local path, replace GGUF placeholders, and keep that copy untracked. External launchers should use one preset at a time; managed mode uses the same aliases and resource gates.

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

`max_concurrent_runs` limits active execution slots before the API returns `429`. `event_replay_limit` sets the in-memory event buffer size per run for Server-Sent Events reconnects. `shutdown_drain_seconds` bounds the full application shutdown window for cancelled run workers and application-owned startup tasks; if either remains active, APEX reports shutdown failure and leaves their dependencies open. The remaining fields define the immutable stop-limit snapshot applied to each run.

`total_tokens` remains cumulative usage accounting for every provider turn. It does not stop a run: multi-turn requests may resend conversation context, while the provider's context-window checks still protect each individual request. Previous `max_total_tokens` configuration values are ignored after beta.3, and old run records retain their recorded ceiling for history inspection.

## OpenTelemetry GenAI tracing

APEX can export distributed trace spans adhering to OpenTelemetry GenAI semantic conventions when an endpoint is configured in `.env`:

- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`: Destination URL for OTLP HTTP trace export (such as a local Arize Phoenix or OpenTelemetry collector).
- `OTEL_EXPORTER_OTLP_TRACES_HEADERS` or `OTEL_EXPORTER_OTLP_HEADERS`: Optional comma-separated `key=value` headers.
- `OTEL_SERVICE_NAME`: Service name attribute, defaulting to `apex`.

When `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is unset, tracing is disabled with zero runtime overhead. Trace spans include run identifiers, model names, token counts, and step durations; they never include prompt or answer text.

## Privacy and development modes

Personal context is off by default for both runtimes. Sandbox mode is available only in `DEV_MODE`, uses a restricted non-personal tool allowlist, and stores conversation history in the sandbox partition. `DEMO_MODE` takes precedence for demo paths and does not contact configured providers.

## Market data

Enable `features.market`, add one to eight `market.symbols`, and place `ALPHA_VANTAGE_API_KEY` in `.env`. Market reads daily closing data, and each symbol can contact Alpha Vantage at most once per UTC calendar day. A successful response remains fresh cached data for that UTC day even when the latest close came from an earlier trading day. Failed symbols retry on a later date with exponential backoff. An enabled connector without symbols or an API key reports unavailable in Sync Health but does not prevent APEX activation.
