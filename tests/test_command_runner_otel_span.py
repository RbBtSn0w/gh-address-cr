from __future__ import annotations

import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from gh_address_cr.core.command_runner import run_cmd
from gh_address_cr.core.otel_semconv import (
    ERROR_TYPE,
    GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_EXIT_CODE,
    PROCESS_PID,
)
from gh_address_cr.telemetry import run_traced


class TestCommandRunnerCallerSpan(unittest.TestCase):
    """Aligns the gh_address_cr.subprocess span with the OTel CLI spans
    'Client (caller) spans' convention: CLIENT kind, process identity, and
    error.type on a genuine non-zero exit from the invoked executable."""

    def setUp(self) -> None:
        self.provider = TracerProvider()
        self.exporter = InMemorySpanExporter()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("test_command_runner_otel_span")

    def _subprocess_span(self):
        spans = self.exporter.get_finished_spans()
        return next(span for span in spans if span.name == GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME)

    def test_successful_command_records_client_kind_and_pid_without_error_type(self) -> None:
        run_traced(self.tracer, "gh-address-cr.cli", lambda: run_cmd(["true"]))

        span = self._subprocess_span()
        self.assertEqual(span.kind, SpanKind.CLIENT)
        self.assertIn(PROCESS_PID, span.attributes)
        self.assertIsInstance(span.attributes[PROCESS_PID], int)
        self.assertEqual(span.attributes[PROCESS_EXECUTABLE_NAME], "true")
        self.assertEqual(span.attributes[PROCESS_EXIT_CODE], 0)
        self.assertNotIn(ERROR_TYPE, span.attributes)

    def test_nonzero_exit_records_error_type(self) -> None:
        with patch("gh_address_cr.core.command_runner.is_transient_gh_failure", return_value=False):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: run_cmd(["false"], retries=1))

        span = self._subprocess_span()
        self.assertEqual(span.attributes[PROCESS_EXIT_CODE], 1)
        self.assertEqual(span.attributes[ERROR_TYPE], "1")

    def test_timeout_records_timeout_error_type_and_exit_124(self) -> None:
        run_traced(
            self.tracer,
            "gh-address-cr.cli",
            lambda: run_cmd(["sleep", "5"], retries=1, timeout=0.05),
        )

        span = self._subprocess_span()
        self.assertEqual(span.attributes[PROCESS_EXIT_CODE], 124)
        self.assertEqual(span.attributes[ERROR_TYPE], "timeout")


if __name__ == "__main__":
    unittest.main()
