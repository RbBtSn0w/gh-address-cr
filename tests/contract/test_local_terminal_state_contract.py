"""Local terminal vocabulary preserves evidence and final-gate policy at every consumer."""

import json
from unittest.mock import patch

from gh_address_cr.core import gate, session
from gh_address_cr.core.logic_validation import generate_logic_validation_signals
from gh_address_cr.core.runtime_kernel.final_gate import (
    build_final_gate_facts,
    evaluate_final_gate_policy,
    project_final_gate,
)
from gh_address_cr.core.runtime_kernel.stack import project_stack_context, revision_binding_for_context
from tests.helpers import PythonScriptTestCase, stack_observation

TERMINAL_STATES = ("closed", "fixed", "clarified", "deferred", "rejected", "verified", "published")


def local_session(state, *, validation=None, blocking=None):
    item = {"item_id": "local-finding:X", "item_kind": "local_finding", "state": state}
    if validation is not None:
        item["validation_evidence"] = [{"command": "unit", "result": validation}]
    if blocking is not None:
        item["blocking"] = blocking
    return {"repo": "octo/example", "pr_number": "102", "items": {item["item_id"]: item}}


def evaluate(payload):
    signals = [signal.to_dict() for signal in generate_logic_validation_signals(payload)]
    facts = build_final_gate_facts(payload, logic_validation_signals=signals)
    projection = project_final_gate(facts)
    decision = evaluate_final_gate_policy(projection)
    return gate.GateResult(payload["repo"], payload["pr_number"], projection.counts, list(decision.failure_codes))


class LocalTerminalStateContractTests(PythonScriptTestCase):
    def test_gate_matrix_preserves_counts_reason_codes_and_exit_codes(self):
        for state in TERMINAL_STATES + ("open", "stale", "unknown"):
            for validation in (None, "failed", "passed"):
                with self.subTest(state=state, validation=validation):
                    result = evaluate(local_session(state, validation=validation))
                    terminal = state in TERMINAL_STATES
                    missing = terminal and validation != "passed"
                    self.assertEqual(result.counts["blocking_local_items_count"], int(not terminal))
                    self.assertEqual(result.counts["missing_validation_evidence_count"], int(missing))
                    self.assertEqual(result.counts["logic_validation_blocking_count"], int(missing))
                    expected = (
                        "FINAL_GATE_BLOCKING_LOCAL_ITEMS" if not terminal
                        else "FINAL_GATE_MISSING_VALIDATION_EVIDENCE" if missing else None
                    )
                    self.assertEqual(result.reason_code, expected)
                    self.assertEqual(result.exit_code, 5 if expected else 0)

    def test_explicit_blocking_keeps_priority_over_terminal_vocabulary(self):
        for state in TERMINAL_STATES:
            result = evaluate(local_session(state, validation="passed", blocking=True))
            self.assertEqual(result.reason_code, "FINAL_GATE_BLOCKING_LOCAL_ITEMS")
        for state in ("open", "stale", "unknown"):
            self.assertEqual(evaluate(local_session(state, blocking=False)).exit_code, 0)

    def test_current_case_handling_at_each_boundary_is_preserved(self):
        payload = local_session("CLOSED")
        self.assertEqual(generate_logic_validation_signals(payload), [])
        self.assertEqual(evaluate(payload).reason_code, "FINAL_GATE_MISSING_VALIDATION_EVIDENCE")

    def test_every_terminal_state_requires_current_stacked_revision_evidence(self):
        context = project_stack_context(stack_observation())
        for state in TERMINAL_STATES:
            with self.subTest(state=state):
                payload = local_session(state, validation="passed")
                session.cache_pull_request_context(payload, context.to_dict())
                binding = revision_binding_for_context(context)
                stale = {**binding, "head_tree_oid": "f" * 40}
                item = payload["items"]["local-finding:X"]
                item["revision_binding"] = stale
                self.assertEqual(evaluate(payload).reason_code, "FINAL_GATE_STALE_REVISION_EVIDENCE")
                item["revision_binding"] = binding
                self.assertEqual(evaluate(payload).exit_code, 0)

    def test_evidence_add_records_only_successful_validation_for_terminal_items(self):
        for index, state in enumerate(TERMINAL_STATES + ("open", "stale", "unknown", "CLOSED")):
            with self.subTest(state=state):
                self.pr = str(200 + index)
                manager = session.SessionManager(self.repo, self.pr)
                payload = manager.create(status="WAITING_FOR_GATE")
                payload["items"] = local_session(state)["items"]
                manager.save(payload)
                args = (
                    "agent", "evidence", "add", self.repo, self.pr,
                    "--item-id", "local-finding:X", "--commit", "abc1234", "--files", "app.py",
                )
                failed = self.run_runtime_module(*args, "--validation", "unit=failed")
                self.assertEqual(failed.returncode, 2, failed.stderr)
                self.assertEqual(json.loads(failed.stdout)["reason_code"], "VALIDATION_EVIDENCE_NOT_SUCCESS")
                with patch("gh_address_cr.github.client.GitHubClient.get_stack_context", return_value=None):
                    result = self.run_runtime_module(*args, "--validation", "unit=passed")
                terminal = state in TERMINAL_STATES or state == "CLOSED"
                self.assertEqual(result.returncode, 0 if terminal else 4, result.stderr or result.stdout)
                summary = json.loads(result.stdout)
                current = manager.load()
                if terminal:
                    self.assertEqual(summary["status"], "VALIDATION_EVIDENCE_RECORDED")
                    self.assertEqual(evaluate(current).exit_code, 0)
                    self.assertTrue(any(row["event_type"] == "validation_evidence_recorded"
                                        for row in session.load_canonical_evidence(self.repo, self.pr)))
                else:
                    self.assertEqual(summary["reason_code"], "ITEM_NOT_TERMINAL")
                    self.assertNotIn("validation_evidence", current["items"]["local-finding:X"])
