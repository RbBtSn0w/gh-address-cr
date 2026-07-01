from __future__ import annotations

import contextlib
import io
import logging
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


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

        with self.assertRaises(SystemExit) as raised:
            telemetry.run_traced(tracer, "gh-address-cr.cli", lambda: (_ for _ in ()).throw(SystemExit(0)))

        self.assertEqual(raised.exception.code, 0)
        span.record_exception.assert_not_called()
        span.set_status.assert_not_called()

    def test_nonzero_system_exit_is_not_recorded_as_error(self) -> None:
        from gh_address_cr import telemetry

        span = MagicMock()
        context_manager = MagicMock()
        context_manager.__enter__.return_value = span
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = context_manager

        with self.assertRaises(SystemExit) as raised:
            telemetry.run_traced(tracer, "gh-address-cr.cli", lambda: (_ for _ in ()).throw(SystemExit(2)))

        self.assertEqual(raised.exception.code, 2)
        span.record_exception.assert_not_called()
        span.set_status.assert_not_called()

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
