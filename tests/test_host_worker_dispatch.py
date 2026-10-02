from __future__ import annotations

import io
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.host import worker_dispatch


class WorkerCommandTests(unittest.TestCase):
    def test_source_command_routes_through_backend_host(self) -> None:
        with patch.object(worker_dispatch.sys, "frozen", False, create=True), patch.object(
            worker_dispatch.sys, "executable", "python.exe"
        ), patch.object(
            worker_dispatch.sys, "_base_executable", "python.exe", create=True
        ):
            command, _environment = worker_dispatch.worker_invocation("speech.wav")
            self.assertEqual(
                command,
                ["python.exe", "-m", "core.backend_host", "worker", "speech-export", "speech.wav"],
            )

    def test_frozen_command_uses_packaged_worker_entrypoint(self) -> None:
        with patch.object(worker_dispatch.sys, "frozen", True, create=True), patch.object(
            worker_dispatch.sys, "executable", "APEX.exe"
        ):
            command, _environment = worker_dispatch.worker_invocation("speech.wav")
            self.assertEqual(
                command,
                ["APEX.exe", "worker", "speech-export", "speech.wav"],
            )


class WorkerDispatchTests(unittest.TestCase):
    def test_non_worker_arguments_are_left_for_host(self) -> None:
        with patch.object(worker_dispatch.importlib, "import_module") as import_module:
            self.assertIsNone(worker_dispatch.dispatch_worker(["serve", "--port", "8000"]))
        import_module.assert_not_called()

    def test_only_speech_export_worker_with_one_argument_is_allowed(self) -> None:
        with patch.object(worker_dispatch.importlib, "import_module") as import_module:
            self.assertEqual(worker_dispatch.dispatch_worker(["worker"]), 2)
            self.assertEqual(worker_dispatch.dispatch_worker(["worker", "other", "x"]), 2)
            self.assertEqual(
                worker_dispatch.dispatch_worker(["worker", "speech-export"]), 2
            )
            self.assertEqual(
                worker_dispatch.dispatch_worker(
                    ["worker", "speech-export", "speech.wav", "extra"]
                ),
                2,
            )
        import_module.assert_not_called()

    def test_speech_export_import_is_lazy_and_receives_only_output_argument(self) -> None:
        received_arguments: list[str] = []
        export_module = types.SimpleNamespace(
            main=lambda argv: (received_arguments.extend(argv) or 0)
        )
        with patch.object(
            worker_dispatch.importlib,
            "import_module",
            return_value=export_module,
        ) as import_module:
            self.assertEqual(
                worker_dispatch.dispatch_worker(
                    ["worker", "speech-export", "speech.wav"]
                ),
                0,
            )
        import_module.assert_called_once_with("core.speaker_export")
        self.assertEqual(received_arguments, ["speech.wav"])


class SpeechExportWorkerTests(unittest.TestCase):
    def test_python_child_invocation_owns_the_real_interpreter_pid(self) -> None:
        from core.host.processes import python_child_invocation

        command, environment = python_child_invocation(
            [
                "-B",
                "-c",
                "import json,os,sys,fastapi; print(json.dumps({'pid':os.getpid(),'prefix':sys.prefix,'fastapi':fastapi.__version__}))",
            ],
            env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        )
        child = subprocess.Popen(
            command,
            env=environment,
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0, stderr)
        import json

        result = json.loads(stdout)
        self.assertEqual(result["pid"], child.pid)
        self.assertEqual(
            os.path.normcase(result["prefix"]),
            os.path.normcase(sys.prefix),
        )
        self.assertTrue(result["fastapi"])

    def test_worker_module_does_not_load_host_configuration_or_api(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = (
            "import sys; import core.speaker_export; "
            "assert not any(name == 'core.api' or name.startswith('core.api.') "
            "or name in {'core.config', 'core.settings', 'core.runtime_profile'} "
            "for name in sys.modules)"
        )
        subprocess.run(
            [sys.executable, "-B", "-c", command],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_worker_reads_json_and_passes_output_path_to_tts(self) -> None:
        from core import speaker_export

        class FakeOutputPath:
            def __str__(self) -> str:
                return "speech.wav"

            def is_file(self) -> bool:
                return True

            def stat(self) -> types.SimpleNamespace:
                return types.SimpleNamespace(st_size=3)

        class FakeEngine:
            def __init__(self) -> None:
                self.properties: list[tuple[str, object]] = []
                self.stopped = False
                self.output_path: str | None = None

            def setProperty(self, name: str, value: object) -> None:
                self.properties.append((name, value))

            def getProperty(self, name: str) -> list[object]:
                return []

            def save_to_file(self, text: str, path: str) -> None:
                self.asserted_text = text
                self.output_path = path

            def runAndWait(self) -> None:
                pass

            def stop(self) -> None:
                self.stopped = True

        engine = FakeEngine()
        pyttsx3_module = types.ModuleType("pyttsx3")
        pyttsx3_module.init = lambda: engine
        with (
            patch.object(
                speaker_export.sys,
                "stdin",
                new=io.StringIO(
                    '{"text":"A saved briefing.","gender":"female"}'
                ),
            ),
            patch.object(speaker_export, "Path", lambda _path: FakeOutputPath()),
            patch.dict(sys.modules, {"pyttsx3": pyttsx3_module}),
        ):
            self.assertEqual(speaker_export.main(["speech.wav"]), 0)

        self.assertEqual(engine.asserted_text, "A saved briefing.")
        self.assertEqual(engine.output_path, "speech.wav")
        self.assertIn(("rate", 175), engine.properties)
        self.assertTrue(engine.stopped)

    def test_worker_rejects_unexpected_argument_count(self) -> None:
        from core import speaker_export

        self.assertEqual(speaker_export.main([]), 2)
        self.assertEqual(speaker_export.main(["one.wav", "two.wav"]), 2)


if __name__ == "__main__":
    unittest.main()
