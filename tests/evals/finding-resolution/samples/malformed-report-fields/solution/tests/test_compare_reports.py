import json
import tempfile
import unittest
from pathlib import Path

from app.compare_reports import collect_reports, flag_kind, summarize


def report(version="3.16.0", origin="package", **fields):
    return {"runtime": {"version": version, "origin": origin}, **fields}


class CompareReportsTests(unittest.TestCase):
    def test_flag_kind_drops_counts(self):
        self.assertEqual(flag_kind("address had 3 failures"), "error_prone:address")
        self.assertEqual(flag_kind("final-gate exceeded 30s threshold"), "duration:final-gate")
        self.assertEqual(flag_kind("something else"), "other")

    def test_summarize_groups_by_runtime(self):
        summary = summarize(
            [
                report(success_rate=100.0, needs_action_count=2, inefficiency_flags=["address had 1 failures"]),
                report(success_rate=80.0, needs_action_count=1),
                report(version="3.15.3", success_rate=100.0),
            ]
        )
        self.assertEqual(sorted(summary), ["3.15.3 package", "3.16.0 package"])
        current = summary["3.16.0 package"]
        self.assertEqual(current["sessions"], 2)
        self.assertEqual(current["median_success_rate"], 90.0)
        self.assertEqual(current["needs_action_total"], 3)
        self.assertEqual(current["flag_kinds"], {"error_prone:address": 1})

    def test_malformed_fields_are_skipped(self):
        summary = summarize(
            [
                report(inefficiency_flags="address had 1 failures", needs_action_count="seven"),
                report(inefficiency_flags=["address had 1 failures"], needs_action_count=2),
            ]
        )["3.16.0 package"]
        self.assertEqual(summary["flag_kinds"], {"error_prone:address": 1})
        self.assertEqual(summary["needs_action_total"], 2)

    def test_collect_reports_skips_unreadable_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a").mkdir()
            (root / "a" / "efficiency-report.json").write_text(json.dumps(report()), encoding="utf-8")
            (root / "b").mkdir()
            (root / "b" / "efficiency-report.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(len(collect_reports(root)), 1)


if __name__ == "__main__":
    unittest.main()
