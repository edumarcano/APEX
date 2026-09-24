from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

from core.api import app
from core.context_vault.selection import ContextVaultSelectionService
from core.knowledge.service import KnowledgeService
from core.knowledge.store import KnowledgeStore
from core.retrieval.store import RetrievalStore
from core.settings.models import ContextVaultScopeSettings, ContextVaultSettings


class ContextVaultApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="apex_context_vault_api_")
        self.path = Path(self.temp_dir.name) / "knowledge.db"
        self.retrieval = RetrievalStore(self.path)
        self.retrieval.initialize()
        self.store = KnowledgeStore(self.path)
        self.store.initialize()
        self.knowledge = KnowledgeService(self.store)
        self.client = TestClient(app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        self.store.close()
        self.retrieval.close()
        self.temp_dir.cleanup()

    def _record(self):
        entity = self.store.create_entity("Project Wire")
        source = self.store.create_source(
            kind="manual", partition="production", locator="private/wire/locator",
            original_text="Private source text that must not appear in preview.",
        )
        return self.store.create_record(
            partition="production", kind="note", text="Public canonical claim.",
            source_ids=(source.id,), subject_entity_id=entity.id,
            predicate="has_status", object_value="ready",
        )

    def test_preview_route_serializes_public_contract_and_missing_scope_is_404(self) -> None:
        record = self._record()
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Wire scope", enabled=True, record_ids=(record.id,),
        )
        service = ContextVaultSelectionService(
            self.knowledge, ContextVaultSettings(enabled=True, scopes=(scope,)),
            destination_configured=True,
        )
        with mock.patch(
            "core.api.routers.cortex._context_vault_selection_service", return_value=service,
        ):
            response = self.client.post(
                "/api/v1/cortex/context-vault/preview", json={"scope_id": str(scope.id)},
            )
            missing = self.client.post(
                "/api/v1/cortex/context-vault/preview", json={"scope_id": str(uuid4())},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["eligible_count"], 1)
        self.assertEqual(payload["records"][0]["record_id"], str(record.id))
        self.assertEqual(payload["records"][0]["projected_path"], f"records/{record.id}.md")
        self.assertNotIn("source_metadata", payload["records"][0])
        self.assertNotIn("review_proposal", payload["records"][0])
        self.assertNotIn("private/wire/locator", json.dumps(payload))
        self.assertNotIn("Private source text", json.dumps(payload))
        self.assertEqual(missing.status_code, 404)

    def test_sensitivity_route_maps_stale_revision_and_blocks_demo_writes(self) -> None:
        record = self._record()
        conversation = mock.Mock()
        conversation.partition.return_value = "production"
        with mock.patch(
            "core.api.routers.cortex.get_knowledge_service", return_value=self.knowledge,
        ), mock.patch(
            "core.api.routers.cortex.get_conversation_service", return_value=conversation,
        ), mock.patch("core.api.routers.cortex.DEMO_MODE", False):
            stale = self.client.patch(
                f"/api/v1/cortex/context/{record.id}/sensitivity",
                json={"sensitive": True, "expected_updated_at": "stale-revision"},
            )

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"], "Context changed or cannot be reconciled.")

        with mock.patch("core.api.routers.cortex.DEMO_MODE", True):
            demo = self.client.patch(
                f"/api/v1/cortex/context/{record.id}/sensitivity",
                json={"sensitive": True, "expected_updated_at": record.updated_at},
            )

        self.assertEqual(demo.status_code, 403)
        self.assertFalse(self.store.get_record(record.id, partition="production").record.sensitive)


if __name__ == "__main__":
    unittest.main()
