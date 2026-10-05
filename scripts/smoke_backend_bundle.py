from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
from core.host.profile_lock import ProfileLock
from core.host.protocol import decode_frame

MAX_CAPTURE = 64 * 1024
MAX_HTTP_BODY = 1024 * 1024
DEFAULT_TIMEOUT = 35.0
STARTUP_TIMEOUT = 60.0


@dataclass
class Check:
    name: str
    status: str
    detail: str | None = None


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str | None = None) -> None:
        self.checks.append(Check(name, status, detail))

    @property
    def failed(self) -> bool:
        return any(item.status == "failed" for item in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "result": "failed" if self.failed else ("unverified" if any(item.status == "unverified" for item in self.checks) else "passed"),
            "checks": [item.__dict__ for item in self.checks],
        }


class BoundedTail:
    def __init__(self, limit: int = MAX_CAPTURE) -> None:
        self.limit = limit
        self._parts: deque[bytes] = deque()
        self._size = 0
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        with self._lock:
            self._parts.append(data)
            self._size += len(data)
            while self._size > self.limit and self._parts:
                excess = self._size - self.limit
                first = self._parts.popleft()
                if len(first) > excess:
                    first = first[excess:]
                    self._parts.appendleft(first)
                    self._size -= excess
                    break
                self._size -= len(first)

    def text(self) -> str:
        with self._lock:
            return b"".join(self._parts).decode("utf-8", "replace")


def _signal_end(frames: queue.Queue[bytes | None]) -> None:
    try:
        frames.put_nowait(None)
    except queue.Full:
        try:
            frames.get_nowait()
        except queue.Empty:
            pass
        try:
            frames.put_nowait(None)
        except queue.Full:
            pass


def _drain(stream: Any, tail: BoundedTail) -> None:
    try:
        while True:
            data = stream.read(4096)
            if not data:
                return
            tail.append(data)
    except (OSError, ValueError):
        return


def _sanitized_environment(root: Path, profile: Path, *, dev: bool = False, demo: bool = False, initialize_local_config: bool = True) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    system_root = env.get("SYSTEMROOT", r"C:\Windows")
    env["PATH"] = os.pathsep.join((str(Path(system_root) / "System32"), system_root))
    temp_root = root / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    env.update({
        "TEMP": str(temp_root), "TMP": str(temp_root),
        "LOCALAPPDATA": str(root / "local-app-data"),
        "APPDATA": str(root / "roaming-app-data"),
        "APEX_DATA_DIR": str(profile.resolve()),
        "PYTHON_DOTENV_DISABLED": "1",
        "DEV_MODE": "true" if dev else "false",
        "DEMO_MODE": "true" if demo else "false",
        "PYTHONUTF8": "1",
    })
    for key in ("TEMP", "LOCALAPPDATA", "APPDATA"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)
    local_config = profile / "config.local.json"
    if initialize_local_config and not local_config.exists():
        local_config.write_text(json.dumps({
            "ollama": {"enabled": False}, "llama_cpp": {"enabled": False},
        }), encoding="utf-8")
    return env


def _http_json(url: str, timeout: float = 4.0) -> object:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} from {url}")
        body = response.read(MAX_HTTP_BODY + 1)
    if len(body) > MAX_HTTP_BODY:
        raise RuntimeError("HTTP response exceeded smoke-test limit")
    return json.loads(body)


def _port_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            listener.bind(("127.0.0.1", 8000))
        except OSError:
            return False
    return True


def _snapshot_resources(bundle: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle).as_posix()
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _copy_bundle(bundle: Path, destination: Path) -> Path:
    target = destination / "APEX 测試 bundle 🚀"
    shutil.copytree(bundle, target)
    return target


def _next_envelope(lines: queue.Queue[bytes | None], deadline: float) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for the managed host control envelope")
        try:
            raw = lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError("timed out waiting for the managed host control envelope") from exc
        if raw is None:
            raise RuntimeError("managed host closed its control stream before readiness")
        return decode_frame(raw).as_dict()


