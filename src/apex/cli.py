"""Thin command-line client for the local APEX HTTP API."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

import requests


API_ROOT = "http://127.0.0.1:8000"
_CONNECT_TIMEOUT_SECONDS = 3.0
_DEFAULT_READ_TIMEOUT_SECONDS = 30.0
_LONG_READ_TIMEOUT_SECONDS = 600.0
_CONTEXT_KINDS = (
    "idea",
    "preference",
    "decision",
    "goal",
    "fact",
    "constraint",
    "note",
    "observation",
)
_CONTEXT_STATUSES = ("active", "conflicting", "superseded", "retracted")
_CONTEXT_REVIEW_DECISIONS = ("pending", "accepted", "rejected", "stale")


@dataclass(frozen=True)
class CliError(Exception):
    """A safe CLI-facing failure from the loopback transport."""

    kind: str
    message: str
    status_code: int | None = None
    detail: object | None = None


class ApiClient:
    """One short-lived session for a single CLI invocation."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        # The CLI is a loopback client, so do not inherit proxy or credential
        # settings that could send local prompts or action data elsewhere.
        self._session.trust_env = False

    def close(self) -> None:
        self._session.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        long_running: bool = False,
    ) -> object:
        try:
            response = self._session.request(
                method,
                f"{API_ROOT}{path}",
                json=payload,
                timeout=(
                    _CONNECT_TIMEOUT_SECONDS,
                    _LONG_READ_TIMEOUT_SECONDS
                    if long_running
                    else _DEFAULT_READ_TIMEOUT_SECONDS,
                ),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise CliError(
                "backend_unavailable",
                "APEX is not reachable at http://127.0.0.1:8000.",
            ) from exc

        if not 200 <= response.status_code < 300:
            try:
                body = response.json()
            except ValueError:
                body = None
            detail = body.get("detail") if isinstance(body, dict) else None
            raise CliError(
                "http_error",
                _http_error_message(response.status_code, detail),
                status_code=response.status_code,
                detail=detail,
            )
        return _json_body(response)


def _json_body(response: requests.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise CliError(
            "invalid_response",
            "APEX returned a response that was not valid JSON.",
            status_code=response.status_code,
        ) from exc


def _http_error_message(status_code: int, detail: object | None) -> str:
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return f"APEX rejected the request (HTTP {status_code})."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apex",
        description="Use the running local APEX backend from the command line.",
    )
    _add_json_option(parser)
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="Show backend readiness.")
    _add_json_option(status)
    status.set_defaults(handler=_status)

    models = commands.add_parser("models", help="List models available to Apex Agent.")
    _add_json_option(models)
    models.set_defaults(handler=_models)

    ask = commands.add_parser("ask", help="Run one Agent turn.")
    _add_json_option(ask)
    ask.add_argument("prompt", help="Prompt for Apex Agent.")
    ask.add_argument("--model", help="Model ID. Defaults to the backend selection.")
    ask.add_argument(
        "--effort",
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        help="Cloud model reasoning effort override.",
    )
    ask.add_argument("--profile", help="Saved or built-in tool profile ID.")
    ask.set_defaults(handler=_ask)

    activity = commands.add_parser("activity", help="Submit or inspect untrusted external activity reports.")
    _add_json_option(activity)
    activity_commands = activity.add_subparsers(dest="activity_command", required=True)
    activity_submit = activity_commands.add_parser("submit", help="Submit one report as the local operator.")
    _add_json_option(activity_submit)
    _add_activity_metadata_arguments(activity_submit, include_markdown_file=True)
    activity_submit.set_defaults(handler=_activity_submit)
    activity_import = activity_commands.add_parser("import", help="Import a JSON or Markdown report file offline.")
    _add_json_option(activity_import)
    activity_import.add_argument("path", help="Path to a JSON report or Markdown body file.")
    activity_import.add_argument("--client", required=True, help="Caller-declared source ID (lowercase letters, digits, hyphen, or underscore).")
    _add_activity_metadata_arguments(activity_import, include_client=False, include_markdown_file=False)
    activity_import.set_defaults(handler=_activity_import)
    activity_list = activity_commands.add_parser("list", help="List received reports in the current partition.")
    _add_json_option(activity_list)
    activity_list.add_argument("--client", help="Filter by caller-declared source ID.")
    activity_list.add_argument("--disposition", choices=("new", "reviewed", "dismissed"), help="Filter inbox disposition.")
    activity_list.add_argument("--limit", type=int, default=50, help="Maximum reports to return (1-100, default 50).")
    activity_list.set_defaults(handler=_activity_list)
    activity_show = activity_commands.add_parser("show", help="Show one immutable activity report.")
    _add_json_option(activity_show)
    activity_show.add_argument("report_id", help="UUID of the activity report.")
    activity_show.set_defaults(handler=_activity_show)
    activity_propose = activity_commands.add_parser(
        "propose-context", help="Create or retrieve a context review from one activity finding.",
    )
    _add_json_option(activity_propose)
    activity_propose.add_argument("report_id", help="UUID of the activity report.")
    activity_propose.add_argument("--finding-reference", required=True, help="Immutable finding location such as /findings/0.")
    activity_propose.add_argument("--correct-record", help="Correct this existing context record instead of proposing a new claim.")
    _add_context_capture_arguments(activity_propose, require_kind=True, include_review_options=False)
    activity_propose.set_defaults(handler=_activity_propose_context)

    context = commands.add_parser("context", help="Inspect, save, or resolve personal context.")
    _add_json_option(context)
    context_commands = context.add_subparsers(dest="context_command", required=True)
    context_status = context_commands.add_parser("status", help="Show retrieval readiness.")
    _add_json_option(context_status)
    context_status.set_defaults(handler=_context_status)
    context_prepare = context_commands.add_parser("prepare", help="Download and prepare the local embedding model.")
    _add_json_option(context_prepare)
    context_prepare.set_defaults(handler=_context_prepare)

    context_list = context_commands.add_parser("list", help="List personal-context records.")
    _add_json_option(context_list)
    context_list.add_argument(
        "--status",
        action="append",
        choices=_CONTEXT_STATUSES,
        help="Filter records by status. Repeat to include multiple statuses.",
    )
    context_list.add_argument(
        "--kind",
        choices=_CONTEXT_KINDS,
        help="Filter records by kind.",
    )
    context_list.add_argument("--query", help="Search saved text and structured fields.")
    context_list.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to return (1-100, default 100).",
    )
    context_list.set_defaults(handler=_context_list)

    context_show = context_commands.add_parser("show", help="Show one personal-context record.")
    _add_json_option(context_show)
    context_show.add_argument("record_id", help="Opaque context record ID.")
    context_show.set_defaults(handler=_context_show)

    context_add = context_commands.add_parser("add", help="Save direct operator context.")
    _add_json_option(context_add)
    _add_context_capture_arguments(context_add, require_kind=True)
    context_add.set_defaults(handler=_context_add)

    context_correct = context_commands.add_parser("correct", help="Correct one context record.")
    _add_json_option(context_correct)
    context_correct.add_argument("record_id", help="Opaque context record ID.")
    _add_context_capture_arguments(context_correct, require_kind=True)
    context_correct.set_defaults(handler=_context_correct)

    context_retract = context_commands.add_parser("retract", help="Propose retracting one context record.")
    _add_json_option(context_retract)
    context_retract.add_argument("record_id", help="Opaque context record ID.")
    context_retract.set_defaults(handler=_context_retract)

    context_review = context_commands.add_parser("review", help="Inspect or resolve context reviews.")
    _add_json_option(context_review)
    review_commands = context_review.add_subparsers(dest="review_command", required=True)

    review_list = review_commands.add_parser("list", help="List context reviews.")
    _add_json_option(review_list)
    review_list.add_argument(
        "--decision",
        action="append",
        choices=_CONTEXT_REVIEW_DECISIONS,
        help="Filter reviews by decision. Repeat to include multiple decisions.",
    )
    review_list.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of reviews to return (1-100, default 50).",
    )
    review_list.set_defaults(handler=_context_review_list)

    review_show = review_commands.add_parser("show", help="Show one context review.")
    _add_json_option(review_show)
    review_show.add_argument("review_id", help="Opaque context review ID.")
    review_show.set_defaults(handler=_context_review_show)

    for name, help_text, handler in (
        ("accept", "Accept one context review.", _context_review_accept),
        ("reject", "Reject one context review.", _context_review_reject),
    ):
        review_decision = review_commands.add_parser(name, help=help_text)
        _add_json_option(review_decision)
        review_decision.add_argument("review_id", help="Opaque context review ID.")
        review_decision.set_defaults(handler=handler)

    context_vault = context_commands.add_parser("vault", help="Inspect and manage local Context vault exports.")
    _add_json_option(context_vault)
    vault_commands = context_vault.add_subparsers(dest="vault_command", required=True)

    vault_status = vault_commands.add_parser("status", help="Show local vault export status.")
    _add_json_option(vault_status)
    vault_status.set_defaults(handler=_context_vault_status)

    vault_preview = vault_commands.add_parser("preview", help="Preview one selected vault scope.")
    _add_json_option(vault_preview)
    vault_preview.add_argument("scope_id", help="Stable scope UUID.")
    vault_preview.set_defaults(handler=_context_vault_preview)

    vault_configure = vault_commands.add_parser("configure", help="Update vault enablement and optional scope settings.")
    _add_json_option(vault_configure)
    vault_enablement = vault_configure.add_mutually_exclusive_group(required=True)
    vault_enablement.add_argument("--enabled", dest="enabled", action="store_true", help="Enable vault exports.")
    vault_enablement.add_argument("--disabled", dest="enabled", action="store_false", help="Disable exports and retain generated files.")
    vault_configure.add_argument(
        "--scopes-file", type=Path,
        help="JSON file containing the complete scopes array to save.",
    )
    vault_configure.set_defaults(handler=_context_vault_configure)

    vault_refresh = vault_commands.add_parser("refresh", help="Refresh enabled vault scopes now.")
    _add_json_option(vault_refresh)
    vault_refresh.set_defaults(handler=_context_vault_refresh)

    vault_remove = vault_commands.add_parser(
        "remove", help="Remove APEX-owned files after disabling export.",
    )
    _add_json_option(vault_remove)
    vault_remove.set_defaults(handler=_context_vault_remove)

    briefing = commands.add_parser("briefing", help="Refresh and generate a briefing.")
    _add_json_option(briefing)
    briefing.add_argument(
        "--mode",
        choices=("flash", "focused", "structured"),
        help="Briefing mode override.",
    )
    briefing.set_defaults(handler=_briefing)

    actions = commands.add_parser("actions", help="Inspect or resolve action proposals.")
    _add_json_option(actions)
    action_commands = actions.add_subparsers(dest="action_command", required=True)
    for name, help_text, handler in (
        ("list", "List recent action proposals.", _actions_list),
        ("show", "Show one action and its audit history.", _actions_show),
        ("approve", "Approve and execute one action.", _actions_approve),
        ("reject", "Reject one action.", _actions_reject),
        ("verify", "Retry verification for one action.", _actions_verify),
    ):
        action = action_commands.add_parser(name, help=help_text)
        _add_json_option(action)
        if name != "list":
            action.add_argument("action_id", help="Opaque action ID.")
        action.set_defaults(handler=handler)

    runs = commands.add_parser("runs", help="Manage and inspect bounded Cortex runs.")
    _add_json_option(runs)
    runs_commands = runs.add_subparsers(dest="runs_command", required=True)

    runs_list = runs_commands.add_parser("list", help="List recent Cortex runs.")
    _add_json_option(runs_list)
    runs_list.add_argument(
        "--status",
        choices=("queued", "running", "cancelling", "completed", "failed", "cancelled", "interrupted"),
        help="Filter runs by status.",
    )
    runs_list.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of runs to return (1-100, default 25).",
    )
    runs_list.set_defaults(handler=_runs_list)

    runs_show = runs_commands.add_parser("show", help="Show detail for one Cortex run.")
    _add_json_option(runs_show)
    runs_show.add_argument("run_id", help="UUID of the run.")
    runs_show.set_defaults(handler=_runs_show)

    runs_cancel = runs_commands.add_parser("cancel", help="Cancel an active Cortex run.")
    _add_json_option(runs_cancel)
    runs_cancel.add_argument("run_id", help="UUID of the run.")
    runs_cancel.set_defaults(handler=_runs_cancel)

    return parser


