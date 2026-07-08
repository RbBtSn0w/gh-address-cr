from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

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
        # Success: span status must NOT be ERROR.
        self.assertNotEqual(span.status.status_code, StatusCode.ERROR)

    def test_nonzero_exit_records_error_type_and_error_status(self) -> None:
        with patch("gh_address_cr.core.command_runner.is_transient_gh_failure", return_value=False):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: run_cmd(["false"], retries=1))

        span = self._subprocess_span()
        self.assertEqual(span.attributes[PROCESS_EXIT_CODE], 1)
        self.assertEqual(span.attributes[ERROR_TYPE], "1")
        # Per CLI spans semconv, exit.code != 0 => span status ERROR.
        self.assertEqual(span.status.status_code, StatusCode.ERROR)

    def test_timeout_records_timeout_error_type_and_error_status(self) -> None:
        run_traced(
            self.tracer,
            "gh-address-cr.cli",
            lambda: run_cmd(["sleep", "5"], retries=1, timeout=0.05),
        )

        span = self._subprocess_span()
        self.assertEqual(span.attributes[PROCESS_EXIT_CODE], 124)
        self.assertEqual(span.attributes[ERROR_TYPE], "timeout")
        self.assertEqual(span.status.status_code, StatusCode.ERROR)

    def test_transient_timeout_then_success_leaves_no_error_residue(self) -> None:
        """A gh command that times out once then succeeds on retry must not
        leave error.type/ERROR status on the final exit.code == 0 span."""
        real_run_cmd = run_cmd
        timed_out = subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=0.05)
        first = MagicMock()
        first.pid = 111
        # First communicate() times out; the post-kill drain call returns.
        first.communicate.side_effect = [timed_out, ("", "")]
        second = MagicMock()
        second.pid = 222
        second.returncode = 0
        second.communicate.return_value = ("{}", "")

        with (
            patch("gh_address_cr.core.command_runner.subprocess.Popen", side_effect=[first, second]),
            patch("gh_address_cr.core.command_runner.time.sleep"),
        ):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: real_run_cmd(["gh", "api"], retries=2))

        span = self._subprocess_span()
        self.assertEqual(span.attributes[PROCESS_EXIT_CODE], 0)
        self.assertNotIn(ERROR_TYPE, span.attributes)
        self.assertNotEqual(span.status.status_code, StatusCode.ERROR)

    def test_timeout_kill_oserror_still_returns_124_without_crashing(self) -> None:
        """If process.kill() races the process exit and raises OSError, run_cmd
        must still return a 124 timed-out result rather than propagating."""
        timed_out = subprocess.TimeoutExpired(cmd=["sleep", "5"], timeout=0.05)
        process = MagicMock()
        process.pid = 999
        process.communicate.side_effect = [timed_out, ("", "")]
        process.kill.side_effect = ProcessLookupError("no such process")

        with patch("gh_address_cr.core.command_runner.subprocess.Popen", return_value=process):
            result = run_traced(
                self.tracer,
                "gh-address-cr.cli",
                lambda: run_cmd(["sleep", "5"], retries=1, timeout=0.05),
            )

        self.assertEqual(result.returncode, 124)
        span = self._subprocess_span()
        self.assertEqual(span.attributes[PROCESS_EXIT_CODE], 124)
        self.assertEqual(span.status.status_code, StatusCode.ERROR)


if __name__ == "__main__":
    unittest.main()
