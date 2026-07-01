"""CLI contract tests for the `consolidation` command family (feature 024, US1)."""

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
        self.assertIn("slices", body)
        self.assertIn("hypotheses", body)

    def test_status_projects_kernel_owner_for_default_slice(self) -> None:
        payload = {
            "schema": "rollout-state.v1",
            "slices": [
                {
                    "slice_id": "slice-check-state",
                    "stage": "default",
                    "enabled": True,
                    "evidence_ref": "evaluation.v1:evaluation_default",
                    "deprecation_window_complete": False,
                }
            ],
            "hypotheses": [],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            state_path = Path(tmp) / "consolidation" / "rollout-state.v1.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            rc, out, _ = _run(["consolidation", "status", "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(out)
        check_axis = next(row for row in body["axes"] if row["axis"] == "check")
        self.assertEqual(check_axis["authoritative_owner"], "kernel")
        self.assertEqual(check_axis["compatibility_direction"], "legacy_from_kernel")

    def test_status_keeps_opt_in_slice_non_authoritative(self) -> None:
        payload = {
            "schema": "rollout-state.v1",
            "slices": [
                {
                    "slice_id": "slice-check-state",
                    "stage": "opt_in",
                    "enabled": True,
                    "evidence_ref": "evaluation.v1:evaluation_opt_in",
                    "deprecation_window_complete": False,
                }
            ],
            "hypotheses": [],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            state_path = Path(tmp) / "consolidation" / "rollout-state.v1.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            rc, out, _ = _run(["consolidation", "status", "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(out)
        check_axis = next(row for row in body["axes"] if row["axis"] == "check")
        self.assertEqual(check_axis["authoritative_owner"], "legacy")
        self.assertEqual(check_axis["compatibility_direction"], "none")

    def test_status_projects_unsupported_cohort_to_legacy(self) -> None:
        payload = {
            "schema": "rollout-state.v1",
            "slices": [
                {
                    "slice_id": "slice-check-state",
                    "stage": "default",
                    "enabled": True,
                    "evidence_ref": "evaluation.v1:evaluation_default",
                    "deprecation_window_complete": False,
                }
            ],
            "hypotheses": [],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            state_path = Path(tmp) / "consolidation" / "rollout-state.v1.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            rc, out, _ = _run(["consolidation", "status", "--cohort", "unsupported-host", "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(out)
        check_axis = next(row for row in body["axes"] if row["axis"] == "check")
        self.assertEqual(check_axis["authoritative_owner"], "legacy")

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


class ConsolidationRolloutCliTests(unittest.TestCase):
    def test_rollout_blocks_default_without_durable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            rc, _, err = _run(["consolidation", "rollout", "--slice", "slice-check-state", "--to", "default"])
        self.assertEqual(rc, 2)
        self.assertIn("INSUFFICIENT_EVIDENCE", err)

    def test_rollout_accepts_default_with_durable_evidence_file(self) -> None:
        evaluation = {
            "schema_version": "evaluation.v1",
            "evaluation_id": "evaluation_default",
            "durable_state": "verified",
            "durable_reason": "DURABLE_VERIFIED",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
            evidence_path = Path(tmp) / "evaluation.json"
            evidence_path.write_text(json.dumps(evaluation), encoding="utf-8")
            rc1, _, _ = _run(["consolidation", "rollout", "--slice", "slice-check-state", "--to", "opt_in"])
            rc2, out, err = _run(
                [
                    "consolidation",
                    "rollout",
                    "--slice",
                    "slice-check-state",
                    "--to",
                    "default",
                    "--evidence-file",
                    str(evidence_path),
                    "--json",
                ]
            )
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0, err)
        body = json.loads(out)
        self.assertEqual(body["resulting_stage"], "default")
        self.assertEqual(body["evidence"]["status"], "durable")

    def test_deprecations_emits_deprecation_inventory_v1(self) -> None:
        rc, out, _ = _run(["consolidation", "deprecations", "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(out)
        self.assertEqual(body["schema"], "deprecation-inventory.v1")
        self.assertTrue(body["entries"])


if __name__ == "__main__":
    unittest.main()
