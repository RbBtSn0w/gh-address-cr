"""Duration flags name each slow operation once (the completion line repeated them)."""

from __future__ import annotations

import unittest

from gh_address_cr.core.telemetry_models import ExternalTelemetryEvent
from gh_address_cr.core.telemetry_reporting import _inefficiency_flags


def event(index: int, operation: str, duration_ms: int) -> ExternalTelemetryEvent:
    return ExternalTelemetryEvent(
        schema_version="1",
        source="runtime",
        source_session_id="s",
        event_id=str(index),
        kind="validation",
        operation=operation,
        status="success",
        duration_ms=duration_ms,
    )


class DurationFlagTests(unittest.TestCase):
    def test_a_slow_operation_seen_twice_is_flagged_once_with_its_count(self):
        slowest = [event(1, "python3 -m unittest discover", 240_000), event(2, "python3 -m unittest discover", 230_000)]

        self.assertEqual(
            _inefficiency_flags(slowest, []),
            ["python3 -m unittest discover exceeded 60s threshold (2 runs)."],
        )

    def test_single_runs_keep_the_existing_text_and_distinct_operations_stay_separate(self):
        slowest = [event(1, "unit-tests", 90_000), event(2, "ui-tests", 70_000), event(3, "lint", 5_000)]

        self.assertEqual(
            _inefficiency_flags(slowest, []),
            ["unit-tests exceeded 60s threshold.", "ui-tests exceeded 60s threshold."],
        )


if __name__ == "__main__":
    unittest.main()
