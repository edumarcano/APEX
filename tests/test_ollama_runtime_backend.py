"""Regression coverage for Ollama local-runtime backend lock invariants."""

from __future__ import annotations

import threading
import unittest
from unittest import mock

from core.agent.providers.ollama_lifecycle import OllamaRuntimeBackend


class OllamaRuntimeBackendLockTests(unittest.TestCase):
    def test_status_snapshot_probes_outside_status_lock(self) -> None:
        backend = OllamaRuntimeBackend()
        status_lock_held_during_probe: list[bool] = []

        def probe_tags() -> tuple[bool, list[str]]:
            status_lock_held_during_probe.append(backend._status_lock.locked())
            return True, ["qwen3:4b-instruct"]

        def probe_loaded() -> list[object]:
            status_lock_held_during_probe.append(backend._status_lock.locked())
            return []

        with (
            mock.patch(
                "core.agent.providers.ollama_lifecycle._probe_ollama_tags",
                side_effect=probe_tags,
            ),
            mock.patch(
                "core.agent.providers.ollama_lifecycle._probe_ollama_loaded_models",
                side_effect=probe_loaded,
            ),
        ):
            snapshot = backend.get_status_snapshot(force_refresh=True)

        self.assertTrue(snapshot["reachable"])
        self.assertEqual(status_lock_held_during_probe, [False, False])

    def test_invalidate_does_not_wait_on_probe_lock(self) -> None:
        backend = OllamaRuntimeBackend()
        entered = threading.Event()
        release = threading.Event()

        def probe_tags() -> tuple[bool, list[str]]:
            entered.set()
            release.wait(timeout=2.0)
            return True, ["qwen3:4b-instruct"]

        def run_probe() -> None:
            with (
                mock.patch(
                    "core.agent.providers.ollama_lifecycle._probe_ollama_tags",
                    side_effect=probe_tags,
                ),
                mock.patch(
                    "core.agent.providers.ollama_lifecycle._probe_ollama_loaded_models",
                    return_value=[],
                ),
            ):
                backend.get_status_snapshot(force_refresh=True)

        worker = threading.Thread(target=run_probe)
        worker.start()
        self.assertTrue(entered.wait(timeout=2.0))
        # Invalidation must complete while the probe is still in flight.
        backend.invalidate_status_snapshot()
        release.set()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
