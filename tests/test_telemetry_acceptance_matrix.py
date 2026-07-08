from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class LayeredTelemetryAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("layered_telemetry_acceptance")

    def tearDown(self) -> None:
        from gh_address_cr import telemetry

        telemetry._reset_telemetry_for_tests()

    def test_adapter_execution_emits_child_span_under_root_invocation(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.commands.high_level import _run_adapter_command

        completed = MagicMock(returncode=0, stdout='{"findings":[]}', stderr="")
        with patch("gh_address_cr.commands.high_level.subprocess.run", return_value=completed):
            result = telemetry.run_traced(
                self.tracer,
                "gh-address-cr.cli",
                lambda: _run_adapter_command(["python3", "-c", "print('ok')"]),
                attributes={"gh_address_cr.command.name": "adapter"},
            )

        self.assertEqual(result, ('{"findings":[]}', None))
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        root_span = next(span for span in spans if span.name == "gh-address-cr.cli")
        adapter_span = next(span for span in spans if span.name == "gh_address_cr.adapter")
        self.assertEqual(adapter_span.parent.span_id, root_span.context.span_id)
        self.assertEqual(adapter_span.attributes["gh_address_cr.adapter.command_label"], "python3")
        self.assertEqual(adapter_span.attributes["gh_address_cr.adapter.exit_code"], 0)

    def test_high_level_phases_remain_events_on_root_span(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.commands.high_level import HighLevelReviewRuntime

        runtime = HighLevelReviewRuntime()
        fake_session = {
            "items": [],
            "local_findings": [],
            "remote_threads": [],
            "metrics": {},
            "loop_state": {},
        }
        fake_result = MagicMock(passed=True)
        fake_result.to_machine_summary.return_value = {"next_action": "No action required."}
        with (
            patch("gh_address_cr.commands.high_level._load_or_create_session", return_value=fake_session),
            patch("gh_address_cr.commands.high_level._set_loop_state"),
            patch("gh_address_cr.commands.high_level._recalc_native_metrics"),
            patch("gh_address_cr.commands.high_level.session_store.save_session"),
            patch("gh_address_cr.commands.high_level._emit_native_summary"),
            patch.object(HighLevelReviewRuntime, "_ingest_and_load_threads", return_value=(fake_session, [])),
            patch("gh_address_cr.commands.high_level.core_gate.evaluate_final_gate", return_value=fake_result),
        ):
            result = telemetry.run_traced(
                self.tracer,
                "gh-address-cr.cli",
                lambda: runtime.handle("review", ["owner/repo", "123"], human=False, lean=False),
                attributes={"gh_address_cr.command.name": "review"},
            )

        self.assertEqual(result, 0)
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        root_span = spans[0]
        event_names = [event.name for event in root_span.events]
        self.assertIn("gh_address_cr.high_level.phase.start", event_names)
        self.assertIn("gh_address_cr.high_level.phase.end", event_names)

    def test_command_session_operation_emits_child_span_and_keeps_summary_event(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.commands.command_session import handle_command_session

        payload = {"operations": [{"id": "op-1", "argv": ["version"]}]}
        with tempfile.TemporaryDirectory() as temp_dir:
            request_path = Path(temp_dir) / "command-session.json"
            request_path.write_text(json.dumps(payload), encoding="utf-8")

            result = telemetry.run_traced(
                self.tracer,
                "gh-address-cr.cli",
                lambda: handle_command_session(["--input", str(request_path)]),
                attributes={"gh_address_cr.command.name": "command-session"},
            )

        self.assertEqual(result, 0)
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        root_span = next(span for span in spans if span.name == "gh-address-cr.cli")
        operation_span = next(span for span in spans if span.name == "gh_address_cr.command_session.operation")
        self.assertEqual(operation_span.parent.span_id, root_span.context.span_id)
        self.assertEqual(operation_span.attributes["gh_address_cr.command_session.operation_id"], "op-1")
        self.assertEqual([event.name for event in root_span.events], ["gh_address_cr.command_session.summary"])

    def test_run_cmd_emits_subprocess_child_span_with_command_attribution(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.core.command_runner import run_cmd
        from gh_address_cr.core.otel_semconv import (
            GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME,
            PROCESS_COMMAND_ARGS,
            PROCESS_EXIT_CODE,
        )

        process = MagicMock(pid=4321, returncode=0)
        process.communicate.return_value = ("{}", "")
        with patch("gh_address_cr.core.command_runner.subprocess.Popen", return_value=process):
            result = telemetry.run_traced(
                self.tracer,
                "gh-address-cr.cli",
                lambda: run_cmd(["gh", "api", "graphql"]),
                attributes={"gh_address_cr.command.name": "address"},
            )

        self.assertEqual(result.returncode, 0)
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        root_span = next(span for span in spans if span.name == "gh-address-cr.cli")
        subprocess_span = next(span for span in spans if span.name == GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME)
        self.assertEqual(subprocess_span.parent.span_id, root_span.context.span_id)
        self.assertEqual(subprocess_span.attributes["gh_address_cr.subprocess.command_label"], "gh api")
        self.assertEqual(list(subprocess_span.attributes[PROCESS_COMMAND_ARGS]), ["gh", "api", "graphql"])
        self.assertEqual(subprocess_span.attributes[PROCESS_EXIT_CODE], 0)
        start_event = next(event for event in root_span.events if event.name == "gh_address_cr.subprocess.start")
        self.assertEqual(list(start_event.attributes["gh_address_cr.subprocess.command_args"]), ["gh", "api", "graphql"])
        end_event = next(event for event in root_span.events if event.name == "gh_address_cr.subprocess.end")
        self.assertEqual(end_event.attributes["gh_address_cr.subprocess.exit_code"], 0)

    def test_high_level_preflight_emits_cli_init_child_span_before_runtime_handle(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.cli import main
        from gh_address_cr.core.otel_semconv import GH_ADDRESS_CR_CLI_INIT_SPAN_NAME, PROCESS_COMMAND_ARGS

        stdout = StringIO()
        with (
            patch("gh_address_cr.cli.preflight_high_level", return_value=None),
            patch("gh_address_cr.cli.handle_native_high_level", return_value=0),
            redirect_stdout(stdout),
        ):
            result = telemetry.run_traced(
                self.tracer,
                "gh-address-cr.cli",
                lambda: main(["review", "owner/repo", "123"]),
                attributes={"gh_address_cr.command.name": "review"},
            )

        self.assertEqual(result, 0)
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        root_span = next(span for span in spans if span.name == "gh-address-cr.cli")
        init_span = next(span for span in spans if span.name == GH_ADDRESS_CR_CLI_INIT_SPAN_NAME)
        self.assertEqual(init_span.parent.span_id, root_span.context.span_id)
        self.assertEqual(init_span.attributes["gh_address_cr.command.name"], "review")
        self.assertEqual(list(init_span.attributes[PROCESS_COMMAND_ARGS]), ["review", "[redacted]", "123"])
        self.assertEqual(init_span.attributes["gh_address_cr.cli.init.exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
