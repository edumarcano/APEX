"""Trust-boundary checks for canonical briefing evidence references."""

from __future__ import annotations

import unittest
from uuid import uuid4

from core.briefings.models import (
    BriefingDraft,
    BriefingEvidence,
    BriefingItemDraft,
    BriefingSectionDraft,
    ExistingRecordReference,
    build_canonical_artifact,
)


class CanonicalBriefingEvidenceTests(unittest.TestCase):
    def _build(self, evidence: BriefingEvidence, item: BriefingItemDraft):
        return build_canonical_artifact(
            session_id=uuid4(),
            draft=BriefingDraft(
                sections=[BriefingSectionDraft(title="Summary", items=[item])]
            ),
            evidence=[evidence],
            coverage=[],
        )

    def test_unavailable_evidence_cannot_support_a_briefing_item(self) -> None:
        evidence = BriefingEvidence(
            source="calendar",
            source_id="event-1",
            available=False,
            unavailable_reason="The source record was removed.",
        )
        item = BriefingItemDraft(
            category="observation",
            title="Meeting",
            body="A meeting was scheduled.",
            evidence_ids=[evidence.id],
        )

        with self.assertRaisesRegex(ValueError, "Unavailable evidence"):
            self._build(evidence, item)

    def test_analysis_and_suggestion_may_cite_observed_evidence(self) -> None:
        evidence = BriefingEvidence(
            source="calendar",
            source_id="event-1",
            trust="observed",
            content="A planning meeting begins at 10:00.",
        )
        draft = BriefingDraft(
            sections=[
                BriefingSectionDraft(
                    title="Interpretation",
                    items=[
                        BriefingItemDraft(
                            category="analysis",
                            title="Schedule pressure",
                            body="The meeting is early in the day.",
                            evidence_ids=[evidence.id],
                        ),
                        BriefingItemDraft(
                            category="suggestion",
                            title="Preparation",
                            body="Consider reviewing the agenda beforehand.",
                            evidence_ids=[evidence.id],
                        ),
                    ],
                )
            ]
        )

        artifact = build_canonical_artifact(
            session_id=uuid4(), draft=draft, evidence=[evidence], coverage=[]
        )

        self.assertEqual(
            [item.category for item in artifact.sections[0].items],
            ["analysis", "suggestion"],
        )

    def test_observation_cannot_relabel_pending_or_untrusted_evidence(self) -> None:
        for trust in ("pending", "untrusted"):
            with self.subTest(trust=trust):
                evidence = BriefingEvidence(
                    source="reports",
                    source_id="report-1",
                    trust=trust,
                    content="An attributed report says conditions may change.",
                )
                item = BriefingItemDraft(
                    category="observation",
                    title="Reported conditions",
                    body="Conditions may change.",
                    evidence_ids=[evidence.id],
                )
                with self.assertRaisesRegex(ValueError, "trust category"):
                    self._build(evidence, item)

    def test_model_cannot_invent_typed_record_references(self) -> None:
        evidence = BriefingEvidence(
            source="actions",
            source_id="action-1",
            trust="observed",
            content="A task was verified.",
            record_reference=ExistingRecordReference(
                kind="action", id="task:custom-action-key"
            ),
        )
        fabricated_reference = ExistingRecordReference(
            kind="action", id="task:other-action-key"
        )
        item = BriefingItemDraft(
            category="observation",
            title="Verified task",
            body="The task is complete.",
            evidence_ids=[evidence.id],
            record_references=[fabricated_reference],
        )

        with self.assertRaisesRegex(ValueError, "Record references"):
            self._build(evidence, item)

    def test_matching_opaque_action_reference_is_preserved(self) -> None:
        action_reference = ExistingRecordReference(
            kind="action", id="task:operator-selected-id"
        )
        evidence = BriefingEvidence(
            source="actions",
            source_id="task:operator-selected-id",
            trust="observed",
            content="The action was verified.",
            record_reference=action_reference,
        )
        item = BriefingItemDraft(
            category="observation",
            title="Verified action",
            body="The action is complete.",
            evidence_ids=[evidence.id],
            record_references=[action_reference],
        )

        artifact = self._build(evidence, item)

        self.assertEqual(
            artifact.sections[0].items[0].record_references,
            [action_reference],
        )


if __name__ == "__main__":
    unittest.main()
