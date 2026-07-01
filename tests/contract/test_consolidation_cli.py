"""CLI contract tests for the `consolidation` command family (feature 024, US1)."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from gh_address_cr import cli

_FIXTURE = Path(__file__).parent.parent / "consolidation" / "fixtures" / "check_state_facts.json"


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class ConsolidationStatusCliTests(unittest.TestCase):
    def test_status_emits_authority_map_v1(self) -> None:
        rc, out, _ = _run(["consolidation", "status", "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(out)
        self.assertEqual(body["schema"], "authority-map.v1")
        self.assertEqual(len(body["axes"]), 7)

    def test_unknown_subcommand_exits_non_zero(self) -> None:
        rc, _, err = _run(["consolidation", "bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("INVALID_ARGUMENTS", err)

    def test_root_output_flags_rejected(self) -> None:
        rc, _, err = _run(["--machine", "consolidation", "status"])
        self.assertEqual(rc, 2)
        self.assertIn("not supported", err)


class ConsolidationParityCliTests(unittest.TestCase):
    def test_parity_emits_parity_report_v1(self) -> None:
        rc, out, _ = _run(
            ["consolidation", "parity", "--slice", "slice-check-state", "--facts", str(_FIXTURE), "--json"]
        )
        self.assertEqual(rc, 0)
        body = json.loads(out)
        self.assertEqual(body["schema"], "parity-report.v1")
        self.assertEqual(body["side_effects_executed"], 0)

    def test_unknown_slice_exits_with_reason_code(self) -> None:
        rc, _, err = _run(
            ["consolidation", "parity", "--slice", "does-not-exist", "--facts", str(_FIXTURE)]
        )
        self.assertEqual(rc, 2)
        self.assertIn("UNKNOWN_SLICE", err)


if __name__ == "__main__":
    unittest.main()
