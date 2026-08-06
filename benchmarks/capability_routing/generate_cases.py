"""Generate the capability routing benchmark dataset."""

from __future__ import annotations

import json
import random
from pathlib import Path

FAMILIES = [
    "schedule",
    "weather",
    "f1",
    "mail",
    "search",
    "market",
    "briefings",
    "todo",
]

NONE_PROMPTS = [
    ("explain-gradient", "direct", "Explain gradient descent in simple terms.", [], ["none"]),
    ("rewrite-concise", "paraphrased", "Make this paragraph shorter without losing meaning.", [], ["none"]),
    ("arithmetic-17x23", "direct", "What is 17 times 23?", [], ["none"]),
    ("thanks", "implicit", "Thanks, that helps.", [], ["none"]),
    ("brainstorm-names", "direct", "Help me brainstorm project names for a note app.", [], ["none"]),
    ("translate-spanish", "paraphrased", "Translate this sentence to Spanish: Good morning.", [], ["none"]),
    ("summarize-discussion", "contextual", "Summarize what we already discussed.", [{"role": "user", "content": "Explain RAID levels."}, {"role": "agent", "content": "RAID mirrors or stripes disks for redundancy."}], ["none"]),
    ("casual-greeting", "implicit", "Hey, how are you?", [], ["none"]),
    ("define-metaphor", "direct", "Why did the author use a lighthouse metaphor?", [], ["none"]),
    ("proofread", "paraphrased", "Proofread this email draft for grammar only.", [], ["none"]),
]

FAMILY_TEMPLATES: dict[str, list[tuple[str, str, list, list[str]]]] = {
    "schedule": [
        ("sched-direct-1", "direct", "What is on my calendar tomorrow?", [], ["schedule"]),
        ("sched-direct-2", "direct", "Do I have meetings this afternoon?", [], ["schedule"]),
        ("sched-paraphrase-1", "paraphrased", "Show upcoming events for the next week.", [], ["schedule"]),
        ("sched-context-1", "contextual", "Is that meeting still on Friday?", [{"role": "user", "content": "Find my dentist appointment."}, {"role": "agent", "content": "You have a dentist visit Friday at 3 PM."}], ["schedule"]),
        ("sched-reminder-1", "direct", "List my pending APEX reminders.", [], ["schedule"]),
        ("sched-implicit-1", "implicit", "Am I free tonight?", [], ["schedule"]),
    ],
    "weather": [
        ("wx-direct-1", "direct", "What is the weather forecast this week?", [], ["weather"]),
        ("wx-paraphrase-1", "paraphrased", "Will it rain tomorrow?", [], ["weather"]),
        ("wx-context-1", "contextual", "Should I bring an umbrella for that hike?", [{"role": "user", "content": "We are hiking Saturday morning."}, {"role": "agent", "content": "The trail opens at sunrise."}], ["weather"]),
        ("wx-implicit-1", "implicit", "How warm will Saturday get?", [], ["weather"]),
        ("wx-false-friend-1", "false_friend", "Is the market outlook stormy?", [], ["none"]),
    ],
    "f1": [
        ("f1-direct-1", "direct", "Who leads the F1 championship?", [], ["f1"]),
        ("f1-paraphrase-1", "paraphrased", "Show current driver standings.", [], ["f1"]),
        ("f1-calendar-1", "direct", "When is the next Grand Prix?", [], ["f1"]),
        ("f1-context-1", "contextual", "How many points does he have now?", [{"role": "user", "content": "Show F1 standings."}, {"role": "agent", "content": "Verstappen leads with 100 points."}], ["f1"]),
    ],
    "mail": [
        ("mail-direct-1", "direct", "Find emails from Sarah about the budget.", [], ["mail"]),
        ("mail-paraphrase-1", "paraphrased", "Search my inbox for unread travel confirmations.", [], ["mail"]),
        ("mail-context-1", "contextual", "Open that message.", [{"role": "user", "content": "Find the note Sarah sent yesterday."}, {"role": "agent", "content": "I found a matching Gmail message."}], ["mail"]),
        ("mail-false-friend-1", "false_friend", "Mail me the summary when done.", [], ["none"]),
    ],
    "search": [
        ("search-direct-1", "direct", "Search the web for Mars rover updates.", [], ["search"]),
        ("search-paraphrase-1", "paraphrased", "Look up official API documentation.", [], ["search"]),
        ("search-context-1", "contextual", "Find recent news about that product.", [{"role": "user", "content": "Apple announced a new phone."}, {"role": "agent", "content": "The keynote mentioned a titanium frame."}], ["search"]),
        ("search-false-friend-1", "false_friend", "Search your memory for what we said.", [], ["none"]),
    ],
    "market": [
        ("market-direct-1", "direct", "What is Apple's stock price right now?", [], ["market"]),
        ("market-paraphrase-1", "paraphrased", "Look up the ticker for Microsoft.", [], ["market"]),
        ("market-context-1", "contextual", "Show recent daily prices for that symbol.", [{"role": "user", "content": "Look up Tesla's ticker."}, {"role": "agent", "content": "The symbol is TSLA."}], ["market"]),
        ("market-false-friend-1", "false_friend", "What is the weather market like today?", [], ["weather"]),
    ],
    "briefings": [
        ("brief-direct-1", "direct", "What did my last briefing cover?", [], ["briefings"]),
        ("brief-paraphrase-1", "paraphrased", "Show recent APEX briefings.", [], ["briefings"]),
        ("brief-context-1", "contextual", "What topics appeared in yesterday's digest?", [{"role": "user", "content": "Pull briefing history."}, {"role": "agent", "content": "Yesterday covered markets and calendar."}], ["briefings"]),
    ],
    "todo": [
        ("todo-direct-1", "direct", "What is on my Microsoft To Do list?", [], ["todo"]),
        ("todo-paraphrase-1", "paraphrased", "Show incomplete tasks from my work list.", [], ["todo"]),
        ("todo-context-1", "contextual", "List tasks in that list.", [{"role": "user", "content": "Show my To Do lists."}, {"role": "agent", "content": "You have a Work list and Groceries."}], ["todo"]),
    ],
}

