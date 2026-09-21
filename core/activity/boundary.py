"""Small HTTP checks shared by the local activity submission boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

MAX_ACTIVITY_REQUEST_BYTES = 256 * 1024


def local_host_allowed(
    host: str,
    *,
    allowed_hosts: Iterable[str],
    port: int | None = None,
) -> bool:
    """Accept an explicit loopback Host header, optionally at one port."""
    value = host.strip().lower()
    if not value:
        return False
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return False
        name, remainder = value[1:end], value[end + 1:]
        if remainder and not remainder.startswith(":"):
            return False
        raw_port = remainder[1:] if remainder else ""
    else:
        name, separator, raw_port = value.partition(":")
        if separator and not raw_port.isdecimal():
            return False
    normalized_allowed_hosts = {
        item.strip().lower().removeprefix("[").removesuffix("]")
        for item in allowed_hosts
    }
    if name not in normalized_allowed_hosts:
        return False
    return port is None or not raw_port or raw_port == str(port)


def local_origin_allowed(origin: str, *, allowed_origins: Iterable[str]) -> bool:
    """Match an Origin exactly after dropping a trailing slash."""
    normalized = origin.strip().rstrip("/").lower()
    if not normalized:
        return False
    parsed = urlsplit(normalized)
    if parsed.path or parsed.query or parsed.fragment or not parsed.scheme or not parsed.hostname:
        return False
    return normalized in {item.strip().rstrip("/").lower() for item in allowed_origins}


def require_local_submission_headers(
    request: Request,
    *,
    allowed_hosts: Iterable[str],
    allowed_origins: Iterable[str],
    port: int | None = None,
) -> None:
    """Reject Host-header attacks and cross-origin browser submissions."""
    if not local_host_allowed(
        request.headers.get("host", ""),
        allowed_hosts=allowed_hosts,
        port=port,
    ):
        raise HTTPException(status_code=status.HTTP_421_MISDIRECTED_REQUEST, detail="Activity submission host is not allowed.")
    origin = request.headers.get("origin")
    if origin and not local_origin_allowed(origin, allowed_origins=allowed_origins):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity submission origin is not allowed.")


async def read_bounded_activity_body(request: Request) -> bytes:
    """Read a report body without accepting more than the stored-report limit."""
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        try:
            if int(raw_length) > MAX_ACTIVITY_REQUEST_BYTES:
                raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Activity report exceeds the 256 KiB limit.")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Length.") from exc
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_ACTIVITY_REQUEST_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Activity report exceeds the 256 KiB limit.")
        chunks.append(chunk)
    return b"".join(chunks)
