import hashlib
import json
import re
import unittest
from unittest.mock import patch


def expected_local_item_id(source: str, finding: dict) -> str:
    def normalize_text(value):
        return re.sub(r"\s+", " ", (value or "").strip()).lower()

    stable = "|".join(
        [
            finding.get("path", ""),
            str(finding.get("start_line") or finding.get("line") or ""),
            str(finding.get("end_line") or ""),
            normalize_text(finding.get("category", "")),
            normalize_text(finding.get("title", "")),
            normalize_text(finding.get("body", "")),
        ]
    )
    fingerprint = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    scoped = json.dumps({"source": source, "fingerprint": fingerprint}, sort_keys=True, separators=(",", ":"))
    return f"local-finding:{hashlib.sha256(scoped.encode('utf-8')).hexdigest()[:16]}"


class NativeIntakeTests(unittest.TestCase):
    def test_normalize_findings_payload_uses_legacy_source_scoped_item_id(self):
        from gh_address_cr.intake.findings import normalize_findings_payload

        raw = json.dumps(
            {
                "findings": [
                    {
                        "rule": "Null Guard",
                        "filename": "src/example.py",
                        "start_line": "12",
                        "end_line": "14",
                        "message": "Validate before dereferencing.",
                        "category": "Correctness",
                    }
                ]
            }
        )

        [finding] = normalize_findings_payload("code-review", raw)

        expected_basis = {
            "title": "Null Guard",
            "path": "src/example.py",
            "line": 12,
            "start_line": "12",
            "end_line": "14",
            "body": "Validate before dereferencing.",
            "category": "Correctness",
        }
        self.assertEqual(finding["item_id"], expected_local_item_id("code-review", expected_basis))
        self.assertEqual(finding["item_kind"], "local_finding")
        self.assertEqual(finding["source"], "code-review")
        self.assertEqual(finding["line"], 12)

    def test_normalize_findings_payload_accepts_fixed_finding_blocks(self):
        from gh_address_cr.intake.findings import normalize_findings_payload

        raw = """```finding
title: Missing test
path: tests/test_example.py
line: 7
body: Add regression coverage.
```"""

        [finding] = normalize_findings_payload("review-to-findings", raw)

        self.assertEqual(finding["title"], "Missing test")
        self.assertEqual(finding["item_kind"], "local_finding")
        self.assertEqual(finding["source"], "review-to-findings")
        self.assertEqual(finding["item_id"], expected_local_item_id("review-to-findings", finding))

    def test_normalize_findings_payload_rejects_unknown_source(self):
        from gh_address_cr.intake.findings import FindingsFormatError, normalize_findings_payload

        with self.assertRaises(FindingsFormatError):
            normalize_findings_payload("unknown", "[]")

    def test_cli_review_handoff_parsers_do_not_import_legacy_modules(self):
        from gh_address_cr import cli

        raw_json = json.dumps([{"title": "Finding", "body": "Body", "path": "src/a.py", "line": 3}])
        raw_blocks = """```finding
title: Finding
path: src/a.py
line: 3
body: Body
```"""

        with patch.object(cli, "_legacy_module", side_effect=AssertionError("legacy import")):
            [record] = cli._parse_records(raw_json)
            [finding] = cli._parse_findings(raw_blocks)
            normalized = cli._normalize_finding(record)

        self.assertEqual(finding["title"], "Finding")
        self.assertEqual(normalized["path"], "src/a.py")


if __name__ == "__main__":
    unittest.main()
