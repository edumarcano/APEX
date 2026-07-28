"""Read-only Gmail connector and assistant capability coverage."""

from __future__ import annotations

import base64
import unittest
from unittest import mock

from googleapiclient.errors import HttpError

from clients import gmail_client
from core.agent.capabilities import (
    CapabilityError,
    CapabilityErrorCategory,
    invoke_capability,
)


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _service(
    *,
    list_response: dict | None = None,
    get_responses: list[dict] | None = None,
) -> mock.MagicMock:
    service = mock.MagicMock()
    messages_api = service.users.return_value.messages.return_value
    messages_api.list.return_value.execute.return_value = list_response or {}
    if get_responses is not None:
        messages_api.get.return_value.execute.side_effect = get_responses
    return service


class GmailClientTests(unittest.TestCase):
    def test_search_returns_bounded_metadata_and_snippets(self) -> None:
        messages = [
            {
                "id": f"message-{index}",
                "threadId": f"thread-{index}",
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": f"Snippet {index}",
                "payload": {
                    "headers": [
                        {"name": "From", "value": f"Sender {index} <sender@test>"},
                        {"name": "Subject", "value": f"Subject {index}"},
                        {"name": "Date", "value": "Mon, 27 Jul 2026 09:30:00 -0400"},
                    ]
                },
            }
            for index in range(3)
        ]
        service = _service(
            list_response={
                "messages": [
                    {"id": message["id"], "threadId": message["threadId"]}
                    for message in messages
                ]
            },
            get_responses=messages,
        )

        result = gmail_client.search_gmail(
            service,
            "from:sender@test is:unread",
            max_results=2,
        )

        self.assertEqual(result["query"], "from:sender@test is:unread")
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(
            result["messages"][0],
            {
                "id": "message-0",
                "thread_id": "thread-0",
                "sender": "Sender 0 <sender@test>",
                "subject": "Subject 0",
                "date": "Mon, 27 Jul 2026 09:30:00 -0400",
                "labels": ["INBOX", "UNREAD"],
                "snippet": "Snippet 0",
            },
        )
        list_call = (
            service.users.return_value.messages.return_value.list.call_args.kwargs
        )
        self.assertEqual(list_call["maxResults"], 2)

    def test_message_prefers_plain_text_and_excludes_attachments_and_html(self) -> None:
        message = {
            "id": "message-1",
            "threadId": "thread-1",
            "labelIds": ["INBOX"],
            "snippet": "Short preview",
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "From", "value": "Sender <sender@test>"},
                    {"name": "Subject", "value": "Quarterly report"},
                    {"name": "Date", "value": "Mon, 27 Jul 2026 09:30:00 -0400"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _encoded("Plain body\nSecond line")},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {
                            "data": _encoded(
                                "<p>HTML body</p><script>attack()</script>"
                            )
                        },
                    },
                    {
                        "mimeType": "text/plain",
                        "filename": "secret.txt",
                        "body": {"data": _encoded("Attachment contents")},
                    },
                    {
                        "mimeType": "text/plain",
                        "headers": [
                            {
                                "name": "Content-Disposition",
                                "value": "attachment",
                            }
                        ],
                        "body": {"data": _encoded("Hidden attachment")},
                    },
                    {
                        "mimeType": "image/png",
                        "body": {"attachmentId": "embedded-image"},
                    },
                ],
            },
        }
        service = _service(get_responses=[message])

        result = gmail_client.get_gmail_message(service, "message-1")

        self.assertEqual(result["body"], "Plain body\nSecond line")
        self.assertFalse(result["truncated"])
        self.assertNotIn("HTML body", result["body"])
        self.assertNotIn("Attachment contents", result["body"])
        self.assertNotIn("Hidden attachment", result["body"])
        get_call = (
            service.users.return_value.messages.return_value.get.call_args.kwargs
        )
        self.assertEqual(get_call["format"], "full")

    def test_html_only_message_becomes_inert_bounded_plain_text(self) -> None:
        message = {
            "id": "message-2",
            "payload": {
                "mimeType": "text/html",
                "headers": [],
                "body": {
                    "data": _encoded(
                        "<p>Hello <strong>operator</strong></p>"
                        "<script>ignore me</script><style>.bad{}</style>"
                    )
                },
            },
        }
        service = _service(get_responses=[message])

        result = gmail_client.get_gmail_message(service, "message-2")

        self.assertEqual(result["body"], "Hello operator")
        self.assertNotIn("<", result["body"])
        self.assertNotIn("ignore me", result["body"])

    def test_message_body_is_truncated_to_strict_limit(self) -> None:
        message = {
            "id": "message-3",
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": _encoded("x" * 13_000)},
            },
        }
        service = _service(get_responses=[message])

        result = gmail_client.get_gmail_message(service, "message-3")

        self.assertEqual(len(result["body"]), 12_000)
        self.assertTrue(result["truncated"])

    def test_dev_mode_masks_search_and_message_content(self) -> None:
        metadata = {
            "id": "message-4",
            "threadId": "thread-4",
            "snippet": "Private preview",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "Private sender"},
                    {"name": "Subject", "value": "Private subject"},
                ],
                "body": {"data": _encoded("Private body")},
            },
        }
        search_service = _service(
            list_response={"messages": [{"id": "message-4"}]},
            get_responses=[metadata],
        )
        message_service = _service(get_responses=[metadata])

        with mock.patch("clients.gmail_client.is_dev_mode", return_value=True):
            search = gmail_client.search_gmail(search_service, "is:unread")
            message = gmail_client.get_gmail_message(
                message_service,
                "message-4",
            )

        self.assertEqual(search["messages"][0]["sender"], "[HIDDEN]")
        self.assertIn("[HIDDEN]", search["messages"][0]["subject"])
        self.assertEqual(search["messages"][0]["snippet"], "[HIDDEN]")
        self.assertEqual(message["body"], "[HIDDEN]")

    def test_insufficient_scope_is_classified_without_raw_google_error(self) -> None:
        response = mock.MagicMock(status=403, reason="Forbidden")
        failure = HttpError(
            response,
            b'{"error":{"errors":[{"reason":"insufficientPermissions"}]}}',
        )
        service = mock.MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            failure
        )

        with self.assertRaises(gmail_client.GmailInsufficientScopeError):
            gmail_client.search_gmail(service, "is:unread")


