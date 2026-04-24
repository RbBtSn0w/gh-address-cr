import json
import sys
import unittest

from tests.helpers import ROOT, SRC_ROOT


sys.path.insert(0, str(SRC_ROOT))


class FindingsIntakeTests(unittest.TestCase):
    def test_fixed_finding_blocks_parse_to_normalized_findings(self):
        from gh_address_cr.intake.findings import parse_finding_blocks

        raw = """```finding
title: Missing guard
path: src/example.py
line: 12
severity: high
body: |
  Validate the input before dereferencing it.
```"""

        self.assertEqual(
            parse_finding_blocks(raw),
            [
                {
                    "title": "Missing guard",
                    "path": "src/example.py",
                    "line": 12,
                    "body": "Validate the input before dereferencing it.",
                    "severity": "high",
                }
            ],
        )

    def test_narrative_markdown_is_rejected(self):
        from gh_address_cr.intake.findings import FindingsFormatError, parse_finding_blocks

        with self.assertRaises(FindingsFormatError) as caught:
            parse_finding_blocks("# Review\n\nThis is prose, not a fixed finding block.")

        self.assertIn("fixed `finding` blocks", str(caught.exception))

    def test_json_finding_records_normalize_aliases_and_envelopes(self):
        from gh_address_cr.intake.findings import parse_records, normalize_finding

        records = parse_records(
            json.dumps(
                {
                    "findings": [
                        {
                            "rule": "null-guard",
                            "filename": "src/a.py",
                            "start_line": "9",
                            "message": "Check for None first.",
                        }
                    ]
                }
            )
        )

        self.assertEqual(
            [normalize_finding(record) for record in records],
            [
                {
                    "title": "null-guard",
                    "path": "src/a.py",
                    "line": 9,
                    "body": "Check for None first.",
                    "start_line": "9",
                }
            ],
        )

    def test_adapter_dispatch_rejects_unknown_source(self):
        from gh_address_cr.intake.adapters import AdapterError, normalize_adapter_payload

        with self.assertRaises(AdapterError):
            normalize_adapter_payload("unknown", "[]")

    def test_adapter_dispatch_accepts_fixed_finding_blocks(self):
        from gh_address_cr.intake.adapters import normalize_adapter_payload

        raw = """```finding
title: Finding
path: src/example.py
line: 3
body: Needs a test.
```"""

        [finding] = normalize_adapter_payload("review-to-findings", raw)
        self.assertEqual(finding["item_kind"], "local_finding")
        self.assertEqual(finding["source"], "review-to-findings")
        self.assertTrue(finding["item_id"].startswith("local-finding:"))

    def test_github_thread_fixture_corpus_normalizes_successfully(self):
        from gh_address_cr.intake.adapters import normalize_github_thread_fixture

        fixture_dir = ROOT / "tests" / "fixtures" / "github_threads"
        fixtures = sorted(fixture_dir.glob("*.json"))
        self.assertGreaterEqual(len(fixtures), 3)

        for path in fixtures:
            with self.subTest(fixture=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(normalize_github_thread_fixture(payload), payload["expected"])


if __name__ == "__main__":
    unittest.main()
