"""Spec 035 P4: within-session slowdown is measured and surfaced.

The local efficiency report only flagged operations over 60 s, and it never saw
gh-address-cr's own commands at all (only subprocesses), so a CR loop that
drifted from 200 ms to 400 ms per command was invisible.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.cli import main
from gh_address_cr.commands.final_gate import _issue_summary
from gh_address_cr.core import session as session_store
from gh_address_cr.core.telemetry import build_efficiency_report
from gh_address_cr.core.telemetry_models import LATENCY_GROWTH_MIN_SAMPLES, ExecutionMetric

REPO = "owner/repo"
PR_NUMBER = "123"
OPERATION = "gh-address-cr agent.submit"


def _write_metrics(durations_ms: list[float], *, persistence_ms: float | None = None) -> None:
    telemetry_file = session_store.workspace_dir(REPO, PR_NUMBER) / "telemetry.jsonl"
    with telemetry_file.open("w", encoding="utf-8") as handle:
        for index, duration in enumerate(durations_ms):
            start = 1_800_000_000.0 + index * 10
            metric = ExecutionMetric(
                command=OPERATION,
                start_time=start,
                end_time=start + duration / 1000,
                exit_code=0,
                execution_id=f"exec-{index}",
                persistence_ms=persistence_ms,
            )
            handle.write(json.dumps(metric.to_dict(), sort_keys=True) + "\n")


class LatencyRegressionContractTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.temp_dir.name}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _growth_flags(self, durations: list[float]) -> list[str]:
        _write_metrics(durations)
        report = build_efficiency_report(REPO, PR_NUMBER)
        return [flag for flag in report["inefficiency_flags"] if "latency grew" in flag]

    def test_sustained_growth_is_flagged(self):
        durations = [100.0] * 3 + [150.0, 180.0, 220.0, 260.0, 300.0] + [320.0] * 4

        flags = self._growth_flags(durations)

        self.assertEqual(len(flags), 1)
        self.assertIn(OPERATION, flags[0])
        self.assertIn("3.2x", flags[0])

    def test_flat_latency_and_small_samples_are_not_flagged(self):
        self.assertEqual(self._growth_flags([100.0, 120.0, 90.0, 110.0] * 3), [])
        self.assertEqual(self._growth_flags([100.0 * (index + 1) for index in range(LATENCY_GROWTH_MIN_SAMPLES - 1)]), [])

    def test_operation_latency_reports_percentiles_and_persistence_share(self):
        _write_metrics([100.0] * 9 + [1000.0], persistence_ms=50.0)

        report = build_efficiency_report(REPO, PR_NUMBER)
        rows = {row["operation"]: row for row in report["operation_latency"]}

        self.assertEqual(rows[OPERATION]["count"], 10)
        self.assertAlmostEqual(rows[OPERATION]["p50_ms"], 100, delta=1)
        self.assertAlmostEqual(rows[OPERATION]["p90_ms"], 100, delta=1)
        self.assertAlmostEqual(rows[OPERATION]["persistence_share"], 500 / 1900, delta=0.005)

    def test_completion_line_issues_surface_latency_growth(self):
        _write_metrics([100.0] * 4 + [400.0] * 8)
        report = build_efficiency_report(REPO, PR_NUMBER)

        issues = _issue_summary(report, success_rate=100.0, total_events=report["total_events"])

        self.assertIn("latency grew", issues)

    def test_binding_telemetry_defers_history_and_never_doubles_records(self):
        from gh_address_cr.core.telemetry_runtime import SessionTelemetry

        _write_metrics([100.0, 110.0, 120.0])
        telemetry_file = session_store.workspace_dir(REPO, PR_NUMBER) / "telemetry.jsonl"
        tracker = SessionTelemetry()
        real_open = Path.open
        reads: list[str] = []

        def tracking_open(path, mode="r", *args, **kwargs):
            if Path(path) == telemetry_file and "r" in mode and "b" not in mode:
                reads.append(mode)
            return real_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", tracking_open):
            tracker.configure_file(telemetry_file)
            tracker.record(OPERATION, 1_900_000_000.0, 1_900_000_000.2, 0)
            self.assertEqual(reads, [], "binding and recording must not load the session's telemetry history")
            metrics = tracker.metrics

        self.assertEqual(len(metrics), 4)
        self.assertEqual(len(telemetry_file.read_text(encoding="utf-8").splitlines()), 4)

    def test_cli_records_its_own_command_with_persistence_time(self):
        manager = session_store.SessionManager(REPO, PR_NUMBER)
        session = manager.create(status="WAITING_FOR_CLASSIFICATION")
        session["items"] = {
            "local:1": {
                "item_id": "local:1", "item_kind": "local_finding", "source": "json", "title": "Finding",
                "body": "Body", "path": "src/a.py", "line": 1, "state": "open", "status": "OPEN",
                "blocking": True, "allowed_actions": ["fix", "clarify", "defer", "reject"],
            }
        }
        manager.save(session)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exit_code = main([
                "agent", "classify", REPO, PR_NUMBER, "local:1", "--classification", "fix", "--note", "Real defect.",
            ])
        rows = [
            json.loads(line)
            for line in (manager.workspace_path / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        own = [row for row in rows if row["command"] == "gh-address-cr agent.classify"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(own), 1)
        self.assertGreater(own[0]["persistence_ms"], 0)
        self.assertGreaterEqual(own[0]["duration"] * 1000, own[0]["persistence_ms"])
        serialized = json.dumps(own)
        for forbidden in (REPO, "local:1", self.temp_dir.name, "Real defect"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
