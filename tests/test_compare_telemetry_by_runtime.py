"""Spec 039 L4: compare archived efficiency reports by runtime build."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.compare_telemetry_by_runtime import collect_reports, compare, flag_kind, main, summarize


def write_report(root: Path, rel: str, *, runtime, success_rate, flags, needs_action=0):
    path = root / rel / "efficiency-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "success_rate": success_rate,
        "inefficiency_flags": flags,
        "needs_action_count": needs_action,
        "report_artifact": str(path),
        "report_generated_at": "2026-10-02T00:00:00+00:00",
    }
    if runtime is not None:
        report["runtime"] = runtime
    path.write_text(json.dumps(report), encoding="utf-8")


RELEASE_3153 = {"version": "3.15.3", "origin": "package", "commit": None}
RELEASE_3160 = {"version": "3.16.0", "origin": "package", "commit": None}
EXIT5_FLAG = "gh-address-cr address had 1 failures, 0 timeouts, and 0 retries."


class CompareTelemetryByRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for index in range(3):
            write_report(self.root, f"archive/o__r/pr-{index}/default", runtime=RELEASE_3153, success_rate=100.0, flags=[])
        for index in range(3, 6):
            write_report(self.root, f"archive/o__r/pr-{index}/default", runtime=RELEASE_3160, success_rate=91.0, flags=[EXIT5_FLAG])
        write_report(self.root, "o__r/pr-9", runtime=None, success_rate=100.0, flags=[])

    def test_flag_kinds_drop_counts_but_keep_the_operation(self):
        self.assertEqual(flag_kind(EXIT5_FLAG), "error_prone:gh-address-cr address")
        self.assertEqual(flag_kind("run unit tests exceeded 60s threshold."), "duration:run unit tests")

    def test_groups_by_runtime_and_keeps_pre_l4_reports_as_unknown(self):
        groups = summarize(collect_reports(self.root))

        self.assertEqual(sorted(groups), ["3.15.3 package", "3.16.0 package", "unknown"])
        self.assertEqual(groups["3.16.0 package"]["sessions"], 3)
        self.assertEqual(groups["3.16.0 package"]["median_success_rate"], 91.0)
        self.assertEqual(groups["3.16.0 package"]["flag_kinds"], {"error_prone:gh-address-cr address": 3})

    def test_check_reports_the_316_regression_against_315(self):
        groups = summarize(collect_reports(self.root))

        problems = compare(groups, baseline="3.15.3 package", candidate="3.16.0 package", max_success_drop=5.0)

        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("success rate" in problem for problem in problems))
        self.assertTrue(any("error_prone:gh-address-cr address" in problem for problem in problems))

    def test_cli_check_exits_nonzero_and_prints_no_paths(self):
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--state-dir", str(self.root), "--baseline", "3.15.3 package", "--candidate", "3.16.0 package"])

        self.assertEqual(code, 1)
        self.assertNotIn(str(self.root), out.getvalue())
        self.assertNotIn("report_artifact", out.getvalue())

    def test_cli_check_passes_for_an_equal_candidate(self):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--state-dir", str(self.root), "--baseline", "3.15.3 package", "--candidate", "3.15.3 package"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