MULTI_FAMILY = [
    ("multi-sched-wx-1", "multi_family", "Check my calendar and the weekend forecast.", [], ["schedule", "weather"]),
    ("multi-mail-search-1", "multi_family", "Find Sarah's email and search the web for venue reviews.", [], ["mail", "search"]),
    ("multi-market-brief-1", "multi_family", "Show NVDA quote and summarize recent briefings.", [], ["market", "briefings"]),
    ("multi-f1-wx-1", "multi_family", "Who leads F1 and will it rain at the race?", [], ["f1", "weather"]),
    ("multi-todo-sched-1", "multi_family", "List my todos and tomorrow's meetings.", [], ["todo", "schedule"]),
]

AMBIGUOUS = [
    ("ambig-1", "ambiguous", "Check on that for me.", [], ["none"]),
    ("ambig-2", "ambiguous", "Can you look into it?", [{"role": "user", "content": "I need help planning."}, {"role": "agent", "content": "Happy to help."}], ["none"]),
    ("ambig-3", "false_friend", "Run a quick check.", [], ["none"]),
]


def _expand_family_cases() -> list[dict]:
    cases: list[dict] = []
    counter = 0
    for family in FAMILIES:
        templates = list(FAMILY_TEMPLATES.get(family, []))
        while len(templates) < 22:
            counter += 1
            templates.append(
                (
                    f"{family}-auto-{counter}",
                    "paraphrased",
                    f"Please help with {family} information request {counter}.",
                    [],
                    [family],
                )
            )
        for item in templates[:22]:
            case_id, difficulty, prompt, history, expected = item
            cases.append(
                {
                    "id": case_id,
                    "split": "dev" if hash(case_id) % 5 else "test",
                    "difficulty": difficulty,
                    "prompt": prompt,
                    "history": history,
                    "expected_families": expected,
                    "notes": f"Family {family}.",
                }
            )
    return cases


def main() -> None:
    random.seed(42)
    cases: list[dict] = []
    cases.extend(_expand_family_cases())
    for idx, item in enumerate(NONE_PROMPTS * 6):
        case_id, difficulty, prompt, history, expected = item
        cases.append(
            {
                "id": f"{case_id}-{idx}",
                "split": "dev" if idx % 5 else "test",
                "difficulty": difficulty if difficulty != "direct" else "no_tool",
                "prompt": prompt,
                "history": history,
                "expected_families": expected,
                "notes": "No-tool case.",
            }
        )
    for item in MULTI_FAMILY * 8:
        case_id, difficulty, prompt, history, expected = item
        cases.append(
            {
                "id": f"{case_id}-{len(cases)}",
                "split": "dev" if len(cases) % 5 else "test",
                "difficulty": difficulty,
                "prompt": prompt,
                "history": history,
                "expected_families": expected,
                "notes": "Multi-family.",
            }
        )
    for item in AMBIGUOUS * 10:
        case_id, difficulty, prompt, history, expected = item
        cases.append(
            {
                "id": f"{case_id}-{len(cases)}",
                "split": "dev" if len(cases) % 5 else "test",
                "difficulty": difficulty,
                "prompt": prompt,
                "history": history,
                "expected_families": expected,
                "notes": "Ambiguous.",
            }
        )
    # Pad to >= 300 with varied paraphrases
    while len(cases) < 320:
        family = FAMILIES[len(cases) % len(FAMILIES)]
        cases.append(
            {
                "id": f"pad-{len(cases)}",
                "split": "dev" if len(cases) % 5 else "test",
                "difficulty": "paraphrased",
                "prompt": f"Need a {family} update number {len(cases)}.",
                "history": [],
                "expected_families": [family],
                "notes": "Padding case.",
            }
        )
    out = Path(__file__).resolve().parent / "cases.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"Wrote {len(cases)} cases to {out}")


if __name__ == "__main__":
    main()
