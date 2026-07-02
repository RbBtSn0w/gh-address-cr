from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from gh_address_cr.core.otel_semconv import (
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    PROCESS_PARENT_PID,
)
from gh_address_cr.telemetry import run_traced


class TestCliOtelContext(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = TracerProvider()
        self.exporter = InMemorySpanExporter()
        self.processor = SimpleSpanProcessor(self.exporter)
        self.provider.add_span_processor(self.processor)
        self.tracer = self.provider.get_tracer("test_cli_otel_context")

    def tearDown(self) -> None:
        from gh_address_cr import telemetry

        telemetry._reset_telemetry_for_tests()

    def _run_via_main_and_get_span(self):
        """Drive the CLI entrypoint (__main__), which now owns identity/session
        attribute assembly, and return the single exported span."""
        from unittest.mock import patch as _patch

        from gh_address_cr.__main__ import main

        with (
            _patch("sys.argv", ["gh-address-cr"]),
            _patch("gh_address_cr.__main__.cli_main", return_value=0),
            _patch("gh_address_cr.__main__.initialize_telemetry", return_value=self.tracer),
            _patch("gh_address_cr.__main__.shutdown_telemetry"),
        ):
            main([])
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        return spans[0]

    def test_traceparent_env_parenting_valid_uppercase(self) -> None:
        """T010: Test that a valid TRACEPARENT environment variable propagates context parenting."""
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        expected_trace_id = int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
        expected_span_id = int("00f067aa0ba902b7", 16)

        with patch.dict(os.environ, {"TRACEPARENT": traceparent}, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertIsNotNone(span.parent)
        self.assertTrue(span.parent.is_valid)
        self.assertEqual(span.parent.trace_id, expected_trace_id)
        self.assertEqual(span.parent.span_id, expected_span_id)

    def test_traceparent_env_parenting_valid_lowercase(self) -> None:
        """T010: Test that a valid traceparent (lowercase) environment variable propagates context parenting."""
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        expected_trace_id = int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
        expected_span_id = int("00f067aa0ba902b7", 16)

        with patch.dict(os.environ, {"traceparent": traceparent}, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertIsNotNone(span.parent)
        self.assertTrue(span.parent.is_valid)
        self.assertEqual(span.parent.trace_id, expected_trace_id)
        self.assertEqual(span.parent.span_id, expected_span_id)

    def test_traceparent_env_parenting_malformed(self) -> None:
        """T010: Test that a malformed TRACEPARENT is ignored and fails open (creates root span)."""
        malformed_values = [
            "invalid-value",
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",  # missing fields
            "00-4bf92f3577b34da6a3ce929d0e0e473g-00f067aa0ba902b7-01",  # invalid hex 'g'
            "00-4bf92f3577b34da6a3ce929d0e0e47360-00f067aa0ba902b7-01",  # too long trace ID
        ]

        for val in malformed_values:
            self.exporter.clear()
            with patch.dict(os.environ, {"TRACEPARENT": val}, clear=True):
                # Ensure execution succeeds normally
                run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

            spans = self.exporter.get_finished_spans()
            self.assertEqual(len(spans), 1)
            span = spans[0]

            # Fail-open: starts a new root span without parenting
            self.assertTrue(span.parent is None or not span.parent.is_valid)

    def test_traceparent_env_parenting_absent(self) -> None:
        """T010: Test that absent TRACEPARENT creates a fresh root span."""
        with patch.dict(os.environ, {}, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertTrue(span.parent is None or not span.parent.is_valid)

    def test_process_parent_pid_normal(self) -> None:
        """T011: process.parent_pid (assembled by __main__) matches os.getppid()."""
        with patch.dict(os.environ, {}, clear=True):
            span = self._run_via_main_and_get_span()

        self.assertIn(PROCESS_PARENT_PID, span.attributes)
        self.assertEqual(span.attributes[PROCESS_PARENT_PID], os.getppid())

    def test_process_parent_pid_exception(self) -> None:
        """T011: process.parent_pid is omitted (fail-open) if os.getppid raises."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("os.getppid", side_effect=OSError("Permission denied")),
        ):
            span = self._run_via_main_and_get_span()

        self.assertNotIn(PROCESS_PARENT_PID, span.attributes)

    def test_agent_session_correlation_case_a(self) -> None:
        """T012 Case A: CLAUDE_CODE_SESSION_ID and AI_AGENT set (via __main__)."""
        env_vars = {
            "CLAUDE_CODE_SESSION_ID": "test-claude-session-123",
            "AI_AGENT": "claude-cli",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            span = self._run_via_main_and_get_span()

        self.assertEqual(span.attributes.get(GEN_AI_CONVERSATION_ID), "test-claude-session-123")
        self.assertEqual(span.attributes.get("gen_ai.conversation.id.source"), "CLAUDE_CODE_SESSION_ID")
        self.assertEqual(span.attributes.get(GEN_AI_AGENT_NAME), "claude-cli")

    def test_agent_session_correlation_case_b_only_gh(self) -> None:
        """T012 Case B: GH_ADDRESS_CR_CONVERSATION_ID set (via __main__)."""
        env_vars = {
            "GH_ADDRESS_CR_CONVERSATION_ID": "test-gh-session-456",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            span = self._run_via_main_and_get_span()

        self.assertEqual(span.attributes.get(GEN_AI_CONVERSATION_ID), "test-gh-session-456")
        self.assertEqual(span.attributes.get("gen_ai.conversation.id.source"), "GH_ADDRESS_CR_CONVERSATION_ID")
        self.assertNotIn(GEN_AI_AGENT_NAME, span.attributes)

    def test_agent_session_correlation_case_b_both(self) -> None:
        """T012 Case B: GH_ADDRESS_CR_CONVERSATION_ID (override) wins over CLAUDE_CODE_SESSION_ID (via __main__)."""
        env_vars = {
            "GH_ADDRESS_CR_CONVERSATION_ID": "test-gh-session-456",
            "CLAUDE_CODE_SESSION_ID": "test-claude-session-123",
            "AI_AGENT": "claude-cli",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            span = self._run_via_main_and_get_span()

        self.assertEqual(span.attributes.get(GEN_AI_CONVERSATION_ID), "test-gh-session-456")
        self.assertEqual(span.attributes.get("gen_ai.conversation.id.source"), "GH_ADDRESS_CR_CONVERSATION_ID")
        self.assertEqual(span.attributes.get(GEN_AI_AGENT_NAME), "claude-cli")

    def test_agent_session_correlation_case_c(self) -> None:
        """T012 Case C: neither session ID set → attributes absent (via __main__)."""
        with patch.dict(os.environ, {}, clear=True):
            span = self._run_via_main_and_get_span()

        self.assertNotIn(GEN_AI_CONVERSATION_ID, span.attributes)
        self.assertNotIn("gen_ai.conversation.id.source", span.attributes)
        self.assertNotIn(GEN_AI_AGENT_NAME, span.attributes)
