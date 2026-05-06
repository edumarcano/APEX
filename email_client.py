import os
from email.utils import parsedate_to_datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def authenticate_gmail():
    """
    Handles Google OAuth2.0 authentication.
    Checks for an existing token.json file, and if not,
    prompts the user to log in and generates a new token

    Returns:
        Credentials to be used with the Gmail API.
    """

    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds


def get_unread_gmail_data(
    creds: Credentials,
) -> dict[str, int | list[dict[str, str]]]:
    """
    Fetches unread email data excluding promotions, social, and updates categories.

    Args:
        creds: Authorized OAuth2 credentials for Gmail API access.

    Returns:
        A dictionary containing the total unread count and a list of up to three
        emails with subject and formatted time.
    """
    service = build('gmail', 'v1', credentials=creds)
    list_resp: dict[str, Any] = (
        service.users()
        .messages()
        .list(
            userId='me',
            q='is:unread -category:promotions -category:social -category:updates' 'newer_than:1d',
        )
        .execute()
    )

    messages_meta: list[dict[str, Any]] = list_resp.get('messages') or []
    estimate = list_resp.get('resultSizeEstimate')
    count: int = len(messages_meta) if estimate is None else int(estimate)

    id_slice = [m['id'] for m in messages_meta[:3]]

    emails: list[dict[str, str]] = []
    for msg_id in id_slice:
        msg: dict[str, Any] = (
            service.users()
            .messages()
            .get(userId='me', id=msg_id, format='full')
            .execute()
        )
        subject: str | None = None
        date_value: str | None = None
        for header in msg.get('payload', {}).get('headers', []):
            header_name = header.get('name', '').lower()
            if header_name == 'subject':
                subject = header.get('value')
            elif header_name == 'date':
                date_value = header.get('value')

        time_str = ''
        if date_value:
            try:
                parsed_datetime = parsedate_to_datetime(date_value)
                time_str = parsed_datetime.strftime('%I:%M %p').lstrip('0')
            except (TypeError, ValueError):
                time_str = ''

        emails.append(
            {
                'subject': subject if subject is not None else '',
                'time': time_str,
            }
        )

    return {'count': count, 'emails': emails}


if __name__ == "__main__":
    print("[SYSTEM]: Attempting Gmail authentication...")
    credentials = authenticate_gmail()

    if credentials and credentials.valid:
        print("[SYSTEM]: Authentication successful! fetching data...")
        inbox_data = get_unread_gmail_data(credentials)
        print(f"[SYSTEM]: Extraction Complete. Data: {inbox_data}")
    else:
        print("[ERROR]: Gmail authentication failed.")