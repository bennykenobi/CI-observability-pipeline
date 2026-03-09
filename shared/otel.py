"""OpenTelemetry setup and helper functions for runtime tracing."""

from __future__ import annotations

from functools import cache
from urllib.parse import urlparse

from google.auth.compute_engine import IDTokenCredentials
from google.auth.transport.requests import AuthorizedSession, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from shared.config import Settings

_CONFIGURED_SERVICES: set[str] = set()


def configure_tracing(settings: Settings, service_name: str) -> None:
    """Configure OTLP trace export once for the given service name."""

    if not settings.otel_exporter_otlp_endpoint:
        return
    if service_name in _CONFIGURED_SERVICES:
        return

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        trace.set_tracer_provider(provider)
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
        headers=_parse_headers(settings.otel_exporter_otlp_headers),
        session=_create_otlp_session(settings),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    _CONFIGURED_SERVICES.add(service_name)


@cache
def get_tracer(name: str):
    """Return a cached tracer for the given module or component name."""

    return trace.get_tracer(name)


def current_trace_fields() -> dict[str, str]:
    """Return trace and span IDs for structured logging when a span is active."""

    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


def set_span_attributes(span, **attributes) -> None:
    """Attach only non-null attributes to the active span."""

    for key, value in attributes.items():
        if value is None:
            continue
        span.set_attribute(key, value)


def _parse_headers(raw_headers: str) -> dict[str, str] | None:
    """Parse OTLP header configuration from a comma-separated env-var string."""

    if not raw_headers:
        return None
    headers: dict[str, str] = {}
    for entry in raw_headers.split(","):
        if "=" not in entry:
            continue
        key, value = entry.split("=", maxsplit=1)
        headers[key.strip()] = value.strip()
    return headers or None


def _create_otlp_session(settings: Settings):
    """Create an authenticated OTLP session for non-local collector endpoints."""

    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint or _is_local_endpoint(endpoint):
        return None

    audience = settings.otel_exporter_otlp_audience or _derive_audience(endpoint)
    credentials = IDTokenCredentials(
        Request(),
        target_audience=audience,
        use_metadata_identity_endpoint=True,
    )
    return AuthorizedSession(credentials)


def _derive_audience(endpoint: str) -> str:
    """Derive the IAM audience from the OTLP endpoint URL."""

    parsed = urlparse(endpoint)
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_local_endpoint(endpoint: str) -> bool:
    """Return true when the OTLP endpoint points at a local development host."""

    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}
