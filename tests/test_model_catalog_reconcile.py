"""Reconciliation coverage for singular APEX Agent model routes."""

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
            reconcile_cloud_model("gemini-3.7-flash"),
            "gemini-3.7-flash",
        )
        self.assertEqual(
            reconcile_cloud_model("openai/gpt-6-luna"),
            "openai/gpt-6-luna",
        )

    def test_unknown_cloud_model_falls_back_to_default(self) -> None:
        self.assertEqual(
            reconcile_cloud_model("nonexistent-cloud-model"),
            DEFAULT_CLOUD_MODEL,
        )

    def test_visible_local_model_remains_selected(self) -> None:
        self.assertEqual(
            reconcile_local_model("gemma-4-E2B-Q4_K_M.gguf"),
            "gemma-4-E2B-Q4_K_M.gguf",
        )

    def test_retired_models_fall_back_to_their_runtime_defaults(self) -> None:
        retired_models = (
            ("cloud", "gpt-5.6-luna", DEFAULT_CLOUD_MODEL),
            ("local", "qwen3:1.7b", DEFAULT_LOCAL_MODEL),
            ("local", "gemma-4-E4B-Q4_K_M.gguf", DEFAULT_LOCAL_MODEL),
            ("local", "Qwen3.5-4B-Q4_K_M.gguf", DEFAULT_LOCAL_MODEL),
        )
        for runtime, model_id, expected in retired_models:
            with self.subTest(runtime=runtime, model=model_id):
                reconcile = reconcile_cloud_model if runtime == "cloud" else reconcile_local_model
                self.assertEqual(reconcile(model_id), expected)

    def test_local_context_window_reconciles_to_model_capabilities(self) -> None:
        self.assertEqual(
            reconcile_local_context_window(
                "llama_cpp", "gemma-4-E2B-Q4_K_M.gguf", 16384
            ),
            16384,
        )
        self.assertEqual(
            reconcile_local_context_window(
                "llama_cpp", "gemma-4-E2B-Q4_K_M.gguf", 65536
            ),
            16384,
        )


if __name__ == "__main__":
    unittest.main()
