from pathlib import Path


def replace_one(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{path}: target not found: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def remove_between(path: str, start: str, end: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    a = text.find(start)
    b = text.find(end, a + len(start)) if a >= 0 else -1
    if a < 0 or b < 0:
        raise SystemExit(f"{path}: removal markers not found")
    p.write_text(text[:a] + text[b:], encoding="utf-8")


# 1. Runtime settings/tool-profile public contract and ownership.
replace_one(
    "docs/api.md",
    '    "briefing": { "default_mode": "panthera" },\n',
    '    "tool_profiles": { "custom_profiles": [], "default_profile_by_agent": {} },\n'
    '    "briefing": { "default_mode": "panthera" },\n',
)
replace_one(
    "docs/api.md",
    '`football.teams` and `market.symbols` are returned in the resolved settings snapshot and are patchable through Runtime Settings. OpenAPI contains the complete shape.\n',
    '`football.teams`, `market.symbols`, and `tool_profiles` are returned in the resolved settings snapshot. OpenAPI contains the complete shape. Tool profiles persist through the same settings store, but the dedicated `/api/v1/cortex/tool-profiles` routes are the canonical mutation workflow for built-in/custom profiles and per-Agent defaults. The generic settings patch continues to accept the complete `tool_profiles` group for contract compatibility.\n',
)
replace_one(
    "docs/api.md",
    'Accepts a strict partial patch for the optional user designation, connectors, sports modules, followed football teams, market symbols, Ask APEX, briefing, voice, llama.cpp enablement, loopback host, optional managed-server paths, and tracked MCP enablement. Unknown fields return `422`. An empty object returns the current envelope without writing.\n',
    'Accepts a strict partial patch for the optional user designation, connectors, sports modules, followed football teams, market symbols, Ask APEX, tool profiles, briefing, voice, llama.cpp enablement, loopback host, optional managed-server paths, and tracked MCP enablement. Unknown fields return `422`. An empty object returns the current envelope without writing. Prefer the dedicated Cortex tool-profile routes for profile creation, editing, deletion, and default assignment.\n',
)
replace_one(
    "docs/configuration.md",
    '| Ask APEX | Global enablement switch, local context preferences, and grounding selection; Cortex owns Agent, effort, and grounding selection |\n',
    '| Ask APEX | Global enablement switch, local context preferences, and grounding selection; Cortex owns Agent, effort, and grounding selection |\n'
    '| Tool profiles | Saved custom tool profiles and per-Agent defaults; edited through Cortex Tools and persisted in `config.local.json` |\n',
)
replace_one(
    "docs/configuration.md",
    'Prompt text remains exclusively in tracked `config.json`; it is not editable through Runtime Settings. Ollama host and resource gates, llama.cpp resource gates and timeouts, router presets, MCP endpoints and allowlists, credentials, and environment modes remain file-configured.\n',
    'Prompt text remains exclusively in tracked `config.json`; it is not editable through Runtime Settings. Ollama host and resource gates, llama.cpp resource gates and timeouts, router presets, MCP endpoints and allowlists, credentials, and environment modes remain file-configured.\n\n`tool_profiles` is part of the resolved settings snapshot and local overlay. Cortex owns the profile editing workflow through the dedicated tool-profile routes; the generic settings patch accepts the complete group only as a lower-level compatibility contract.\n',
)

# 2. Development-only local Agent role metadata.
replace_one("core/agent/catalog.py", 'description="Lightweight on-device fallback for quick tasks on constrained systems.",', 'description="Lightweight local development Agent for evaluating constrained-system workflows.",')
replace_one("core/agent/catalog.py", 'capability_tags=("Lightweight", "Fast fallback", "Constrained local"),', 'capability_tags=("Lightweight", "Development", "Constrained local"),')
replace_one("core/agent/catalog.py", 'description="Private on-device generalist for capable offline work without cloud processing.",', 'description="Local development generalist for evaluating capable offline work without cloud processing.",')
replace_one("core/agent/catalog.py", 'capability_tags=("Larger model", "Primary local"),', 'capability_tags=("Larger model", "Development local"),')

# 3. Apodemus is the real missing/invalid local default.
replace_one(
    "core/settings/normalize.py",
    '    local_agent = ask_apex.get("local_agent", "mus")\n    if local_agent not in VALID_LOCAL_SETTINGS_AGENTS:\n        local_agent = "mus"\n',
    '    local_agent = ask_apex.get("local_agent", "apodemus")\n    if local_agent not in VALID_LOCAL_SETTINGS_AGENTS:\n        local_agent = "apodemus"\n',
)
replace_one("tests/test_settings_store.py", '        self.assertEqual(snap.ask_apex.local_agent, "mus")\n', '        self.assertEqual(snap.ask_apex.local_agent, "apodemus")\n')

# 4. Benchmark documentation discoverability and validation.
replace_one(
    "README.md",
    '| [Frontend Guide](frontend/README.md) | Work specifically in the React/TypeScript application |\n',
    '| [Frontend Guide](frontend/README.md) | Work specifically in the React/TypeScript application |\n'
    '| [Local Model Benchmarking](benchmarks/README.md) | Compare local Agents and one-off llama.cpp candidates with the developer benchmark utility |\n',
)
replace_one(
    "docs/configuration.md",
    '#### llama.cpp configuration\n',
    'For repeatable local Agent and candidate-model comparisons, see [Local Model Benchmarking](../benchmarks/README.md). Benchmark results remain machine-specific and gitignored.\n\n#### llama.cpp configuration\n',
)
replace_one(
    "scripts/check_docs.py",
    '        root / ".env.example",\n        root / "frontend" / "README.md",\n    ]\n',
    '        root / ".env.example",\n        root / "frontend" / "README.md",\n        root / "benchmarks" / "README.md",\n    ]\n',
)

# 5. Remove obsolete hard startup gate while preserving scanner telemetry helpers.
replace_one("core/config.py", '    "ENABLE_STARTUP_GATE",\n', '')
replace_one(
    "core/config.py",
    'ENABLE_STARTUP_GATE: Final[bool] = _parse_env_bool(\n    os.getenv("ENABLE_STARTUP_GATE"),\n    key="ENABLE_STARTUP_GATE",\n    default=True,\n)\n\n',
    '',
)
replace_one("core/scanner.py", 'from datetime import datetime, timedelta, timezone\n', '')
replace_one("core/scanner.py", 'from dotenv import load_dotenv\n\nfrom core import database\nfrom core.config import ENABLE_STARTUP_GATE, ENV_PATH, is_dev_mode\n\nload_dotenv(dotenv_path=ENV_PATH)\n\nCOOLDOWN_SECONDS = 3600\n', '')
remove_between("core/scanner.py", '\ndef _enforce_production_gate() -> bool:\n', '\n\nif __name__ == "__main__":\n')
replace_one(
    "core/scanner.py",
    '\n    if should_run():\n        print("[SCANNER]: Checks passed.")\n    else:\n        print("[SCANNER]: Checks failed.")\n',
    '\n',
)
replace_one("tests/test_runtime_modes.py", '"""Characterization coverage for DEV_MODE, DEMO_MODE, gate, and synthesis fallback."""', '"""Characterization coverage for DEV_MODE, DEMO_MODE, and synthesis fallback."""')
remove_between("tests/test_runtime_modes.py", '\n\nclass ScannerGateModeTests(unittest.TestCase):\n', '\n\nclass BrainFallbackShapeTests(unittest.TestCase):\n')

# 6. Record MCP fail-closed exception to atomic local settings rejection.
replace_one(
    "docs/decisions.md",
    '**Trade-off.** Invalid local configuration must fail as one layer rather than partially applying. The store validates the full overlay and publishes it only after a transactional file replacement succeeds.\n',
    '**Trade-off.** Invalid editable runtime settings reject the local layer as a unit, except MCP configuration: malformed optional MCP fields or providers fail closed independently so one integration cannot invalidate unrelated local preferences. Successful settings writes still use transactional replacement before the new snapshot is published.\n',
)

# 7. Frontend state ownership.
replace_one(
    "docs/architecture.md",
    '| `useCortex` | Browser-held conversation, Agent status, explicit tool-selection diagnostics, and tool cards |\n',
    '| `useCortex` | Browser-held conversation, Agent status, query submission, tool traces, and returned tool cards |\n'
    '| `useToolCatalog` | Agent-specific tool catalog, profile application, and session-persistent selection |\n'
    '| `useToolPreflight` | Debounced next-request tool and context token estimates |\n',
)
replace_one(
    "docs/agent-guidance/frontend.md",
    '- Use `useApexData()` for boot configuration and reminders. Use the focused hooks for their respective concerns instead of adding to `useApexData()`: `useAppActivation()` for standby/activated lifecycle, `usePreflight()` for preflight warning/blocker dialog flow, `useTelemetrySnapshot()` for on-demand telemetry refresh, and `useBriefingPipeline()` for trigger/status polling and briefing/digest state.\n',
    '- Use `useApexData()` for boot configuration and reminders. Use focused hooks for their respective concerns instead of adding to `useApexData()`: `useAppActivation()` for standby/activated lifecycle, `usePreflight()` for preflight warning/blocker dialog flow, `useTelemetrySnapshot()` for on-demand telemetry refresh, `useBriefingPipeline()` for trigger/status polling and briefing/digest state, `useCortex()` for Agent conversation/query results, `useToolCatalog()` for catalog/profile/selection state, and `useToolPreflight()` for next-request token estimates.\n',
)

# 8. Explicitly document the experimental Agent loop limit.
replace_one(
    "docs/api.md",
    'Cortex Engine Agent loops are bounded. Panthera can use up to 6 model turns and 10 tool calls; the other cloud Agents can use up to 4 turns and 6 calls; Sorex uses up to 2/3 turns/calls, while Mus, Apodemus, and Neotoma use up to 3/4 respectively. The last model turn is answer-only.\n',
    'Cortex Engine Agent loops are bounded. Panthera can use up to 6 model turns and 10 tool calls; the other cloud Agents can use up to 4 turns and 6 calls; Sorex uses up to 2/3 turns/calls, while Mus, Apodemus, Neotoma, and Unnamed Experimental Agent use up to 3/4 respectively. The last model turn is answer-only.\n',
)

# Optional A. Correct Design System heading ownership.
old = '''### Unified Tools selector\n\n### Cortex Agent catalog\n\nThe Cortex inspector is the detailed Agent-configuration surface. Show one selected `APEX <Agent>` card; its popover presents catalog-provided names, descriptions, model metadata, ordered tags, availability, and compact pricing. The Home command rail may expose the same catalog through a compact Agent trigger, but it does not duplicate inspector-owned effort, grounding, local-tool, or lifecycle controls. The composer shows only the short Agent name and a send control. Agent marks, accent color, responsive card layout, and popover behavior are frontend presentation concerns; catalog content is backend-owned.\n\nTreat `Configured` as credentials present but not provider-verified. Display verification and runtime-failure states with text and iconography, not color alone. `Verify access` remains a secondary action inside an expanded cloud card and must not be nested inside its Agent-selection button.\n\nStability is a reusable catalog treatment: **Preview** uses amber, **Experimental** uses cyan, and **Stable** has no stability badge. Apply these semantics wherever Agent catalog stability is shown; do not infer stability from the provider, runtime, or Agent mark.\n\nThe Tools control is shared by cloud and local Agents. Its collapsed state shows the active profile or `Custom`, selected-tool count, and cumulative estimated schema tokens. Its expanded surface provides profile selection, search, APEX-family and MCP-server toggles, individual tool overrides, disabled availability reasons, group subtotals, select-all/clear actions, and the estimated next-request breakdown. Selection changes only prompt exposure; MCP settings remain a separate authority boundary.\n\nThe local context meter uses monospace tabular numerals and displays used/available tokens. Neutral text is the default; amber is reserved for at least 80% utilization. Token estimates are diagnostics, not progress animation, and must remain readable without color.\n\n'''
new = '''### Unified Tools selector\n\nThe Tools control is shared by cloud and local Agents. Its collapsed state shows the active profile or `Custom`, selected-tool count, and cumulative estimated schema tokens. Its expanded surface provides profile selection, search, APEX-family and MCP-server toggles, individual tool overrides, disabled availability reasons, group subtotals, select-all/clear actions, and the estimated next-request breakdown. Selection changes only prompt exposure; MCP settings remain a separate authority boundary.\n\nThe local context meter uses monospace tabular numerals and displays used/available tokens. Neutral text is the default; amber is reserved for at least 80% utilization. Token estimates are diagnostics, not progress animation, and must remain readable without color.\n\n### Cortex Agent catalog\n\nThe Cortex inspector is the detailed Agent-configuration surface. Show one selected `APEX <Agent>` card; its popover presents catalog-provided names, descriptions, model metadata, ordered tags, availability, and compact pricing. The Home command rail may expose the same catalog through a compact Agent trigger, but it does not duplicate inspector-owned effort, grounding, local-tool, or lifecycle controls. The composer shows only the short Agent name and a send control. Agent marks, accent color, responsive card layout, and popover behavior are frontend presentation concerns; catalog content is backend-owned.\n\nTreat `Configured` as credentials present but not provider-verified. Display verification and runtime-failure states with text and iconography, not color alone. `Verify access` remains a secondary action inside an expanded cloud card and must not be nested inside its Agent-selection button.\n\nStability is a reusable catalog treatment: **Preview** uses amber, **Experimental** uses cyan, and **Stable** has no stability badge. Apply these semantics wherever Agent catalog stability is shown; do not infer stability from the provider, runtime, or Agent mark.\n\n'''
replace_one("docs/design-system.md", old, new)

# Optional B. Privacy wording for remote Ollama versus loopback-only llama.cpp.
replace_one(
    "docs/privacy.md",
    'APEX treats Ollama and llama.cpp as local by default; configuring a remote local-runtime host moves that model traffic outside the machine boundary.\n',
    'APEX treats Ollama and llama.cpp as local by default. Ollama may be configured with a remote host, which moves that model traffic outside the machine boundary; APEX requires the llama.cpp router host to remain loopback-only.\n',
)

# Optional C. Canonical agent guidance runs the docs checker.
replace_one(
    "AGENTS.md",
    '- Documentation or agent-configuration changes: validate referenced paths and metadata, then run `git diff --check`.\n',
    '- Documentation or agent-configuration changes: validate referenced paths and metadata, run `uv run python scripts/check_docs.py` for public documentation changes, then run `git diff --check`.\n',
)
