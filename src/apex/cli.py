"""Thin command-line client for the local APEX HTTP API."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Sequence
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

    agents = commands.add_parser("agents", help="List visible Apex Agents.")
    _add_json_option(agents)
    agents.set_defaults(handler=_agents)

    ask = commands.add_parser("ask", help="Run one Agent turn.")
    _add_json_option(ask)
    ask.add_argument("prompt", help="Prompt for the selected Agent.")
    ask.add_argument("--agent", help="Apex Agent key. Defaults to the backend selection.")
    ask.add_argument(
        "--effort",
        choices=("light", "focused", "extended"),
        help="Cloud Agent effort override.",
    )
    ask.add_argument("--profile", help="Saved or built-in tool profile ID.")
    ask.set_defaults(handler=_ask)

    briefing = commands.add_parser("briefing", help="Refresh and generate a briefing.")
    _add_json_option(briefing)
    briefing.add_argument(
        "--mode",
        choices=("panthera", "felis", "structured_digest"),
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
    selection = config.get("agent_initial_selection")
    if isinstance(selection, dict):
        agent = selection.get("agent")
        runtime = selection.get("runtime")
        effort = selection.get("effort")
        payload["agent"] = {
            "key": agent if isinstance(agent, str) else config.get("default_agent"),
            "runtime": runtime if isinstance(runtime, str) else None,
            "effort": effort if isinstance(effort, str) else None,
        }
    elif isinstance(config.get("default_agent"), str):
        payload["agent"] = {"key": config["default_agent"]}
    _emit(payload, json_mode, _render_status)
    return 0


def _agents(_args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    payload = client.request("GET", "/api/v1/agents")
    _require_list(payload, "Agent list")
    _emit(payload, json_mode, _render_agents)
    return 0


def _ask(args: argparse.Namespace, client: ApiClient, json_mode: bool) -> int:
    prompt = args.prompt.strip()
    if not prompt:
        raise CliError("invalid_input", "Prompt must contain non-whitespace text.")
    request_payload: dict[str, object] = {"prompt": prompt}
    if args.agent is not None:
        request_payload["agent"] = args.agent
    if args.effort is not None:
        request_payload["effort"] = args.effort
    if args.profile is not None:
        request_payload["tool_profile_id"] = args.profile
    payload = client.request(
        "POST", "/api/v1/cortex/query", payload=request_payload, long_running=True
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


def _render_agents(payload: object) -> None:
    if not isinstance(payload, list):
        print("APEX returned an unexpected Agent list.")
        return
    if not payload:
        print("No Apex Agents are available.")
        return
    for agent in payload:
        if not isinstance(agent, dict):
            continue
        name = agent.get("display_name", agent.get("key", "Unknown Agent"))
        key = agent.get("key", "unknown")
        print(f"{name} ({key})")
        print(
            "  "
            f"{agent.get('runtime', 'unknown')} | {agent.get('provider', 'unknown')} | "
            f"{agent.get('configured_model', 'unknown')}"
        )
        print(f"  Status: {agent.get('status', 'unknown')}")


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


if __name__ == "__main__":
    raise SystemExit(main())
