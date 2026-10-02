"""Rehearse profile isolation across fresh source and frozen-style processes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

_AUDIT_HELPERS = r'''
import os

def _canonical(value):
    if isinstance(value, int) or value is None:
        return None
    try:
        raw = os.fsdecode(os.fspath(value))
        if not os.path.isabs(raw):
            raw = os.path.join(os.getcwd(), raw)
        return os.path.normcase(os.path.realpath(raw))
    except (TypeError, ValueError, OSError):
        return None

def _inside(candidate, root):
    candidate = _canonical(candidate)
    root = _canonical(root)
    if candidate is None or root is None:
        return False
    try:
        return os.path.commonpath((candidate, root)) == root
    except ValueError:
        return False

_protected_roots = tuple(filter(None, (
    os.environ["APEX_AUDIT_RESOURCE_ROOT"],
    os.environ["APEX_AUDIT_CWD"],
    os.environ.get("APEX_AUDIT_INSTALLATION_ROOT"),
)))
_write_violations = []
_write_events = {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.chmod", "os.link", "os.symlink", "os.truncate"}
_write_flags = (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)

def _deny_if_protected(path, event):
    matching_root = next((root for root in _protected_roots if _inside(path, root)), None)
    if matching_root is not None:
        _write_violations.append((event, str(path)))
        raise PermissionError("write outside the selected data profile denied: " + repr((event, str(path), matching_root)))

def _audit(event, args):
    if event == "open":
        path = args[0] if args else None
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        writing = (isinstance(mode, str) and any(token in mode for token in "wax+")) or bool(flags & _write_flags)
        if writing:
            _deny_if_protected(path, event)
    elif event == "sqlite3.connect":
        _deny_if_protected(args[0] if args else None, event)
    elif event in _write_events:
        for path in args[:2] if event == "os.rename" else args[:1]:
            _deny_if_protected(path, event)

import sys
sys.addaudithook(_audit)

def _assert_no_write_violations():
    if _write_violations:
        raise AssertionError("forbidden write attempts: " + repr(_write_violations))
'''

def _source_create_script() -> str:
    return _AUDIT_HELPERS + r'''
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from core.runtime_paths import get_runtime_paths, initialize_environment
paths = initialize_environment()
_assert_no_write_violations()

from core import database
from core.settings.models import SettingsPatch
from core.settings.store import RuntimeSettingsStore
from clients import google_auth, market_client, sports_client

assert paths.resource_root == Path(os.environ["APEX_EXPECT_RESOURCE"]).resolve()
assert paths.data_root == Path(os.environ["APEX_DATA_DIR"]).resolve()
assert database.DB_NAME == str(paths.database_path)

database.initialize_db()
reminder_id = database.save_reminder("runtime profile rehearsal")

settings = RuntimeSettingsStore()
settings.apply_patch(SettingsPatch(user_designation="Profile Operator"))

market_cache = market_client._empty_cache()
market_cache["collection_revision"] = 17
assert market_client._write_cache(market_cache)
f1_marker = {"raceName": "Profile Grand Prix"}
sports_client._write_f1_cache(f1_marker)
kickoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
football_fixture = {
    "fixture_id": "profile-fixture",
    "team_id": 71,
    "team": "Profile FC",
    "opponent": "Runtime United",
    "home_or_away": "home",
    "competition_id": 5,
    "competition": "Profile League",
    "kickoff_at": kickoff,
}
sports_client._write_football_cache({71: [football_fixture]})

class _Credentials:
    valid = True
    expired = False
    refresh_token = None
    def to_json(self):
        return json.dumps({"token": "runtime-profile-token"})

class _Flow:
    def run_local_server(self, *, port):
        assert port == 0
        return _Credentials()

from unittest.mock import patch
with (
    patch.object(google_auth.InstalledAppFlow, "from_client_secrets_file", return_value=_Flow()) as flow,
    patch.object(google_auth, "build", return_value=object()) as build,
):
    google_auth.get_service("calendar", "v3")
    assert flow.call_args.args[0] == str(paths.google_credentials_path)
    build.assert_called_once()

from core.retrieval.docs import documentation_paths
from core.mock.demo_fixture import _load_raw_fixture
from core.api.demo import load_mock_agent_responses
assert any(path.name == "README.md" for path in documentation_paths())
assert isinstance(_load_raw_fixture(), dict)
responses, fallback = load_mock_agent_responses()
assert isinstance(responses, list) and isinstance(fallback, dict)

_assert_no_write_violations()
print("__APEX_RESULT__" + json.dumps({
    "resource_root": str(paths.resource_root),
    "data_root": str(paths.data_root),
    "database_path": str(paths.database_path),
    "reminder_id": reminder_id,
    "designation": settings.get_snapshot().user_designation,
    "market_revision": market_cache["collection_revision"],
    "f1_marker": f1_marker["raceName"],
    "football_fixture": football_fixture["fixture_id"],
}))
'''


def _source_restart_script() -> str:
    return _AUDIT_HELPERS + r'''
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from core.runtime_paths import get_runtime_paths, initialize_environment
paths = initialize_environment()
_assert_no_write_violations()

from core import database
from core.settings.store import RuntimeSettingsStore
from clients import google_auth, market_client, sports_client

assert paths.resource_root == Path(os.environ["APEX_EXPECT_RESOURCE"]).resolve()
assert paths.data_root == Path(os.environ["APEX_DATA_DIR"]).resolve()
assert os.environ["PROFILE_FROM_DOTENV"] == "loaded-from-profile"
assert os.environ["PROFILE_PRECEDENCE"] == "process-value"
assert database.DB_NAME == str(paths.database_path)

reminders = database.fetch_local_reminders()
assert [row["note"] for row in reminders] == ["runtime profile rehearsal"]
settings = RuntimeSettingsStore()
assert settings.get_snapshot().user_designation == "Profile Operator"
assert market_client._read_cache()["collection_revision"] == 17
assert sports_client._read_f1_cache()["f1_map"]["raceName"] == "Profile Grand Prix"
now = datetime.now(timezone.utc)
football = sports_client._read_football_cache(now=now)
assert football[71][1][0]["fixture_id"] == "profile-fixture"

class _Credentials:
    valid = True
    expired = False
    refresh_token = None

from unittest.mock import patch
with (
    patch.object(google_auth.Credentials, "from_authorized_user_file", return_value=_Credentials()) as load_token,
    patch.object(google_auth, "build", return_value=object()) as build,
):
    google_auth.get_service("calendar", "v3")
    assert load_token.call_args.args[0] == str(paths.google_token_path)
    assert Path(paths.google_token_path).read_text(encoding="utf-8") == '{"token": "runtime-profile-token"}'
    build.assert_called_once()

_assert_no_write_violations()
print("__APEX_RESULT__" + json.dumps({
    "resource_root": str(paths.resource_root),
    "data_root": str(paths.data_root),
    "reminder": reminders[0]["note"],
    "designation": settings.get_snapshot().user_designation,
    "market_revision": market_client._read_cache()["collection_revision"],
    "f1_marker": sports_client._read_f1_cache()["f1_map"]["raceName"],
    "football_fixture": football[71][1][0]["fixture_id"],
    "google_token_path": str(paths.google_token_path),
}))
'''


def _frozen_script() -> str:
    return r'''
import json
import os
import sys
from pathlib import Path
_real_executable = sys.executable
# Model only the frozen path inputs here. The packaged Python bootloader and
# its dependency search rules are a separate bundle-build acceptance gate.
sys.frozen = True
sys._MEIPASS = os.environ["APEX_SIM_RESOURCE_ROOT"]
sys.executable = os.environ["APEX_SIM_EXECUTABLE"]
''' + _AUDIT_HELPERS + r'''
from core.runtime_paths import get_runtime_paths, initialize_environment
paths = initialize_environment()
del sys.frozen
del sys._MEIPASS
sys.executable = _real_executable
_assert_no_write_violations()
from core import database
from core.mock.demo_fixture import _load_raw_fixture
from core.api.demo import load_mock_agent_responses
from core.retrieval.docs import documentation_paths

expected_resource = Path(os.environ["APEX_SIM_RESOURCE_ROOT"]).resolve()
expected_data = (Path(os.environ["LOCALAPPDATA"]) / "APEX").resolve()
assert paths.resource_root == expected_resource
assert paths.data_root == expected_data
assert paths.installation_root == Path(os.environ["APEX_SIM_EXECUTABLE"]).resolve().parent
assert database.DB_NAME == str(paths.database_path)
database.initialize_db()
database.save_reminder("frozen profile rehearsal")
assert isinstance(_load_raw_fixture(), dict)
responses, fallback = load_mock_agent_responses()
assert isinstance(responses, list) and isinstance(fallback, dict)
assert {path.name for path in documentation_paths()} >= {"README.md", "runtime-profile.md"}
_assert_no_write_violations()
print("__APEX_RESULT__" + json.dumps({
    "resource_root": str(paths.resource_root),
    "data_root": str(paths.data_root),
    "database_path": str(paths.database_path),
    "reminder": database.fetch_local_reminders()[0]["note"],
}))
'''


def _bad_writer_script() -> str:
    return _AUDIT_HELPERS + r'''
import json
import os
from pathlib import Path
from core.runtime_paths import get_runtime_paths, initialize_environment
paths = initialize_environment()
_assert_no_write_violations()
from core import database
try:
    database.initialize_db()
except OSError as exc:
    failure = type(exc).__name__
else:
    raise AssertionError("database initialization unexpectedly accepted a file as its data root")
_assert_no_write_violations()
print("__APEX_RESULT__" + json.dumps({"data_root": str(paths.data_root), "failure": failure}))
'''


class RuntimeProfileRehearsalTests(unittest.TestCase):
    def _run_child(self, script: str, *, cwd: Path, env: dict[str, str]) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if completed.returncode != 0:
            self.fail(
                "runtime-profile child failed "
                f"(exit={completed.returncode})\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        result_lines = [
            line.removeprefix("__APEX_RESULT__")
            for line in completed.stdout.splitlines()
            if line.startswith("__APEX_RESULT__")
        ]
        self.assertEqual(len(result_lines), 1, completed.stdout)
        return json.loads(result_lines[0])

    def _base_env(self, *, cwd: Path, resource_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPOSITORY_ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["APEX_AUDIT_RESOURCE_ROOT"] = str(resource_root)
        env["APEX_AUDIT_CWD"] = str(cwd)
        env.pop("APEX_AUDIT_INSTALLATION_ROOT", None)
        env["APEX_EXPECT_RESOURCE"] = str(resource_root)
        env.pop("PYTHON_DOTENV_DISABLED", None)
        return env

    def test_source_override_persists_data_across_restarts_and_frozen_resources_stay_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profile-rehearsal-") as temp_dir:
            root = Path(temp_dir)
            self.assertFalse(
                root.resolve().is_relative_to(REPOSITORY_ROOT.resolve()),
                "the scratch area must stay outside the source resource tree",
            )
            source_profile = root / "profiles" / "nested" / "source"
            source_cwd = root / "source-cwd"
            source_cwd.mkdir()
            self.assertFalse(source_profile.exists())

            source_env = self._base_env(cwd=source_cwd, resource_root=REPOSITORY_ROOT)
            source_env["APEX_DATA_DIR"] = str(source_profile)
            source_env.pop("PROFILE_FROM_DOTENV", None)
            source_env["PROFILE_PRECEDENCE"] = "process-value"

            created = self._run_child(_source_create_script(), cwd=source_cwd, env=source_env)
            self.assertTrue(source_profile.is_dir(), "database startup must create a fresh profile parent")
            self.assertEqual(created["resource_root"], str(REPOSITORY_ROOT.resolve()))
            self.assertEqual(created["data_root"], str(source_profile.resolve()))
            self.assertEqual(created["designation"], "Profile Operator")
            self.assertFalse(any(source_cwd.iterdir()), "the unrelated working directory must remain untouched")

            other_profile = root / "wrong-profile"
            (source_profile / ".env").write_text(
                "PROFILE_FROM_DOTENV=loaded-from-profile\n"
                "PROFILE_PRECEDENCE=file-value\n"
                f"APEX_DATA_DIR={other_profile}\n",
                encoding="utf-8",
            )
            restarted = self._run_child(_source_restart_script(), cwd=source_cwd, env=source_env)
            self.assertEqual(restarted["data_root"], str(source_profile.resolve()))
            self.assertEqual(restarted["reminder"], "runtime profile rehearsal")
            self.assertEqual(restarted["designation"], "Profile Operator")
            self.assertEqual(restarted["market_revision"], 17)
            self.assertEqual(restarted["f1_marker"], "Profile Grand Prix")
            self.assertEqual(restarted["football_fixture"], "profile-fixture")
            self.assertFalse(other_profile.exists(), "the selected profile's .env must not retarget writes")
            self.assertFalse(any(source_cwd.iterdir()), "the unrelated working directory must remain untouched")

            resource_root = root / "frozen-resources" / "_internal"
            (resource_root / "core" / "mock").mkdir(parents=True)
            (resource_root / "docs").mkdir()
            shutil.copy2(REPOSITORY_ROOT / "config.json", resource_root / "config.json")
            shutil.copy2(REPOSITORY_ROOT / "README.md", resource_root / "README.md")
            shutil.copy2(
                REPOSITORY_ROOT / "docs" / "identity-and-naming.md",
                resource_root / "docs" / "runtime-profile.md",
            )
            shutil.copy2(
                REPOSITORY_ROOT / "core" / "mock" / "telemetry.json",
                resource_root / "core" / "mock" / "telemetry.json",
            )
            shutil.copy2(
                REPOSITORY_ROOT / "core" / "mock" / "assistant.json",
                resource_root / "core" / "mock" / "assistant.json",
            )
            frozen_cwd = root / "frozen-cwd"
            install_root = root / "installed-app"
            local_app_data = root / "local-app-data"
            frozen_cwd.mkdir()
            install_root.mkdir()
            executable = install_root / "APEX.exe"
            frozen_env = self._base_env(cwd=frozen_cwd, resource_root=resource_root)
            frozen_env.pop("APEX_DATA_DIR", None)
            frozen_env["LOCALAPPDATA"] = str(local_app_data)
            frozen_env["APEX_SIM_RESOURCE_ROOT"] = str(resource_root)
            frozen_env["APEX_SIM_EXECUTABLE"] = str(executable)
            frozen_env["APEX_AUDIT_INSTALLATION_ROOT"] = str(install_root)
            frozen_env.pop("PROFILE_FROM_DOTENV", None)

            frozen_files = {
                path.relative_to(resource_root): path.read_bytes()
                for path in resource_root.rglob("*")
                if path.is_file()
            }
            frozen = self._run_child(_frozen_script(), cwd=frozen_cwd, env=frozen_env)
            self.assertEqual(frozen["resource_root"], str(resource_root.resolve()))
            self.assertEqual(frozen["data_root"], str((local_app_data / "APEX").resolve()))
            self.assertEqual(frozen["reminder"], "frozen profile rehearsal")
            self.assertTrue((local_app_data / "APEX" / "apex_memory.db").is_file())
            self.assertFalse(any(install_root.iterdir()), "the simulated installation directory must remain untouched")
            self.assertEqual(
                {
                    path.relative_to(resource_root): path.read_bytes()
                    for path in resource_root.rglob("*")
                    if path.is_file()
                },
                frozen_files,
                "the simulated frozen resource tree must remain byte-for-byte unchanged",
            )
            self.assertFalse(any(frozen_cwd.iterdir()), "the frozen working directory must remain untouched")

            blocked_root = root / "data-root-is-a-file"
            blocked_root.write_text("not a directory", encoding="utf-8")
            failure_env = self._base_env(cwd=source_cwd, resource_root=REPOSITORY_ROOT)
            failure_env["APEX_DATA_DIR"] = str(blocked_root)
            failure_env["PYTHON_DOTENV_DISABLED"] = "1"
            failed = self._run_child(_bad_writer_script(), cwd=source_cwd, env=failure_env)
            self.assertEqual(failed["data_root"], str(blocked_root.resolve()))
            self.assertIn(failed["failure"], {"FileExistsError", "NotADirectoryError"})
            self.assertFalse(any(source_cwd.iterdir()), "failed writes must not fall back to the working directory")


if __name__ == "__main__":
    unittest.main()
