"""Process-level OpenTelemetry tracing for the gh-address-cr CLI."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

import requests
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NoOpTracer, Span, SpanKind, Status, StatusCode, Tracer, get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from gh_address_cr.core.otel_semconv import (
    ERROR_TYPE,
    PROCESS_EXIT_CODE,
)

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
_active_tracer: ContextVar[Tracer | None] = ContextVar("gh_address_cr_active_tracer", default=None)

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


def resolve_parent_context(environ: Mapping[str, str]) -> Context | None:
    """Resolve the parent context from the environment.

    Extracts traceparent using TraceContextTextMapPropagator, supporting
    both TRACEPARENT and traceparent keys. Fail-open.
    """
    try:
        val = environ.get("TRACEPARENT") or environ.get("traceparent")
        if not val:
            return None
        return TraceContextTextMapPropagator().extract(carrier={"traceparent": val})
    except Exception:
        return None


def run_traced(
    tracer: Tracer,
    span_name: str,
    operation: Callable[[], T],
    *,
    attributes: Mapping[str, str | bool | int | float | Sequence[str]] | None = None,
    context: Context | None = None,
) -> T | int:
    """Run an operation in a span and explicitly record failures."""
    if context is None:
        context = resolve_parent_context(os.environ)

    token = _active_tracer.set(tracer)
    try:
        with tracer.start_as_current_span(
            span_name,
            record_exception=False,
            set_status_on_exception=False,
            context=context,
        ) as span:
            # run_traced owns span lifecycle + parent context + exit.code/error.type
            # only. Execution identity (executable.name/pid/parent_pid), agent-session
            # correlation, args, gen_ai, and vcs attributes are assembled by the CLI
            # entrypoint (__main__) and passed in via ``attributes``.
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)

            try:
                result = operation()
                # Normal Return
                exit_code = result if isinstance(result, int) and not isinstance(result, bool) else 0
                span.set_attribute(PROCESS_EXIT_CODE, exit_code)
                return result
            except SystemExit as error:
                exit_code = (
                    error.code
                    if isinstance(error.code, int) and not isinstance(error.code, bool)
                    else (0 if error.code is None else 1)
                )
                span.set_attribute(PROCESS_EXIT_CODE, exit_code)
                return exit_code
            except KeyboardInterrupt as error:
                span.set_attribute(PROCESS_EXIT_CODE, 1)
                span.set_attribute(ERROR_TYPE, "keyboard_interrupt")
                _record_sanitized_error(span, error)
                raise
            except Exception as error:
                span.set_attribute(PROCESS_EXIT_CODE, 1)
                err_type = "timeout" if isinstance(error, TimeoutError) else "_OTHER"
                span.set_attribute(ERROR_TYPE, err_type)
                _record_sanitized_error(span, error)
                raise
    finally:
        _active_tracer.reset(token)


def _record_sanitized_error(span: Span, error: BaseException) -> None:
    sanitized_error = RuntimeError(type(error).__name__)
    span.record_exception(sanitized_error)
    span.set_status(Status(StatusCode.ERROR))


def set_current_span_attributes(attributes: Mapping[str, str | bool | int | float | Sequence[str]]) -> None:
    span = get_current_span()
    if not span.is_recording():
        return
    for key, value in attributes.items():
        span.set_attribute(key, value)


def get_current_span_attributes(
    keys: Sequence[str],
) -> dict[str, str | bool | int | float | Sequence[str]]:
    span = get_current_span()
    if not span.is_recording():
        return {}
    current_attributes = getattr(span, "attributes", None)
    if not isinstance(current_attributes, Mapping):
        return {}
    return {key: current_attributes[key] for key in keys if key in current_attributes}


def add_current_span_event(
    name: str,
    attributes: Mapping[str, str | bool | int | float | Sequence[str]] | None = None,
) -> None:
    span = get_current_span()
    if not span.is_recording():
        return
    if attributes:
        span.add_event(name, attributes=dict(attributes))
        return
    span.add_event(name)


@contextmanager
def start_child_span(
    name: str,
    *,
    attributes: Mapping[str, str | bool | int | float | Sequence[str]] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[Span]:
    """Start a child span under the current active span when tracing is active.

    Maintainer rule: only use this for independently measurable workflow
    operations. Checkpoint-style timeline annotations should stay as
    ``add_current_span_event(...)`` on the current active span.

    Constitutional guarantee: this never starts a new root span. If there is
    no recording parent span in the current context (for example, called
    outside ``run_traced``), it falls back to yielding the current
    (non-recording) span instead of silently starting an unparented trace.
    """
    tracer = _active_tracer.get() or _tracer
    current_span = get_current_span()
    if tracer is None or not current_span.is_recording():
        yield current_span
        return
    with tracer.start_as_current_span(
        name,
        record_exception=False,
        set_status_on_exception=False,
        kind=kind,
    ) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


def _reset_telemetry_for_tests() -> None:
    """Reset module-owned state without flushing mocked test providers."""
    global _trace_provider, _tracer
    _trace_provider = None
    _tracer = None
    for logger_name, disabled in _logger_disabled_states.items():
        logging.getLogger(logger_name).disabled = disabled
    _logger_disabled_states.clear()
