import unittest

from gh_address_cr.core.severity import (
    extract_review_priority_evidence,
    extract_severity_evidence,
    normalize_severity,
    review_priority_evidence,
    review_priority_for_publish,
)


class SeverityEvidenceTests(unittest.TestCase):
    def test_extracts_only_explicit_p_scale_severity_markers(self):
        cases = [
            ("Severity: P1", "P1"),
            ("priority = `P2`", "P2"),
            ("[P3] tighten the guard", "P3"),
            ("P1 Badge rejects unsafe fallback", "P1"),
            ("![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)", "P2"),
        ]

        for body, expected in cases:
            with self.subTest(body=body):
                evidence = extract_severity_evidence(body, source="github_first_comment")
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence["value"], expected)

    def test_ignores_p_scale_tokens_without_explicit_marker_context(self):
        cases = [
            "src/p1_parser.py should reject blank input.",
            "Follow up in /p2-fix/ before release.",
            "The P3 parser path should be refactored later.",
        ]

        for body in cases:
            with self.subTest(body=body):
                self.assertIsNone(extract_severity_evidence(body, source="github_first_comment"))

    def test_review_priority_requires_explicit_priority_context(self):
        cases = [
            "![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)",
            "high priority issue in the review output",
            "Priority: low",
        ]

        for body in cases:
            with self.subTest(body=body):
                self.assertIsNotNone(extract_review_priority_evidence(body, source="github_first_comment"))

        for body in ("high-level plan", "The temperature is high.", "medium sized refactor"):
            with self.subTest(body=body):
                self.assertIsNone(extract_review_priority_evidence(body, source="github_first_comment"))

    def test_normalize_severity_does_not_treat_falsy_values_as_missing_pass_state(self):
        self.assertIsNone(normalize_severity(False))
        self.assertIsNone(normalize_severity(0))
        self.assertIsNone(normalize_severity(None))

    def test_review_priority_for_publish_tolerates_missing_item(self):
        self.assertEqual(review_priority_for_publish(None), (None, None))
        self.assertEqual(review_priority_for_publish([]), (None, None))

    def test_review_priority_evidence_accepts_explicit_payload_values(self):
        evidence = review_priority_evidence(
            "High",
            source="github_payload",
            raw_marker="High",
            observed_from="https://example.test/thread",
        )

        self.assertEqual(
            evidence,
            {
                "value": "high",
                "source": "github_payload",
                "raw_marker": "High",
                "observed_from": "https://example.test/thread",
            },
        )
        self.assertIsNone(review_priority_evidence("urgent", source="github_payload"))


if __name__ == "__main__":
    unittest.main()
