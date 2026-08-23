"""Reconciliation helpers for Cloud/Local model routes."""

from __future__ import annotations

import unittest
from unittest import mock

from core.agent.model_catalog import (
    reconcile_cloud_model,
    reconcile_local_context_window,
    reconcile_local_model,
)
from core.settings.normalize import normalize_layer


class ModelCatalogReconcileTests(unittest.TestCase):
    def test_cloud_dev_only_model_falls_back_when_dev_mode_false(self) -> None:
        with mock.patch("core.config.is_dev_mode", return_value=False):
            model = reconcile_cloud_model(
                "grok-4.5",
                dev_mode=False,
            )

        self.assertEqual(model, "gpt-5.6-luna")

    def test_local_dev_only_model_falls_back_when_dev_mode_false(self) -> None:
        with mock.patch("core.config.is_dev_mode", return_value=False):
            model = reconcile_local_model(
                "qwen3:1.7b",
                dev_mode=False,
            )

        self.assertEqual(model, "gemma-4-E2B-Q4_K_M.gguf")

    def test_local_qwen35_model_remains_when_dev_mode_false(self) -> None:
        with mock.patch("core.config.is_dev_mode", return_value=False):
            model = reconcile_local_model(
                "Qwen3.5-4B-Q4_K_M.gguf",
                dev_mode=False,
            )

        self.assertEqual(model, "Qwen3.5-4B-Q4_K_M.gguf")

    def test_dev_only_selections_remain_when_dev_mode_true(self) -> None:
        with mock.patch("core.config.is_dev_mode", return_value=True):
            cloud = reconcile_cloud_model(
                "grok-4.5",
                dev_mode=True,
            )
            local = reconcile_local_model(
                "qwen3:1.7b",
                dev_mode=True,
            )

        self.assertEqual(cloud, "grok-4.5")
        self.assertEqual(local, "qwen3:1.7b")

    def test_normalize_layer_reconciles_model_only_dev_only_cloud(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "cloud": {
                            "model": "grok-4.5",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        cloud = normalized["ask_apex"]["cloud"]
        self.assertEqual(cloud["model"], "gpt-5.6-luna")

    def test_normalize_layer_reconciles_model_only_dev_only_local(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "local": {
                            "model": "qwen3:1.7b",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        local = normalized["ask_apex"]["local"]
        self.assertEqual(local["model"], "gemma-4-E2B-Q4_K_M.gguf")

    def test_local_model_change_reconciles_incompatible_context_window(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "local": {
                            "model": "gemma-4-E2B-Q4_K_M.gguf",
                            "context_window": 131072,
                            "reasoning_mode": "focused",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        local = normalized["ask_apex"]["local"]
        self.assertEqual(local["context_window"], 131072)
        self.assertEqual(local["reasoning_mode"], "focused")

        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            switched = normalize_layer(
                {
                    "ask_apex": {
                        "local": {
                            "model": "gemma-4-E4B-Q4_K_M.gguf",
                            "context_window": 131072,
                            "reasoning_mode": "focused",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        updated = switched["ask_apex"]["local"]
        self.assertEqual(updated["model"], "gemma-4-E4B-Q4_K_M.gguf")
        self.assertEqual(updated["context_window"], 16384)
        self.assertEqual(updated["reasoning_mode"], "focused")

    def test_reconcile_local_context_window_keeps_supported_preset(self) -> None:
        self.assertEqual(
            reconcile_local_context_window(
                "llama_cpp",
                "gemma-4-E4B-Q4_K_M.gguf",
                65536,
            ),
            65536,
        )


if __name__ == "__main__":
    unittest.main()
