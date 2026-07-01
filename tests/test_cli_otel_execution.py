from __future__ import annotations

import os
import sys
import unittest

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from gh_address_cr.core.otel_semconv import (
    ERROR_TYPE,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_EXIT_CODE,
    PROCESS_PID,
)
from gh_address_cr.telemetry import run_traced


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

    def test_propagated_exception_keyboard_interrupt_records_error_and_synthetic_exit_code(self) -> None:
        """T005: Test a KeyboardInterrupt exception propagated by run_traced records status ERROR, process.exit.code 1, and error.type 'keyboard_interrupt'."""
        def dummy_operation() -> None:
            raise KeyboardInterrupt("interrupt")

        with self.assertRaises(KeyboardInterrupt):
            run_traced(
                self.tracer,
                "gh-address-cr.cli",
                dummy_operation,
            )

        exported_spans = self.exporter.get_finished_spans()
        self.assertEqual(len(exported_spans), 1)
        span = exported_spans[0]

        attributes = span.attributes
        self.assertEqual(attributes.get(PROCESS_EXIT_CODE), 1)
        self.assertEqual(attributes.get(ERROR_TYPE), "keyboard_interrupt")
        self.assertEqual(span.status.status_code, StatusCode.ERROR)

    def test_propagated_exception_timeout_records_error_and_synthetic_exit_code(self) -> None:
        """T005: Test a TimeoutError exception propagated by run_traced records status ERROR, process.exit.code 1, and error.type 'timeout'."""
        def dummy_operation() -> None:
            raise TimeoutError("timeout occurred")

        with self.assertRaises(TimeoutError):
            run_traced(
                self.tracer,
                "gh-address-cr.cli",
                dummy_operation,
            )

        exported_spans = self.exporter.get_finished_spans()
        self.assertEqual(len(exported_spans), 1)
        span = exported_spans[0]

        attributes = span.attributes
        self.assertEqual(attributes.get(PROCESS_EXIT_CODE), 1)
        self.assertEqual(attributes.get(ERROR_TYPE), "timeout")
        self.assertEqual(span.status.status_code, StatusCode.ERROR)

    def test_propagated_exception_other_records_error_and_synthetic_exit_code(self) -> None:
        """T005: Test a ValueError exception propagated by run_traced records status ERROR, process.exit.code 1, and error.type '_OTHER'."""
        def dummy_operation() -> None:
            raise ValueError("some other error")

        with self.assertRaises(ValueError):
            run_traced(
                self.tracer,
                "gh-address-cr.cli",
                dummy_operation,
            )

        exported_spans = self.exporter.get_finished_spans()
        self.assertEqual(len(exported_spans), 1)
        span = exported_spans[0]

        attributes = span.attributes
        self.assertEqual(attributes.get(PROCESS_EXIT_CODE), 1)
        self.assertEqual(attributes.get(ERROR_TYPE), "_OTHER")
        self.assertEqual(span.status.status_code, StatusCode.ERROR)

    def test_nonzero_status_return_records_exit_code_without_error_type(self) -> None:
        """T005: Test that a non-zero status return from a dummy operation records exit code but no error.type or ERROR status."""
        def dummy_operation() -> int:
            return 6

        result = run_traced(
            self.tracer,
            "gh-address-cr.cli",
            dummy_operation,
        )

        self.assertEqual(result, 6)

        exported_spans = self.exporter.get_finished_spans()
        self.assertEqual(len(exported_spans), 1)
        span = exported_spans[0]

        attributes = span.attributes
        self.assertEqual(attributes.get(PROCESS_EXIT_CODE), 6)
        self.assertNotIn(ERROR_TYPE, attributes)
        self.assertNotEqual(span.status.status_code, StatusCode.ERROR)

    def test_system_exit_zero_records_success(self) -> None:
        """T005: Test that SystemExit with code 0 propagates and records exit code 0 without error.type."""
        def dummy_operation() -> None:
            raise SystemExit(0)

        with self.assertRaises(SystemExit) as context:
            run_traced(
                self.tracer,
                "gh-address-cr.cli",
                dummy_operation,
            )
        self.assertEqual(context.exception.code, 0)

        exported_spans = self.exporter.get_finished_spans()
        self.assertEqual(len(exported_spans), 1)
        span = exported_spans[0]

        attributes = span.attributes
        self.assertEqual(attributes.get(PROCESS_EXIT_CODE), 0)
        self.assertNotIn(ERROR_TYPE, attributes)
        self.assertNotEqual(span.status.status_code, StatusCode.ERROR)

    def test_system_exit_nonzero_records_status_without_error_type(self) -> None:
        """T005: Test that SystemExit with a non-zero code propagates and records exit code but no error.type or ERROR status."""
        def dummy_operation() -> None:
            raise SystemExit(2)

        with self.assertRaises(SystemExit) as context:
            run_traced(
                self.tracer,
                "gh-address-cr.cli",
                dummy_operation,
            )
        self.assertEqual(context.exception.code, 2)

        exported_spans = self.exporter.get_finished_spans()
        self.assertEqual(len(exported_spans), 1)
        span = exported_spans[0]

        attributes = span.attributes
        self.assertEqual(attributes.get(PROCESS_EXIT_CODE), 2)
        self.assertNotIn(ERROR_TYPE, attributes)
        self.assertNotEqual(span.status.status_code, StatusCode.ERROR)


if __name__ == "__main__":
    unittest.main()
