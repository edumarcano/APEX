"""Separately started, submission-only external activity gateway.

The normal APEX API deliberately does not import this module.  It owns only a
small SQLite-backed activity service, a JSON endpoint, and FastMCP's
Streamable HTTP transport.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Scope, Send

from core import database
from core.activity import (
    ActivityClientDisabledError,
    ActivityConflictError,
    ActivityPermissionError,
    ActivityReportContent,
    ActivityService,
    ActivityStore,
    ActivityStoreError,
    ActivitySubmissionRequest,
)
from core.activity.boundary import MAX_ACTIVITY_REQUEST_BYTES, require_local_submission_headers
from core.activity.cloudflare import (
    CloudflareAccessAuthorizationError,
    CloudflareAccessConfiguration,
    CloudflareAccessIdentity,
    CloudflareAccessVerificationError,
    CloudflareAccessVerifier,
)
from core.config import (
    DEMO_MODE,
    load_activity_client_registrations,
    load_cloudflare_access_configuration,
)
from core.conversations.service import ConversationService

_LOGGER = logging.getLogger(__name__)
_BODY_LIMIT_BYTES = MAX_ACTIVITY_REQUEST_BYTES
_RATE_WINDOW_SECONDS = 60.0
_RATE_ATTEMPTS = 30
_LOCAL_ORIGIN_TEMPLATE = "http://{host}:{port}"


class GatewayConfigurationError(ValueError):
    """The separately started gateway was given an unsafe configuration."""


class GatewayRateLimitError(RuntimeError):
    """A configured client exhausted its local fixed-window allowance."""


class GatewayAuthenticationError(RuntimeError):
    """A submission does not satisfy the active gateway authentication mode."""


class GatewayClientBindingError(RuntimeError):
    """A request names a client different from the verified Access binding."""


def _loopback_bind_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class GatewayOptions:
    mode: Literal["local", "cloudflare"] = "local"
    host: str = "127.0.0.1"
    port: int = 8001

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise GatewayConfigurationError("Gateway port must be between 1 and 65535.")
        if not _loopback_bind_host(self.host):
            raise GatewayConfigurationError("The activity gateway must bind to a loopback address.")

    @property
    def local_hosts(self) -> tuple[str, ...]:
        normalized = self.host.strip().lower()
        if normalized == "127.0.0.1":
            return ("127.0.0.1", "localhost", "[::1]")
        if normalized == "::1":
            return ("[::1]",)
        return (self.host.strip(),)

    @property
    def local_origins(self) -> tuple[str, ...]:
        return tuple(
            _LOCAL_ORIGIN_TEMPLATE.format(host=host, port=self.port)
            for host in self.local_hosts
        )


class _FixedWindowLimiter:
    """Keep a bounded, process-local count for both submission adapters."""

    def __init__(self, *, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str) -> None:
        now = self._now()
        with self._lock:
            started_at, count = self._windows.get(client_id, (now, 0))
            if now - started_at >= _RATE_WINDOW_SECONDS:
                started_at, count = now, 0
            if count >= _RATE_ATTEMPTS:
                raise GatewayRateLimitError("activity_rate_limited")
            self._windows[client_id] = (started_at, count + 1)


class GatewaySubmissionService:
    """Submit a boundary-resolved identity through the shared activity service."""

    def __init__(self, activity_service: ActivityService, *, limiter: _FixedWindowLimiter | None = None) -> None:
        self._activity_service = activity_service
        self._limiter = limiter or _FixedWindowLimiter()

    def submit(
        self,
        *,
        client_id: str,
        principal: str,
        partition: str | None,
        report: ActivityReportContent,
    ) -> dict[str, object]:
        self._limiter.check(client_id)
        receipt = self._activity_service.submit(
            client_id=client_id,
            principal=principal,
            partition=partition,
            content=report,
        )
        _LOGGER.info(
            "External activity gateway accepted client_id=%s report_id=%s duplicate=%s",
            client_id,
            receipt.report.id,
            receipt.duplicate,
        )
        return {
            "id": str(receipt.report.id),
            "received_at": receipt.report.received_at,
            "duplicate": receipt.duplicate,
        }


class GatewayAuthenticator:
    """Resolve local or Cloudflare Access requests to generic principals."""

    def __init__(
        self,
        options: GatewayOptions,
        *,
        cloudflare: CloudflareAccessConfiguration | None = None,
        verifier: CloudflareAccessVerifier | None = None,
    ) -> None:
        self._options = options
        self._cloudflare = cloudflare
        self._verifier = verifier
        if options.mode == "cloudflare":
            if cloudflare is None:
                raise GatewayConfigurationError(
                    "Cloudflare mode requires external_activity.cloudflare issuer, JWKS, and application bindings."
                )
            self._verifier = verifier or CloudflareAccessVerifier(cloudflare)

    async def resolve(self, request: Request, requested_client_id: str) -> CloudflareAccessIdentity:
        if self._options.mode == "local":
            require_local_submission_headers(
                request,
                allowed_hosts=self._options.local_hosts,
                allowed_origins=self._options.local_origins,
                port=self._options.port,
            )
            return CloudflareAccessIdentity(client_id=requested_client_id, principal="operator")
        assertion = request.headers.get("Cf-Access-Jwt-Assertion", "")
        try:
            claims = await asyncio.to_thread(self._verifier.verify, assertion)  # type: ignore[union-attr]
            binding = self._cloudflare.resolve_binding(claims)  # type: ignore[union-attr]
        except CloudflareAccessVerificationError as exc:
            raise GatewayAuthenticationError("Cloudflare Access assertion could not be verified.") from exc
        except CloudflareAccessAuthorizationError as exc:
            raise GatewayAuthenticationError("Cloudflare Access assertion is not authorized for activity submission.") from exc
        if requested_client_id != binding.client_id:
            raise GatewayClientBindingError("Requested client does not match the Cloudflare Access application binding.")
        return CloudflareAccessIdentity(client_id=binding.client_id, principal=binding.principal)


class _BodyLimitMiddleware:
    """Reject streamed request bodies before endpoint parsing can retain them."""

    def __init__(self, app: ASGIApp, *, limit_bytes: int = _BODY_LIMIT_BYTES) -> None:
        self.app = app
        self.limit_bytes = limit_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = next((value for key, value in scope.get("headers", []) if key.lower() == b"content-length"), None)
        if content_length is not None:
            try:
                if int(content_length) > self.limit_bytes:
                    await PlainTextResponse("Request body exceeds the 256 KiB limit.", status_code=413)(scope, receive, send)
                    return
            except ValueError:
                await PlainTextResponse("Invalid Content-Length.", status_code=400)(scope, receive, send)
                return
        size = 0

        async def limited_receive() -> Message:
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.limit_bytes:
                    raise GatewayRequestTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except GatewayRequestTooLarge:
            await PlainTextResponse("Request body exceeds the 256 KiB limit.", status_code=413)(scope, receive, send)


class _GatewayRequestGuardMiddleware:
    """Apply the exact gateway Host and Origin allowlists before FastMCP."""

    def __init__(self, app: ASGIApp, *, options: GatewayOptions) -> None:
        self.app = app
        self.options = options

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            self.options.mode == "local"
            and scope["type"] == "http"
            and str(scope.get("path", "")).startswith("/mcp")
        ):
            try:
                require_local_submission_headers(
                    Request(scope),
                    allowed_hosts=self.options.local_hosts,
                    allowed_origins=self.options.local_origins,
                    port=self.options.port,
                )
            except HTTPException as exc:
                await PlainTextResponse(str(exc.detail), status_code=exc.status_code)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class GatewayRequestTooLarge(RuntimeError):
    pass


def _gateway_error(error: Exception) -> HTTPException:
    if isinstance(error, GatewayAuthenticationError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cloudflare Access authentication failed.")
    if isinstance(error, GatewayClientBindingError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity client does not match the Access application.")
    if isinstance(error, GatewayRateLimitError):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Activity submission rate limit exceeded.")
    if isinstance(error, ActivityConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The submission key was already used for different report content.")
    if isinstance(error, ActivityClientDisabledError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity client is disabled or unavailable.")
    if isinstance(error, ActivityPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity submission is not permitted for this client and partition.")
    if isinstance(error, ActivityStoreError):
        if str(error) == "report_too_large":
            return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Activity report exceeds the 256 KiB limit.")
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Activity report is invalid.")
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Activity inbox is unavailable.")


def create_gateway_app(
    options: GatewayOptions = GatewayOptions(),
    *,
    cloudflare: CloudflareAccessConfiguration | None = None,
    verifier: CloudflareAccessVerifier | None = None,
) -> FastAPI:
    """Build the opt-in gateway without importing the main API or connectors."""
    options.validate()
    store = ActivityStore(None if DEMO_MODE else database.DB_NAME)
    service = ActivityService(
        store,
        load_activity_client_registrations(),
        registration_loader=lambda: load_activity_client_registrations(refresh=True),
        demo_mode=DEMO_MODE,
    )
    submissions = GatewaySubmissionService(service)
    authenticator = GatewayAuthenticator(
        options,
        cloudflare=cloudflare if cloudflare is not None else load_cloudflare_access_configuration(),
        verifier=verifier,
    )
    mcp = FastMCP("APEX Activity Submission", instructions="Submit one external activity report to the local APEX inbox.")

    @mcp.tool(name="submit_activity", description="Submit one immutable external activity report.")
    async def submit_activity(client_id: str, report: ActivityReportContent) -> dict[str, object]:
        try:
            identity = await authenticator.resolve(get_http_request(), client_id)
            return submissions.submit(
                client_id=identity.client_id,
                principal=identity.principal,
                partition=None if options.mode == "cloudflare" else ConversationService.partition(),
                report=report,
            )
        except Exception as exc:
            _LOGGER.warning("External activity MCP submission failed client_id=%s category=%s", client_id, type(exc).__name__)
            raise ToolError(_gateway_error(exc).detail) from exc

    mcp_options: dict[str, object] = {
        "path": "/",
        "transport": "streamable-http",
        "json_response": True,
        "host_origin_protection": options.mode == "local",
    }
    if options.mode == "local":
        mcp_options["allowed_hosts"] = list(options.local_hosts)
        mcp_options["allowed_origins"] = list(options.local_origins)
    mcp_app = mcp.http_app(**mcp_options)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.initialize()
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            store.close()

    app = FastAPI(title="APEX external activity gateway", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(_BodyLimitMiddleware)
    app.add_middleware(_GatewayRequestGuardMiddleware, options=options)
    app.state.activity_service = service
    app.state.submission_service = submissions
    app.state.authenticator = authenticator
    app.state.mcp_server = mcp

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/activity/reports", status_code=status.HTTP_201_CREATED)
    async def submit_json(request: Request) -> JSONResponse:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Activity submissions require application/json.")
        try:
            payload = ActivitySubmissionRequest.model_validate_json(await request.body())
            identity = await authenticator.resolve(request, payload.client_id)
            receipt = submissions.submit(
                client_id=identity.client_id,
                principal=identity.principal,
                partition=None if options.mode == "cloudflare" else ConversationService.partition(),
                report=payload.report,
            )
            return JSONResponse(receipt, status_code=status.HTTP_201_CREATED)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Activity report is invalid.") from exc
        except HTTPException:
            raise
        except Exception as exc:
            _LOGGER.warning("External activity JSON submission failed category=%s", type(exc).__name__)
            raise _gateway_error(exc) from exc

    app.mount("/mcp", mcp_app)
    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start APEX's submission-only external activity gateway.")
    parser.add_argument("--mode", choices=("local", "cloudflare"), default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    options = GatewayOptions(mode=args.mode, host=args.host, port=args.port)
    options.validate()
    uvicorn.run(create_gateway_app(options), host=options.host, port=options.port)


if __name__ == "__main__":
    main()
