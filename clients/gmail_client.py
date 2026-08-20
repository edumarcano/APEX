import base64
import html
import re
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

from googleapiclient.errors import HttpError

from clients.google_auth import get_service
from core.config import is_dev_mode

_DEV_MASKED_SUBJECT = "[HIDDEN] Message content masked due to DEV_MODE"
_DEV_OFFLINE_SUBJECT = (
    "[HIDDEN] Local sandbox: Gmail unavailable (offline / token missing)"
)
_DEV_MASKED_VALUE = "[HIDDEN]"
_MAX_SEARCH_RESULTS = 20
_MAX_SNIPPET_CHARS = 500
_MAX_MESSAGE_BODY_CHARS = 12_000
_MAX_ENCODED_BODY_CHARS = 64_000
_MAX_HEADER_CHARS = 300
_MAX_IDENTIFIER_CHARS = 256
_MAX_LABELS = 5
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class GmailAuthenticationRequiredError(RuntimeError):
    """Raised when Gmail credentials are missing or no longer valid."""


class GmailInsufficientScopeError(RuntimeError):
    """Raised when the Google token does not grant Gmail read access."""


class _PlainTextHTMLParser(HTMLParser):
    """Extract inert text from an HTML-only email body."""

    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "table",
        "tr",
    }
    _IGNORED_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif tag in self._BLOCK_TAGS and self.parts:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in self._BLOCK_TAGS and self.parts:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _sanitize_plain_text(value: str, *, limit: int) -> tuple[str, bool]:
    normalized = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHARACTERS.sub("", normalized)
    lines = [" ".join(line.split()) for line in normalized.splitlines()]
    cleaned = "\n".join(line for line in lines if line).strip()
    if len(cleaned) <= limit:
        return cleaned, False
    return cleaned[:limit].rstrip(), True


def _bounded_text(value: Any, *, limit: int) -> str:
    return _sanitize_plain_text(str(value or ""), limit=limit)[0]


def _decode_body_data(data: Any) -> str:
    if not isinstance(data, str) or not data:
        return ""
    bounded = data[:_MAX_ENCODED_BODY_CHARS]
    if len(data) > _MAX_ENCODED_BODY_CHARS:
        bounded = bounded[: len(bounded) - (len(bounded) % 4)]
    try:
        padding = "=" * (-len(bounded) % 4)
        decoded = base64.urlsafe_b64decode(bounded + padding)
        return decoded.decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _html_to_plain_text(value: str) -> str:
    parser = _PlainTextHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return ""
    return "".join(parser.parts)


def _payload_text(payload: Any) -> tuple[str, bool]:
    """Return bounded inert text, preferring text/plain over HTML fallback."""
    if not isinstance(payload, dict):
        return "", False

    plain_parts: list[str] = []
    html_parts: list[str] = []

    def visit(part: Any) -> None:
        if not isinstance(part, dict):
            return
        if part.get("filename"):
            return
        body = part.get("body")
        if isinstance(body, dict) and body.get("attachmentId"):
            return
        part_headers = _headers(part)
        if (
            part_headers.get("content-disposition", "")
            .lower()
            .startswith("attachment")
            or part_headers.get("content-id")
        ):
            return

        mime_type = str(part.get("mimeType") or "").lower()
        decoded = _decode_body_data(body.get("data") if isinstance(body, dict) else None)
        if decoded:
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(_html_to_plain_text(decoded))

        for child in part.get("parts") or []:
            visit(child)

    visit(payload)
    selected = "\n".join(plain_parts or html_parts)
    return _sanitize_plain_text(selected, limit=_MAX_MESSAGE_BODY_CHARS)


