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
        """T011: Test process.parent_pid attribute matches os.getppid()."""
        with patch.dict(os.environ, {}, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertIn(PROCESS_PARENT_PID, span.attributes)
        self.assertEqual(span.attributes[PROCESS_PARENT_PID], os.getppid())

    def test_process_parent_pid_exception(self) -> None:
        """T011: Test process.parent_pid attribute is omitted if os.getppid raises exception."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("os.getppid", side_effect=OSError("Permission denied")),
        ):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertNotIn(PROCESS_PARENT_PID, span.attributes)

    def test_agent_session_correlation_case_a(self) -> None:
        """T012 Case A: Test attributes when CLAUDE_CODE_SESSION_ID and AI_AGENT are set."""
        env_vars = {
            "CLAUDE_CODE_SESSION_ID": "test-claude-session-123",
            "AI_AGENT": "claude-cli",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertEqual(span.attributes.get(GEN_AI_CONVERSATION_ID), "test-claude-session-123")
        self.assertEqual(span.attributes.get("gen_ai.conversation.id.source"), "CLAUDE_CODE_SESSION_ID")
        self.assertEqual(span.attributes.get(GEN_AI_AGENT_NAME), "claude-cli")

    def test_agent_session_correlation_case_b_only_gh(self) -> None:
        """T012 Case B: Test attributes when GH_ADDRESS_CR_CONVERSATION_ID is set."""
        env_vars = {
            "GH_ADDRESS_CR_CONVERSATION_ID": "test-gh-session-456",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertEqual(span.attributes.get(GEN_AI_CONVERSATION_ID), "test-gh-session-456")
        self.assertEqual(span.attributes.get("gen_ai.conversation.id.source"), "GH_ADDRESS_CR_CONVERSATION_ID")
        self.assertNotIn(GEN_AI_AGENT_NAME, span.attributes)

    def test_agent_session_correlation_case_b_both(self) -> None:
        """T012 Case B: Test GH_ADDRESS_CR_CONVERSATION_ID takes precedence over CLAUDE_CODE_SESSION_ID."""
        env_vars = {
            "GH_ADDRESS_CR_CONVERSATION_ID": "test-gh-session-456",
            "CLAUDE_CODE_SESSION_ID": "test-claude-session-123",
            "AI_AGENT": "claude-cli",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertEqual(span.attributes.get(GEN_AI_CONVERSATION_ID), "test-gh-session-456")
        self.assertEqual(span.attributes.get("gen_ai.conversation.id.source"), "GH_ADDRESS_CR_CONVERSATION_ID")
        # gen_ai.agent.name can still be recorded if AI_AGENT is set
        self.assertEqual(span.attributes.get(GEN_AI_AGENT_NAME), "claude-cli")

    def test_agent_session_correlation_case_c(self) -> None:
        """T012 Case C: Test attributes when neither session ID is set."""
        with patch.dict(os.environ, {}, clear=True):
            run_traced(self.tracer, "gh-address-cr.cli", lambda: None)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        span = spans[0]

        self.assertNotIn(GEN_AI_CONVERSATION_ID, span.attributes)
        self.assertNotIn("gen_ai.conversation.id.source", span.attributes)
        self.assertNotIn(GEN_AI_AGENT_NAME, span.attributes)
