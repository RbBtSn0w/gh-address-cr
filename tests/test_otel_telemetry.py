from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class OpenTelemetryInitializationTests(unittest.TestCase):
    def tearDown(self) -> None:
        from gh_address_cr import telemetry

        telemetry._reset_telemetry_for_tests()

    def test_opt_out_returns_noop_tracer_without_creating_exporter(self) -> None:
        from gh_address_cr import telemetry

        with (
            patch.dict(os.environ, {"DISABLE_TELEMETRY": "1"}, clear=True),
            patch.object(telemetry, "OTLPSpanExporter") as exporter,
        ):
            tracer = telemetry.initialize_telemetry()

        self.assertEqual(type(tracer).__name__, "NoOpTracer")
        exporter.assert_not_called()

    def test_do_not_track_returns_noop_tracer(self) -> None:
        from gh_address_cr import telemetry

        with patch.dict(os.environ, {"DO_NOT_TRACK": "1"}, clear=True):
            tracer = telemetry.initialize_telemetry()

        self.assertEqual(type(tracer).__name__, "NoOpTracer")

    def test_initialization_configures_product_resource_and_gateway(self) -> None:
        from gh_address_cr import telemetry

        provider = MagicMock()
        tracer = MagicMock()
        provider.get_tracer.return_value = tracer

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(telemetry, "TracerProvider", return_value=provider) as provider_type,
            patch.object(telemetry, "OTLPSpanExporter") as exporter_type,
            patch.object(telemetry, "BatchSpanProcessor") as processor_type,
        ):
            result = telemetry.initialize_telemetry()

        self.assertIs(result, tracer)
        resource = provider_type.call_args.kwargs["resource"]
        self.assertEqual(resource.attributes["service.name"], "gh-address-cr")
        exporter_type.assert_called_once()
        exporter_arguments = exporter_type.call_args.kwargs
        self.assertEqual(exporter_arguments["endpoint"], telemetry.OTLP_TRACES_ENDPOINT)
        self.assertEqual(exporter_arguments["timeout"], telemetry.EXPORT_TIMEOUT_SECONDS)
        self.assertEqual(exporter_arguments["headers"], telemetry._SAFE_EXPORT_HEADERS)
        self.assertFalse(exporter_arguments["session"].trust_env)
        processor_type.assert_called_once_with(
            exporter_type.return_value,
            export_timeout_millis=telemetry.EXPORT_TIMEOUT_MILLIS,
        )
        provider.add_span_processor.assert_called_once_with(processor_type.return_value)

    def test_test_environment_uses_isolated_service_name(self) -> None:
        from gh_address_cr import telemetry

        provider = MagicMock()
        provider.get_tracer.return_value = MagicMock()
        with (
            patch.dict(os.environ, {telemetry.TELEMETRY_ENVIRONMENT_VARIABLE: "test"}, clear=True),
            patch.object(telemetry, "TracerProvider", return_value=provider) as provider_type,
            patch.object(telemetry, "OTLPSpanExporter"),
            patch.object(telemetry, "BatchSpanProcessor"),
        ):
            telemetry.initialize_telemetry()

        resource = provider_type.call_args.kwargs["resource"]
        self.assertEqual(resource.attributes["service.name"], "gh-address-cr-test")

    def test_initialization_does_not_inherit_ambient_otlp_credentials(self) -> None:
        from gh_address_cr import telemetry

        provider = MagicMock()
        provider.get_tracer.return_value = MagicMock()
        ambient_credentials = {
            "OTEL_EXPORTER_OTLP_HEADERS": "authorization=Bearer%20global-secret",
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "x-api-key=trace-secret",
            "OTEL_PYTHON_EXPORTER_OTLP_HTTP_TRACES_CREDENTIAL_PROVIDER": "invalid.module:provider",
        }

        with (
            patch.dict(os.environ, ambient_credentials, clear=True),
            patch.object(telemetry, "TracerProvider", return_value=provider),
            patch.object(telemetry, "BatchSpanProcessor") as processor_type,
        ):
            telemetry.initialize_telemetry()

        exporter = processor_type.call_args.args[0]
        request_headers = {key.lower(): value for key, value in exporter._session.headers.items()}
        self.assertNotIn("authorization", request_headers)
        self.assertNotIn("x-api-key", request_headers)
        self.assertEqual(request_headers["x-gh-address-cr-telemetry"], "1")
        self.assertFalse(exporter._session.trust_env)

    def test_shutdown_flushes_provider_once(self) -> None:
        from gh_address_cr import telemetry

        provider = MagicMock()
        provider.get_tracer.return_value = MagicMock()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(telemetry, "TracerProvider", return_value=provider),
            patch.object(telemetry, "OTLPSpanExporter"),
            patch.object(telemetry, "BatchSpanProcessor"),
        ):
            telemetry.initialize_telemetry()
            telemetry.shutdown_telemetry()
            telemetry.shutdown_telemetry()

        provider.shutdown.assert_called_once_with()

    def test_shutdown_returns_within_fail_open_budget_when_provider_blocks(self) -> None:
        from gh_address_cr import telemetry

        shutdown_started = threading.Event()
        release_shutdown = threading.Event()
        provider = MagicMock()
        provider.get_tracer.return_value = MagicMock()

        def block_shutdown() -> None:
            shutdown_started.set()
            release_shutdown.wait(timeout=2)

        provider.shutdown.side_effect = block_shutdown
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(telemetry, "TracerProvider", return_value=provider),
            patch.object(telemetry, "OTLPSpanExporter"),
            patch.object(telemetry, "BatchSpanProcessor"),
        ):
            telemetry.initialize_telemetry()
            started_at = time.monotonic()
            telemetry.shutdown_telemetry()
            elapsed = time.monotonic() - started_at

        self.assertTrue(shutdown_started.wait(timeout=0.1))
        self.assertLess(elapsed, 0.5)
        release_shutdown.set()

    def test_initialization_keeps_exporter_failures_off_stderr(self) -> None:
        from gh_address_cr import telemetry

        provider = MagicMock()
        provider.get_tracer.return_value = MagicMock()
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(telemetry, "TracerProvider", return_value=provider),
            patch.object(telemetry, "OTLPSpanExporter"),
            patch.object(telemetry, "BatchSpanProcessor"),
            contextlib.redirect_stderr(stderr),
        ):
            telemetry.initialize_telemetry()
            for logger_name in telemetry._OTEL_EXPORT_LOGGERS:
                logging.getLogger(logger_name).error("Failed to export span batch: token=secret")

        self.assertEqual(stderr.getvalue(), "")