def _headers(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    result: dict[str, str] = {}
    for header in payload.get("headers") or []:
        if not isinstance(header, dict):
            continue
        name = header.get("name")
        value = header.get("value")
        if isinstance(name, str) and isinstance(value, str):
            result[name.lower()] = _bounded_text(value, limit=_MAX_HEADER_CHARS)
    return result


def _labels(message: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for label in (message.get("labelIds") or [])[:_MAX_LABELS]:
        if not isinstance(label, str):
            continue
        cleaned = _bounded_text(label, limit=50)
        if cleaned:
            labels.append(cleaned)
    return labels


def _message_metadata(
    message: dict[str, Any],
    *,
    fallback_id: str,
    fallback_thread_id: str = "",
) -> dict[str, Any]:
    headers = _headers(message.get("payload"))
    return {
        "id": _bounded_text(
            message.get("id") or fallback_id, limit=_MAX_IDENTIFIER_CHARS
        ),
        "thread_id": _bounded_text(
            message.get("threadId") or fallback_thread_id,
            limit=_MAX_IDENTIFIER_CHARS,
        ),
        "sender": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "labels": _labels(message),
        "snippet": _bounded_text(
            message.get("snippet"), limit=_MAX_SNIPPET_CHARS
        ),
    }


def _mask_private_message_fields(message: dict[str, Any]) -> None:
    if not is_dev_mode():
        return
    message.update(
        {
            "sender": _DEV_MASKED_VALUE,
            "subject": _DEV_MASKED_SUBJECT,
            "snippet": _DEV_MASKED_VALUE,
        }
    )
    if "body" in message:
        message.update({"body": _DEV_MASKED_VALUE, "truncated": False})


def _raise_typed_gmail_error(exc: HttpError) -> None:
    status = getattr(exc.resp, "status", None)
    detail = bytes(exc.content or b"").lower()
    if status == 401:
        raise GmailAuthenticationRequiredError(
            "Gmail authentication is required."
        ) from exc
    if status == 403 and any(
        marker in detail
        for marker in (
            b"insufficientpermissions",
            b"insufficient permission",
            b"insufficient authentication scopes",
            b"insufficient_scope",
        )
    ):
        raise GmailInsufficientScopeError(
            "Gmail read permission is required."
        ) from exc
    raise exc


def search_gmail(
    service: Any,
    query: str,
    *,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search Gmail and return bounded read-only message metadata."""
    bounded_count = max(1, min(_MAX_SEARCH_RESULTS, int(max_results)))
    try:
        response: dict[str, Any] = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=bounded_count)
            .execute()
        )
        messages = response.get("messages") or []
        results: list[dict[str, Any]] = []
        for item in messages[:bounded_count]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            requested_id = _bounded_text(
                item["id"], limit=_MAX_IDENTIFIER_CHARS
            )
            if not requested_id:
                continue
            message: dict[str, Any] = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=requested_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            result = _message_metadata(
                message,
                fallback_id=requested_id,
                fallback_thread_id=str(item.get("threadId") or ""),
            )
            _mask_private_message_fields(result)
            results.append(result)
        return {
            "query": _bounded_text(query, limit=500),
            "result_count": len(results),
            "messages": results,
        }
    except HttpError as exc:
        _raise_typed_gmail_error(exc)
        raise


def get_gmail_message(service: Any, message_id: str) -> dict[str, Any]:
    """Retrieve one Gmail message as bounded, sanitized plain text."""
    try:
        message: dict[str, Any] = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        body, truncated = _payload_text(message.get("payload"))
        result = _message_metadata(
            message,
            fallback_id=message_id,
        )
        result.update({"body": body, "truncated": truncated})
        _mask_private_message_fields(result)
        return result
    except HttpError as exc:
        _raise_typed_gmail_error(exc)
        raise


def get_unread_gmail_data(service: Any) -> dict[str, Any]:
    """
    Fetches unread email data excluding promotions, social, and updates categories.

    Args:
        service: A service object for the Gmail API.

    Returns:
        A dictionary containing the primary-inbox unread count and up to eight
        metadata-only recent candidates. Message bodies are never requested.
    """
    try:
        list_resp: dict[str, Any] = (
            service.users()
            .messages()
            .list(
                userId='me',
                q=(
                    'is:unread -category:promotions -category:social '
                    '-category:updates'
                ),
                maxResults=8,
            )
            .execute()
        )

        messages_meta: list[dict[str, Any]] = list_resp.get('messages') or []
        estimate = list_resp.get('resultSizeEstimate')
        count: int = len(messages_meta) if estimate is None else int(estimate)

        id_slice = [m['id'] for m in messages_meta[:8] if isinstance(m, dict) and isinstance(m.get('id'), str)]

        emails: list[dict[str, str]] = []
        for msg_id in id_slice:
            msg: dict[str, Any] = (
                service.users()
                .messages()
                .get(
                    userId='me',
                    id=msg_id,
                    format='metadata',
                    metadataHeaders=['subject', 'date', 'from'],
                )
                .execute()
            )
            subject: str | None = None
            date_value: str | None = None
            sender: str | None = None
            for header in msg.get('payload', {}).get('headers', []):
                header_name = header.get('name', '').lower()
                if header_name == 'subject':
                    subject = header.get('value')
                elif header_name == 'date':
                    date_value = header.get('value')
                elif header_name == 'from':
                    sender = header.get('value')

            time_str = ''
            received_at = ''
            if date_value:
                try:
                    parsed_datetime = parsedate_to_datetime(date_value)
                    time_str = parsed_datetime.strftime('%I:%M %p').lstrip('0')
                    received_at = parsed_datetime.isoformat()
                except (TypeError, ValueError):
                    time_str = ''

            emails.append(
                {
                    'subject': subject if subject is not None else '',
                    'time': time_str,
                    'sender': sender if sender is not None else '',
                    'received_at': received_at,
                    'snippet': _bounded_text(msg.get('snippet'), limit=_MAX_SNIPPET_CHARS),
                }
            )

        if is_dev_mode():
            return {
                'count': count,
                'emails': [
                    {
                        'subject': _DEV_MASKED_SUBJECT,
                        'time': email.get('time', ''),
                        'sender': _DEV_MASKED_VALUE,
                        'received_at': email.get('received_at', ''),
                        'snippet': _DEV_MASKED_VALUE,
                    }
                    for email in emails
                ],
            }

        return {'count': count, 'emails': emails}
    except Exception:
        if is_dev_mode():
            return {
                'count': 0,
                'emails': [{'subject': _DEV_OFFLINE_SUBJECT, 'time': '', 'sender': _DEV_MASKED_VALUE, 'received_at': '', 'snippet': _DEV_MASKED_VALUE}],
            }
        raise


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
