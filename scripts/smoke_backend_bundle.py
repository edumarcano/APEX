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


def _sanitized_environment(root: Path, profile: Path, *, dev: bool = False, demo: bool = False) -> dict[str, str]:
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
    if not local_config.exists():
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


def _run_once(bundle: Path, report: Report, *, dev: bool = False, demo: bool = False, probe: Path | None = None, fastembed_cache: Path | None = None, kokoro_assets: Path | None = None, run_probe: bool = True) -> None:
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
        process, frames, _stdout, stderr, launch_id = _spawn_host(bundle / "apex-backend.exe", profile, root, dev=dev, demo=demo)
        spawned.append(process)
        started = _next_envelope(frames, time.monotonic() + DEFAULT_TIMEOUT)
        if started.get("type") != "starting" or started.get("request_id") != launch_id:
            raise RuntimeError("managed host did not acknowledge the launch with a starting envelope")
        ready = _next_envelope(frames, time.monotonic() + DEFAULT_TIMEOUT)
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
                output = _cli(probe, ["optional-assets"], cwd, probe_env, timeout_seconds=120)
                result = json.loads(output)
                if result.get("status") != "passed":
                    raise RuntimeError(f"real optional asset probe failed: {result}")
                report.add("fastembed_and_kokoro_real_assets", "passed")
            else:
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
            eof_starting = _next_envelope(eof_frames, time.monotonic() + DEFAULT_TIMEOUT)
            eof_ready = _next_envelope(eof_frames, time.monotonic() + DEFAULT_TIMEOUT)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded real-process checks against an APEX backend bundle.")
    parser.add_argument("--bundle", type=Path, required=True, help="Directory containing apex-backend.exe, apex.exe, and _internal.")
    parser.add_argument("--probe", type=Path, help="Separate build-only frozen probe executable.")
    parser.add_argument("--report", type=Path, help="Optional JSON report output file.")
    parser.add_argument("--strict", action="store_true", help="Require real optional model assets and every branch-3 bundle check to pass.")
    parser.add_argument("--fastembed-cache", type=Path, help="Test-only external FastEmbed model cache.")
    parser.add_argument("--kokoro-assets", type=Path, help="Test-only directory containing Kokoro ONNX and voice files.")
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
                _run_once(copied, report, probe=probe_copy, fastembed_cache=args.fastembed_cache, kokoro_assets=args.kokoro_assets)
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
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
