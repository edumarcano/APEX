import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

[SCOPES] = ["https://www.googleapis.com/auth/gmail.readonly"]

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

if __name__ == "__main__":
    print("[SYSTEM]: Attempting Gmail authentication...")
    credentials = authenticate_gmail()
    if credentials and credentials.valid:
        print("[SYSTEM]: Authentication successful! token.json created.")
    else:
        print("[ERROR]: Gmail authentication failed.")