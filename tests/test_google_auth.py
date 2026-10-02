"""Runtime-profile paths used by Google OAuth persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from clients import google_auth


class GoogleAuthRuntimePathTests(unittest.TestCase):
    def test_refresh_reads_and_writes_token_under_selected_data_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-google-auth-") as temporary:
            root = Path(temporary) / "managed-data"
            paths = SimpleNamespace(
                google_token_path=root / "token.json",
                google_credentials_path=root / "credentials.json",
            )
            root.mkdir(parents=True)
            paths.google_token_path.touch()
            credentials = Mock(valid=False, expired=True, refresh_token="refresh")
            credentials.to_json.return_value = '{"token":"refreshed"}'
            with patch.object(google_auth, "get_runtime_paths", return_value=paths), patch.object(
                google_auth, "initialize_environment"
            ), patch.object(
                google_auth.Credentials,
                "from_authorized_user_file",
                return_value=credentials,
            ) as load_credentials, patch.object(
                google_auth, "Request"
            ) as request, patch.object(google_auth, "build", return_value="service"):
                service = google_auth.get_service("gmail", "v1")

            self.assertEqual(service, "service")
            load_credentials.assert_called_once_with(str(paths.google_token_path), google_auth.SCOPES)
            credentials.refresh.assert_called_once_with(request.return_value)
            self.assertEqual(paths.google_token_path.read_text(encoding="utf-8"), '{"token":"refreshed"}')

    def test_interactive_auth_uses_selected_credentials_and_token_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-google-auth-") as temporary:
            root = Path(temporary) / "managed-data"
            paths = SimpleNamespace(
                google_token_path=root / "token.json",
                google_credentials_path=root / "credentials.json",
            )
            flow = Mock()
            credentials = Mock(valid=True, expired=False, refresh_token=None)
            credentials.to_json.return_value = '{"token":"new"}'
            flow.run_local_server.return_value = credentials
            with patch.object(google_auth, "get_runtime_paths", return_value=paths), patch.object(
                google_auth, "initialize_environment"
            ), patch.object(
                google_auth, "Credentials"
            ) as credentials_type, patch.object(
                google_auth.InstalledAppFlow,
                "from_client_secrets_file",
                return_value=flow,
            ) as create_flow, patch.object(google_auth, "build", return_value="service"):
                credentials_type.from_authorized_user_file.side_effect = FileNotFoundError
                service = google_auth.get_service("calendar", "v3")

            self.assertEqual(service, "service")
            create_flow.assert_called_once_with(str(paths.google_credentials_path), google_auth.SCOPES)
            self.assertEqual(paths.google_token_path.read_text(encoding="utf-8"), '{"token":"new"}')


if __name__ == "__main__":
    unittest.main()
