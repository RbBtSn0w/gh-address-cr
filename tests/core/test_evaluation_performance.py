from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path


class EvaluationPerformanceTestIntent:
    risk = "The local evaluation catalog or interval union can make routine agent workflows materially slower."
    why_automation = "The plan declares explicit 10,000-run and algorithmic scaling budgets."
    why_existing_tests_insufficient = "Functional contracts do not detect query or span-count regressions."
    chosen_layer = "Local deterministic performance contract over generated public records."
    fragility_analysis = "Budgets are intentionally broad and exclude database construction from query timing."
    if_omitted = "Telemetry intended to reduce latency could itself become a hidden latency source."


class EvaluationPerformanceTests(unittest.TestCase):
    def test_ten_thousand_run_query_completes_within_two_seconds(self):
        from gh_address_cr.core.evaluation.catalog import EvaluationCatalog

        records = [
            {
                "run_id": f"run-{index}", "repo": "owner/repo", "pr_number": str(index),
                "runtime_version": "1.0", "cohort_key": "items:1|files:1-3|diff:1-100|mix:fix-only",
                "projection_fingerprint": f"fp-{index}",
            }
            for index in range(10_000)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            catalog = EvaluationCatalog(Path(tmp) / "catalog.sqlite3")
            catalog.rebuild(records)
            started = time.perf_counter()
            rows = catalog.query_runs("1.0")
            elapsed = time.perf_counter() - started

        self.assertEqual(len(rows), 10_000)
        self.assertLess(elapsed, 2.0)

    def test_interval_union_scaling_budget(self):
        from gh_address_cr.core.evaluation.timing import interval_union_ms

        spans = [{"started_at_ms": index * 2, "ended_at_ms": index * 2 + 3} for index in range(25_000)]
        started = time.perf_counter()
        total = interval_union_ms(spans)
        elapsed = time.perf_counter() - started

        self.assertGreater(total, 0)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
