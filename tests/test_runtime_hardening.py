"""Coverage for run ID context propagation into logs and metadata."""

from __future__ import annotations

import logging
import unittest

from core.api.models import RuntimeMetadata
from core.api.state import PipelineState
from core.runtime_logging import get_run_id, run_id_scope


class RunIdPropagationTests(unittest.TestCase):
    def test_run_id_scope_binds_context(self) -> None:
        self.assertIsNone(get_run_id())
        with run_id_scope("abc-123"):
            self.assertEqual(get_run_id(), "abc-123")
        self.assertIsNone(get_run_id())

    def test_pipeline_state_exposes_run_id(self) -> None:
        state = PipelineState()
        self.assertIsNone(state.get_state())
        state.begin_run("run-xyz")
        state.update(1, "GATE")
        snapshot = state.get_state()
        assert snapshot is not None
        self.assertEqual(snapshot["run_id"], "run-xyz")
        self.assertEqual(snapshot["step"], 1)
        state.reset()
        self.assertIsNone(state.get_state())

    def test_runtime_metadata_persists_run_id(self) -> None:
        metadata = RuntimeMetadata(
            run_id="run-persist",
            dev_mode_active=False,
            demo_mode_active=False,
            synthesis_strategy="cloud",
            tts_strategy="google",
            active_tts_engine="google",
            system_load_throttled=False,
        )
        dumped = metadata.model_dump()
        self.assertEqual(dumped["run_id"], "run-persist")
        restored = RuntimeMetadata.model_validate(dumped)
        self.assertEqual(restored.run_id, "run-persist")

    def test_logger_includes_run_id_filter(self) -> None:
        from core.runtime_logging import RunIdFilter, configure_logging

        configure_logging()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        with run_id_scope("log-run"):
            self.assertTrue(RunIdFilter().filter(record))
            self.assertEqual(getattr(record, "run_id"), "log-run")


if __name__ == "__main__":
    unittest.main()
