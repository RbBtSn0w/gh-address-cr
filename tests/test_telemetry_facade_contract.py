from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from gh_address_cr import otel_tracing, telemetry

# Implementation detail that used to be mirrored onto the facade purely so tests
# could monkeypatch `gh_address_cr.telemetry`. Re-exporting any of these again
# recreates the patch surface this contract exists to keep closed.
IMPLEMENTATION_ONLY_NAMES = (
    "TracerProvider",
    "OTLPSpanExporter",
    "BatchSpanProcessor",
    "TELEMETRY_ENVIRONMENT_VARIABLE",
    "OTLP_TRACES_ENDPOINT",
    "EXPORT_TIMEOUT_SECONDS",
    "EXPORT_TIMEOUT_MILLIS",
    "_SAFE_EXPORT_HEADERS",
    "_OTEL_EXPORT_LOGGERS",
    "_reset_telemetry_for_tests",
    "_sync_patchable_globals",
)


class TelemetryFacadeContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        otel_tracing._reset_telemetry_for_tests()

    def test_documented_public_api_is_the_implementation_object(self) -> None:
        self.assertEqual(
            telemetry.__all__,
            [
                "add_current_span_event",
                "get_current_span_attributes",
                "initialize_telemetry",
                "resolve_parent_context",
                "run_traced",
                "set_current_span_attributes",
                "shutdown_telemetry",
                "start_child_span",
            ],
        )
        for name in telemetry.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(telemetry, name), getattr(otel_tracing, name))

    def test_facade_does_not_re_export_implementation_internals(self) -> None:
        for name in IMPLEMENTATION_ONLY_NAMES:
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(telemetry, name),
                    f"{name} belongs to gh_address_cr.otel_tracing, not the public facade",
                )

    def test_facade_initialization_observes_implementation_patches(self) -> None:
        provider = MagicMock()
        tracer = MagicMock()
        provider.get_tracer.return_value = tracer

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(otel_tracing, "TracerProvider", return_value=provider),
            patch.object(otel_tracing, "OTLPSpanExporter"),
            patch.object(otel_tracing, "BatchSpanProcessor"),
        ):
            result = telemetry.initialize_telemetry()

        self.assertIs(result, tracer)


if __name__ == "__main__":
    unittest.main()
