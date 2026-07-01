"""Process-level OpenTelemetry tracing for the gh-address-cr CLI."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import TypeVar

import requests
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NoOpTracer, Span, Status, StatusCode, Tracer

SERVICE_NAME_VALUE = "gh-address-cr"
TELEMETRY_ENVIRONMENT_VARIABLE = "GH_ADDRESS_CR_TELEMETRY_ENVIRONMENT"
OTLP_TRACES_ENDPOINT = "https://telemetry-gateway.hamiltonsnow.workers.dev/v1/traces"
_INSTRUMENTATION_NAME = "gh_address_cr"
EXPORT_TIMEOUT_SECONDS = 0.15
EXPORT_TIMEOUT_MILLIS = EXPORT_TIMEOUT_SECONDS * 1000
SHUTDOWN_JOIN_TIMEOUT_SECONDS = 0.2
_SAFE_EXPORT_HEADERS = {"X-GH-Address-CR-Telemetry": "1"}
_OTEL_EXPORT_LOGGERS = (
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.sdk._shared_internal",
)

_trace_provider: TracerProvider | None = None
_tracer: Tracer | None = None
_logger_disabled_states: dict[str, bool] = {}

T = TypeVar("T")


def _telemetry_disabled() -> bool:
    return os.environ.get("DISABLE_TELEMETRY") == "1" or os.environ.get("DO_NOT_TRACK") == "1"


def initialize_telemetry() -> Tracer:
    """Initialize OTLP tracing once and return a tracer.

    No credentials are configured here. The edge gateway owns credential
    injection. Users can disable all initialization with DISABLE_TELEMETRY=1
    or DO_NOT_TRACK=1.
    """
    global _trace_provider, _tracer

    if _telemetry_disabled():
        return NoOpTracer()
    if _tracer is not None:
        return _tracer

    _silence_exporter_diagnostics()
    export_session = requests.Session()
    export_session.trust_env = False
    exporter = OTLPSpanExporter(
        endpoint=OTLP_TRACES_ENDPOINT,
        headers=dict(_SAFE_EXPORT_HEADERS),
        timeout=EXPORT_TIMEOUT_SECONDS,
        session=export_session,
    )
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: _service_name()}))
    provider.add_span_processor(BatchSpanProcessor(exporter, export_timeout_millis=EXPORT_TIMEOUT_MILLIS))

    _trace_provider = provider
    _tracer = provider.get_tracer(_INSTRUMENTATION_NAME)
    return _tracer


def _service_name() -> str:
    if os.environ.get(TELEMETRY_ENVIRONMENT_VARIABLE) == "test":
        return f"{SERVICE_NAME_VALUE}-test"
    return SERVICE_NAME_VALUE


def _silence_exporter_diagnostics() -> None:
    for logger_name in _OTEL_EXPORT_LOGGERS:
        logger = logging.getLogger(logger_name)
        _logger_disabled_states.setdefault(logger_name, logger.disabled)
        logger.disabled = True


def shutdown_telemetry() -> None:
    """Attempt a bounded flush without delaying CLI completion."""
    global _trace_provider, _tracer

    provider = _trace_provider
    if provider is None:
        return

    _trace_provider = None
    _tracer = None
    shutdown_thread = threading.Thread(
        target=_shutdown_provider,
        args=(provider,),
        name="gh-address-cr-telemetry-shutdown",
        daemon=True,
    )
    shutdown_thread.start()
    shutdown_thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_SECONDS)


def _shutdown_provider(provider: TracerProvider) -> None:
    try:
        provider.shutdown()
    except Exception:
        # Telemetry is observed evidence and must never change CLI completion.
        return


def run_traced(
    tracer: Tracer,
    span_name: str,
    operation: Callable[[], T],
    *,
    attributes: Mapping[str, str | bool | int | float] | None = None,
) -> T:
    """Run an operation in a span and explicitly record failures."""
    with tracer.start_as_current_span(
        span_name,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            return operation()
        except SystemExit as error:
            if error.code not in (None, 0):
                _record_sanitized_error(span, error)
            raise
        except BaseException as error:
            _record_sanitized_error(span, error)
            raise


def _record_sanitized_error(span: Span, error: BaseException) -> None:
    sanitized_error = RuntimeError(type(error).__name__)
    span.record_exception(sanitized_error)
    span.set_status(Status(StatusCode.ERROR))


def _reset_telemetry_for_tests() -> None:
    """Reset module-owned state without flushing mocked test providers."""
    global _trace_provider, _tracer
    _trace_provider = None
    _tracer = None
    for logger_name, disabled in _logger_disabled_states.items():
        logging.getLogger(logger_name).disabled = disabled
    _logger_disabled_states.clear()
