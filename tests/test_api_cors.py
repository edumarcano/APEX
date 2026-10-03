"""CORS behavior at the production FastAPI middleware boundary."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from core.api.app import DEFAULT_ALLOWED_ORIGINS, app, get_allowed_origins


class ApiCorsTests(unittest.TestCase):
    def setUp(self) -> None:
        # Do not enter the app lifespan: CORS and the root health route need no
        # database or writable runtime profile.
        self.client = TestClient(app)

    def test_desktop_shell_origin_is_allowed_for_api_get(self) -> None:
        response = self.client.get(
            "/", headers={"Origin": "http://tauri.localhost"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://tauri.localhost",
        )

    def test_desktop_shell_preflight_allows_sse_replay_and_cancel_headers(self) -> None:
        origin = "http://tauri.localhost"
        preflights = (
            ("/api/v1/cortex/runs/example/events", "GET", "last-event-id"),
            ("/api/v1/cortex/runs/example/cancel", "POST", "content-type"),
        )

        for path, method, requested_headers in preflights:
            with self.subTest(path=path):
                response = self.client.options(
                    path,
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": method,
                        "Access-Control-Request-Headers": requested_headers,
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers.get("access-control-allow-origin"), origin
                )
                self.assertIn(
                    requested_headers,
                    response.headers.get("access-control-allow-headers", "").lower(),
                )

    def test_unrelated_browser_origin_is_not_allowed(self) -> None:
        response = self.client.get(
            "/", headers={"Origin": "https://example.invalid"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_explicit_allowed_origins_replace_defaults(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "APEX_ALLOWED_ORIGINS": (
                    "https://hud.example, http://localhost:6000"
                )
            },
        ):
            self.assertEqual(
                get_allowed_origins(),
                ["https://hud.example", "http://localhost:6000"],
            )
            self.assertNotIn("http://tauri.localhost", get_allowed_origins())

        self.assertIn("http://tauri.localhost", DEFAULT_ALLOWED_ORIGINS)


if __name__ == "__main__":
    unittest.main()
