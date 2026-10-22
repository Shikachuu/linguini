"""Optional OpenTelemetry export of agent runs."""

from __future__ import annotations

import logging

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic_ai import InstrumentationSettings
from pydantic_ai.capabilities import Instrumentation

from linguini.config import Settings

log = logging.getLogger(__name__)


def configure(settings: Settings) -> tuple[TracerProvider, Instrumentation] | None:
    """Build an exporter for ``LINGUINI_OTEL_ENDPOINT`` without touching process-wide state.

    Returns:
        The provider to shut down on exit and the capability to attach to agents, or None when off.
    """
    if settings.otel_endpoint is None:
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": "linguini"}))
    exporter = OTLPSpanExporter(endpoint=str(settings.otel_endpoint), timeout=5)
    provider.add_span_processor(BatchSpanProcessor(exporter, export_timeout_millis=5000))
    log.info("tracing enabled, exporting to %s", settings.otel_endpoint)
    return provider, Instrumentation(InstrumentationSettings(tracer_provider=provider, include_content=False))
