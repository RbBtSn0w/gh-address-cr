from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from gh_address_cr.core.otel_semconv import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    GEN_AI_TOOL_NAME,
    PROCESS_COMMAND_ARGS,
)


class TestCliOtelGenai(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = TracerProvider()
        self.exporter = InMemorySpanExporter()
        self.processor = SimpleSpanProcessor(self.exporter)
        self.provider.add_span_processor(self.processor)
        self.tracer = self.provider.get_tracer("test_cli_otel_genai")

    def tearDown(self) -> None:
        from gh_address_cr import telemetry

        telemetry._reset_telemetry_for_tests()

    def _run_cli_main_and_get_span(self, argv: list[str] | None) -> unittest.TestCase:
        # Patch sys.argv for the duration of the main run
        fake_sys_argv = ["gh-address-cr"]
        if argv is not None:
            fake_sys_argv.extend(argv)

        from gh_address_cr.__main__ import main

        # Mock cli_main to prevent actual command logic execution
        with (
            patch("sys.argv", fake_sys_argv),
            patch("gh_address_cr.__main__.cli_main", return_value=0),
            patch("gh_address_cr.__main__.initialize_telemetry", return_value=self.tracer),
            patch("gh_address_cr.__main__.shutdown_telemetry"),
        ):
            main(argv)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1, "Expected exactly one process span to be exported")
        return spans[0]

    def test_genai_tool_call_attributes_with_subcommand(self) -> None:
        """T017 & T018: Test attributes when command has subcommands (e.g., 'agent submit')."""
        span = self._run_cli_main_and_get_span(["agent", "submit"])
        attributes = span.attributes

        # Assert gen_ai.operation.name is strictly "execute_tool"
        self.assertEqual(attributes.get(GEN_AI_OPERATION_NAME), "execute_tool")

        # Assert gen_ai.tool.name is set to the top-level command token "agent"
        self.assertEqual(attributes.get(GEN_AI_TOOL_NAME), "agent")

        # Assert gen_ai.tool.call.arguments is a valid JSON string of sanitized arguments matching process.command_args
        self.assertIn(GEN_AI_TOOL_CALL_ARGUMENTS, attributes)
        tool_call_args = json.loads(attributes[GEN_AI_TOOL_CALL_ARGUMENTS])
        self.assertIn(PROCESS_COMMAND_ARGS, attributes)
        cmd_args = list(attributes[PROCESS_COMMAND_ARGS])
        self.assertEqual(cmd_args, tool_call_args)

        # Assert gen_ai.tool.call.result is completely absent
        self.assertNotIn(GEN_AI_TOOL_CALL_RESULT, attributes)
        self.assertNotIn("gen_ai.tool.call.result", attributes)

    def test_genai_tool_call_attributes_with_help_long(self) -> None:
        """T017 & T018: Test attributes when command is '--help'."""
        span = self._run_cli_main_and_get_span(["--help"])
        attributes = span.attributes

        self.assertEqual(attributes.get(GEN_AI_OPERATION_NAME), "execute_tool")
        # For help options, it should default to "gh-address-cr"
        self.assertEqual(attributes.get(GEN_AI_TOOL_NAME), "gh-address-cr")

        self.assertIn(GEN_AI_TOOL_CALL_ARGUMENTS, attributes)
        tool_call_args = json.loads(attributes[GEN_AI_TOOL_CALL_ARGUMENTS])
        cmd_args = list(attributes[PROCESS_COMMAND_ARGS])
        self.assertEqual(cmd_args, tool_call_args)

        self.assertNotIn(GEN_AI_TOOL_CALL_RESULT, attributes)

    def test_genai_tool_call_attributes_with_help_short(self) -> None:
        """T017 & T018: Test attributes when command is '-h'."""
        span = self._run_cli_main_and_get_span(["-h"])
        attributes = span.attributes

        self.assertEqual(attributes.get(GEN_AI_OPERATION_NAME), "execute_tool")
        # For help options, it should default to "gh-address-cr"
        self.assertEqual(attributes.get(GEN_AI_TOOL_NAME), "gh-address-cr")

        self.assertNotIn(GEN_AI_TOOL_CALL_RESULT, attributes)

    def test_genai_tool_call_attributes_with_version(self) -> None:
        """T017 & T018: Test attributes when command is '--version'."""
        span = self._run_cli_main_and_get_span(["--version"])
        attributes = span.attributes

        self.assertEqual(attributes.get(GEN_AI_OPERATION_NAME), "execute_tool")
        # For version options, it should default to "gh-address-cr"
        self.assertEqual(attributes.get(GEN_AI_TOOL_NAME), "gh-address-cr")

        self.assertNotIn(GEN_AI_TOOL_CALL_RESULT, attributes)

    def test_genai_tool_call_attributes_with_no_arguments_empty_list(self) -> None:
        """T017 & T018: Test attributes when command has no arguments (empty list)."""
        span = self._run_cli_main_and_get_span([])
        attributes = span.attributes

        self.assertEqual(attributes.get(GEN_AI_OPERATION_NAME), "execute_tool")
        # For no arguments, it should default to "gh-address-cr"
        self.assertEqual(attributes.get(GEN_AI_TOOL_NAME), "gh-address-cr")

        self.assertNotIn(GEN_AI_TOOL_CALL_RESULT, attributes)

    def test_genai_tool_call_attributes_with_no_arguments_none(self) -> None:
        """T017 & T018: Test attributes when command has no arguments (None)."""
        span = self._run_cli_main_and_get_span(None)
        attributes = span.attributes

        self.assertEqual(attributes.get(GEN_AI_OPERATION_NAME), "execute_tool")
        # For no arguments, it should default to "gh-address-cr"
        self.assertEqual(attributes.get(GEN_AI_TOOL_NAME), "gh-address-cr")

        self.assertNotIn(GEN_AI_TOOL_CALL_RESULT, attributes)

    def test_pr_owner_repo_redacted_from_all_span_attributes(self) -> None:
        """T029/C-12: a PR-scoped run must not leak the plain owner/repo in ANY
        span attribute (command_args / tool.call.arguments), only the hashed
        vcs.repository.name. The redacted repo slot preserves position."""
        span = self._run_cli_main_and_get_span(["review", "acme-corp/secret-widgets", "123"])
        attributes = span.attributes

        # No plain owner/repo/URL anywhere on the span
        for value in attributes.values():
            value_str = str(value)
            self.assertNotIn("acme-corp", value_str)
            self.assertNotIn("secret-widgets", value_str)
            self.assertNotIn("github.com", value_str)

        # command_args still carries the command + PR number + redacted repo slot
        cmd_args = list(attributes[PROCESS_COMMAND_ARGS])
        self.assertIn("review", cmd_args)
        self.assertIn("123", cmd_args)
        self.assertIn("[redacted]", cmd_args)
        # tool.call.arguments still equals command_args (shared sanitized value)
        self.assertEqual(cmd_args, json.loads(attributes[GEN_AI_TOOL_CALL_ARGUMENTS]))
        # the PR is still identifiable via the hashed repo + PR number
        self.assertEqual(attributes.get("vcs.change.id"), "123")
        self.assertEqual(len(attributes.get("vcs.repository.name")), 64)


if __name__ == "__main__":
    unittest.main()
