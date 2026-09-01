# Configuration

APEX keeps portable defaults in `config.json` and machine-specific settings, credentials, local paths, and model runtime details in `config.local.json` and `.env`. Do not commit secrets or GGUF paths.

## Runtime Settings

Runtime Settings persist the editable parts of the resolved configuration. `ask_apex` uses schema version 19 and has one native identity plus model-based routing:

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

## Models and credentials

The fresh interactive default is OpenRouter DeepSeek V4 Flash with Low reasoning. Cloud models require their documented provider credential: `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`. Local models run through Ollama or llama.cpp and their availability is reported per model in Cortex.

Only one local generation may run at a time. APEX checks runtime reachability, installed models, resource gates, and residency before a cold load. The provider-neutral unload control releases the current local model.

## Briefing modes

Briefings are fixed routes, independent of the interactive model. Focused uses OpenRouter DeepSeek V4 Flash with High reasoning; Flash uses Gemma E2B through llama.cpp at 16K with reasoning disabled; Structured is deterministic. Fallback order is Focused, Flash, then Structured.

## External and managed router modes

Configure llama.cpp aliases with one preset per exposed context size. A tracked placeholder is [`docs/examples/llama-cpp-apex-local-models.preset.ini`](examples/llama-cpp-apex-local-models.preset.ini). Copy it to a machine-local path, replace GGUF placeholders, and keep that copy untracked. External launchers should use one preset at a time; managed mode uses the same aliases and resource gates.

## Privacy and development modes

Personal context is off by default for both runtimes. Sandbox mode is available only in `DEV_MODE`, uses a restricted non-personal tool allowlist, and stores conversation history in the sandbox partition. `DEMO_MODE` takes precedence for demo paths and does not contact configured providers.
