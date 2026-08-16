"""Reconciliation helpers for Panthera/Lynx provider-runtime-model routes."""

from __future__ import annotations

import unittest
from unittest import mock

from core.agent.model_catalog import (
    reconcile_lynx_context_window,
    reconcile_lynx_runtime_model,
    reconcile_panthera_provider_model,
)
from core.settings.normalize import normalize_layer


class ModelCatalogReconcileTests(unittest.TestCase):
    def test_panthera_dev_only_model_falls_back_when_dev_mode_false(self) -> None:
        with mock.patch("core.config.is_dev_mode", return_value=False):
            provider, model = reconcile_panthera_provider_model(
                "xai",
                "grok-4.5",
                dev_mode=False,
            )

        self.assertEqual((provider, model), ("openai", "gpt-5.6-luna"))

    def test_lynx_dev_only_model_falls_back_when_dev_mode_false(self) -> None:
        with mock.patch("core.config.is_dev_mode", return_value=False):
            runtime, model = reconcile_lynx_runtime_model(
                "ollama",
                "qwen3:1.7b",
                dev_mode=False,
            )

        self.assertEqual((runtime, model), ("llama_cpp", "gemma-4-E2B-Q4_K_M.gguf"))

    def test_dev_only_selections_remain_when_dev_mode_true(self) -> None:
        with mock.patch("core.config.is_dev_mode", return_value=True):
            panthera = reconcile_panthera_provider_model(
                "xai",
                "grok-4.5",
                dev_mode=True,
            )
            lynx = reconcile_lynx_runtime_model(
                "ollama",
                "qwen3:1.7b",
                dev_mode=True,
            )

        self.assertEqual(panthera, ("xai", "grok-4.5"))
        self.assertEqual(lynx, ("ollama", "qwen3:1.7b"))

    def test_normalize_layer_reconciles_saved_dev_only_panthera_route(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "panthera": {
                            "provider": "xai",
                            "model": "grok-4.5",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        panthera = normalized["ask_apex"]["panthera"]
        self.assertEqual(panthera["model"], "gpt-5.6-luna")
        self.assertNotIn("provider", panthera)

    def test_normalize_layer_reconciles_model_only_dev_only_panthera(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "panthera": {
                            "model": "grok-4.5",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        panthera = normalized["ask_apex"]["panthera"]
        self.assertEqual(panthera["model"], "gpt-5.6-luna")
        self.assertNotIn("provider", panthera)

    def test_normalize_layer_reconciles_saved_dev_only_lynx_route(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "lynx": {
                            "runtime": "ollama",
                            "model": "qwen3:4b-instruct",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        lynx = normalized["ask_apex"]["lynx"]
        self.assertEqual(lynx["model"], "gemma-4-E2B-Q4_K_M.gguf")
        self.assertNotIn("runtime", lynx)

    def test_normalize_layer_reconciles_model_only_dev_only_lynx(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "lynx": {
                            "model": "qwen3:1.7b",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        lynx = normalized["ask_apex"]["lynx"]
        self.assertEqual(lynx["model"], "gemma-4-E2B-Q4_K_M.gguf")
        self.assertNotIn("runtime", lynx)

    def test_lynx_model_change_reconciles_incompatible_context_window(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            normalized = normalize_layer(
                {
                    "ask_apex": {
                        "lynx": {
                            "runtime": "llama_cpp",
                            "model": "gemma-4-E2B-Q4_K_M.gguf",
                            "context_window": 131072,
                            "reasoning_mode": "focused",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        lynx = normalized["ask_apex"]["lynx"]
        self.assertEqual(lynx["context_window"], 131072)
        self.assertEqual(lynx["reasoning_mode"], "focused")

        with mock.patch("core.settings.normalize.is_dev_mode", return_value=False):
            switched = normalize_layer(
                {
                    "ask_apex": {
                        "lynx": {
                            "runtime": "llama_cpp",
                            "model": "gemma-4-E4B-Q4_K_M.gguf",
                            "context_window": 131072,
                            "reasoning_mode": "focused",
                        }
                    }
                },
                layer_name="config.local.json",
            )

        updated = switched["ask_apex"]["lynx"]
        self.assertEqual(updated["model"], "gemma-4-E4B-Q4_K_M.gguf")
        self.assertEqual(updated["context_window"], 16384)
        self.assertEqual(updated["reasoning_mode"], "focused")

    def test_reconcile_lynx_context_window_keeps_supported_preset(self) -> None:
        self.assertEqual(
            reconcile_lynx_context_window(
                "llama_cpp",
                "gemma-4-E4B-Q4_K_M.gguf",
                65536,
            ),
            65536,
        )
