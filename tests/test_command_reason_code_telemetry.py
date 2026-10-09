"""A failed command's reason code reaches the outcome metric and the root span."""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from gh_address_cr.commands.common import (
    emit_scope_resolution_error,
    output_generic_agent_error,
    output_session_error,
    output_workflow_error,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.telemetry_runtime import (
    command_reason_code,
    note_command_reason_code,
    reset_command_reason_code,
)

ATTRIBUTE = "gh_address_cr.command.reason_code"


class CommandReasonCodeTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = provider.get_tracer("test_command_reason_code_telemetry")
        reset_command_reason_code()
        self.addCleanup(reset_command_reason_code)

    def _exported_attributes(self):
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        return dict(spans[0].attributes or {})

    def test_enum_reason_code_is_exported_on_the_current_span(self):
        with self.tracer.start_as_current_span("gh-address-cr.cli"):
            note_command_reason_code("COMMIT_NOT_IN_PR")

        self.assertEqual(command_reason_code(), "COMMIT_NOT_IN_PR")
        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "COMMIT_NOT_IN_PR")

    def test_non_enum_text_is_kept_for_the_metric_but_never_exported(self):
        with self.tracer.start_as_current_span("gh-address-cr.cli"):
            note_command_reason_code("free text with /Users/someone/path")

        self.assertNotIn(ATTRIBUTE, self._exported_attributes())

    def test_missing_reason_code_exports_nothing(self):
        with self.tracer.start_as_current_span("gh-address-cr.cli"):
            note_command_reason_code(None)

        self.assertNotIn(ATTRIBUTE, self._exported_attributes())

    def test_workflow_error_output_records_its_reason_code(self):
        error = WorkflowError(
            status="PUBLISH_BLOCKED",
            reason_code="COMMIT_NOT_IN_PR",
            waiting_on="commit_evidence",
            exit_code=5,
            message="blocked",
        )

        with (
            self.tracer.start_as_current_span("gh-address-cr.cli"),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = output_workflow_error(error, repo="o/r", pr_number="1")

        self.assertEqual(exit_code, 5)
        self.assertEqual(command_reason_code(), "COMMIT_NOT_IN_PR")
        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "COMMIT_NOT_IN_PR")

    def test_generic_agent_error_output_records_its_reason_code(self):
        with (
            self.tracer.start_as_current_span("gh-address-cr.cli"),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = output_generic_agent_error("o/r", "1", "SESSION_NOT_FOUND", "no session")

        self.assertEqual(exit_code, 5)
        self.assertEqual(command_reason_code(), "SESSION_NOT_FOUND")
        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "SESSION_NOT_FOUND")

    def test_session_error_output_records_the_guidance_reason_code(self):
        guidance = {"reason_code": "PERSISTENCE_BUSY", "next_action": "retry", "waiting_on": "runtime_store"}

        with (
            patch("gh_address_cr.core.session.session_error_guidance", return_value=guidance),
            patch("gh_address_cr.commands.common.remediation_for", return_value=None),
            self.tracer.start_as_current_span("gh-address-cr.cli"),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = output_session_error(RuntimeError("busy"), repo="o/r", pr_number="1")

        self.assertEqual(exit_code, 5)
        self.assertEqual(command_reason_code(), "PERSISTENCE_BUSY")
        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "PERSISTENCE_BUSY")

    def test_scope_resolution_error_records_its_reason_code(self):
        payload = {"status": "PR_SCOPE_UNRESOLVED", "reason_code": "PARTIAL_PR_SCOPE", "next_action": "pass both", "exit_code": 2}

        with (
            self.tracer.start_as_current_span("gh-address-cr.cli"),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = emit_scope_resolution_error(payload)

        self.assertEqual(exit_code, 2)
        self.assertEqual(command_reason_code(), "PARTIAL_PR_SCOPE")
        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "PARTIAL_PR_SCOPE")


if __name__ == "__main__":
    unittest.main()