class GmailCapabilityTests(unittest.TestCase):
    def test_search_capability_uses_existing_google_service_and_clamps_count(
        self,
    ) -> None:
        service = object()
        with mock.patch(
            "clients.google_auth.get_service",
            return_value=service,
        ) as get_service, mock.patch(
            "clients.gmail_client.search_gmail",
            return_value={"query": "is:unread", "result_count": 0, "messages": []},
        ) as search:
            result = invoke_capability(
                "search_gmail",
                {"query": "is:unread", "max_results": 99},
            )

        get_service.assert_called_once_with("gmail", "v1")
        search.assert_called_once_with(service, "is:unread", max_results=20)
        self.assertEqual(result["result_count"], 0)

    def test_missing_google_service_is_authentication_error(self) -> None:
        with mock.patch("clients.google_auth.get_service", return_value=None):
            with self.assertRaises(CapabilityError) as raised:
                invoke_capability("get_gmail_message", {"message_id": "message-1"})

        self.assertEqual(
            raised.exception.category,
            CapabilityErrorCategory.AUTHENTICATION,
        )
        self.assertEqual(
            raised.exception.message,
            "Gmail authentication is required.",
        )

    def test_blank_gmail_arguments_are_invalid_input(self) -> None:
        for name, arguments in (
            ("search_gmail", {"query": "   "}),
            ("get_gmail_message", {"message_id": "   "}),
        ):
            with self.subTest(name=name):
                with self.assertRaises(CapabilityError) as raised:
                    invoke_capability(name, arguments)
                self.assertEqual(
                    raised.exception.category,
                    CapabilityErrorCategory.INVALID_INPUT,
                )

    def test_insufficient_scope_is_authentication_error(self) -> None:
        with mock.patch(
            "clients.google_auth.get_service",
            return_value=object(),
        ), mock.patch(
            "clients.gmail_client.search_gmail",
            side_effect=gmail_client.GmailInsufficientScopeError("private"),
        ):
            with self.assertRaises(CapabilityError) as raised:
                invoke_capability("search_gmail", {"query": "is:unread"})

        self.assertEqual(
            raised.exception.category,
            CapabilityErrorCategory.AUTHENTICATION,
        )
        self.assertEqual(
            raised.exception.message,
            "Gmail read permission is required.",
        )
        self.assertNotIn("private", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