def _next_startup_envelope(
    lines: queue.Queue[bytes | None],
    process: subprocess.Popen[bytes],
    stderr: BoundedTail,
    *,
    stage: str,
    timeout: float = STARTUP_TIMEOUT,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        return _next_envelope(lines, started + timeout)
    except (TimeoutError, RuntimeError) as exc:
        elapsed = time.monotonic() - started
        raise RuntimeError(
            f"managed host startup failed while waiting for {stage} envelope "
            f"after {elapsed:.1f}s (pid={process.pid}, exit_code={process.poll()}): "
            f"{exc}; stderr tail: {stderr.text()[-MAX_CAPTURE:]}"
        ) from exc


def _spawn_host(exe: Path, profile: Path, root: Path, *, dev: bool = False, demo: bool = False, environment: dict[str, str] | None = None) -> tuple[subprocess.Popen[bytes], queue.Queue[bytes | None], BoundedTail, BoundedTail, str]:
    env = environment or _sanitized_environment(root, profile, dev=dev, demo=demo)
    process = subprocess.Popen(
        [str(exe), "serve", "--managed"], cwd=root, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    assert process.stdout is not None and process.stderr is not None and process.stdin is not None
    frames: queue.Queue[bytes | None] = queue.Queue(maxsize=128)
    stdout_tail, stderr_tail = BoundedTail(), BoundedTail()

    def read_frames() -> None:
        try:
            while True:
                line = process.stdout.readline(64 * 1024 + 1)
                if not line:
                    _signal_end(frames)
                    return
                stdout_tail.append(line)
                if len(line) > 64 * 1024 or not line.endswith(b"\n"):
                    _signal_end(frames)
                    return
                try:
                    frames.put_nowait(line)
                except queue.Full:
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        frames.put_nowait(None)
                    except queue.Full:
                        pass
                    return
        except (OSError, ValueError):
            _signal_end(frames)

    threading.Thread(target=read_frames, daemon=True, name="apex-smoke-protocol-drain").start()
    threading.Thread(target=_drain, args=(process.stderr, stderr_tail), daemon=True, name="apex-smoke-stderr-drain").start()
    launch_id = str(uuid.uuid4())
    process.stdin.write(json.dumps({
        "version": 1, "type": "start", "request_id": launch_id,
        "payload": {"launch_id": launch_id},
    }, separators=(",", ":")).encode("utf-8") + b"\n")
    process.stdin.flush()
    return process, frames, stdout_tail, stderr_tail, launch_id


def _stop_host(process: subprocess.Popen[bytes], frames: queue.Queue[bytes | None], stderr: BoundedTail, launch_id: str | None, *, timeout_seconds: int = 60) -> None:
    if process.poll() is not None:
        raise RuntimeError(
            f"managed host exited before graceful shutdown (code={process.returncode}); "
            "no stopped envelope was observed; stderr tail: " + stderr.text()
        )
    if process.stdin is not None and not process.stdin.closed:
        try:
            if launch_id:
                process.stdin.write(json.dumps({
                    "version": 1, "type": "shutdown", "request_id": str(uuid.uuid4()), "payload": {},
                }, separators=(",", ":")).encode("utf-8") + b"\n")
                process.stdin.flush()
        except OSError:
            pass
    deadline = time.monotonic() + max(1, timeout_seconds) + 5
    stopped = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            envelope = _next_envelope(frames, min(deadline, time.monotonic() + 0.4))
        except TimeoutError:
            continue
        if envelope.get("type") == "stopped":
            stopped = True
            break
        if envelope.get("type") == "error":
            raise RuntimeError(f"managed host reported shutdown failure: {envelope.get('payload')}")
    try:
        process.wait(timeout=max(1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise RuntimeError("managed host did not exit within its shutdown budget; stderr tail: " + stderr.text())
    if process.stdin is not None and not process.stdin.closed:
        process.stdin.close()
    if not stopped or process.returncode != 0:
        raise RuntimeError(f"managed host did not complete graceful shutdown (stopped={stopped}, code={process.returncode}); stderr tail: {stderr.text()}")


def _cli(exe: Path, argv: list[str], cwd: Path, env: dict[str, str], *, timeout_seconds: int = 30) -> str:
    result = subprocess.Popen([str(exe), *argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.stdout is not None and result.stderr is not None
    stdout, stderr = BoundedTail(), BoundedTail()
    threads = [
        threading.Thread(target=_drain, args=(result.stdout, stdout), daemon=True),
        threading.Thread(target=_drain, args=(result.stderr, stderr), daemon=True),
    ]
    for thread in threads: thread.start()
    try:
        try:
            code = result.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            result.kill()
            result.wait(timeout=5)
            raise RuntimeError(f"CLI {argv[0]} exceeded its {timeout_seconds} second timeout") from exc
    finally:
        for thread in threads:
            thread.join(timeout=2)
        if any(thread.is_alive() for thread in threads):
            # The child has been reaped, so EOF should normally finish both
            # readers. Close only as a fallback for a stalled drain, then give
            # it one more bounded chance to exit.
            for stream in (result.stdout, result.stderr):
                if not stream.closed:
                    stream.close()
            for thread in threads:
                thread.join(timeout=1)
        else:
            for stream in (result.stdout, result.stderr):
                if not stream.closed:
                    stream.close()
    if code:
        raise RuntimeError(
            f"CLI {argv[0]} exited {code}; stdout tail: {stdout.text()[-2048:]}; "
            f"stderr tail: {stderr.text()[-2048:]}"
        )
    return stdout.text()


def _setup_request(
    exe: Path,
    root: Path,
    profile: Path,
    operation: str,
    *,
    source: Path | None = None,
    preview_id: str | None = None,
    expected_error_code: str | None = None,
    timeout_seconds: int = 180,
    initialize_local_config: bool = False,
) -> dict[str, Any]:
    """Exercise the frozen, bounded first-run helper protocol in a child process."""
    env = _sanitized_environment(
        root, profile, initialize_local_config=initialize_local_config
    )
    request_id = str(uuid.uuid4())
    request: dict[str, object] = {
        "version": 1, "request_id": request_id, "operation": operation,
    }
    if source is not None:
        request["source_dir"] = str(source.resolve())
    if preview_id is not None:
        request["preview_id"] = preview_id
    process = subprocess.Popen(
        [str(exe), "setup"], cwd=root, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout_tail = BoundedTail(4 * 1024 * 1024)
    stderr_tail = BoundedTail(MAX_CAPTURE)
    assert process.stdout is not None and process.stderr is not None and process.stdin is not None
    drain_threads = [
        threading.Thread(target=_drain, args=(process.stdout, stdout_tail), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr_tail), daemon=True),
    ]
    for thread in drain_threads:
        thread.start()
    try:
        process.stdin.write(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
        process.stdin.close()
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError(f"frozen setup helper timed out during {operation}") from None
    finally:
        for thread in drain_threads:
            thread.join(timeout=5)
    stdout, stderr = stdout_tail.text().encode("utf-8"), stderr_tail.text()
    if process.returncode not in {0, 1}:
        raise RuntimeError(f"frozen setup helper failed during {operation} (exit={process.returncode}); {stderr[-MAX_CAPTURE:]}")
    results: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if len(line) > 64 * 1024:
            raise RuntimeError("frozen setup helper exceeded the protocol frame limit")
        try:
            envelope = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError("frozen setup helper returned malformed protocol JSON") from None
        if not isinstance(envelope, dict) or envelope.get("version") != 1 or envelope.get("request_id") != request_id:
            raise RuntimeError("frozen setup helper returned a mismatched protocol envelope")
        if envelope.get("type") == "progress":
            payload = envelope.get("payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("stage"), str):
                raise RuntimeError("frozen setup helper returned malformed progress")
            continue
        if envelope.get("type") not in {"result", "error"} or not isinstance(envelope.get("payload"), dict):
            raise RuntimeError("frozen setup helper returned an invalid terminal envelope")
        results.append(envelope)
    if len(results) != 1:
        code = results[0].get("payload", {}).get("code") if results else "missing_result"
        raise RuntimeError(f"frozen setup helper operation {operation} did not succeed ({code})")
    if results[0].get("type") == "error":
        payload = results[0].get("payload", {})
        code = payload.get("code") if isinstance(payload, dict) else None
        if expected_error_code is not None and code == expected_error_code and process.returncode == 1:
            return payload
        raise RuntimeError(f"frozen setup helper operation {operation} returned an unexpected error ({code})")
    if results[0].get("type") != "result":
        raise RuntimeError(f"frozen setup helper operation {operation} returned an invalid terminal envelope")
    if process.returncode != 0:
        raise RuntimeError(f"frozen setup helper operation {operation} returned a result with exit={process.returncode}")
    if expected_error_code is not None:
        raise RuntimeError(f"frozen setup helper operation {operation} unexpectedly succeeded")
    return results[0]["payload"]


def _fixture_cli(probe: Path | None, helper: Path, command: str, profile: Path, root: Path) -> dict[str, Any]:
    if probe is not None and probe.is_file():
        argv = ["import-fixture", command, str(profile)]
        executable = probe
    else:
        argv = [str(helper), command, str(profile)]
        executable = Path(sys.executable)
    result = json.loads(_cli(executable, argv, root, dict(os.environ), timeout_seconds=60))
    if not isinstance(result, dict):
        raise RuntimeError("production-data rehearsal fixture returned a non-object result")
    return result


def _run_interrupted_import_recovery(
    exe: Path, root: Path, source: Path, destination: Path, *,
    expected_source_fingerprint: str, expected_cache_sha256: str, helper: Path, probe: Path | None,
) -> None:
    """Terminate only the setup helper after a journaled production copy begins."""
    env = _sanitized_environment(root, destination, initialize_local_config=False)
    request_id = str(uuid.uuid4())
    request = {
        "version": 1, "request_id": request_id, "operation": "import",
        "source_dir": str(source.resolve()),
        # The preview identity is derived from the stable source inventory, so
        # the separate helper process can validate the explicit preview result.
    }
    preview = _setup_request(exe, root, destination, "preview", source=source)
    preview_id = preview.get("preview_id")
    if not preview.get("can_import") or not isinstance(preview_id, str) or not preview_id:
        raise RuntimeError("interrupt rehearsal source did not produce an importable frozen preview")
    request["preview_id"] = preview_id
    process = subprocess.Popen(
        [str(exe), "setup"], cwd=root, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    frames: queue.Queue[bytes | BaseException | None] = queue.Queue(maxsize=64)
    stderr_tail = BoundedTail(MAX_CAPTURE)

    def read_frames() -> None:
        try:
            while True:
                line = process.stdout.readline(64 * 1024 + 1)
                if not line:
                    frames.put(None)
                    return
                if len(line) > 64 * 1024:
                    frames.put(RuntimeError("interrupted helper exceeded the setup protocol frame bound"))
                    return
                frames.put(line)
        except BaseException as exc:
            frames.put(exc)

    readers = [
        threading.Thread(target=read_frames, daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr_tail), daemon=True),
    ]
    for thread in readers:
        thread.start()
    process.stdin.write(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
    process.stdin.close()
    journal = destination / ".apex-import-journal.json"
    marker = destination / "smoke-unrelated-destination-marker.txt"
    interrupted = False
    deadline = time.monotonic() + 180
    try:
        while time.monotonic() < deadline:
            try:
                line = frames.get(timeout=0.2)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if line is None:
                break
            if isinstance(line, BaseException):
                raise RuntimeError(f"could not read interrupted helper progress: {type(line).__name__}")
            try:
                envelope = json.loads(line)
            except (UnicodeError, json.JSONDecodeError):
                raise RuntimeError("interrupted helper emitted malformed setup protocol JSON") from None
            if not isinstance(envelope, dict) or envelope.get("version") != 1 or envelope.get("request_id") != request_id:
                raise RuntimeError("interrupted helper emitted a mismatched setup protocol envelope")
            payload = envelope.get("payload")
            if envelope.get("type") == "progress" and isinstance(payload, dict) and payload.get("stage") == "copying" and journal.is_file():
                if process.poll() is not None:
                    break
                marker.write_bytes(b"unrelated file created after import journaling\n")
                if process.poll() is not None:
                    marker.unlink()
                    break
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                interrupted = True
                break
            if envelope.get("type") in {"result", "error"}:
                break
        if not interrupted:
            raise RuntimeError("frozen helper completed or timed out before journaled managed-file copying was observable")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for thread in readers:
            thread.join(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    if not journal.is_file() or marker.read_bytes() != b"unrelated file created after import journaling\n":
        raise RuntimeError("interrupted import did not leave its journal and unrelated destination marker for recovery")
    status = _setup_request(exe, root, destination, "status")
    if status.get("phase") != "recovery_required" or status.get("error_code") != "import_recovery_required":
        raise RuntimeError("frozen helper did not block a profile with an interrupted import journal")
    recovered = _setup_request(exe, root, destination, "recover")
    if recovered.get("phase") != "choice_required" or recovered.get("error_code") is not None:
        raise RuntimeError("frozen helper could not recover the interrupted destination to a known choice-required state")
    if journal.exists() or marker.read_bytes() != b"unrelated file created after import journaling\n":
        raise RuntimeError("recovery did not remove its journal or it removed/changed an unrelated destination file")
    source_fingerprint = _fixture_cli(probe, helper, "fingerprint", source, root).get("fingerprint")
    cache = root / "local-app-data" / "APEX" / "auth" / "microsoft_todo_token_cache.bin"
    if source_fingerprint != expected_source_fingerprint or hashlib.sha256(cache.read_bytes()).hexdigest() != expected_cache_sha256:
        raise RuntimeError("interrupted import or recovery changed source profile bytes or encrypted Microsoft cache bytes")
    retry_preview = _setup_request(exe, root, destination, "preview", source=source)
    retry_preview_id = retry_preview.get("preview_id")
    if retry_preview.get("can_import") is not True or not isinstance(retry_preview_id, str):
        raise RuntimeError("recovered destination could not produce a fresh import preview")
    retry_result = _setup_request(
        exe, root, destination, "import", source=source, preview_id=retry_preview_id,
    )
    if retry_result.get("phase") != "ready" or marker.read_bytes() != b"unrelated file created after import journaling\n":
        raise RuntimeError("retry after recovery did not import the source or preserve the unrelated destination marker")
    source_read = _fixture_cli(probe, helper, "verify", source, root)
    recovered_read = _fixture_cli(probe, helper, "verify", destination, root)
    if (
        recovered_read.get("action_status") != "outcome_unknown"
        or recovered_read.get("action_events") != source_read.get("action_events")
        or recovered_read.get("action_effects") != source_read.get("action_effects")
        or recovered_read.get("action_effects") != 1
        or recovered_read.get("historical_news_readable") is not True
        or recovered_read.get("speech_audio_readable") is not True
    ):
        raise RuntimeError("successful retry after recovery did not preserve production domain readers and action state")


def _run_import_preservation_smoke(bundle: Path, root: Path, report: Report, *, probe: Path | None) -> None:
    """Import a production-owned disposable profile and reopen it twice frozen."""
    source = root / "import-source-profile"
    destination = root / "imported-disposable-profile"
    helper = REPOSITORY_ROOT / "scripts" / "data_import_rehearsal.py"
    try:
        seed = _fixture_cli(probe, helper, "seed", source, root)
        if not isinstance(seed, dict) or not isinstance(seed.get("source_fingerprint"), str):
            raise RuntimeError("rehearsal fixture did not return its source fingerprint")
        baseline = _fixture_cli(probe, helper, "verify", source, root)
        status = _setup_request(bundle / "apex-backend.exe", root, destination, "status")
        if status.get("phase") != "choice_required":
            raise RuntimeError("blank frozen profile did not require an explicit setup choice")
        preview = _setup_request(
            bundle / "apex-backend.exe", root, destination, "preview", source=source,
        )
        if preview.get("can_import") is not True or preview.get("blockers"):
            raise RuntimeError("valid production fixture was blocked during import preview")
        preview_id = preview.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id:
            raise RuntimeError("import preview did not bind an identity token")
        if str(source.resolve()).casefold() in json.dumps(preview, ensure_ascii=False).casefold():
            raise RuntimeError("import preview exposed the source's absolute path")
        refusal = root / "existing-destination-profile"
        refusal.mkdir()
        refusal_db = refusal / "apex_memory.db"
        refusal_bytes = b"operator-owned destination database sentinel"
        refusal_db.write_bytes(refusal_bytes)
        refusal_marker = refusal / "keep-me.txt"
        refusal_marker.write_text("keep", encoding="utf-8")
        refusal_preview = _setup_request(
            bundle / "apex-backend.exe", root, refusal, "preview", source=source,
        )
        refusal_id = refusal_preview.get("preview_id")
        if refusal_preview.get("can_import") is not False or not isinstance(refusal_id, str):
            raise RuntimeError("frozen setup helper did not block preview into a profile with an existing database")
        _setup_request(
            bundle / "apex-backend.exe", root, refusal, "import", source=source,
            preview_id=refusal_id, expected_error_code="destination_database_exists",
        )
        if refusal_db.read_bytes() != refusal_bytes or refusal_marker.read_text(encoding="utf-8") != "keep":
            raise RuntimeError("frozen setup helper changed existing destination files during refusal")
        report.add("import_existing_destination_refusal", "passed", "frozen helper refused to replace an existing destination database and preserved an unrelated marker")
        interruption_destination = root / "interrupted-destination-profile"
        _run_interrupted_import_recovery(
            bundle / "apex-backend.exe", root, source, interruption_destination,
            expected_source_fingerprint=str(seed["source_fingerprint"]),
            expected_cache_sha256=str(seed["microsoft_cache_sha256"]),
            helper=helper, probe=probe,
        )
        report.add("import_interrupted_recovery", "passed", "journaled frozen import was terminated during managed-file copying, recovered to source choice, then re-previewed and imported the same destination while preserving unrelated bytes")
        imported = _setup_request(
            bundle / "apex-backend.exe", root, destination, "import",
            source=source, preview_id=preview_id,
        )
        if imported.get("phase") != "ready":
            raise RuntimeError("frozen import did not finish in the ready state")

        def verify_profile() -> dict[str, Any]:
            return _fixture_cli(probe, helper, "verify", destination, root)

        first = verify_profile()
        if first.get("action_status") != "outcome_unknown" or first.get("action_events") != baseline.get("action_events") or first.get("action_effects") != baseline.get("action_effects") or first.get("action_effects") != 1:
            raise RuntimeError("unknown action or its durable effect changed during import")
        local_cache = root / "local-app-data" / "APEX" / "auth" / "microsoft_todo_token_cache.bin"
        if not local_cache.is_file() or hashlib.sha256(local_cache.read_bytes()).hexdigest() != seed.get("microsoft_cache_sha256"):
            raise RuntimeError("same-user encrypted Microsoft cache bytes changed during import")
        for restart_number in (1, 2):
            process, frames, _stdout, stderr, launch_id = _spawn_host(
                bundle / "apex-backend.exe", destination, root,
            )
            try:
                starting = _next_startup_envelope(frames, process, stderr, stage="imported-profile starting")
                ready = _next_startup_envelope(frames, process, stderr, stage="imported-profile ready")
                identity = ready.get("payload")
                if (
                    starting.get("type") != "starting"
                    or ready.get("type") != "ready"
                    or ready.get("request_id") != launch_id
                    or not isinstance(identity, dict)
                    or identity.get("pid") != process.pid
                    or identity.get("launch_id") != launch_id
                    or identity.get("hosting_mode") != "managed"
                    or _http_json("http://127.0.0.1:8000/api/v1/runtime") != identity
                ):
                    raise RuntimeError("imported-profile runtime identity did not match its managed child")
                expected = hashlib.sha256(os.path.normcase(str(destination.resolve())).encode("utf-8")).hexdigest()
                if identity.get("data_root_fingerprint") != expected:
                    raise RuntimeError("imported-profile runtime identity selected a different data root")
                _stop_host(
                    process, frames, stderr, launch_id,
                    timeout_seconds=int(identity["shutdown_timeout_seconds"]),
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
            after_startup = verify_profile()
            if after_startup.get("action_status") != "outcome_unknown" or after_startup.get("action_events") != baseline.get("action_events") or after_startup.get("action_effects") != baseline.get("action_effects") or after_startup.get("action_effects") != 1:
                raise RuntimeError(f"backend startup {restart_number} replayed or changed an uncertain action effect")
            if hashlib.sha256(local_cache.read_bytes()).hexdigest() != seed.get("microsoft_cache_sha256"):
                raise RuntimeError("backend startup changed the same-user encrypted Microsoft cache")

        source_fingerprint = _fixture_cli(probe, helper, "fingerprint", source, root).get("fingerprint")
        if source_fingerprint != seed.get("source_fingerprint"):
            raise RuntimeError("import changed managed source bytes")
        report.add(
            "import_preservation_and_restart",
            "passed",
            "production history, reports, historical News, speech bytes, vault ownership, credentials, local assets, encrypted cache, and unknown action effect survived import and two backend starts",
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        report.add("import_preservation_and_restart", "failed", str(exc))



def _check_install_contained_data_root(bundle: Path, scratch: Path, report: Report) -> None:
    invalid_root = (bundle / "_internal" / ".apex-smoke-invalid-data").resolve()
    env = _sanitized_environment(scratch, scratch / "invalid-root-profile")
    env["APEX_DATA_DIR"] = str(invalid_root)
    process = subprocess.Popen(
        [str(bundle / "apex-backend.exe"), "serve", "--managed"], cwd=scratch, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    frames: queue.Queue[bytes | None] = queue.Queue(maxsize=8)
    stderr = BoundedTail()

    def drain_protocol() -> None:
        try:
            while True:
                line = process.stdout.readline(64 * 1024 + 1)
                if not line:
                    _signal_end(frames)
                    return
                frames.put(line, timeout=2)
        except (OSError, ValueError, queue.Full):
            try: frames.put_nowait(None)
            except queue.Full: pass

    threading.Thread(target=drain_protocol, daemon=True).start()
    threading.Thread(target=_drain, args=(process.stderr, stderr), daemon=True).start()
    launch_id = str(uuid.uuid4())
    process.stdin.write(json.dumps({"version": 1, "type": "start", "request_id": launch_id, "payload": {"launch_id": launch_id}}, separators=(",", ":")).encode("utf-8") + b"\n")
    process.stdin.flush()
    try:
        error = _next_envelope(frames, time.monotonic() + 15)
        process.stdin.close()
        code = process.wait(timeout=15)
        if error.get("type") != "error" or error.get("payload", {}).get("code") != "startup_failed" or code == 0 or invalid_root.exists():
            raise RuntimeError("install-contained data root was not rejected before writes: " + stderr.text())
        report.add("install_contained_data_root_rejected", "passed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _run_once(bundle: Path, report: Report, *, dev: bool = False, demo: bool = False, probe: Path | None = None, fastembed_cache: Path | None = None, kokoro_assets: Path | None = None, run_probe: bool = True, inference_timeout: int = 120) -> None:
    if not _port_available():
        report.add("api_port_available", "failed", "127.0.0.1:8000 is occupied; stop the owner or run the smoke gate on a clear host. The existing process was left untouched.")
        return
    report.add("api_port_available", "passed")
    root = Path(tempfile.mkdtemp(prefix="apex-smoke-測試-"))
    profile = root / "disposable-profile"
    cwd = root / "unrelated-working-directory"
    cwd.mkdir()
    process: subprocess.Popen[bytes] | None = None
    frames: queue.Queue[bytes | None] | None = None
    stderr = BoundedTail()
    launch_id: str | None = None
    shutdown_timeout_seconds = 60
    spawned: list[subprocess.Popen[bytes]] = []
    try:
        setup_status = _setup_request(bundle / "apex-backend.exe", root, profile, "status")
        if setup_status.get("phase") != "choice_required":
            raise RuntimeError("blank frozen profile did not require a first-run choice")
        fresh_start = _setup_request(bundle / "apex-backend.exe", root, profile, "fresh_start")
        if fresh_start.get("phase") != "ready":
            raise RuntimeError("frozen Fresh Start did not ready the blank profile")
        report.add("first_run_fresh_start", "passed", "explicit Fresh Start readied an empty disposable profile")
        process, frames, _stdout, stderr, launch_id = _spawn_host(bundle / "apex-backend.exe", profile, root, dev=dev, demo=demo)
        spawned.append(process)
        started = _next_startup_envelope(frames, process, stderr, stage="starting")
        if started.get("type") != "starting" or started.get("request_id") != launch_id:
            raise RuntimeError("managed host did not acknowledge the launch with a starting envelope")
        ready = _next_startup_envelope(frames, process, stderr, stage="ready")
        if ready.get("type") != "ready" or ready.get("request_id") != launch_id:
            raise RuntimeError(f"managed host failed readiness: {ready.get('type')} {ready.get('payload')}")
        identity = ready.get("payload")
        if not isinstance(identity, dict) or identity.get("pid") != process.pid or identity.get("launch_id") != launch_id or identity.get("hosting_mode") != "managed":
            raise RuntimeError("ready identity did not match the launched child pid, launch ID, and managed mode")
        http_identity = _http_json("http://127.0.0.1:8000/api/v1/runtime")
        if http_identity != identity:
            raise RuntimeError("ready envelope identity differs from GET /api/v1/runtime")
        if identity.get("app_id") != "apex" or not identity.get("app_version") or not identity.get("build_id") or not identity.get("data_root_fingerprint"):
            raise RuntimeError("runtime identity is missing application/build/profile identity")
        expected_profile = hashlib.sha256(os.path.normcase(str(profile.resolve())).encode("utf-8")).hexdigest()
        if identity.get("data_root_fingerprint") != expected_profile:
            raise RuntimeError("runtime identity profile fingerprint does not match the disposable data root")
        shutdown_timeout_seconds = int(identity["shutdown_timeout_seconds"])
        build_info = json.loads((bundle / "_internal" / "build-info.json").read_text(encoding="utf-8"))
        if build_info.get("build_id") != identity.get("build_id"):
            raise RuntimeError("frozen build-info build ID does not match the host runtime identity")
        version_key = "app_version" if "app_version" in build_info else "application_version"
        if build_info.get(version_key) != identity.get("app_version"):
            raise RuntimeError("frozen build-info application version does not match the host runtime identity")
        bundle_manifest = json.loads((bundle / "bundle-manifest.json").read_text(encoding="utf-8"))
        if bundle_manifest.get("build_id") != identity.get("build_id"):
            raise RuntimeError("bundle manifest build ID does not match the host runtime identity")
        report.add("managed_readiness_identity", "passed")
        env = _sanitized_environment(root, profile, dev=dev, demo=demo)
        status = _cli(bundle / "apex.exe", ["status", "--json"], cwd, env)
        models = _cli(bundle / "apex.exe", ["models", "--json"], cwd, env)
        retrieval = _cli(bundle / "apex.exe", ["context", "status", "--json"], cwd, env)
        records = _cli(bundle / "apex.exe", ["context", "list", "--limit", "5", "--json"], cwd, env)
        json.loads(status); json.loads(models); json.loads(retrieval); json.loads(records)
        report.add("cli_status_models_and_read_commands", "passed")
        if run_probe and probe is not None and probe.is_file():
            probe_root = root / "frozen-probe-profile"
            probe_env = _sanitized_environment(root, probe_root, dev=dev, demo=demo)
            for scenario in ("imports", "retrieval", "audio-worker", "no-model-assets"):
                output = _cli(probe, [scenario], cwd, probe_env)
                result = json.loads(output)
                if result.get("status") != "passed" or result.get("scenario") != scenario:
                    raise RuntimeError(f"frozen probe scenario {scenario} failed: {result}")
                if scenario == "no-model-assets" and (result.get("evidence", {}).get("package") != "loaded" or result.get("evidence", {}).get("model_status") != "embedding_initialization_failed"):
                    raise RuntimeError(f"no-weight FastEmbed failure did not prove packaged module availability: {result}")
            invalid_worker = subprocess.Popen([str(probe), "worker", "unsupported"], cwd=cwd, env=probe_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            spawned.append(invalid_worker)
            invalid_out, invalid_err = invalid_worker.communicate(timeout=15)
            if invalid_worker.returncode != 2 or len(invalid_out) > MAX_CAPTURE or len(invalid_err) > MAX_CAPTURE:
                raise RuntimeError("frozen probe accepted an invalid worker request or exceeded output bounds")
            report.add("frozen_imports_retrieval_worker", "passed")
            if fastembed_cache is not None and kokoro_assets is not None:
                fastembed_target = probe_root / "weights" / "fastembed"
                kokoro_target = probe_root / "core" / "weights" / "kokoro"
                shutil.copytree(fastembed_cache, fastembed_target, dirs_exist_ok=True)
                shutil.copytree(kokoro_assets, kokoro_target, dirs_exist_ok=True)
                semantic_output = _cli(probe, ["semantic-assets"], cwd, probe_env, timeout_seconds=inference_timeout)
                semantic_result = json.loads(semantic_output)
                semantic_evidence = semantic_result.get("evidence", {})
                if (
                    semantic_result.get("status") != "passed"
                    or semantic_result.get("scenario") != "semantic-assets"
                    or semantic_evidence.get("retrieval_mode") != "semantic"
                    or not semantic_evidence.get("semantic_results")
                ):
                    raise RuntimeError(f"real FastEmbed semantic probe failed: {semantic_result}")
                report.add("fastembed_real_semantic_search", "passed", f"{semantic_evidence['semantic_results']} results")

                kokoro_output = _cli(probe, ["kokoro-assets"], cwd, probe_env, timeout_seconds=inference_timeout)
                kokoro_result = json.loads(kokoro_output)
                kokoro_evidence = kokoro_result.get("evidence", {})
                if (
                    kokoro_result.get("status") != "passed"
                    or kokoro_result.get("scenario") != "kokoro-assets"
                    or kokoro_evidence.get("kokoro_engine") != "kokoro"
                    or not kokoro_evidence.get("wav_bytes")
                ):
                    raise RuntimeError(f"real Kokoro synthesis probe failed: {kokoro_result}")
                report.add("kokoro_real_wav_synthesis", "passed", f"{kokoro_evidence['wav_bytes']} bytes")
                report.add("fastembed_and_kokoro_real_assets", "passed")
            else:
                report.add("fastembed_real_semantic_search", "unverified", "supply --fastembed-cache to execute real semantic inference")
                report.add("kokoro_real_wav_synthesis", "unverified", "supply --kokoro-assets to execute real Kokoro synthesis")
                report.add("fastembed_and_kokoro_real_assets", "unverified", "supply --fastembed-cache and --kokoro-assets to execute real inference")
        elif run_probe:
            report.add("frozen_probe_imports_retrieval_worker", "unverified", "build probe at build/backend-bundle/smoke-probe/apex-bundle-probe.exe or pass --probe")
        if not dev and not demo:
            direct_worker = root / "backend-worker.wav"
            worker = subprocess.Popen(
                [str(bundle / "apex-backend.exe"), "worker", "speech-export", str(direct_worker)],
                cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            spawned.append(worker)
            assert worker.stdin is not None and worker.stdout is not None and worker.stderr is not None
            worker_stdout, worker_stderr = BoundedTail(), BoundedTail()
            worker_threads = [
                threading.Thread(target=_drain, args=(worker.stdout, worker_stdout), daemon=True),
                threading.Thread(target=_drain, args=(worker.stderr, worker_stderr), daemon=True),
            ]
            for thread in worker_threads: thread.start()
            worker.stdin.write(json.dumps({"text": "APEX frozen backend worker smoke.", "gender": "female"}, separators=(",", ":")).encode("utf-8"))
            worker.stdin.close()
            try:
                worker_code = worker.wait(timeout=90)
            except subprocess.TimeoutExpired:
                worker.kill(); worker.wait(timeout=5)
                raise RuntimeError("production backend speech-export worker timed out")
            for thread in worker_threads: thread.join(timeout=2)
            for stream in (worker.stdout, worker.stderr): stream.close()
            audio = direct_worker.read_bytes() if direct_worker.is_file() else b""
            if worker_code != 0 or not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
                raise RuntimeError(f"production backend worker did not write a valid WAV (code={worker_code}; {worker_stderr.text()[-1024:]})")
            report.add("production_backend_worker_valid_wav", "passed", f"{len(audio)} bytes")
            direct_worker.unlink(missing_ok=True)
        second = subprocess.Popen([str(bundle / "apex-backend.exe"), "serve", "--managed"], cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        spawned.append(second)
        assert second.stdin is not None and second.stdout is not None
        second_err = BoundedTail()
        threading.Thread(target=_drain, args=(second.stderr, second_err), daemon=True).start()
        second_lines: queue.Queue[bytes | None] = queue.Queue(maxsize=16)
        def drain_second() -> None:
            try:
                while True:
                    line = second.stdout.readline(64 * 1024 + 1)
                    if not line: _signal_end(second_lines); return
                    second_lines.put(line, timeout=2)
            except (OSError, ValueError, queue.Full):
                try: second_lines.put_nowait(None)
                except queue.Full: pass
        threading.Thread(target=drain_second, daemon=True).start()
        duplicate_id = str(uuid.uuid4())
        second.stdin.write(json.dumps({"version": 1, "type": "start", "request_id": duplicate_id, "payload": {"launch_id": duplicate_id}}, separators=(",", ":")).encode() + b"\n")
        second.stdin.flush()
        duplicate = _next_envelope(second_lines, time.monotonic() + 15)
        second.stdin.close()
        code = second.wait(timeout=15)
        if duplicate.get("type") != "error" or duplicate.get("payload", {}).get("code") != "port_in_use" or code == 0 or process.poll() is not None:
            raise RuntimeError(f"port conflict was not rejected while preserving the existing owner (type={duplicate.get('type')}, code={duplicate.get('payload', {}).get('code')})")
        if _http_json("http://127.0.0.1:8000/api/v1/runtime") != identity:
            raise RuntimeError("port-conflict handling disturbed the existing backend")
        report.add("port_conflict_existing_owner_preserved", "passed")
        _stop_host(process, frames, stderr, launch_id, timeout_seconds=shutdown_timeout_seconds)
        process = None
        report.add("graceful_shutdown", "passed")
        locked_profile = root / "locked-profile"
        locked_environment = _sanitized_environment(root, locked_profile)
        with ProfileLock(locked_profile):
            locked_process, locked_frames, _locked_stdout, locked_stderr, locked_launch_id = _spawn_host(
                bundle / "apex-backend.exe", locked_profile, root, environment=locked_environment
            )
            try:
                locked_error = _next_envelope(locked_frames, time.monotonic() + 15)
                if locked_error.get("type") != "error" or locked_error.get("payload", {}).get("code") != "profile_in_use":
                    raise RuntimeError(f"profile conflict was not rejected: {locked_error.get('payload')}")
                if locked_process.wait(timeout=15) == 0 or (locked_profile / "apex_memory.db").exists():
                    raise RuntimeError("profile conflict created persistence or exited successfully")
            finally:
                if locked_process.poll() is None:
                    locked_process.kill()
                    locked_process.wait(timeout=5)
                for stream in (locked_process.stdin, locked_process.stdout, locked_process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
        report.add("profile_conflict_rejected_before_database", "passed")
        if not demo and not (profile / "apex_memory.db").exists():
            raise RuntimeError("backend did not create persistence in the disposable profile")
        eof_root = Path(tempfile.mkdtemp(prefix="apex-parent-eof-測試-"))
        eof_error = None
        eof_process = None
        try:
            eof_process, eof_frames, _eof_stdout, eof_stderr, eof_launch_id = _spawn_host(
                bundle / "apex-backend.exe", eof_root / "profile", eof_root
            )
            eof_starting = _next_startup_envelope(eof_frames, eof_process, eof_stderr, stage="parent-EOF starting")
            eof_ready = _next_startup_envelope(eof_frames, eof_process, eof_stderr, stage="parent-EOF ready")
            if eof_starting.get("type") != "starting" or eof_ready.get("type") != "ready" or eof_ready.get("request_id") != eof_launch_id:
                raise RuntimeError("parent-EOF host did not become ready")
            assert eof_process.stdin is not None
            eof_process.stdin.close()
            eof_error: dict[str, Any] | None = None
            eof_shutdown_timeout = int(eof_ready["payload"]["shutdown_timeout_seconds"])
            eof_deadline = time.monotonic() + eof_shutdown_timeout + 5
            while time.monotonic() < eof_deadline:
                try:
                    envelope = _next_envelope(eof_frames, min(eof_deadline, time.monotonic() + 0.5))
                except TimeoutError:
                    if eof_process.poll() is not None:
                        continue
                    continue
                except RuntimeError as exc:
                    if "closed its control stream" in str(exc):
                        break
                    raise
                if envelope.get("type") == "error":
                    eof_error = envelope
                    break
            try:
                eof_code = eof_process.wait(timeout=max(1, eof_deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("managed host did not stop after parent control-channel EOF; " + eof_stderr.text()) from exc
            if eof_code == 0 or eof_error is None or eof_error.get("payload", {}).get("code") != "protocol_error":
                raise RuntimeError("parent EOF did not produce the documented protocol-error shutdown")
            report.add("parent_eof_protocol_error_cleanup", "passed")
        finally:
            if eof_process is not None and eof_process.poll() is None:
                eof_process.kill()
                eof_process.wait(timeout=5)
            shutil.rmtree(eof_root, ignore_errors=True)
        if not report.failed and run_probe:
            _run_import_preservation_smoke(bundle, root, report, probe=probe)
    finally:
        for child in spawned:
            if child.poll() is None:
                if child.stdin is not None and not child.stdin.closed:
                    child.stdin.close()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        shutil.rmtree(root, ignore_errors=True)


def _emit_report(result: dict[str, object], report_path: Path | None, stream: Any = None) -> None:
    if report_path:
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rendered = json.dumps(result, ensure_ascii=True, indent=2)
    print(rendered, file=stream if stream is not None else sys.stdout)


def _inference_timeout(value: str) -> int:
    try:
        timeout = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer between 30 and 600 seconds") from None
    if not 30 <= timeout <= 600:
        raise argparse.ArgumentTypeError("must be between 30 and 600 seconds")
    return timeout


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bounded real-process checks against an APEX backend bundle.")
    parser.add_argument("--bundle", type=Path, required=True, help="Directory containing apex-backend.exe, apex.exe, and _internal.")
    parser.add_argument("--probe", type=Path, help="Separate build-only frozen probe executable.")
    parser.add_argument("--report", type=Path, help="Optional JSON report output file.")
    parser.add_argument("--strict", action="store_true", help="Require real optional model assets and every branch-3 bundle check to pass.")
    parser.add_argument("--fastembed-cache", type=Path, help="Test-only external FastEmbed model cache.")
    parser.add_argument("--kokoro-assets", type=Path, help="Test-only directory containing Kokoro ONNX and voice files.")
    parser.add_argument(
        "--inference-timeout",
        type=_inference_timeout,
        default=120,
        help="Timeout in seconds for real semantic and Kokoro asset inference (30..600; default: 120).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = Report()
    bundle = args.bundle.resolve()
    required = [bundle / "apex-backend.exe", bundle / "apex.exe", bundle / "_internal", bundle / "bundle-manifest.json"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        report.add("bundle_shape", "failed", "missing expected bundle files: " + ", ".join(missing))
    elif not _port_available():
        report.add("api_port_available", "failed", "127.0.0.1:8000 is occupied; owner left untouched")
    else:
        with tempfile.TemporaryDirectory(prefix="apex-bundle-smoke-") as temp:
            scratch = Path(temp)
            try:
                copied = _copy_bundle(bundle, scratch)
                probe_source = args.probe or (Path("build/backend-bundle/smoke-probe/apex-bundle-probe.exe"))
                probe_copy = None
                if probe_source.is_file():
                    probe_copy = scratch / "Frozen Probe 測試 🚦.exe"
                    shutil.copy2(probe_source, probe_copy)
                    probe_internal = probe_source.parent / "_internal"
                    if probe_internal.is_dir():
                        shutil.copytree(probe_internal, scratch / "_internal", dirs_exist_ok=True)
                before = _snapshot_resources(copied)
                report.add("copied_outside_checkout_to_unicode_path", "passed")
                _check_install_contained_data_root(copied, scratch, report)
                _run_once(
                    copied,
                    report,
                    probe=probe_copy,
                    fastembed_cache=args.fastembed_cache,
                    kokoro_assets=args.kokoro_assets,
                    inference_timeout=args.inference_timeout,
                )
                for mode, kwargs in (("dev_mode_safe_start", {"dev": True}), ("demo_mode_safe_start", {"demo": True})):
                    if not report.failed:
                        new_checks = len(report.checks)
                        _run_once(copied, report, probe=probe_copy, fastembed_cache=args.fastembed_cache, kokoro_assets=args.kokoro_assets, run_probe=False, **kwargs)
                        if not any(item.status == "failed" for item in report.checks[new_checks:]):
                            report.add(mode, "passed")
                after = _snapshot_resources(copied)
                if before != after:
                    report.add("immutable_resource_hashes", "failed", "bundle resources changed during smoke runs")
                else:
                    report.add("immutable_resource_hashes", "passed", f"{len(before)} resource hashes unchanged")
                if probe_copy is None:
                    report.add("worker_audio_export", "unverified", "requires the separate frozen probe executable and Windows SAPI")
                if not args.fastembed_cache or not args.kokoro_assets:
                    report.add("external_fastembed_and_kokoro_assets", "unverified", "supply both test-only asset paths to enable real optional model inference")
                if args.strict:
                    if not args.fastembed_cache or not args.fastembed_cache.is_dir():
                        report.add("fastembed_real_model", "failed", "strict mode requires --fastembed-cache with real model files")
                    if not args.kokoro_assets or not args.kokoro_assets.is_dir():
                        report.add("kokoro_real_model", "failed", "strict mode requires --kokoro-assets with real ONNX and voice files")
                    if probe_copy is None:
                        report.add("frozen_probe_required", "failed", "strict mode requires the separately built frozen probe executable")
                    if any(item.status == "unverified" for item in report.checks):
                        report.add("strict_gate_complete", "failed", "strict acceptance requires every gate to be verified")
            except Exception as exc:
                report.add("bundle_smoke", "failed", f"{type(exc).__name__}: {exc}")
                if args.strict:
                    report.add("strict_gate_requirements", "failed", "strict mode stopped before every required frozen check passed")
    result = report.as_dict()
    _emit_report(result, args.report)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
