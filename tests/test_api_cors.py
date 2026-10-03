"""CORS behavior at the production FastAPI middleware boundary."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class ApiCorsTests(unittest.TestCase):
    def _run_production_app_checks(
        self, script: str, *, allowed_origins: str | None
    ) -> None:
        env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        env["PYTHON_DOTENV_DISABLED"] = "1"
        if allowed_origins is not None:
            env["APEX_ALLOWED_ORIGINS"] = allowed_origins

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"production CORS checks failed:\n{result.stdout}\n{result.stderr}",
        )

    def test_default_origins_allow_desktop_get_and_preflights(self) -> None:
        self._run_production_app_checks(
            r"""
from fastapi.testclient import TestClient
from core.api.app import app

client = TestClient(app)
origin = "http://tauri.localhost"
get_response = client.get("/", headers={"Origin": origin})
assert get_response.status_code == 200
assert get_response.headers.get("access-control-allow-origin") == origin

for path, method, requested_header in (
    ("/api/v1/cortex/runs/example/events", "GET", "last-event-id"),
    ("/api/v1/cortex/runs/example/cancel", "POST", "content-type"),
):
    response = client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": requested_header,
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == origin
    allow_headers = response.headers.get("access-control-allow-headers", "").lower()
    assert requested_header in allow_headers

unrelated = client.get("/", headers={"Origin": "https://example.invalid"})
assert unrelated.status_code == 200
assert "access-control-allow-origin" not in unrelated.headers
""",
            allowed_origins=None,
        )

    def test_configured_origins_replace_defaults_in_production_middleware(self) -> None:
        self._run_production_app_checks(
            r"""
from fastapi.testclient import TestClient
from core.api.app import app

client = TestClient(app)
configured = "https://hud.example"
accepted = client.get("/", headers={"Origin": configured})
assert accepted.status_code == 200
assert accepted.headers.get("access-control-allow-origin") == configured

native = "http://tauri.localhost"
rejected = client.get("/", headers={"Origin": native})
assert rejected.status_code == 200
assert "access-control-allow-origin" not in rejected.headers

preflight = client.options(
    "/api/v1/cortex/runs/example/cancel",
    headers={
        "Origin": native,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    },
)
assert preflight.status_code == 400
assert "access-control-allow-origin" not in preflight.headers
""",
            allowed_origins="https://hud.example",
        )


if __name__ == "__main__":
    unittest.main()
