from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from core.runtime_paths import get_runtime_paths, initialize_environment

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/calendar.readonly"]


def get_service(api_name: str, api_version: str) -> Any:
    """Get a service object for the given API name and version."""
    initialize_environment()
    paths = get_runtime_paths()
    creds = None
    if paths.google_token_path.exists():
        creds = Credentials.from_authorized_user_file(str(paths.google_token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(paths.google_credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
            
        paths.google_token_path.parent.mkdir(parents=True, exist_ok=True)
        with paths.google_token_path.open('w', encoding='utf-8') as token:
            token.write(creds.to_json())
    return build(api_name, api_version, credentials=creds)
