import json
import subprocess
import sys
import unittest

from tests.helpers import ROOT

BENCHMARK = ROOT / "scripts" / "benchmark_runtime_store.py"


class RuntimeStoreBenchmarkTest(unittest.TestCase):
    def test_benchmark_reports_cr_loop_shape_without_timing_assertions(self):
        result = subprocess.run(
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
            ],
            text=True,
            capture_output=True,
            timeout=120,
            cwd=ROOT,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(set(report["profiles"]), {"S"})
        profile = report["profiles"]["S"]
        self.assertEqual(profile["workload"], {"items": 50, "evidence": 200, "crs_run": 5})
        self.assertEqual(set(profile["steps_ms"]), {"classify", "next", "submit"})
        for summary in (*profile["steps_ms"].values(), profile["per_cr_ms"]):
            self.assertEqual(set(summary), {"p50", "p90", "max"})
            self.assertGreater(summary["p50"], 0)
        self.assertGreater(profile["first_load_ms"], 0)
        self.assertEqual(set(profile["load_session_ms"]), {"before_loop", "after_loop"})
        self.assertGreater(profile["degradation_ratio"], 0)


if __name__ == "__main__":
    unittest.main()