class TracedExecutionTests(unittest.TestCase):
    def test_records_exception_and_error_status_before_reraising(self) -> None:
        from gh_address_cr import telemetry

        span = MagicMock()
        context_manager = MagicMock()
        context_manager.__enter__.return_value = span
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = context_manager

        private_error = ValueError("token=secret /Users/alice/private.py")
        with self.assertRaises(ValueError) as raised:
            telemetry.run_traced(tracer, "gh-address-cr.cli", lambda: (_ for _ in ()).throw(private_error))

        self.assertIs(raised.exception, private_error)
        recorded_error = span.record_exception.call_args.args[0]
        self.assertIsNot(recorded_error, private_error)
        self.assertEqual(str(recorded_error), "ValueError")
        self.assertIsNone(recorded_error.__traceback__)
        status = span.set_status.call_args.args[0]
        self.assertEqual(status.status_code.name, "ERROR")
        self.assertIsNone(status.description)

    def test_successful_system_exit_is_not_recorded_as_error(self) -> None:
        from gh_address_cr import telemetry

        span = MagicMock()
        context_manager = MagicMock()
        context_manager.__enter__.return_value = span
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = context_manager

        result = telemetry.run_traced(tracer, "gh-address-cr.cli", lambda: (_ for _ in ()).throw(SystemExit(0)))

        self.assertEqual(result, 0)
        span.record_exception.assert_not_called()
        span.set_status.assert_not_called()

    def test_nonzero_system_exit_is_not_recorded_as_error(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.core.otel_semconv import PROCESS_EXIT_CODE

        span = MagicMock()
        context_manager = MagicMock()
        context_manager.__enter__.return_value = span
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = context_manager

        result = telemetry.run_traced(tracer, "gh-address-cr.cli", lambda: (_ for _ in ()).throw(SystemExit(2)))

        self.assertEqual(result, 2)
        span.record_exception.assert_not_called()
        span.set_status.assert_not_called()
        span.set_attribute.assert_any_call(PROCESS_EXIT_CODE, 2)

    def test_span_event_helper_emits_events_on_the_active_span(self) -> None:
        from gh_address_cr import telemetry

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test_span_event_helper")

        def operation() -> int:
            telemetry.add_current_span_event(
                "gh-address-cr.test.phase.start",
                {"gh_address_cr.test.phase": "start", "gh_address_cr.test.step": 1},
            )
            telemetry.add_current_span_event(
                "gh-address-cr.test.phase.end",
                {"gh_address_cr.test.phase": "end", "gh_address_cr.test.step": 1},
            )
            return 0

        result = telemetry.run_traced(tracer, "gh-address-cr.cli", operation)

        self.assertEqual(result, 0)
        spans = exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        event_names = [event.name for event in spans[0].events]
        self.assertEqual(event_names, ["gh-address-cr.test.phase.start", "gh-address-cr.test.phase.end"])

    def test_command_session_emits_operation_timeline_events(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.commands.command_session import handle_command_session

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test_command_session_events")

        payload = {"operations": [{"id": "op-1", "argv": ["version"]}]}
        with tempfile.TemporaryDirectory() as temp_dir:
            request_path = Path(temp_dir) / "command-session.json"
            request_path.write_text(json.dumps(payload), encoding="utf-8")

            result = telemetry.run_traced(
                tracer,
                "gh-address-cr.cli",
                lambda: handle_command_session(["--input", str(request_path)]),
            )

        self.assertEqual(result, 0)
        spans = exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        event_names = [event.name for event in spans[0].events]
        self.assertEqual(
            event_names,
            [
                "gh_address_cr.command_session.operation.start",
                "gh_address_cr.command_session.operation.end",
                "gh_address_cr.command_session.summary",
            ],
        )
        self.assertEqual(spans[0].attributes["gh_address_cr.command.name"], "command-session")
        self.assertEqual(spans[0].attributes["gh_address_cr.command.path"], "command-session")
        start_event_attrs = dict(spans[0].events[0].attributes or {})
        end_event_attrs = dict(spans[0].events[1].attributes or {})
        self.assertEqual(start_event_attrs["gh_address_cr.command_session.operation_id"], "op-1")
        self.assertEqual(end_event_attrs["gh_address_cr.command_session.operation_id"], "op-1")

    def test_command_session_redacts_unsafe_operation_ids_in_timeline_events(self) -> None:
        from gh_address_cr import telemetry
        from gh_address_cr.commands.command_session import handle_command_session

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test_command_session_event_redaction")

        payload = {
            "operations": [
                {
                    "id": "/Users/snow/secrets/token=ghp_example",
                    "argv": ["version"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            request_path = Path(temp_dir) / "command-session.json"
            request_path.write_text(json.dumps(payload), encoding="utf-8")

            result = telemetry.run_traced(
                tracer,
                "gh-address-cr.cli",
                lambda: handle_command_session(["--input", str(request_path)]),
            )

        self.assertEqual(result, 0)
        spans = exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        for event in spans[0].events[:2]:
            attributes = dict(event.attributes or {})
            self.assertEqual(attributes["gh_address_cr.command_session.operation_id"], "[redacted]")

    def test_cli_main_keeps_single_span_while_recording_command_attributes(self) -> None:
        from unittest.mock import patch as _patch

        from gh_address_cr.__main__ import main

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test_cli_main_single_span")

        with (
            _patch("sys.argv", ["gh-address-cr", "version"]),
            _patch("gh_address_cr.__main__.initialize_telemetry", return_value=tracer),
            _patch("gh_address_cr.__main__.shutdown_telemetry"),
        ):
            result = main(["version"])

        self.assertEqual(result, 0)
        spans = exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].attributes["gh_address_cr.command.path"], "version")
        self.assertEqual(spans[0].attributes["gh_address_cr.command.exit_code"], 0)

    @patch("gh_address_cr.__main__.shutdown_telemetry")
    @patch("gh_address_cr.__main__.initialize_telemetry")
    @patch("gh_address_cr.__main__.cli_main", side_effect=KeyboardInterrupt)
    def test_cli_entrypoint_flushes_after_abnormal_exit(self, cli_main, initialize, shutdown) -> None:
        from gh_address_cr.__main__ import main

        tracer = initialize.return_value
        with self.assertRaises(KeyboardInterrupt):
            main([])

        tracer.start_as_current_span.assert_called_once()
        shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
