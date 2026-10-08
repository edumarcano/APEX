from __future__ import annotations

import json
import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import diagnose_distribution_sapi as diagnostics


def _diagnostic_payload(gender: str = "male", *, worker_exit_code: int = 3, wav_frames: int = 0) -> bytes:
    return json.dumps({
        "schema_version": 1,
        "scenario": "sapi-export-diagnostic",
        "status": "diagnostic",
        "voice_gender": gender,
        "worker_exit_code": worker_exit_code,
        "wav_present": True,
        "wav_bytes": 46,
        "wav_frames": wav_frames,
        "wav_rate": 22050,
        "wav_channels": 1,
        "wav_sample_width_bytes": 2,
        "wav_duration_seconds": 0.0,
        "wav_parse_error_type": None,
        "error_event_count": 1,
        "errors": [{
            "exception_type": "RuntimeError",
            "hresult": -1,
            "sapi_save_to_file_line_offset": 34,
        }],
        "private_extra": "must not be projected",
    }).encode("utf-8")


class DistributionSapiDiagnosticsTests(unittest.TestCase):
    def test_runs_source_and_frozen_in_both_environment_contexts(self) -> None:
        scratch = Path.cwd() / "apex-smoke-測試-fixture"
        project = scratch / "project"
        frozen = project / "build" / "apex-bundle-probe.exe"
        emitted: list[dict[str, object]] = []
        with mock.patch.dict("os.environ", {"USERPROFILE": "private-profile", "PROGRAMDATA": "private-program-data"}), \
                mock.patch.object(Path, "is_file", return_value=True), \
                mock.patch.object(Path, "mkdir"), \
                mock.patch.object(Path, "exists", return_value=False), \
                mock.patch.object(Path, "write_text"), \
                mock.patch.object(
                    diagnostics.subprocess,
                    "run",
                    side_effect=lambda command, **_kwargs: subprocess.CompletedProcess(
                        command, 0, _diagnostic_payload(command[-1]), b"private stderr"
                    ),
                ) as run, \
                mock.patch.object(diagnostics, "_sanitized_environment", wraps=diagnostics._sanitized_environment) as sanitized_environment:
            results = diagnostics.run_diagnostics(
                frozen,
                project_root=project,
                scratch_root=scratch / "scratch",
                on_result=emitted.append,
            )

        self.assertEqual(len(run.call_args_list), 8)
        self.assertEqual(len(results), 8)
        self.assertEqual(emitted, results)
        self.assertEqual(
            [
                (result["environment"], result["mode"], result["voice_gender"])
                for result in results
            ],
            [
                (context, mode, gender)
                for context in ("normal", "strict-sanitized")
                for mode in ("source", "frozen")
                for gender in ("male", "female")
            ],
        )
        source_command = run.call_args_list[0].args[0]
        frozen_command = run.call_args_list[2].args[0]
        self.assertEqual(source_command[0], diagnostics.sys.executable)
        self.assertTrue(Path(source_command[1]).is_absolute())
        self.assertEqual(frozen_command[0], str(frozen.resolve()))
        self.assertNotIn(str((project / "packaging" / "windows" / "smoke" / "probe.py").resolve()), frozen_command)
        self.assertEqual(results[0]["worker_exit_code"], 3)
        self.assertEqual(results[0]["wav_frames"], 0)
        self.assertEqual(results[0]["errors"], [{
            "exception_type": "RuntimeError",
            "hresult": -1,
            "sapi_save_to_file_line_offset": 34,
        }])
        projected = json.dumps(results)
        self.assertNotIn("private_extra", projected)
        self.assertNotIn("private stderr", projected)
        strict_env = run.call_args_list[4].kwargs["env"]
        self.assertEqual(sanitized_environment.call_count, 4)
        self.assertNotIn("USERPROFILE", strict_env)
        self.assertNotIn("PROGRAMDATA", strict_env)
        self.assertIn("測試", strict_env["TEMP"])

    def test_private_output_and_timeout_details_are_not_exposed(self) -> None:
        env = {"APEX_DATA_DIR": "private-profile"}
        with mock.patch.object(
            diagnostics.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, b"private stdout", b"private stderr"),
        ):
            with self.assertRaisesRegex(diagnostics.DiagnosticError, "output was invalid") as invalid:
                diagnostics._invoke(["probe"], environment=env, cwd=Path("."), mode="frozen", context="strict-sanitized", gender="male")
        self.assertNotIn("private", str(invalid.exception))

        with mock.patch.object(
            diagnostics.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["probe"], 60, output=b"private stdout", stderr=b"private stderr"),
        ):
            with self.assertRaisesRegex(diagnostics.DiagnosticError, "timed out") as timed_out:
                diagnostics._invoke(
                    ["probe"], environment=env, cwd=Path("."), mode="frozen", context="strict-sanitized", gender="male"
                )
        self.assertNotIn("private", str(timed_out.exception))

    def test_source_only_without_frozen_probe_fails_on_empty_wav(self) -> None:
        scratch = Path.cwd() / "apex-smoke-測試-source-only"
        output = io.StringIO()
        error = io.StringIO()
        temporary_directory = mock.MagicMock()
        temporary_directory.__enter__.return_value = str(scratch)
        temporary_directory.__exit__.return_value = False
        with mock.patch.object(diagnostics.tempfile, "TemporaryDirectory", return_value=temporary_directory), \
                mock.patch.object(Path, "is_file", return_value=True), \
                mock.patch.object(Path, "mkdir"), \
                mock.patch.object(Path, "exists", return_value=False), \
                mock.patch.object(Path, "write_text"), \
                mock.patch.object(
                    diagnostics.subprocess,
                    "run",
                    side_effect=lambda command, **_kwargs: subprocess.CompletedProcess(
                        command,
                        0,
                        _diagnostic_payload(command[-1], worker_exit_code=0, wav_frames=0),
                        b"private stderr",
                    ),
                ) as run, \
                redirect_stdout(output), redirect_stderr(error):
            exit_code = diagnostics.main(["--source-only"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(run.call_count, 4)
        self.assertTrue(all(call.args[0][0] == diagnostics.sys.executable for call in run.call_args_list))
        self.assertTrue(all("apex-bundle-probe.exe" not in " ".join(call.args[0]) for call in run.call_args_list))
        self.assertEqual(output.getvalue().count("APEX_SAPI_EXPORT_DIAGNOSTIC {"), 4)
        self.assertIn('"wav_frames":0', output.getvalue())
        self.assertIn("reason=source-audio-unhealthy", error.getvalue())
        self.assertNotIn("private", output.getvalue() + error.getvalue())


if __name__ == "__main__":
    unittest.main()
