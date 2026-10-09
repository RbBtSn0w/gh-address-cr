import json
import subprocess
import sys
import unittest

from tests.helpers import ROOT

BENCHMARK = ROOT / "scripts" / "benchmark_runtime_store.py"


def _run_smoke(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(BENCHMARK),
            "--profile",
            "S",
            "--cr-limit",
            "5",
            "--load-samples",
            "1",
            "--json",
            *extra,
        ],
        text=True,
        capture_output=True,
        timeout=120,
        cwd=ROOT,
    )


class RuntimeStoreBenchmarkTest(unittest.TestCase):
    def test_benchmark_reports_cr_loop_shape_without_timing_assertions(self):
        result = _run_smoke()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["tracing"], {"enabled": False, "spans_exported": 0})
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(set(report["profiles"]), {"S"})
        profile = report["profiles"]["S"]
        self.assertEqual(profile["workload"], {"items": 50, "evidence": 200, "crs_run": 5})
        self.assertEqual(set(profile["steps_ms"]), {"classify", "next", "submit"})
        self.assertEqual(set(profile["cost_breakdown_ms"]), {"classify", "next", "submit"})
        for summary in (*profile["steps_ms"].values(), profile["per_cr_ms"]):
            self.assertEqual(set(summary), {"p50", "p90", "max"})
            self.assertGreater(summary["p50"], 0)
        for breakdown in profile["cost_breakdown_ms"].values():
            self.assertEqual(set(breakdown), {"load", "transaction", "materialization", "other"})
            for component in breakdown.values():
                self.assertEqual(set(component), {"p50", "p90", "max"})
                self.assertGreaterEqual(component["p50"], 0)
        self.assertEqual(
            set(profile["cost_breakdown_degradation_ratio"]),
            {"classify", "next", "submit"},
        )
        self.assertGreater(profile["first_load_ms"], 0)
        self.assertEqual(set(profile["load_session_ms"]), {"before_loop", "after_loop"})
        self.assertGreater(profile["degradation_ratio"], 0)

    def test_trace_mode_records_persistence_spans_under_a_cli_root_span(self):
        result = _run_smoke("--trace")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["tracing"]["enabled"])
        # 5 CRs x 3 steps each produce a root span plus persistence child spans.
        self.assertGreater(report["tracing"]["spans_exported"], 15)
        self.assertEqual(report["profiles"]["S"]["workload"]["crs_run"], 5)


if __name__ == "__main__":
    unittest.main()
