# Privacy and Data Boundaries

APEX is local-first, but it is not entirely offline. The HUD, API, SQLite database, and default Ollama endpoint run on the local machine; enabled connectors and cloud model or speech providers send selected data needed for their configured operation to external services.

## Local Service Boundary

`launcher.py` binds FastAPI to `127.0.0.1:8000` and the compiled HUD to `127.0.0.1:5500`. The API has no authentication, so loopback binding is part of the security model. LAN and public access are intentionally unsupported; adding either would require authentication, authorization, and transport-security work first.

`APEX_ALLOWED_ORIGINS` changes which browser origins can call the API. CORS is not authentication and does not protect a remotely bound service from non-browser clients.

## Briefing Synthesis Data

Enabled connectors return typed `ConnectorResult` objects. Briefing orchestration selects a bounded set of facts for `SynthesisInput`: weather, limited email subjects and unread count, limited news headlines, calendar facts, reminders, F1, football, and connector-health fields. Before model use, text is Unicode-normalized, stripped of control characters and markup, truncated per field, serialized to at most 2,000 characters, and wrapped in `<untrusted_connector_data>` markers.

Gemini and Ollama receive the same sanitized payload. Concatenated connector display strings are returned to the HUD for compatibility but are never forwarded to a briefing model. Briefing synthesis receives no assistant tools or chat history, disables model thinking, limits output to 512 tokens, and accepts only the expected speech/insight marker format. Invalid provider output falls back to deterministic synthesis from the same typed input.

The untrusted-data markers and output validation reduce prompt-injection risk; they do not make model output a security boundary. Connector text should still be treated as untrusted evidence, and model output must not authorize actions.

### Current cloud-processing limitation

A normal production run currently routes briefing synthesis through Gemini. This is a known personal-data trade-off until the remaining v1.17 work makes local and raw production paths independently usable. The typed payload is smaller and safer than raw connector telemetry, but it can still contain personal facts such as calendar events, reminders, email subjects, or briefing context.

On the Gemini API unpaid/free tier, Google states that submitted content and generated responses may be used to provide, improve, and develop Google products and machine-learning technologies, and that human reviewers may process API inputs and outputs. Sanitization limits what APEX sends; it does not make free-tier cloud processing confidential. The current free-tier path is therefore not appropriate for sensitive or confidential personal data. See Google's [Gemini API terms](https://ai.google.dev/gemini-api/terms) and [pricing data-use table](https://ai.google.dev/gemini-api/docs/pricing).

Google states that paid Gemini API services do not use prompts or responses to improve products, although limited abuse-monitoring retention can still apply. Moving this project to paid Gemini usage would provide that stronger provider boundary while cloud synthesis remains mandatory. Local and raw production synthesis are planned as part of the remaining v1.17 work.

## Assistant Data

The assistant is a separate path from briefing synthesis. A cloud profile sends the current prompt, the browser-provided conversation history, selected latest-briefing context, and any requested tool results to Gemini. A local profile sends the same categories to the configured Ollama host, which defaults to `http://localhost:11434` and can be changed in APEX configuration. Tool results are wrapped in `<untrusted_tool_output>` markers before another model turn.

Conversation history is held by the browser tab and is lost on reload. There is no server-side chat-session store. The latest persisted briefing can be added to assistant context so relative questions about the visible HUD can be answered.

## Local Persistence

`apex_memory.db` stores production run timestamps, reminders, up to 50 recent briefing records, structured digests, and runtime metadata such as `run_id`. New run and briefing timestamps are timezone-aware UTC; legacy timezone-naive run timestamps remain readable as local wall-clock values.

The SQLite database is local but not encrypted by APEX. Operating-system account access and filesystem permissions protect it at rest. Database files, WAL files, caches, OAuth tokens, credentials, generated audio, and local model weights are gitignored.

## Credentials and Child Processes

Secrets and machine-specific credential paths belong in `.env`; non-secret runtime preferences belong in `config.json` or the gitignored `config.local.json`. The uvicorn child receives the backend environment because it owns connector and provider access. The static server and browser receive a restricted environment containing only process essentials, so API keys are not copied into those child environments.

OAuth credentials and service-account keys remain local files. They must not be committed. `.env.example` contains placeholders only.

## Logging

The API and launcher use standard module loggers. Briefing records receive a `run_id` that is propagated into pipeline state, persisted metadata, and relevant worker-thread logs for correlation. Operational failures log component names, stable categories, and exception types rather than connector payloads or credentials. Malformed history records are identified by row ID and parse-error category without logging the stored briefing or digest contents.

Public assistant tool failures use stable messages instead of raw exception strings. Logs and public errors should still be reviewed when new connectors or providers are added, because third-party exception objects are not guaranteed to be privacy-safe.

## Runtime Modes

- `DEMO_MODE=true` uses static mock briefing and assistant data, skips live connectors, and does not write briefing history.
- `DEV_MODE=true` bypasses the startup gate and production run logging. Gmail and Calendar may still make live OAuth-authenticated requests, but returned content is masked before briefing use.
- Production mode calls only enabled connectors. Disabling a connector skips its network or authentication attempt and excludes it from synthesis and Sync Health scoring.
