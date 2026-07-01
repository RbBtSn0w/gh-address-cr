"""Quickstart scenario validation for feature 024."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gh_address_cr import cli

_FIXTURE = Path(__file__).parent / "fixtures" / "check_state_facts.json"
_DURABLE_EVIDENCE = {
    "schema_version": "evaluation.v1",
    "evaluation_id": "evaluation_default",
    "durable_state": "verified",
    "durable_reason": "DURABLE_VERIFIED",
}


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class QuickstartScenarioTests(unittest.TestCase):
    def test_scenario_1_single_authoritative_owner_per_axis(self) -> None:
        rc, out, _ = _run(["consolidation", "status", "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        axes = payload["axes"]
        self.assertEqual(len(axes), 7)
        self.assertEqual(len({row["axis"] for row in axes}), 7)

    def test_scenario_2_deterministic_side_effect_free_parity(self) -> None:
        first = _run(["consolidation", "parity", "--slice", "slice-check-state", "--facts", str(_FIXTURE), "--json"])
        second = _run(["consolidation", "parity", "--slice", "slice-check-state", "--facts", str(_FIXTURE), "--json"])
        self.assertEqual(first[0], 0)
        self.assertEqual(first[1], second[1])
        self.assertEqual(json.loads(first[1])["side_effects_executed"], 0)

    def test_scenario_3_default_rollout_blocks_without_durable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            rc1, _, _ = _run(["consolidation", "rollout", "--slice", "slice-check-state", "--to", "opt_in"])
            rc, _, err = _run(["consolidation", "rollout", "--slice", "slice-check-state", "--to", "default"])
        self.assertEqual(rc1, 0)
        self.assertEqual(rc, 2)
        self.assertIn("INSUFFICIENT_EVIDENCE", err)

    def test_scenario_4_rollout_is_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            rc1, out1, _ = _run(["consolidation", "rollout", "--slice", "slice-check-state", "--to", "opt_in", "--json"])
            rc2, out2, _ = _run(["consolidation", "rollout", "--slice", "slice-check-state", "--to", "shadow", "--json"])
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        self.assertEqual(json.loads(out1)["resulting_stage"], "opt_in")
        self.assertEqual(json.loads(out2)["resulting_stage"], "shadow")

    def test_scenario_5_independent_optimization_hypotheses_are_visible(self) -> None:
        rc, out, _ = _run(["consolidation", "status", "--json"])
        self.assertEqual(rc, 0)
        hypotheses = json.loads(out)["hypotheses"]
        self.assertEqual({row["hypothesis_id"] for row in hypotheses}, {"output_truncation", "command_session", "workflow_surface_removal"})

    def test_scenario_6_unsupported_cohort_stays_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            evidence_path = Path(tmp) / "evaluation.json"
            evidence_path.write_text(json.dumps(_DURABLE_EVIDENCE), encoding="utf-8")
            rc1, _, _ = _run(["consolidation", "rollout", "--slice", "slice-check-state", "--to", "opt_in"])
            rc2, _, _ = _run(
                [
                    "consolidation",
                    "rollout",
                    "--slice",
                    "slice-check-state",
                    "--to",
                    "default",
                    "--evidence-file",
                    str(evidence_path),
                ]
            )
            rc3, out, _ = _run(["consolidation", "status", "--cohort", "unsupported-host", "--json"])
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        self.assertEqual(rc3, 0)
        check_axis = next(row for row in json.loads(out)["axes"] if row["axis"] == "check")
        self.assertEqual(check_axis["authoritative_owner"], "legacy")


if __name__ == "__main__":
    unittest.main()
