"""OpenTelemetry tracing service and provider lifecycle for APEX."""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Tracer

_LOGGER = logging.getLogger(__name__)

_DEFAULT_SERVICE_NAME = "apex"


def parse_otlp_headers(raw: str | None) -> dict[str, str]:
    """Parse comma-separated OTLP header key=value pairs."""
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for part in raw.split(","):
        item = part.strip()
        if "=" in item:
            key, val = item.split("=", 1)
            headers[key.strip()] = val.strip()
    return headers


class TracingService:
    """Manages OpenTelemetry tracer provider lifecycle and OTLP export."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        headers: dict[str, str] | None = None,
        service_name: str | None = None,
        tracer_provider: Any = None,
    ) -> None:
        self._endpoint = (
            endpoint
            if endpoint is not None
            else os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        )
        if headers is not None:
            self._headers = headers
        else:
            raw_headers = os.getenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or os.getenv(
                "OTEL_EXPORTER_OTLP_HEADERS"
            )
            self._headers = parse_otlp_headers(raw_headers)
        self._service_name = (
            service_name
            or os.getenv("OTEL_SERVICE_NAME")
            or _DEFAULT_SERVICE_NAME
        )
        self._provider = tracer_provider
        self._enabled = False
        self._initialized = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def initialize(self) -> None:
        """Initialize OpenTelemetry tracer provider if an endpoint is configured."""
        if self._initialized:
            return
        self._initialized = True

        if self._provider is not None:
            self._enabled = True
            try:
                if getattr(trace, "_TRACER_PROVIDER", None) is None:
                    trace.set_tracer_provider(self._provider)
            except Exception:
                pass
            return

        if not self._endpoint:
            self._enabled = False
            return

        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        except (ImportError, ModuleNotFoundError) as exc:
            _LOGGER.warning(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT is set, but OpenTelemetry SDK or "
                "exporter packages are not installed (%s). Tracing will remain disabled.",
                exc,
            )
            self._enabled = False
            return
        except Exception as exc:
            _LOGGER.warning(
                "Failed to import OpenTelemetry components (%s). Tracing will remain disabled.",
                exc,
            )
            self._enabled = False
            return

        try:
            resource = Resource.create({"service.name": self._service_name})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(
                endpoint=self._endpoint,
                headers=self._headers,
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self._provider = provider
            self._enabled = True
            _LOGGER.info(
                "OpenTelemetry tracing initialized (endpoint=%s, service=%s).",
                self._endpoint,
                self._service_name,
            )
        except Exception as exc:
            _LOGGER.warning(
                "Failed to initialize OpenTelemetry TracerProvider (%s). Tracing will remain disabled.",
                exc,
            )
            self._enabled = False

    def shutdown(self) -> None:
        """Flush and shutdown the tracer provider."""
        if self._provider is not None and hasattr(self._provider, "shutdown"):
            try:
                self._provider.shutdown()
            except Exception as exc:
                _LOGGER.warning("Error shutting down OpenTelemetry TracerProvider: %s", exc)
        self._enabled = False
        self._initialized = False

    def get_tracer(self, name: str = "apex") -> Tracer:
        """Return a tracer instance from the current provider."""
        if self._provider is not None:
            return self._provider.get_tracer(name)
        return trace.get_tracer(name)


_TRACING_SERVICE: TracingService | None = None


def get_tracing_service() -> TracingService:
    """Return the application-level tracing service."""
    global _TRACING_SERVICE
    if _TRACING_SERVICE is None:
        _TRACING_SERVICE = TracingService()
    return _TRACING_SERVICE


def set_tracing_service(service: TracingService | None) -> None:
    """Set the application-level tracing service (primarily for testing)."""
    global _TRACING_SERVICE
    _TRACING_SERVICE = service
