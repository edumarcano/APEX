"""One-off bulk update for Agent Family Consolidation test keys."""

from __future__ import annotations

import re
from pathlib import Path

REPLACEMENTS = [
    ('agent_key="apodemus"', 'agent_key="lynx"'),
    ('agent_key: str = "apodemus"', 'agent_key: str = "lynx"'),
    ('agent="apodemus"', 'agent="lynx"'),
    ("agent='apodemus'", "agent='lynx'"),
    ('start_agent_warmup("apodemus")', 'start_agent_warmup("lynx")'),
    ('"apodemus-16k"', '"gemma-4-e2b-16k"'),
    ('"apodemus-4k"', '"gemma-4-e2b-4k"'),
    ('return_value="apodemus"', 'return_value="lynx"'),
    ('agent: "apodemus"', 'agent: "lynx"'),
    ('agent="neotoma"', 'agent="lynx"'),
    ('agent="sorex"', 'agent="lynx"'),
    ('agent="mus"', 'agent="lynx"'),
    ('agent="acinonyx"', 'agent="panthera"'),
    ('agent="neofelis"', 'agent="panthera"'),
    ('agent="delphinus"', 'agent="panthera"'),
    ('agent="orcinus"', 'agent="panthera"'),
    ('resolve_selected_tools("sorex"', 'resolve_selected_tools("lynx"'),
    ('resolve_selected_tools("mus"', 'resolve_selected_tools("lynx"'),
    ('resolve_selected_tools("apodemus"', 'resolve_selected_tools("lynx"'),
    ('resolve_selected_tools("acinonyx"', 'resolve_selected_tools("panthera"'),
    ('project_descriptor_for_agent("sorex"', 'project_descriptor_for_agent("lynx"'),
    ('project_descriptor_for_agent("mus"', 'project_descriptor_for_agent("lynx"'),
    ('project_descriptor_for_agent("apodemus"', 'project_descriptor_for_agent("lynx"'),
    ('project_descriptor_for_agent("neotoma"', 'project_descriptor_for_agent("lynx"'),
    ('build_tool_catalog("sorex"', 'build_tool_catalog("lynx"'),
    ('_apodemus_profile', '_lynx_profile'),
    ('You are Apex Apodemus', 'You are Apex Lynx'),
    ('build_concrete_agent("apodemus"', 'build_concrete_agent("lynx"'),
    ('build_concrete_agent("neotoma"', 'build_concrete_agent("lynx"'),
    ('build_concrete_agent("sorex"', 'build_concrete_agent("lynx"'),
    ('build_concrete_agent("mus"', 'build_concrete_agent("lynx"'),
    ('build_concrete_agent("acinonyx"', 'build_concrete_agent("panthera"'),
    ('build_concrete_agent("neofelis"', 'build_concrete_agent("panthera"'),
    ('filter_agent_capabilities("acinonyx"', 'filter_agent_capabilities("panthera"'),
    ('hosted_tools_for_agent("neofelis"', 'hosted_tools_for_agent("panthera"'),
    ('hosted_tools_for_agent("delphinus"', 'hosted_tools_for_agent("panthera"'),
    ('hosted_tools_for_agent("orcinus"', 'hosted_tools_for_agent("panthera"'),
]

SKIP = {
    "test_agent_catalog.py",
    "test_agent_prompt_composition.py",
    "test_agent_query_validation.py",
    "test_settings_migrations.py",
    "test_synthesis.py",
    "agent_fixtures.py",
    "update_test_agent_keys.py",
}


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "tests"
    for path in root.rglob("*.py"):
        if path.name in SKIP:
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"updated {path.relative_to(root.parent)}")


if __name__ == "__main__":
    main()
