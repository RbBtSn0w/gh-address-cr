"""Process-level OpenTelemetry tracing for the gh-address-cr CLI."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar
from urllib.parse import urlsplit, urlunsplit

import requests
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import (
    SERVICE_NAME,
    SERVICE_NAMESPACE,
    SERVICE_VERSION,
    TELEMETRY_SDK_LANGUAGE,
    TELEMETRY_SDK_NAME,
    TELEMETRY_SDK_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.sdk.version import __version__ as otel_sdk_version
from opentelemetry.trace import NoOpTracer, Span, SpanKind, Status, StatusCode, Tracer, get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from gh_address_cr import __version__
from gh_address_cr.core.otel_semconv import (
    ERROR_TYPE,
    PROCESS_EXIT_CODE,
)

SERVICE_NAME_VALUE = "gh-address-cr"
SERVICE_NAMESPACE_VALUE = "com.hamiltonsnow"
# Retained as a compatibility symbol. A distributable client does not map this
# host-local hint into service identity or deployment environment attributes.
TELEMETRY_ENVIRONMENT_VARIABLE = "GH_ADDRESS_CR_TELEMETRY_ENVIRONMENT"
OTLP_TRACES_ENDPOINT = "https://telemetry-gateway.hamiltonsnow.workers.dev/v1/traces"
GATEWAY_ORIGINS = {
    "https://telemetry-gateway-development.hamiltonsnow.workers.dev",
    "https://telemetry-gateway-staging.hamiltonsnow.workers.dev",
    "https://telemetry-gateway.hamiltonsnow.workers.dev",
}
_INSTRUMENTATION_NAME = "gh_address_cr"
EXPORT_TIMEOUT_SECONDS = 2.0
EXPORT_TIMEOUT_MILLIS = EXPORT_TIMEOUT_SECONDS * 1000
SHUTDOWN_JOIN_TIMEOUT_SECONDS = 2.2
_SAFE_EXPORT_HEADERS = {"otel-gateway-profile": "anonymous-client-v1"}
MAX_QUEUE_SIZE = 128
MAX_EXPORT_BATCH_SIZE = 32
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
    endpoint = _traces_endpoint(os.environ)
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers=_gateway_headers(endpoint),
        timeout=EXPORT_TIMEOUT_SECONDS,
        compression=Compression.Gzip,
        session=export_session,
    )
    provider = TracerProvider(
        resource=Resource(
            {
                SERVICE_NAME: SERVICE_NAME_VALUE,
                SERVICE_NAMESPACE: SERVICE_NAMESPACE_VALUE,
                SERVICE_VERSION: __version__,
                TELEMETRY_SDK_LANGUAGE: "python",
                TELEMETRY_SDK_NAME: "opentelemetry",
                TELEMETRY_SDK_VERSION: otel_sdk_version,
            }
        ),
        sampler=ALWAYS_ON,
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            max_queue_size=MAX_QUEUE_SIZE,
            max_export_batch_size=MAX_EXPORT_BATCH_SIZE,
            export_timeout_millis=EXPORT_TIMEOUT_MILLIS,
        )
    )

    _trace_provider = provider
    _tracer = provider.get_tracer(_INSTRUMENTATION_NAME)
    return _tracer


def _traces_endpoint(environ: Mapping[str, str]) -> str:
    signal_endpoint = environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    if signal_endpoint:
        return signal_endpoint
    base_endpoint = environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if base_endpoint:
        parsed = urlsplit(base_endpoint)
        path = parsed.path.rstrip("/")
        if not path.endswith("/v1/traces"):
            path = f"{path}/v1/traces" if path else "/v1/traces"
        return urlunsplit(parsed._replace(path=path))
    return OTLP_TRACES_ENDPOINT


def _gateway_headers(endpoint: str) -> dict[str, str]:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        return (
            dict(_SAFE_EXPORT_HEADERS)
            if (
                parsed.scheme.lower() == "https"
                and f"https://{parsed.hostname}" in GATEWAY_ORIGINS
                and (parsed.port or 443) == 443
            )
            else {}
        )
    except ValueError:
        return {}


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
    non_error_exit_codes: Collection[int] = (),
) -> T | int:
    """Run an operation in a span and explicitly record failures.

    Core CLI-spans error rule: a non-zero exit code marks the span as an error
    (``error.type`` + ERROR status). ``non_error_exit_codes`` lets the domain
    layer exempt exit codes that are a deliberate status vocabulary rather than
    failures (see ``STATUS_EXIT_CODES`` in ``cli.py`` and contract C-3); those
    exempted codes record ``process.exit.code`` only. A propagated exception is
    always an error regardless of the exempt set.
    """
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
                _mark_exit_outcome(span, exit_code, non_error_exit_codes)
                return result
            except SystemExit as error:
                exit_code = (
                    error.code
                    if isinstance(error.code, int) and not isinstance(error.code, bool)
                    else (0 if error.code is None else 1)
                )
                span.set_attribute(PROCESS_EXIT_CODE, exit_code)
                _mark_exit_outcome(span, exit_code, non_error_exit_codes)
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


def _mark_exit_outcome(span: Span, exit_code: int, non_error_exit_codes: Collection[int]) -> None:
    """Apply the CLI-spans error rule to a non-crash exit.

    A non-zero exit code is an error (``error.type`` = ``_OTHER`` per the OTel
    well-known fallback + ERROR span status) unless it is a domain status code
    exempted via ``non_error_exit_codes``.
    """
    if exit_code == 0 or exit_code in non_error_exit_codes:
        return
    span.set_attribute(ERROR_TYPE, "_OTHER")
    span.set_status(Status(StatusCode.ERROR))


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
