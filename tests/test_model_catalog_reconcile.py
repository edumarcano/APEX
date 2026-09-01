"""Reconciliation coverage for singular Apex Agent model routes."""

from __future__ import annotations

import unittest

from core.agent.model_catalog import (
    DEFAULT_CLOUD_MODEL,
    DEFAULT_LOCAL_MODEL,
    reconcile_cloud_model,
    reconcile_local_context_window,
    reconcile_local_model,
)


class ModelCatalogReconcileTests(unittest.TestCase):
    def test_visible_cloud_model_remains_selected(self) -> None:
        self.assertEqual(
            reconcile_cloud_model("gemini-3.7-flash", dev_mode=False),
            "gemini-3.7-flash",
        )

    def test_unknown_cloud_model_falls_back_to_default(self) -> None:
        self.assertEqual(
            reconcile_cloud_model("nonexistent-cloud-model", dev_mode=False),
            DEFAULT_CLOUD_MODEL,
        )

    def test_hidden_local_model_falls_back_outside_dev_mode(self) -> None:
        self.assertEqual(reconcile_local_model("qwen3:1.7b", dev_mode=False), DEFAULT_LOCAL_MODEL)

    def test_visible_local_model_remains_selected(self) -> None:
        self.assertEqual(
            reconcile_local_model("Qwen3.5-4B-Q4_K_M.gguf", dev_mode=False),
            "Qwen3.5-4B-Q4_K_M.gguf",
        )

    def test_dev_only_models_remain_when_development_mode_is_enabled(self) -> None:
        self.assertEqual(reconcile_cloud_model("gemini-3.7-flash", dev_mode=True), "gemini-3.7-flash")
        self.assertEqual(reconcile_local_model("qwen3:1.7b", dev_mode=True), "qwen3:1.7b")

    def test_local_context_window_reconciles_to_model_capabilities(self) -> None:
        self.assertEqual(
            reconcile_local_context_window(
                "llama_cpp", "gemma-4-E4B-Q4_K_M.gguf", 65536
            ),
            65536,
        )


if __name__ == "__main__":
    unittest.main()
