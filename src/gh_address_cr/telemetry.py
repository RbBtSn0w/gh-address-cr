"""Public tracing façade for the gh-address-cr CLI.

The implementation lives in `otel_tracing.py`. This module is the documented
import path for embedders (see the telemetry section of `README.md`) and
re-exports the public tracing API only. Implementation details — the OTel SDK
classes, exporter constants, and test-only reset helpers — stay private to
`otel_tracing.py`; reach for them there, not through this façade.
"""

from __future__ import annotations

from gh_address_cr.otel_tracing import (
    add_current_span_event,
    get_current_span_attributes,
    initialize_telemetry,
    resolve_parent_context,
    run_traced,
    set_current_span_attributes,
    shutdown_telemetry,
    start_child_span,
)

__all__ = [
    "add_current_span_event",
    "get_current_span_attributes",
    "initialize_telemetry",
    "resolve_parent_context",
    "run_traced",
    "set_current_span_attributes",
    "shutdown_telemetry",
    "start_child_span",
]
