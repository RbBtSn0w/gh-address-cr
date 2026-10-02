from __future__ import annotations

import unittest

from scripts.validate_cr_lifecycle_dogfood import run_controlled_dogfood


class CRLifecycleDogfoodTest(unittest.TestCase):
    def test_controlled_dogfood_produces_ten_complete_eligible_sessions(self):
        report = run_controlled_dogfood()

        self.assertEqual(report["schema_version"], "cr-lifecycle-dogfood.v1")
        self.assertEqual(report["sample_kind"], "controlled_premerge")
        self.assertFalse(report["threshold_eligible"])
        self.assertEqual(report["session_count"], 10)
        self.assertEqual(report["eligible_items"], 10)
        self.assertEqual(report["excluded_items"], 0)
        self.assertEqual(report["first_pass_verified_rate"]["numerator"], 10)
        self.assertEqual(report["first_pass_verified_rate"]["denominator"], 10)
        self.assertEqual(report["exclusion_reasons"], [])
        self.assertTrue(all(session["status"] == "SUCCESS" for session in report["sessions"]))
        self.assertTrue(all(session["completeness"] == "complete" for session in report["sessions"]))


if __name__ == "__main__":
    unittest.main()
