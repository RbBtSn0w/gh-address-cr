import json
import subprocess
import sys
import unittest

from tests.helpers import ROOT

BENCHMARK = ROOT / "scripts" / "benchmark_telemetry_grouping.py"


class TelemetryGroupingBenchmarkTest(unittest.TestCase):
    def test_benchmark_reports_equivalent_results_for_both_grouping_hotspots(self):
        result = subprocess.run(
            [
                sys.executable,
                str(BENCHMARK),
                "--events",
                "100",
                "--groups",
                "5",
                "--samples",
                "1",
                "--warmups",
                "0",
                "--json",
            ],
            text=True,
            capture_output=True,
            timeout=30,
            cwd=ROOT,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["workload"], {"events": 100, "groups": 5})
        self.assertEqual(set(report["benchmarks"]), {"telemetry_reporting", "cr_metrics"})
        for benchmark in report["benchmarks"].values():
            self.assertTrue(benchmark["outputs_equivalent"])
            self.assertGreater(benchmark["baseline_median_ns"], 0)
            self.assertGreater(benchmark["candidate_median_ns"], 0)
