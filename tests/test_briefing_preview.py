from __future__ import annotations

import unittest
import json
from uuid import uuid4

from core.briefings.daily_inputs import _evidence
from core.briefings.preview import BriefingPreviewParser


class BriefingPreviewParserTests(unittest.TestCase):
    def test_exposes_only_completed_validated_sections_from_fragmented_json(self) -> None:
        evidence = _evidence(
            source="reminders", source_id="task-1", identity_kind="provider", trust="observed",
            content="Prepare the roadmap review.",
        )
        parser = BriefingPreviewParser()
        section = json.dumps({
            "title": "Today",
            "items": [{
                "category": "observation", "title": "Roadmap review",
                "body": 'Prepare the review "today".', "evidence_ids": [str(evidence.id)],
            }],
        }, separators=(",", ":"))
        self.assertIsNone(parser.feed('{"sections":[' + section[:-1], [evidence]))
        completed = parser.feed(section[-1], [evidence])
        self.assertEqual(completed, [{
            "title": "Today",
            "items": [{
                "category": "observation",
                "title": "Roadmap review",
                "body": 'Prepare the review "today".',
            }],
        }])

    def test_does_not_expose_items_with_unknown_or_mismatched_evidence(self) -> None:
        evidence = _evidence(
            source="reminders", source_id="task-1", identity_kind="provider", trust="observed",
            content="A reminder.",
        )
        unknown = uuid4()
        parser = BriefingPreviewParser()
        hidden = parser.feed(
            f'{{"sections":[{{"title":"Today","items":[{{"category":"observation","title":"Unsupported",'
            f'"body":"Not supported.","evidence_ids":["{unknown}"]}}]}}]}}',
            [evidence],
        )
        self.assertIsNone(hidden)
        self.assertEqual(parser.sections, [])

        parser = BriefingPreviewParser()
        trust_mismatch = parser.feed(
            json.dumps({"sections": [{"title": "Today", "items": [{
                "category": "accepted_context", "title": "Mismatched",
                "body": "Wrong trust.", "evidence_ids": [str(evidence.id)],
            }]}]}),
            [evidence],
        )
        self.assertIsNone(trust_mismatch)
        self.assertEqual(parser.sections, [])


if __name__ == "__main__":
    unittest.main()
