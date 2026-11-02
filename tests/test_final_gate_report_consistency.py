"""Completion reports share lifecycle evidence across output and archive boundaries."""

import contextlib
import hashlib
import io
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.commands import final_gate
from gh_address_cr.core import gate
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.runtime_kernel.stack import project_stack_context
from gh_address_cr.core.session import SessionManager
from gh_address_cr.core.stack_gate import StackGateResult
from tests.helpers import stack_observation


class FinalGateReportConsistencyTests(unittest.TestCase):
    def test_lifecycle_survives_output_and_archive_boundaries(self):
        for stack, machine, archive, lifecycle_kind in itertools.product(
            (False, True), (False, True), (False, True), ("eligible", "empty", "unavailable", "failure")
        ):
            with self.subTest(stack=stack, machine=machine, archive=archive, lifecycle=lifecycle_kind):
                self.check_report(stack, machine, archive, lifecycle_kind)

    def check_report(self, stack, machine, archive, lifecycle_kind):
        repo, pr = "octo/example", "102"
        layer_result = gate.GateResult(repo, pr, {key: 0 for key in gate.COUNT_KEYS}, [])
        stack_result = StackGateResult(
            repo, pr, project_stack_context(stack_observation()), ("101", "102"), ()
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "octo__example" / "pr-102"

            def build_lifecycle(*args, **kwargs):
                if lifecycle_kind == "failure":
                    raise OSError("injected lifecycle failure")
                report = {
                    "status": "UNAVAILABLE" if lifecycle_kind == "unavailable" else "SUCCESS",
                    "completeness": "unavailable" if lifecycle_kind == "unavailable" else "complete",
                    "diagnostics": ["injected lifecycle unavailable"] if lifecycle_kind == "unavailable" else [],
                    "report_artifact": str(workspace / "cr-metrics.json"),
                    "aggregates": {
                        "eligible_items": 2 if lifecycle_kind == "eligible" else 0,
                        "excluded_items": 1,
                        "observed_to_verified_ms": {"median": 4500, "p90": 8000},
                        "first_pass_verified_rate": {"numerator": 1, "denominator": 2, "rate": 0.5},
                    },
                }
                write_json_atomic(workspace / "cr-metrics.json", report)
                return report

            with (
                patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp, "DISABLE_TELEMETRY": "1"}),
                patch.object(final_gate.core_gate.Gatekeeper, "run", return_value=layer_result),
                patch.object(final_gate.core_stack_gate, "run_stack_gate", return_value=stack_result),
                patch.object(final_gate.core_cr_metrics, "build_cr_summary", side_effect=build_lifecycle),
                contextlib.redirect_stdout(stdout := io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                manager = SessionManager(repo, pr)
                manager.save(manager.create(status="WAITING_FOR_GATE"))
                flags = ["--machine" if machine else "--human", "--auto-clean" if archive else "--no-auto-clean"]
                if stack:
                    flags.append("--stack")
                exit_code = final_gate.handle_final_gate(repo, pr, flags)

            self.assertEqual(exit_code, 0)
            self.assertEqual(workspace.exists(), not archive)
            output = stdout.getvalue()
            payload = json.loads(output) if machine else None
            artifact_name = "stack-audit-summary.md" if stack else "audit_summary.md"
            artifact = next(Path(tmp).rglob(artifact_name))
            summary = artifact.read_text()
            lifecycle = json.loads((artifact.parent / "cr-metrics.json").read_text())
            expected_status = "UNAVAILABLE" if lifecycle_kind in {"failure", "unavailable"} else "SUCCESS"
            self.assertEqual(lifecycle["status"], expected_status)
            self.assertIn(f"cr_metrics_status: {expected_status}", summary)
            marker = "lifecycle: 2 eligible/1 excluded"
            self.assertEqual(marker in summary, lifecycle_kind == "eligible")
            if machine:
                self.assertEqual(payload["status"], "PASSED")
                self.assertEqual(payload["completion_summary"]["lifecycle_status"], expected_status)
                self.assertEqual(marker in payload["completion_summary_line"], lifecycle_kind == "eligible")
                guidance = payload["completion_summary_guidance"]
                self.assertEqual(Path(payload["artifact_path"]), artifact)
            else:
                guidance = output
                self.assertEqual(marker in output, lifecycle_kind == "eligible")
                self.assertIn(f"cr_metrics_status={expected_status}", output)
            self.assertIn(str(artifact.parent / "cr-metrics.json"), guidance)
            self.assertIn(hashlib.sha256(artifact.read_bytes()).hexdigest(), guidance)
            if lifecycle_kind in {"failure", "unavailable"}:
                self.assertTrue(lifecycle["diagnostics"])
                self.assertIn(lifecycle["diagnostics"][0], summary)
                if not machine:
                    self.assertIn(lifecycle["diagnostics"][0], output)
            if archive:
                self.assertNotIn(str(workspace), summary)
                self.assertNotIn(str(workspace), guidance)
