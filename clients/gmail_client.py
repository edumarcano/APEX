from email.utils import parsedate_to_datetime
from typing import Any

from clients.google_auth import get_service


def get_unread_gmail_data(service: Any) -> dict[str, int | list[dict[str, str]]]:
    """
    Fetches unread email data excluding promotions, social, and updates categories.

    Args:
        service: A service object for the Gmail API.

    Returns:
        A dictionary containing the total unread count and a list of up to three
        emails with subject and formatted time.
    """
    list_resp: dict[str, Any] = (
        service.users()
        .messages()
        .list(
            userId='me',
            q='is:unread -category:promotions -category:social -category:updates newer_than:1d',
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
    print("[GMAIL] Attempting Gmail authentication.")
    service = get_service('gmail', 'v1')

    if service:
        print("[GMAIL] Authentication successful. Fetching data.")
        inbox_data = get_unread_gmail_data(service)
        unread_count = int(inbox_data.get("count", 0))
        sampled_count = len(inbox_data.get("emails", []))
        print(
            f"[GMAIL] Successfully fetched {unread_count} unread messages "
            f"(sampled {sampled_count})."
        )
    else:
        print("[GMAIL] Error: Gmail authentication failed.")
