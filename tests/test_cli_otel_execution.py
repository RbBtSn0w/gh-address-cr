from __future__ import annotations

import os
import sys
import unittest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from gh_address_cr.telemetry import run_traced
from gh_address_cr.core.otel_semconv import (
    ERROR_TYPE,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_EXIT_CODE,
    PROCESS_PID,
)


class TestCliOtelExecution(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = TracerProvider()
        self.exporter = InMemorySpanExporter()
        self.processor = SimpleSpanProcessor(self.exporter)
        self.provider.add_span_processor(self.processor)
        self.tracer = self.provider.get_tracer("test_cli_otel_execution")

    def test_successful_run_records_execution_identity_and_success_status(self) -> None:
        """T004: Test a successful execution of a function wrapped by run_traced records execution identity and success status."""
        def dummy_operation() -> str:
            return "success"

        result = run_traced(
            self.tracer,
            "gh-address-cr.cli",
            dummy_operation,
        )

        self.assertEqual(result, "success")

        exported_spans = self.exporter.get_finished_spans()
        self.assertEqual(len(exported_spans), 1)
        span = exported_spans[0]

        # Assert basic span fields
        self.assertEqual(span.name, "gh-address-cr.cli")
        self.assertEqual(span.kind, SpanKind.INTERNAL)

        # Assert execution identity attributes
        attributes = span.attributes
        self.assertIn(PROCESS_EXECUTABLE_NAME, attributes)
        self.assertEqual(attributes[PROCESS_EXECUTABLE_NAME], os.path.basename(sys.executable))

        self.assertIn(PROCESS_PID, attributes)
        self.assertEqual(attributes[PROCESS_PID], os.getpid())
        self.assertIsInstance(attributes[PROCESS_PID], int)

        # Assert success exit code
        self.assertIn(PROCESS_EXIT_CODE, attributes)
        self.assertEqual(attributes[PROCESS_EXIT_CODE], 0)

        # Assert error.type is absent on success
        self.assertNotIn(ERROR_TYPE, attributes)


if __name__ == "__main__":
    unittest.main()