def _add_json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print the complete API response as JSON.",
    )


def _add_context_capture_arguments(
    parser: argparse.ArgumentParser, *, require_kind: bool, include_review_options: bool = True,
) -> None:
    parser.add_argument("text", help="Context text.")
    parser.add_argument(
        "--kind",
        required=require_kind,
        choices=_CONTEXT_KINDS,
        help="Context kind.",
    )
    parser.add_argument("--subject", help="Structured subject entity name.")
    parser.add_argument("--predicate", help="Structured predicate.")
    parser.add_argument("--object-entity", dest="object_entity", help="Structured object entity name.")
    parser.add_argument("--object-value", dest="object_value", help="Structured scalar object value.")
    parser.add_argument("--effective-at", dest="effective_at", help="Effective date or timestamp in ISO-8601 format.")
    if include_review_options:
        parser.add_argument(
            "--sensitive",
            action="store_true",
            help="Mark the context as sensitive and require review.",
        )
        parser.add_argument("--idempotency-key", dest="idempotency_key", help="Stable key for retry-safe submission.")


def _add_activity_metadata_arguments(parser: argparse.ArgumentParser, *, include_client: bool = True, include_markdown_file: bool = False) -> None:
    """Add version-one fields used for direct submission and Markdown imports."""
    if include_client:
        parser.add_argument("--client", required=True, help="Caller-declared source ID (lowercase letters, digits, hyphen, or underscore).")
    parser.add_argument("--submission-key", help="Stable retry key; required for direct or Markdown input.")
    parser.add_argument("--title", help="Short report title; required for direct or Markdown input.")
    parser.add_argument("--task-status", help="Task status; required for direct or Markdown input.")
    parser.add_argument("--outcome", help="Report outcome; required for direct or Markdown input.")
    parser.add_argument("--finding", action="append", help="Structured finding text. Repeat for multiple findings.")
    parser.add_argument("--evidence-link", action="append", help="Evidence URL or reference. Repeat as needed.")
    parser.add_argument("--artifact-reference", action="append", help="Artifact reference only; APEX never fetches it.")
    parser.add_argument("--unresolved-question", action="append", help="Unresolved question. Repeat as needed.")
    parser.add_argument("--suggested-follow-up", help="Optional suggested next step.")
    parser.add_argument("--subject", action="append", help="Untrusted subject label. Repeat as needed.")
    parser.add_argument("--project", action="append", help="Untrusted project label. Repeat as needed.")
    parser.add_argument("--occurred-at", help="Occurrence timestamp in ISO-8601 format.")
    parser.add_argument("--native-task-url", help="Native task URL or reference.")
    if include_markdown_file:
        parser.add_argument("--markdown-file", help="Optional Markdown body file.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_mode = bool(getattr(args, "json_mode", False))
    client = ApiClient()
    try:
        return args.handler(args, client, json_mode)
    except CliError as exc:
        _emit_error(exc, json_mode)
        return 1
    except KeyboardInterrupt:
        _emit_error(CliError("interrupted", "APEX command interrupted."), json_mode)
        return 1
    finally:
        client.close()


def _status(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    readiness = _require_mapping(
        client.request("GET", "/api/v1/health/ready"), "readiness"
    )
    config = _require_mapping(
        client.request("GET", "/api/v1/config"), "runtime configuration"
    )
    payload = dict(readiness)
    selection = config.get("cortex_initial_selection")
    if isinstance(selection, dict):
        agent = selection.get("agent")
        runtime = selection.get("runtime")
        effort = selection.get("effort")
        display_name = selection.get("display_name")
        payload["agent"] = {
            "key": agent if isinstance(agent, str) else "apex",
            "display_name": (
                display_name
                if isinstance(display_name, str) and display_name.strip()
                else "Apex Agent"
            ),
            "runtime": runtime if isinstance(runtime, str) else None,
            "effort": effort if isinstance(effort, str) else None,
            "model_id": selection.get("model_id") if isinstance(selection.get("model_id"), str) else None,
        }
    _emit(payload, json_mode, _render_status)
    return 0


def _models(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = _require_mapping(client.request("GET", "/api/v1/cortex/agent"), "model catalog")
    _emit(payload, json_mode, _render_models)
    return 0


def _ask(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    prompt = args.prompt.strip()
    if not prompt:
        raise CliError("invalid_input", "Prompt must contain non-whitespace text.")
    request_payload: dict[str, object] = {"prompt": prompt}
    if args.model is not None:
        request_payload["model_id"] = args.model
    if args.effort is not None:
        request_payload["effort"] = args.effort
    if args.profile is not None:
        request_payload["tool_profile_id"] = args.profile
    conversation = _require_mapping(client.request(
        "POST", "/api/v1/cortex/conversations",
        payload={"origin": "cli", "title": _cli_conversation_title(prompt)},
    ), "conversation")
    conversation_id = conversation.get("id")
    if not isinstance(conversation_id, str):
        raise CliError("invalid_response", "APEX did not return a conversation ID.")
    request_payload["user_message_id"] = str(uuid.uuid4())
    request_payload["agent_message_id"] = str(uuid.uuid4())
    payload = client.request(
        "POST", f"/api/v1/cortex/conversations/{quote(conversation_id, safe='')}/turns",
        payload=request_payload, long_running=True,
    )
    response = _require_mapping(payload, "Agent response")
    if not isinstance(response.get("answer"), str):
        raise CliError("invalid_response", "APEX Agent response did not include an answer.")
    if response.get("error"):
        if not json_mode:
            _render_ask(payload)
        _emit_error(
            CliError("agent_error", str(response["error"])),
            json_mode=json_mode,
        )
        return 1
    _emit(payload, json_mode, _render_ask)
    return 0


def _context_status(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = _require_mapping(
        client.request("GET", "/api/v1/cortex/retrieval/status"),
        "retrieval status",
    )
    _emit(payload, json_mode, _render_context_status)
    return 0


def _context_vault_status(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = _require_mapping(client.request("GET", "/api/v1/cortex/vault"), "Context vault status")
    _emit(payload, json_mode, _render_context_vault_status)
    return 0


def _context_vault_preview(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = _require_mapping(
        client.request(
            "POST", "/api/v1/cortex/vault/preview", payload={"scope_id": args.scope_id},
        ),
        "Context vault preview",
    )
    _emit(payload, json_mode, _render_context_vault_preview)
    return 0


def _context_vault_configure(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    context_vault: dict[str, object] = {"enabled": args.enabled}
    if args.scopes_file is not None:
        try:
            scopes = json.loads(args.scopes_file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CliError("invalid_input", "Could not read the Context vault scopes file.") from exc
        except json.JSONDecodeError as exc:
            raise CliError("invalid_input", "Context vault scopes file must contain valid JSON.") from exc
        if not isinstance(scopes, list) or any(not isinstance(scope, dict) for scope in scopes):
            raise CliError("invalid_input", "Context vault scopes file must contain a JSON array of scope objects.")
        context_vault["scopes"] = scopes
    response = _require_mapping(
        client.request("PATCH", "/api/v1/settings", payload={"context_vault": context_vault}),
        "updated settings",
    )
    settings = response.get("settings")
    result = settings.get("context_vault") if isinstance(settings, dict) else None
    if not isinstance(result, dict):
        raise CliError("invalid_response", "APEX did not return the saved Context vault settings.")
    _emit(result, json_mode, _render_context_vault_settings)
    return 0


def _context_vault_refresh(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = _require_mapping(
        client.request("POST", "/api/v1/cortex/vault/refresh", long_running=True),
        "Context vault refresh status",
    )
    _emit(payload, json_mode, _render_context_vault_status)
    return _context_vault_operation_exit_code(payload)


def _context_vault_remove(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = _require_mapping(
        client.request("DELETE", "/api/v1/cortex/vault/copies", long_running=True),
        "Context vault removal status",
    )
    _emit(payload, json_mode, _render_context_vault_status)
    return _context_vault_operation_exit_code(payload)


def _context_vault_operation_exit_code(payload: dict[str, object]) -> int:
    """Preserve status output while signaling a failed or still-dirty operation."""
    if payload.get("last_error_code") or payload.get("dirty") is True:
        return 1
    return 0


def _activity_submit(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    report = _activity_metadata_payload(args)
    if args.markdown_file is not None:
        report["markdown_body"] = _read_activity_file(args.markdown_file, "Markdown")
    _submit_activity(client, args.client, report, json_mode)
    return 0


def _activity_import(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    path = Path(args.path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = _read_activity_file(path, "JSON")
        try:
            report = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliError("invalid_input", "Activity JSON import must contain valid JSON.") from exc
        if not isinstance(report, dict):
            raise CliError("invalid_input", "Activity JSON import must contain one report object.")
        if _activity_metadata_payload(args, required=False):
            raise CliError("invalid_input", "JSON imports carry their own report metadata; remove metadata options.")
    elif suffix in {".md", ".markdown"}:
        report = _activity_metadata_payload(args)
        report["markdown_body"] = _read_activity_file(path, "Markdown")
    else:
        raise CliError("invalid_input", "Activity imports require a .json, .md, or .markdown file.")
    _submit_activity(client, args.client, report, json_mode)
    return 0


def _activity_list(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    query: list[tuple[str, object]] = [("limit", args.limit)]
    if args.client is not None:
        query.append(("client_id", args.client))
    if args.disposition is not None:
        query.append(("disposition", args.disposition))
    payload = client.request("GET", _query_path("/api/v1/activity/reports", query))
    _require_list(payload, "activity report list")
    _emit(payload, json_mode, _render_activity_list)
    return 0


def _activity_show(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request("GET", _opaque_path(args.report_id, "Activity report ID", "/api/v1/activity/reports"))
    _require_mapping(payload, "activity report detail")
    _emit(payload, json_mode, _render_activity_detail)
    return 0


def _activity_propose_context(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    capture = _context_capture_payload(args)
    capture.pop("sensitive", None)
    capture.pop("idempotency_key", None)
    capture["finding_reference"] = args.finding_reference
    if args.correct_record is not None:
        capture["correction_record_id"] = args.correct_record
    payload = _require_mapping(
        client.request(
            "POST", _opaque_path(args.report_id, "Activity report ID", "/api/v1/activity/reports") + "/context-proposals",
            payload=capture,
        ),
        "activity context proposal",
    )
    if payload.get("decision") not in _CONTEXT_REVIEW_DECISIONS or not isinstance(payload.get("id"), str):
        raise CliError("invalid_response", "APEX did not return a valid context review.")
    _emit(payload, json_mode, _render_context_review_detail)
    return 0


def _activity_metadata_payload(args: argparse.Namespace, *, required: bool = True) -> dict[str, object]:
    values = {
        "submission_key": getattr(args, "submission_key", None),
        "title": getattr(args, "title", None),
        "task_status": getattr(args, "task_status", None),
        "outcome": getattr(args, "outcome", None),
    }
    missing = [name.replace("_", "-") for name, value in values.items() if not isinstance(value, str) or not value.strip()]
    if required and missing:
        raise CliError("invalid_input", "Activity submissions require " + ", ".join(f"--{name}" for name in missing) + ".")
    report: dict[str, object] = {name: value.strip() for name, value in values.items() if isinstance(value, str) and value.strip()}
    mapping = {
        "finding": "findings", "evidence_link": "evidence_links", "artifact_reference": "artifact_references",
        "unresolved_question": "unresolved_questions", "subject": "subjects", "project": "projects",
    }
    for argument, field in mapping.items():
        entries = getattr(args, argument, None)
        if entries:
            report[field] = [{"text": entry} for entry in entries] if field == "findings" else entries
    for argument, field in (("suggested_follow_up", "suggested_follow_up"), ("occurred_at", "occurred_at"), ("native_task_url", "native_task_url")):
        value = getattr(args, argument, None)
        if isinstance(value, str) and value.strip():
            report[field] = value.strip()
    return report


def _read_activity_file(path_value: str | Path, label: str) -> str:
    path = Path(path_value)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CliError("invalid_input", f"Could not read {label} activity file: {path}") from exc


def _submit_activity(client: ApiClient, client_id: str, report: dict[str, object], json_mode: bool) -> None:
    payload = client.request("POST", "/api/v1/activity/reports", payload={"client_id": client_id, "report": report})
    _require_mapping(payload, "activity submission receipt")
    _emit(payload, json_mode, _render_activity_receipt)


def _context_prepare(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = _require_mapping(
        client.request(
            "POST",
            "/api/v1/cortex/retrieval/prepare",
            long_running=True,
        ),
        "retrieval preparation response",
    )
    _emit(payload, json_mode, _render_context_status)
    return 0


def _context_list(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    query: list[tuple[str, object]] = []
    for status in args.status or []:
        query.append(("status", status))
    if args.kind is not None:
        query.append(("kind", args.kind))
    if args.query is not None:
        query.append(("q", args.query))
    query.append(("limit", args.limit))
    payload = client.request("GET", _query_path("/api/v1/cortex/context", query))
    _require_list(payload, "context record list")
    _emit(payload, json_mode, _render_context_list)
    return 0


def _context_show(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request("GET", _context_record_path(args.record_id))
    _require_mapping(payload, "context record detail")
    _emit(payload, json_mode, _render_context_detail)
    return 0


def _context_add(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request(
        "POST",
        "/api/v1/cortex/context/saves",
        payload=_context_capture_payload(args),
    )
    _require_context_save_response(payload)
    _emit(payload, json_mode, _render_context_save)
    return 0


def _context_correct(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    detail = _require_mapping(
        client.request("GET", _context_record_path(args.record_id)),
        "context record detail",
    )
    updated_at = detail.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise CliError("invalid_response", "APEX context record detail did not include updated_at.")
    request_payload = _context_capture_payload(args)
    request_payload["correction_record_id"] = args.record_id
    request_payload["expected_updated_at"] = updated_at
    payload = client.request(
        "POST",
        "/api/v1/cortex/context/saves",
        payload=request_payload,
    )
    _require_context_save_response(payload)
    _emit(payload, json_mode, _render_context_save)
    return 0


def _context_retract(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request(
        "POST",
        "/api/v1/cortex/context/actions",
        payload={"operation": "retract", "record_id": args.record_id},
    )
    result = _require_mapping(payload, "context action proposal")
    if not isinstance(result.get("action_id"), str):
        raise CliError("invalid_response", "APEX context action did not include an action ID.")
    if _context_action_review_id(result) is None:
        raise CliError("invalid_response", "APEX context action did not include a review ID.")
    _emit(result, json_mode, _render_context_action)
    return 0


def _context_review_list(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    query: list[tuple[str, object]] = []
    for decision in args.decision or []:
        query.append(("decision", decision))
    query.append(("limit", args.limit))
    payload = client.request(
        "GET",
        _query_path("/api/v1/cortex/context/reviews", query),
    )
    _require_list(payload, "context review list")
    _emit(payload, json_mode, _render_context_review_list)
    return 0


def _context_review_show(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request("GET", _context_review_path(args.review_id))
    _require_mapping(payload, "context review detail")
    _emit(payload, json_mode, _render_context_review_detail)
    return 0


def _context_review_accept(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    return _resolve_context_review(args.review_id, "accept", client, json_mode)


def _context_review_reject(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    return _resolve_context_review(args.review_id, "reject", client, json_mode)


def _resolve_context_review(
    review_id: str,
    operation: str,
    client: ApiClient,
    json_mode: bool,
) -> int:
    detail = _require_mapping(
        client.request("GET", _context_review_path(review_id)),
        "context review detail",
    )
    expected_revisions = detail.get("expected_revisions")
    if not isinstance(expected_revisions, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in expected_revisions.items()
    ):
        raise CliError("invalid_response", "APEX context review detail did not include expected revisions.")
    payload = client.request(
        "POST",
        f"{_context_review_path(review_id)}/{operation}",
        payload={"expected_revisions": expected_revisions},
    )
    result = _require_mapping(payload, "context review result")
    _emit(result, json_mode, _render_context_review_result)
    return 0


def _context_capture_payload(args: argparse.Namespace) -> dict[str, object]:
    text = args.text.strip()
    if not text:
        raise CliError("invalid_input", "Context text must contain non-whitespace text.")
    payload: dict[str, object] = {
        "text": text,
        "kind": args.kind,
        "sensitive": bool(getattr(args, "sensitive", False)),
    }
    for name in ("subject", "predicate", "object_entity", "object_value", "effective_at", "idempotency_key"):
        value = getattr(args, name, None)
        if value is not None:
            payload[name] = value
    return payload


def _require_context_save_response(payload: object) -> dict[str, object]:
    result = _require_mapping(payload, "context save response")
    outcome = result.get("outcome")
    if outcome not in {"saved", "review_required"}:
        raise CliError("invalid_response", "APEX returned an invalid context save outcome.")
    required_id = "record_id" if outcome == "saved" else "review_id"
    if not isinstance(result.get(required_id), str) or not str(result[required_id]).strip():
        raise CliError("invalid_response", f"APEX context save did not include {required_id}.")
    return result


def _query_path(path: str, query: list[tuple[str, object]]) -> str:
    if not query:
        return path
    return path + "?" + "&".join(
        f"{quote(str(key), safe='')}={quote(str(value), safe='')}"
        for key, value in query
    )


def _context_record_path(record_id: str) -> str:
    return _opaque_path(record_id, "Context record ID", "/api/v1/cortex/context")


def _context_review_path(review_id: str) -> str:
    return _opaque_path(review_id, "Context review ID", "/api/v1/cortex/context/reviews")


def _opaque_path(identifier: str, label: str, prefix: str) -> str:
    value = identifier.strip()
    if not value:
        raise CliError("invalid_input", f"{label} must contain non-whitespace text.")
    return f"{prefix}/{quote(value, safe='')}"


def _cli_conversation_title(prompt: str) -> str:
    title = f"CLI: {' '.join(prompt.split())}"
    return title if len(title) <= 80 else f"{title[:79]}…"


def _briefing(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload: dict[str, object] = {}
    if args.mode is not None:
        payload["mode"] = args.mode
    result = client.request(
        "POST", "/api/v1/trigger", payload=payload, long_running=True
    )
    response = _require_mapping(result, "briefing response")
    if not isinstance(response.get("briefing"), str):
        raise CliError("invalid_response", "APEX briefing response did not include briefing text.")
    _emit(result, json_mode, _render_briefing)
    return 0


def _actions_list(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request("GET", "/api/v1/actions")
    _require_list(payload, "action list")
    _emit(payload, json_mode, _render_actions_list)
    return 0


def _actions_show(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request("GET", _action_path(args.action_id))
    _require_mapping(payload, "action detail")
    _emit(payload, json_mode, _render_action_detail)
    return 0


def _actions_approve(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    return _resolve_action(args.action_id, "approve", "verified", client, json_mode)


def _actions_reject(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    return _resolve_action(args.action_id, "reject", "rejected", client, json_mode)


def _actions_verify(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    return _resolve_action(args.action_id, "verify", "verified", client, json_mode)


def _resolve_action(
    action_id: str,
    operation: str,
    expected_status: str,
    client: ApiClient,
    json_mode: bool,
) -> int:
    detail = _require_mapping(client.request("GET", _action_path(action_id)), "action detail")
    if not isinstance(detail.get("version"), int):
        raise CliError("invalid_response", "APEX action detail did not include a version.")
    result = _require_mapping(client.request(
        "POST",
        f"{_action_path(action_id)}/{operation}",
        payload={"expected_version": detail["version"]},
        long_running=operation == "approve",
    ), "action result")
    if not isinstance(result.get("status"), str):
        raise CliError("invalid_response", "APEX action result did not include a status.")
    _emit(result, json_mode, _render_action_result)
    if result["status"] != expected_status:
        return 1
    return 0


def _action_path(action_id: str) -> str:
    if not action_id.strip():
        raise CliError("invalid_input", "Action ID must contain non-whitespace text.")
    return f"/api/v1/actions/{quote(action_id, safe='')}"


def _require_mapping(payload: object, label: str) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    raise CliError("invalid_response", f"APEX returned an invalid {label}.")


def _require_list(payload: object, label: str) -> list[object]:
    if isinstance(payload, list):
        return payload
    raise CliError("invalid_response", f"APEX returned an invalid {label}.")


def _emit(payload: object, json_mode: bool, renderer: Any) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    renderer(payload)


def _emit_error(error: CliError, json_mode: bool) -> None:
    if json_mode:
        error_body: dict[str, object] = {"kind": error.kind, "message": error.message}
        if error.status_code is not None:
            error_body["status_code"] = error.status_code
        if error.detail is not None:
            error_body["detail"] = error.detail
        print(json.dumps({"error": error_body}, ensure_ascii=False, indent=2, default=str))
        return
    print(error.message, file=sys.stderr)


def _render_status(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected readiness response.")
        return
    print("APEX is ready.")
    for key in ("config", "database"):
        value = payload.get(key)
        if isinstance(value, str):
            print(f"{key.capitalize()}: {value}")
    agent = payload.get("agent")
    if isinstance(agent, dict) and isinstance(agent.get("key"), str):
        label = agent.get("display_name")
        description = (
            label
            if isinstance(label, str) and label.strip()
            else agent["key"]
        )
        if isinstance(agent.get("runtime"), str):
            description += f" ({agent['runtime']})"
        print(f"Agent: {description}")
        if isinstance(agent.get("model_id"), str):
            print(f"Model: {agent['model_id']}")


def _render_models(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected model catalog.")
        return
    catalog = payload.get("model_catalog")
    if not isinstance(catalog, list):
        print("APEX returned an invalid model catalog.")
        return
    header = payload.get("display_name")
    print(
        header
        if isinstance(header, str) and header.strip()
        else "Apex Agent"
    )
    for model in catalog:
        if not isinstance(model, dict):
            continue
        name = model.get("display_name", model.get("model_id", "Unknown model"))
        print(f"{name} ({model.get('model_id', 'unknown')})")
        print(
            "  "
            f"{model.get('runtime', 'unknown')} | {model.get('provider', 'unknown')}"
        )
        print(f"  Status: {model.get('status', 'unknown')}")


def _render_ask(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected Agent response.")
        return
    answer = payload.get("answer")
    if isinstance(answer, str) and answer:
        print(answer)
    for result in payload.get("tool_outputs", []):
        if not isinstance(result, dict):
            continue
        output = result.get("output")
        if not isinstance(output, dict):
            continue
        action_id = output.get("action_id")
        message = output.get("message")
        if isinstance(message, str):
            print(f"\n{message}")
        if isinstance(action_id, str):
            print(f"Action ID: {action_id}")


def _render_activity_receipt(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected activity receipt.")
        return
    receipt = "Duplicate receipt" if payload.get("duplicate") else "Received"
    print(f"{receipt}: {payload.get('id', 'unknown')}")
    print(f"Received At: {payload.get('received_at', 'unknown')}")


def _render_activity_list(payload: object) -> None:
    if not isinstance(payload, list):
        print("APEX returned an unexpected activity report list.")
        return
    if not payload:
        print("No activity reports found.")
        return
    for report in payload:
        if not isinstance(report, dict):
            continue
        content = report.get("report") if isinstance(report.get("report"), dict) else {}
        print(
            f"{report.get('id', 'unknown')} | {report.get('client_display_name', 'unknown')} | "
            f"{report.get('disposition', 'unknown')} | {content.get('title', 'Untitled')}"
        )


def _render_activity_detail(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected activity report response.")
        return
    content = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    print(f"Report ID: {payload.get('id', 'unknown')}")
    print(f"Source: {payload.get('client_display_name', 'unknown')} ({payload.get('client_id', 'unknown')})")
    print(f"Partition: {payload.get('partition', 'unknown')}")
    print(f"Disposition: {payload.get('disposition', 'unknown')}")
    print(f"Received At: {payload.get('received_at', 'unknown')}")
    print(f"Title: {content.get('title', 'unknown')}")
    print(f"Task Status: {content.get('task_status', 'unknown')}")
    print(f"Outcome: {content.get('outcome', '')}")
    for label, field in (("Findings", "findings"), ("Evidence", "evidence_links"), ("Artifacts", "artifact_references"), ("Unresolved questions", "unresolved_questions")):
        entries = content.get(field)
        if isinstance(entries, list) and entries:
            print(f"{label}:")
            for entry in entries:
                text = entry.get("text", entry) if isinstance(entry, dict) else entry
                print(f"- {text}")
    for label, field in (("Suggested follow-up", "suggested_follow_up"), ("Occurred At", "occurred_at"), ("Native task", "native_task_url"), ("Markdown", "markdown_body")):
        value = content.get(field)
        if value:
            print(f"{label}: {value}")


def _render_context_list(payload: object) -> None:
    if not isinstance(payload, list):
        print("APEX returned an unexpected context record list.")
        return
    if not payload:
        print("No personal-context records found.")
        return
    for record in payload:
        if not isinstance(record, dict):
            continue
        record_id = record.get("id", "unknown")
        kind = record.get("kind", "unknown")
        status = record.get("status", "unknown")
        text = record.get("text", "")
        print(f"{record_id} | {kind} | {status}")
        if isinstance(text, str) and text:
            print(f"  {text}")


def _render_context_detail(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected context record response.")
        return
    print(f"Record ID: {payload.get('id', 'unknown')}")
    print(f"Kind: {payload.get('kind', 'unknown')}")
    print(f"Status: {payload.get('status', 'unknown')}")
    print(f"Text: {payload.get('text', '')}")
    _render_context_structured_fields(payload)
    if payload.get("effective_at"):
        print(f"Effective At: {payload.get('effective_at')}")
    print(f"Created At: {payload.get('created_at', 'unknown')}")
    print(f"Updated At: {payload.get('updated_at', 'unknown')}")

    print("Sources:")
    sources = payload.get("sources")
    if isinstance(sources, list) and sources:
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id", "unknown")
            source_kind = source.get("kind", "unknown")
            origin = source.get("origin", "unknown")
            derivation = source.get("derivation", "unknown")
            locator = source.get("locator", "unknown")
            occurred_at = source.get("occurred_at") or "Not recorded"
            captured_at = source.get("captured_at") or "Not recorded"
            linked_at = source.get("linked_at") or "Not recorded"
            original_text = source.get("original_text", "")
            print(f"- {source_id} | {source_kind} | {origin} | {derivation}")
            print(f"  Locator: {locator}")
            print(f"  Occurred At: {occurred_at}")
            print(f"  Captured At: {captured_at}")
            print(f"  Linked At: {linked_at}")
            if isinstance(original_text, str) and original_text:
                print(f"  Original: {original_text}")
    else:
        print("- None")

    print("History:")
    history = payload.get("history")
    if isinstance(history, list) and history:
        for event in history:
            if not isinstance(event, dict):
                continue
            line = (
                f"- {event.get('created_at', 'unknown')} | "
                f"{event.get('operation', 'unknown')} | "
                f"{event.get('reason_code', 'unknown')} | "
                f"{event.get('actor', 'unknown')}"
            )
            references = []
            for key in ("related_record_id", "source_id", "action_id", "review_id"):
                value = event.get(key)
                if isinstance(value, str) and value:
                    references.append(f"{key}={value}")
            if references:
                line += " | " + ", ".join(references)
            print(line)
    else:
        print("- None")

    print(f"Related record IDs: {_display_ids(payload.get('related_records'), 'id')}")
    print(f"Pending review IDs: {_display_ids(payload.get('pending_review_ids'))}")
    print(f"Predecessor IDs: {_display_ids(payload.get('predecessors'))}")
    print(f"Superseded by IDs: {_display_ids(payload.get('superseded_by'))}")


def _render_context_structured_fields(payload: dict[str, object]) -> None:
    subject = payload.get("subject")
    predicate = payload.get("predicate")
    object_entity = payload.get("object_entity")
    object_value = payload.get("object_value")
    if not any(value is not None for value in (subject, predicate, object_entity, object_value)):
        return
    print("Structured:")
    if isinstance(subject, dict):
        print(f"  Subject: {_entity_display(subject)}")
    elif subject is not None:
        print(f"  Subject: {subject}")
    if predicate is not None:
        print(f"  Predicate: {predicate}")
    if isinstance(object_entity, dict):
        print(f"  Object Entity: {_entity_display(object_entity)}")
    elif object_entity is not None:
        print(f"  Object Entity: {object_entity}")
    if object_value is not None:
        print(f"  Object Value: {object_value}")


def _entity_display(entity: dict[str, object]) -> str:
    name = entity.get("name")
    identifier = entity.get("id")
    if isinstance(name, str) and isinstance(identifier, str):
        return f"{name} ({identifier})"
    if isinstance(name, str):
        return name
    if isinstance(identifier, str):
        return identifier
    return "unknown"


def _display_ids(items: object, key: str | None = None) -> str:
    if not isinstance(items, list):
        return "None"
    identifiers: list[str] = []
    for item in items:
        value = item.get(key) if key and isinstance(item, dict) else item
        if isinstance(value, str) and value:
            identifiers.append(value)
    return ", ".join(identifiers) if identifiers else "None"


def _render_context_save(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected context save response.")
        return
    outcome = payload.get("outcome")
    if outcome == "saved":
        print(f"Saved context record: {payload.get('record_id', 'unknown')}")
    elif outcome == "review_required":
        print(f"Needs review: {payload.get('review_id', 'unknown')}")
    else:
        print(f"Context save outcome: {outcome or 'unknown'}")


def _render_context_action(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected context action response.")
        return
    print(f"Action ID: {payload.get('action_id', 'unknown')}")
    review_id = _context_action_review_id(payload)
    print(f"Review ID: {review_id if isinstance(review_id, str) else 'unknown'}")
    print(f"Status: {payload.get('status', 'proposed')}")


def _context_action_review_id(payload: dict[str, object]) -> str | None:
    review_id = payload.get("review_id")
    if isinstance(review_id, str) and review_id.strip():
        return review_id
    proposal = payload.get("proposal")
    arguments = proposal.get("arguments") if isinstance(proposal, dict) else None
    review_id = arguments.get("review_id") if isinstance(arguments, dict) else None
    return review_id if isinstance(review_id, str) and review_id.strip() else None


def _render_context_review_list(payload: object) -> None:
    if not isinstance(payload, list):
        print("APEX returned an unexpected context review list.")
        return
    if not payload:
        print("No context reviews found.")
        return
    for review in payload:
        if not isinstance(review, dict):
            continue
        reasons = review.get("reason_codes")
        reason_text = ", ".join(str(item) for item in reasons) if isinstance(reasons, list) else ""
        line = (
            f"{review.get('id', 'unknown')} | {review.get('decision', 'unknown')} | "
            f"{review.get('operation', 'unknown')}"
        )
        if reason_text:
            line += f" | {reason_text}"
        print(line)


def _render_context_review_detail(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected context review response.")
        return
    print(f"Review ID: {payload.get('id', 'unknown')}")
    print(f"Decision: {payload.get('decision', 'unknown')}")
    print(f"Operation: {payload.get('operation', 'unknown')}")
    print(f"Partition: {payload.get('partition', 'unknown')}")
    reason_codes = payload.get("reason_codes")
    if isinstance(reason_codes, list):
        print(f"Reasons: {', '.join(str(item) for item in reason_codes) or 'None'}")
    if payload.get("action_id"):
        print(f"Action ID: {payload.get('action_id')}")
    print("Expected revisions:")
    revisions = payload.get("expected_revisions")
    if isinstance(revisions, dict) and revisions:
        for record_id, revision in revisions.items():
            print(f"- {record_id}: {revision}")
    else:
        print("- None")
    for label in ("proposal", "evidence"):
        value = payload.get(label)
        if isinstance(value, dict) and value:
            print(f"{label.capitalize()}:")
            print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _render_context_review_result(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected context review response.")
        return
    print(f"Review ID: {payload.get('id', 'unknown')}")
    print(f"Decision: {payload.get('decision', 'unknown')}")
    if payload.get("action_id"):
        print(f"Action ID: {payload.get('action_id')}")


def _render_context_status(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected retrieval status.")
        return
    mode = payload.get("mode", "unknown")
    state = payload.get("state", "unknown")
    print(f"Retrieval: {mode} ({state})")
    print(f"Indexed items: {payload.get('indexed_items', 0)}")
    print(f"Embeddings: {payload.get('embedding_items', 0)}")
    print(f"Pending items: {payload.get('pending_items', 0)}")
    error = payload.get("error_category")
    if isinstance(error, str) and error:
        print(f"Status: {error}")


def _render_context_vault_status(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected Context vault status.")
        return
    enabled = "enabled" if payload.get("enabled") else "disabled"
    dirty = "pending changes" if payload.get("dirty") else "up to date"
    print(f"Context vault exports are {enabled}; {dirty}.")
    if payload.get("export_restricted"):
        print(f"Production export is restricted ({payload.get('restriction_code') or 'restricted'}).")
    destination = payload.get("destination_path")
    if isinstance(destination, str) and destination:
        print(f"Destination: {destination}")
    current_revision = payload.get("knowledge_revision")
    exported_revision = payload.get("exported_revision")
    print(
        f"Revision: {exported_revision if exported_revision is not None else 'none'} / "
        f"{current_revision if current_revision is not None else 'unknown'}; "
        f"{payload.get('owned_file_count', 0)} managed files."
    )
    if payload.get("refreshing"):
        print("Refresh is in progress.")
    if payload.get("last_error_code"):
        print(f"Last error: {payload['last_error_code']}")
    retained = payload.get("retained_destinations")
    if isinstance(retained, list) and retained:
        print("Copies retained at: " + ", ".join(str(item) for item in retained))


def _render_context_vault_preview(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected Context vault preview.")
        return
    print(
        f"{payload.get('scope_name', 'Scope')}: {payload.get('eligible_count', 0)} of "
        f"{payload.get('candidate_count', 0)} candidate records are eligible."
    )
    if payload.get("export_restricted"):
        print(f"Production export is restricted ({payload.get('restriction_code') or 'restricted'}).")
    records = payload.get("records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            state = "eligible" if record.get("eligible") else "excluded"
            reasons = record.get("exclusion_reasons")
            suffix = f" ({', '.join(str(item) for item in reasons)})" if isinstance(reasons, list) and reasons else ""
            print(f"- {record.get('record_id')}: {state}{suffix} — {record.get('text', '')}")


def _render_context_vault_settings(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned unexpected Context vault settings.")
        return
    enabled = "enabled" if payload.get("enabled") else "disabled"
    scopes = payload.get("scopes")
    count = len(scopes) if isinstance(scopes, list) else 0
    print(f"Context vault exports are {enabled} across {count} scope(s).")


def _render_briefing(payload: object) -> None:
    if isinstance(payload, dict) and isinstance(payload.get("briefing"), str):
        print(payload["briefing"])
        return
    print("APEX returned an unexpected briefing response.")


def _render_actions_list(payload: object) -> None:
    if not isinstance(payload, list):
        print("APEX returned an unexpected action list.")
        return
    if not payload:
        print("No recent actions.")
        return
    for action in payload:
        if not isinstance(action, dict):
            continue
        proposal = action.get("proposal") if isinstance(action.get("proposal"), dict) else {}
        print(
            f"{action.get('action_id', 'unknown')} | {action.get('status', 'unknown')} | "
            f"{proposal.get('risk', 'unknown')}"
        )
        summary = proposal.get("summary")
        if isinstance(summary, str):
            print(f"  {summary}")


def _render_action_detail(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected action response.")
        return
    proposal = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else {}
    print(f"Action ID: {payload.get('action_id', 'unknown')}")
    print(f"Status: {payload.get('status', 'unknown')}")
    print(f"Risk: {proposal.get('risk', 'unknown')}")
    print(f"Capability: {proposal.get('capability_name', 'unknown')}")
    print(f"Summary: {proposal.get('summary', 'unknown')}")
    print("Arguments:")
    print(json.dumps(proposal.get("arguments", {}), ensure_ascii=False, indent=2, default=str))
    events = payload.get("events")
    if isinstance(events, list) and events:
        print("Audit:")
        for event in events:
            if not isinstance(event, dict):
                continue
            print(
                f"- {event.get('occurred_at', 'unknown')} | {event.get('actor', 'unknown')} | "
                f"{event.get('to_status', 'unknown')} | {event.get('result_code', 'unknown')}"
            )


def _render_action_result(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected action result.")
        return
    print(f"Action ID: {payload.get('action_id', 'unknown')}")
    print(f"Status: {payload.get('status', 'unknown')}")


def _runs_list(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    params: list[str] = []
    if getattr(args, "status", None) is not None:
        params.append(f"status={quote(args.status, safe='')}")
    limit = getattr(args, "limit", 25)
    params.append(f"limit={limit}")
    query = f"?{'&'.join(params)}"
    payload = client.request("GET", f"/api/v1/cortex/runs{query}")
    _require_list(payload, "run list")
    _emit(payload, json_mode, _render_runs_list)
    return 0


def _runs_show(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    run_id = args.run_id.strip()
    if not run_id:
        raise CliError("invalid_input", "Run ID must contain non-whitespace text.")
    payload = client.request("GET", f"/api/v1/cortex/runs/{quote(run_id, safe='')}")
    _require_mapping(payload, "run detail")
    _emit(payload, json_mode, _render_run_detail)
    return 0


def _runs_cancel(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    run_id = args.run_id.strip()
    if not run_id:
        raise CliError("invalid_input", "Run ID must contain non-whitespace text.")
    payload = client.request("POST", f"/api/v1/cortex/runs/{quote(run_id, safe='')}/cancel")
    _require_mapping(payload, "run detail")
    _emit(payload, json_mode, _render_run_cancelled)
    return 0


def _render_runs_list(payload: object) -> None:
    if not isinstance(payload, list):
        print("APEX returned an unexpected run list.")
        return
    if not payload:
        print("No Cortex runs found.")
        return
    for item in payload:
        if not isinstance(item, dict):
            continue
        run_id = item.get("id", "unknown")
        status = item.get("status", "unknown")
        model = item.get("resolved_model") or item.get("requested_model", "unknown")
        runtime = item.get("runtime", "unknown")
        tokens = item.get("total_tokens", 0)
        elapsed = item.get("elapsed_seconds", 0.0)
        print(f"{run_id} | {status} | {model} ({runtime}) | {tokens} tok | {elapsed:.1f}s")


def _render_run_detail(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected run response.")
        return
    print(f"Run ID: {payload.get('id', 'unknown')}")
    print(f"Status: {payload.get('status', 'unknown')}")
    if payload.get("stop_reason"):
        print(f"Stop Reason: {payload.get('stop_reason')}")
    print(f"Conversation ID: {payload.get('conversation_id', 'unknown')}")
    model = payload.get("resolved_model") or payload.get("requested_model", "unknown")
    runtime = payload.get("runtime") or "unknown"
    provider = payload.get("provider") or "unknown"
    print(f"Model: {model} ({runtime} / {provider})")
    print(f"Tokens: {payload.get('total_tokens', 0)} ({payload.get('usage_quality', 'unavailable')})")
    print(f"Elapsed: {payload.get('elapsed_seconds', 0.0):.1f}s")
    print(f"Turns: {payload.get('turns_count', 0)} | Tool calls: {payload.get('tool_calls_count', 0)} | Retries: {payload.get('retries_count', 0)}")
    if payload.get("trace_id"):
        print(f"Trace ID: {payload.get('trace_id')}")
    evidence = payload.get("evidence")
    if isinstance(evidence, dict):
        persisted = evidence.get("answer_persisted", False)
        print(f"Answer Persisted: {persisted}")
        counts = evidence.get("tool_outcome_counts")
        if isinstance(counts, dict) and counts:
            print(f"Tool Outcomes: {counts}")
        action_ids = evidence.get("action_ids")
        if isinstance(action_ids, list) and action_ids:
            print(f"Action IDs: {', '.join(action_ids)}")
    err = payload.get("error")
    if isinstance(err, dict):
        print(f"Error: {err.get('code', 'failed')} - {err.get('message', '')}")


def _render_run_cancelled(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected cancel response.")
        return
    print(f"Run ID: {payload.get('id', 'unknown')}")
    print(f"Status: {payload.get('status', 'unknown')}")
    if payload.get("stop_reason"):
        print(f"Stop Reason: {payload.get('stop_reason')}")


if __name__ == "__main__":
    raise SystemExit(main())
