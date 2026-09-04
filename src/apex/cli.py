"""Thin command-line client for the local APEX HTTP API."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Generator, Sequence
from urllib.parse import quote

import requests


API_ROOT = "http://127.0.0.1:8000"
_CONNECT_TIMEOUT_SECONDS = 3.0
_DEFAULT_READ_TIMEOUT_SECONDS = 30.0
_LONG_READ_TIMEOUT_SECONDS = 600.0


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

    def stream_events(
        self,
        path: str,
        *,
        last_event_id: int | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        headers = {"Accept": "text/event-stream"}
        if last_event_id is not None and last_event_id > 0:
            headers["Last-Event-ID"] = str(last_event_id)
        try:
            response = self._session.get(
                f"{API_ROOT}{path}",
                headers=headers,
                stream=True,
                timeout=(_CONNECT_TIMEOUT_SECONDS, _LONG_READ_TIMEOUT_SECONDS),
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

        current_id: int | None = None
        current_event: str | None = None
        current_data: list[str] = []

        for line in response.iter_lines(decode_unicode=True):
            if line is None:
                continue
            line_str = line.strip("\r")
            if not line_str:
                if current_data or current_event is not None:
                    raw_data = "\n".join(current_data)
                    payload: Any = None
                    if raw_data:
                        try:
                            payload = json.loads(raw_data)
                        except ValueError:
                            payload = raw_data
                    yield {
                        "id": current_id,
                        "type": current_event or "message",
                        "payload": payload,
                        "raw": raw_data,
                    }
                current_id = None
                current_event = None
                current_data = []
                continue

            if line_str.startswith(":"):
                continue
            if line_str.startswith("id:"):
                val = line_str[3:].strip()
                try:
                    current_id = int(val)
                except ValueError:
                    pass
            elif line_str.startswith("event:"):
                current_event = line_str[6:].strip()
            elif line_str.startswith("data:"):
                current_data.append(line_str[5:].lstrip(" "))


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

    context = commands.add_parser("context", help="Inspect or prepare local retrieval.")
    _add_json_option(context)
    context_commands = context.add_subparsers(dest="context_command", required=True)
    context_status = context_commands.add_parser("status", help="Show retrieval readiness.")
    _add_json_option(context_status)
    context_status.set_defaults(handler=_context_status)
    context_prepare = context_commands.add_parser("prepare", help="Download and prepare the local embedding model.")
    _add_json_option(context_prepare)
    context_prepare.set_defaults(handler=_context_prepare)

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

    runs_start = runs_commands.add_parser("start", help="Start a Cortex run.")
    _add_json_option(runs_start)
    runs_start.add_argument("prompt", help="Prompt for Apex Agent.")
    runs_start.add_argument("--model", help="Model ID. Defaults to the backend selection.")
    runs_start.add_argument(
        "--effort",
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        help="Cloud model reasoning effort override.",
    )
    runs_start.add_argument("--profile", help="Saved or built-in tool profile ID.")
    runs_start.add_argument(
        "--detach",
        action="store_true",
        help="Start in the background and output the run record without following.",
    )
    runs_start.set_defaults(handler=_runs_start)

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

    runs_follow = runs_commands.add_parser("follow", help="Stream live events from an active run.")
    _add_json_option(runs_follow)
    runs_follow.add_argument("run_id", help="UUID of the run.")
    runs_follow.set_defaults(handler=_runs_follow)

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
        payload["agent"] = {
            "key": agent if isinstance(agent, str) else "apex",
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
        description = agent["key"]
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
    print("Apex Agent")
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


def _runs_start(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
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

    conversation = _require_mapping(
        client.request(
            "POST",
            "/api/v1/cortex/conversations",
            payload={"origin": "cli", "title": _cli_conversation_title(prompt)},
        ),
        "conversation",
    )
    conversation_id = conversation.get("id")
    if not isinstance(conversation_id, str):
        raise CliError("invalid_response", "APEX did not return a conversation ID.")

    request_payload["user_message_id"] = str(uuid.uuid4())
    request_payload["agent_message_id"] = str(uuid.uuid4())

    run_record = _require_mapping(
        client.request(
            "POST",
            f"/api/v1/cortex/conversations/{quote(conversation_id, safe='')}/runs",
            payload=request_payload,
        ),
        "run record",
    )
    run_id = run_record.get("id")
    if not isinstance(run_id, str):
        raise CliError("invalid_response", "APEX did not return a run ID.")

    detach = bool(getattr(args, "detach", False))
    if detach:
        _emit(run_record, json_mode, _render_run_start_detached)
        return 0

    if not json_mode:
        print(f"[Run started: {run_id}]", file=sys.stderr)
    return _follow_run_stream(client, run_id, json_mode)


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


def _runs_follow(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    run_id = args.run_id.strip()
    if not run_id:
        raise CliError("invalid_input", "Run ID must contain non-whitespace text.")
    return _follow_run_stream(client, run_id, json_mode)


def _runs_cancel(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    run_id = args.run_id.strip()
    if not run_id:
        raise CliError("invalid_input", "Run ID must contain non-whitespace text.")
    payload = client.request("POST", f"/api/v1/cortex/runs/{quote(run_id, safe='')}/cancel")
    _require_mapping(payload, "run detail")
    _emit(payload, json_mode, _render_run_cancelled)
    return 0


def _follow_run_stream(
    client: ApiClient,
    run_id: str,
    json_mode: bool,
    *,
    max_reconnects: int = 3,
) -> int:
    path = f"/api/v1/cortex/runs/{quote(run_id, safe='')}/events"
    last_id: int | None = None
    terminal_reached = False
    exit_code = 0
    reconnect_attempts = 0

    while not terminal_reached:
        try:
            for event in client.stream_events(path, last_event_id=last_id):
                if event.get("id") is not None:
                    last_id = event["id"]
                reconnect_attempts = 0

                event_type = event.get("type")
                payload = event.get("payload")

                if json_mode:
                    raw = event.get("raw")
                    if raw:
                        print(raw, flush=True)
                    elif isinstance(payload, dict):
                        print(json.dumps(payload, ensure_ascii=False), flush=True)
                else:
                    _render_stream_event(event_type, payload)

                if event_type == "run.completed":
                    terminal_reached = True
                    record = payload.get("record") if isinstance(payload, dict) else payload
                    if isinstance(record, dict):
                        status = record.get("status")
                        exit_code = 0 if status == "completed" else 1
                    break
                elif event_type == "run.status" and isinstance(payload, dict):
                    status = payload.get("status")
                    if status in {"completed", "failed", "cancelled", "interrupted"}:
                        terminal_reached = True
                        exit_code = 0 if status == "completed" else 1

            if terminal_reached:
                break

            if reconnect_attempts < max_reconnects:
                reconnect_attempts += 1
                time.sleep(0.2)
                continue
            else:
                break
        except KeyboardInterrupt:
            if not json_mode:
                print(f"\n[Detached from run {run_id}. Run continues in background.]", file=sys.stderr)
            return 0
        except CliError:
            if reconnect_attempts < max_reconnects and not terminal_reached:
                reconnect_attempts += 1
                time.sleep(0.2)
                continue
            raise

    return exit_code


def _render_stream_event(event_type: str | None, payload: Any) -> None:
    if not isinstance(payload, dict):
        return

    if event_type == "response.delta":
        delta = payload.get("delta")
        if isinstance(delta, str):
            sys.stdout.write(delta)
            sys.stdout.flush()
    elif event_type == "response.reset":
        sys.stdout.write("\n")
        sys.stdout.flush()
        print("[Provisional response reset for tool execution]", file=sys.stderr)
    elif event_type == "model.started":
        turn = payload.get("turn", 1)
        print(f"[Model started: turn {turn}]", file=sys.stderr)
    elif event_type == "tool.started":
        name = payload.get("name", "tool")
        print(f"[Tool started: {name}]", file=sys.stderr)
    elif event_type == "tool.completed":
        name = payload.get("name", "tool")
        status = payload.get("status", "ok")
        duration = payload.get("duration_ms")
        dur_str = f" ({status}, {duration:.0f}ms)" if isinstance(duration, (int, float)) else f" ({status})"
        print(f"[Tool completed: {name}{dur_str}]", file=sys.stderr)
    elif event_type == "action.proposed":
        action_id = payload.get("action_id", "unknown")
        risk = payload.get("risk", "unknown")
        print(f"[Action proposed: {action_id} | risk: {risk}]", file=sys.stderr)
    elif event_type == "run.status":
        status = payload.get("status", "unknown")
        print(f"[Run status: {status}]", file=sys.stderr)
    elif event_type == "run.snapshot":
        answer = payload.get("answer")
        if isinstance(answer, str) and answer:
            sys.stdout.write(answer)
            sys.stdout.flush()
    elif event_type == "run.completed":
        sys.stdout.write("\n")
        sys.stdout.flush()
        record = payload.get("record") if isinstance(payload.get("record"), dict) else payload
        status = record.get("status", "completed")
        elapsed = record.get("elapsed_seconds", 0.0)
        tokens = record.get("total_tokens", 0)
        model = record.get("resolved_model") or record.get("requested_model", "unknown")
        print(f"[Run {status}: {elapsed:.1f}s | {tokens} tokens | {model}]", file=sys.stderr)
        err = record.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code") or "failed"
            print(f"Error: {msg}", file=sys.stderr)


def _render_run_start_detached(payload: object) -> None:
    if not isinstance(payload, dict):
        print("APEX returned an unexpected run response.")
        return
    print(f"Run ID: {payload.get('id', 'unknown')}")
    print(f"Status: {payload.get('status', 'unknown')}")
    print(f"Model: {payload.get('requested_model', 'unknown')}")
    print(f"Conversation ID: {payload.get('conversation_id', 'unknown')}")
    print(f"To follow: uv run apex runs follow {payload.get('id', '<run_id>')}")


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
