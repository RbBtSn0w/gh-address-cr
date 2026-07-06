"""Compatibility shim for process-level OpenTelemetry tracing.

This module preserves the historical `gh_address_cr.telemetry` patch surface
used by tests and callers while the implementation lives in `otel_tracing.py`.
"""

from __future__ import annotations

from gh_address_cr import otel_tracing as _impl
from opentelemetry.trace import Tracer

TracerProvider = _impl.TracerProvider
OTLPSpanExporter = _impl.OTLPSpanExporter
BatchSpanProcessor = _impl.BatchSpanProcessor
TELEMETRY_ENVIRONMENT_VARIABLE = _impl.TELEMETRY_ENVIRONMENT_VARIABLE
OTLP_TRACES_ENDPOINT = _impl.OTLP_TRACES_ENDPOINT
EXPORT_TIMEOUT_SECONDS = _impl.EXPORT_TIMEOUT_SECONDS
EXPORT_TIMEOUT_MILLIS = _impl.EXPORT_TIMEOUT_MILLIS
_SAFE_EXPORT_HEADERS = _impl._SAFE_EXPORT_HEADERS
_OTEL_EXPORT_LOGGERS = _impl._OTEL_EXPORT_LOGGERS

resolve_parent_context = _impl.resolve_parent_context
run_traced = _impl.run_traced
set_current_span_attributes = _impl.set_current_span_attributes
get_current_span_attributes = _impl.get_current_span_attributes
add_current_span_event = _impl.add_current_span_event
start_child_span = _impl.start_child_span
_reset_telemetry_for_tests = _impl._reset_telemetry_for_tests

__all__ = [
    "BatchSpanProcessor",
    "EXPORT_TIMEOUT_MILLIS",
    "EXPORT_TIMEOUT_SECONDS",
    "OTLPSpanExporter",
    "OTLP_TRACES_ENDPOINT",
    "TELEMETRY_ENVIRONMENT_VARIABLE",
    "TracerProvider",
    "add_current_span_event",
    "get_current_span_attributes",
    "initialize_telemetry",
    "resolve_parent_context",
    "run_traced",
    "set_current_span_attributes",
    "shutdown_telemetry",
    "start_child_span",
]


def _sync_patchable_globals() -> None:
    _impl.TracerProvider = TracerProvider  # type: ignore[misc]
    _impl.OTLPSpanExporter = OTLPSpanExporter  # type: ignore[misc]
    _impl.BatchSpanProcessor = BatchSpanProcessor  # type: ignore[misc]
    _impl.TELEMETRY_ENVIRONMENT_VARIABLE = TELEMETRY_ENVIRONMENT_VARIABLE
    _impl.OTLP_TRACES_ENDPOINT = OTLP_TRACES_ENDPOINT
    _impl.EXPORT_TIMEOUT_SECONDS = EXPORT_TIMEOUT_SECONDS
    _impl.EXPORT_TIMEOUT_MILLIS = EXPORT_TIMEOUT_MILLIS
    _impl._SAFE_EXPORT_HEADERS = _SAFE_EXPORT_HEADERS
    _impl._OTEL_EXPORT_LOGGERS = _OTEL_EXPORT_LOGGERS


def initialize_telemetry() -> Tracer:
    _sync_patchable_globals()
    return _impl.initialize_telemetry()


def shutdown_telemetry() -> None:
    _sync_patchable_globals()
    _impl.shutdown_telemetry()
