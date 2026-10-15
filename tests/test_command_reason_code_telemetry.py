"""A failed command's reason code reaches the outcome metric and the root span."""

from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from gh_address_cr.commands.common import (
    emit_scope_resolution_error,
    output_generic_agent_error,
    output_session_error,
    output_workflow_error,
    write_json_summary,
)
from gh_address_cr.commands.final_gate import report_final_gate_error
from gh_address_cr.core import protocol_codes
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

    def test_json_summary_writer_records_its_reason_code(self):
        with (
            self.tracer.start_as_current_span("gh-address-cr.cli"),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            write_json_summary({"status": "FAILED", "reason_code": "COMMAND_SESSION_INPUT_INVALID", "exit_code": 2})

        self.assertIn('"COMMAND_SESSION_INPUT_INVALID"', stdout.getvalue())
        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "COMMAND_SESSION_INPUT_INVALID")

    def test_summary_without_reason_code_keeps_the_recorded_one(self):
        with self.tracer.start_as_current_span("gh-address-cr.cli"), contextlib.redirect_stdout(io.StringIO()):
            note_command_reason_code("STACK_CONTEXT_UNAVAILABLE")
            write_json_summary({"status": "SUCCESS"})

        self.assertEqual(command_reason_code(), "STACK_CONTEXT_UNAVAILABLE")

    def test_human_mode_final_gate_error_still_records_its_reason_code(self):
        with (
            self.tracer.start_as_current_span("gh-address-cr.cli"),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            report_final_gate_error(
                "o/r", "1", "FINAL_GATE_EVALUATION_FAILED", "boom", 5, machine_requested=False
            )

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "FINAL_GATE_EVALUATION_FAILED")

    def test_orchestrator_signal_records_its_reason_code(self):
        from gh_address_cr.orchestrator.harness import _output_signal

        with self.tracer.start_as_current_span("gh-address-cr.cli"), contextlib.redirect_stdout(io.StringIO()):
            _output_signal("FAILED", "PAYLOAD_CORRUPT", "RETRY", "bad payload")

        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "PAYLOAD_CORRUPT")

    def test_submit_feedback_result_records_its_reason_code(self):
        from gh_address_cr.commands.submit_feedback import emit_result

        with self.tracer.start_as_current_span("gh-address-cr.cli"), contextlib.redirect_stdout(io.StringIO()):
            emit_result({"status": "FAILED", "reason_code": "FEEDBACK_REPO_INVALID"}, 2)

        self.assertEqual(self._exported_attributes()[ATTRIBUTE], "FEEDBACK_REPO_INVALID")


class RootSpanReasonCodeTests(unittest.TestCase):
    """Failing commands put their reason code on the root ``gh-address-cr.cli`` span."""

    def _run(self, argv, *patches):
        from gh_address_cr.__main__ import main

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test_root_span_reason_code")
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}))
            stack.enter_context(patch("sys.argv", ["gh-address-cr", *argv]))
            stack.enter_context(patch("gh_address_cr.__main__.initialize_telemetry", return_value=tracer))
            stack.enter_context(patch("gh_address_cr.__main__.shutdown_telemetry"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            for item in patches:
                stack.enter_context(item)
            result = main(argv)
        root = next(span for span in exporter.get_finished_spans() if span.name == "gh-address-cr.cli")
        return result, dict(root.attributes or {})

    def test_agent_resolve_rejection_reaches_the_root_span(self):
        rejection = WorkflowError(
            status="REQUEST_REJECTED",
            reason_code=protocol_codes.STACK_CONTEXT_UNAVAILABLE,
            waiting_on="stack_refresh",
            exit_code=5,
            message="ActionRequest was not issued because known stacked-PR context could not be refreshed.",
        )
        result, attributes = self._run(
            ["agent", "resolve", "octo/example", "7", "PRRT_example", "--commit", "abc1234", "--files", "a.py"],
            patch("gh_address_cr.commands.agent._dispatch_agent_resolve", side_effect=rejection),
        )

        self.assertEqual(result, 5)
        self.assertEqual(attributes[ATTRIBUTE], protocol_codes.STACK_CONTEXT_UNAVAILABLE)

    def test_agent_next_missing_classification_reaches_the_root_span(self):
        rejection = WorkflowError(
            status="REQUEST_REJECTED",
            reason_code=protocol_codes.MISSING_CLASSIFICATION,
            waiting_on="classification",
            exit_code=5,
            message="classify first",
        )
        result, attributes = self._run(
            ["agent", "next", "octo/example", "7", "--role", "fixer"],
            patch("gh_address_cr.core.agent_protocol.issue_action_request", side_effect=rejection),
        )

        self.assertEqual(result, 5)
        self.assertEqual(attributes[ATTRIBUTE], protocol_codes.MISSING_CLASSIFICATION)

    def test_command_session_input_error_reaches_the_root_span(self):
        result, attributes = self._run(["command-session", "--input", "/nonexistent/operations.json"])

        self.assertEqual(result, 2)
        self.assertEqual(attributes[ATTRIBUTE], "COMMAND_SESSION_INPUT_INVALID")

    def test_runtime_incompatibility_reaches_the_root_span(self):
        incompatible = {"status": "INCOMPATIBLE", "reason_code": "RUNTIME_TOO_OLD", "exit_code": 5}
        result, attributes = self._run(
            ["adapter", "check-runtime"],
            patch("gh_address_cr.core.workflow.runtime_compatibility", return_value=incompatible),
        )

        self.assertEqual(result, 5)
        self.assertEqual(attributes[ATTRIBUTE], "RUNTIME_TOO_OLD")


class MachineSummaryChokePointContractTests(unittest.TestCase):
    """Every JSON summary on stdout goes through a writer that records its reason code."""

    # Writers allowed to call sys.stdout.write(json.dumps(...)) directly; each one first
    # calls note_summary_reason_code. The other two keep their established compact format.
    ALLOWED_WRITERS = {
        "commands/common.py": "write_json_summary",
        "orchestrator/harness.py": "_write_payload",
        "commands/submit_feedback.py": "emit_result",
    }
    # Writers whose output is not a summary and carries no reason code.
    NON_SUMMARY_WRITERS = {
        "commands/review_to_findings.py": 1,  # the normalized findings array itself
    }
    STDOUT_JSON = re.compile(r"(?:sys\.stdout\.write|print)\(json\.dumps\(|json\.dump\([^)]*sys\.stdout")

    def test_json_stdout_writes_only_happen_in_reason_code_aware_writers(self):
        package = Path(__file__).resolve().parents[1] / "src" / "gh_address_cr"
        offenders = []
        for path in sorted(package.rglob("*.py")):
            relative = path.relative_to(package).as_posix()
            text = path.read_text(encoding="utf-8")
            count = len(self.STDOUT_JSON.findall(text))
            if relative in self.NON_SUMMARY_WRITERS:
                self.assertEqual(count, self.NON_SUMMARY_WRITERS[relative], relative)
            elif relative in self.ALLOWED_WRITERS:
                writer = self.ALLOWED_WRITERS[relative]
                body = text.split(f"def {writer}(", 1)[1].split("\ndef ", 1)[0]
                self.assertEqual(count, 1, relative)
                self.assertIn("json.dumps(", body, relative)
                self.assertIn("note_summary_reason_code(payload)", body, relative)
            elif count:
                offenders.append(relative)
        self.assertEqual(offenders, [], "route JSON summaries through commands.common.write_json_summary")


if __name__ == "__main__":
    unittest.main()
