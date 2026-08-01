"""Public stacked-PR contract tests for spec 031."""

from __future__ import annotations

import unittest

from gh_address_cr.core import protocol_codes
from tests.helpers import stack_observation

STACK_REASON_CODES = (
    "STACK_CONTEXT_UNAVAILABLE",
    "STACK_CONTEXT_INVALID",
    "STACK_CONTEXT_STALE",
    "STACK_MEMBER_SESSION_MISSING",
    "STACK_MEMBER_SESSION_INVALID",
    "STACK_MEMBER_DRAFT",
    "STACK_MEMBER_CLOSED",
    "STACK_MEMBER_QUEUED",
    "STACK_MEMBER_BLOCKED",
    "STACK_ACTION_CONTEXT_MISMATCH",
    "FINAL_GATE_STALE_REVISION_EVIDENCE",
    "FINAL_GATE_UNBOUND_REVISION_EVIDENCE",
)


class RevisionBindingContractTests(unittest.TestCase):
    def test_publish_preflight_rejects_invalid_current_context_before_side_effects(self):
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.publisher import _verify_publish_revision_bindings
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        invalid_observation = stack_observation(selected_pr_number="102")
        invalid_observation["members"][1]["position"] = 1

        class Client:
            def get_stack_context(self, repo, pr_number):
                return project_stack_context(invalid_observation)

        item = {"accepted_response": {"validation_commands": [{"command": "unit", "result": "passed"}]}}
        with self.assertRaises(WorkflowError) as caught:
            _verify_publish_revision_bindings(
                "octo/example",
                "102",
                {"metadata": {}},
                [("github-thread:abc", item)],
                Client(),
            )

        self.assertEqual(caught.exception.reason_code, "STACK_CONTEXT_INVALID")
        self.assertEqual(caught.exception.waiting_on, "stack_refresh")

    def test_publish_preflight_rejects_unbound_response_on_current_stack_member(self):
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.publisher import _verify_publish_revision_bindings
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        class Client:
            side_effect_count = 0

            def get_stack_context(self, repo, pr_number):
                return project_stack_context(stack_observation(selected_pr_number=pr_number))

            def post_reply(self, *args):
                self.side_effect_count += 1

            def resolve_thread(self, *args):
                self.side_effect_count += 1

        client = Client()
        item = {"accepted_response": {"validation_commands": [{"command": "unit", "result": "passed"}]}}

        with self.assertRaises(WorkflowError) as caught:
            _verify_publish_revision_bindings(
                "octo/example",
                "102",
                {"metadata": {}},
                [("github-thread:abc", item)],
                client,
            )

        self.assertEqual(caught.exception.reason_code, "FINAL_GATE_UNBOUND_REVISION_EVIDENCE")
        self.assertEqual(caught.exception.waiting_on, "validation_evidence")
        self.assertEqual(client.side_effect_count, 0)

    def test_publish_preflight_rejects_stale_binding_before_side_effects(self):
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.publisher import _verify_publish_revision_bindings
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context, revision_binding_for_context

        original = project_stack_context(stack_observation(selected_pr_number="102"))
        binding = revision_binding_for_context(original)
        changed = stack_observation(selected_pr_number="102")
        changed["members"][1]["head_oid"] = "f" * 40

        class Client:
            side_effect_count = 0

            def get_stack_context(self, repo, pr_number):
                return project_stack_context(changed)

            def post_reply(self, *args):
                self.side_effect_count += 1

            def resolve_thread(self, *args):
                self.side_effect_count += 1

        client = Client()
        item = {"accepted_response": {"revision_binding": binding}}
        with self.assertRaises(WorkflowError) as caught:
            _verify_publish_revision_bindings(
                "octo/example",
                "102",
                {"metadata": {}},
                [("github-thread:abc", item)],
                client,
            )

        self.assertEqual(caught.exception.reason_code, "STALE_REQUEST_CONTEXT")
        self.assertEqual(caught.exception.waiting_on, "stack_refresh")
        self.assertEqual(client.side_effect_count, 0)

    def test_head_or_topology_change_makes_binding_stale(self):
        from gh_address_cr.core.runtime_kernel.stack import (
            compare_revision_binding,
            project_stack_context,
            revision_binding_for_context,
        )

        original = project_stack_context(stack_observation(selected_pr_number="102"))
        binding = revision_binding_for_context(original)
        changed = stack_observation(selected_pr_number="102")
        changed["members"][1]["head_oid"] = "f" * 40
        refreshed = project_stack_context(changed)

        self.assertEqual(compare_revision_binding(binding, refreshed), "STALE_REQUEST_CONTEXT")

    def test_binding_for_different_selected_pr_is_rejected(self):
        from gh_address_cr.core.runtime_kernel.stack import (
            compare_revision_binding,
            project_stack_context,
            revision_binding_for_context,
        )

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        binding = revision_binding_for_context(context)
        wrong_owner = project_stack_context(stack_observation(selected_pr_number="103"))

        self.assertEqual(compare_revision_binding(binding, wrong_owner), "STACK_ACTION_CONTEXT_MISMATCH")


class StackFinalGateContractTests(unittest.TestCase):
    def test_machine_contract_names_stack_segment_and_covered_range(self):
        from gh_address_cr.core.gate import GateResult
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: GateResult("octo/example", pr, {}, []),
            closing_context=context,
        ).to_machine_summary()

        self.assertEqual(result["schema_version"], "stack_gate_result.v1")
        self.assertEqual(result["completion_scope"], "stack_segment")
        self.assertEqual(result["stack_gate"]["covered_pr_numbers"], ["101", "102"])


class TelemetryPrivacyContractTests(unittest.TestCase):
    def test_stack_telemetry_contains_only_bounded_dimensions(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context
        from gh_address_cr.core.telemetry_safety import stack_telemetry_attributes

        attributes = stack_telemetry_attributes(project_stack_context(stack_observation()))

        self.assertEqual(
            set(attributes),
            {
                "gh_address_cr.stack.availability",
                "gh_address_cr.stack.size_bucket",
                "gh_address_cr.stack.position_bucket",
            },
        )


class StackReasonCodeContractTests(unittest.TestCase):
    def test_stack_reason_codes_are_canonical_constants(self):
        for name in STACK_REASON_CODES:
            self.assertEqual(getattr(protocol_codes, name), name)


class StackContextContractTests(unittest.TestCase):
    def test_present_context_serializes_versioned_additive_machine_shape(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        payload = project_stack_context(stack_observation()).to_dict()

        self.assertEqual(payload["schema_version"], "stack_context.v1")
        self.assertEqual(payload["availability"], "present")
        self.assertEqual(payload["stack"]["number"], 7)
        self.assertEqual(payload["stack"]["selected_position"], 2)
        self.assertEqual(len(payload["stack"]["members"]), 3)
        self.assertIn("topology_fingerprint", payload)

    def test_unavailable_context_has_bounded_diagnostics(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        payload = project_stack_context(
            {
                "schema_version": "stack_observation.v1",
                "availability": "unavailable",
                "repo": "octo/example",
                "selected_pr_number": "101",
                "observed_at": "2026-08-01T12:00:00Z",
                "diagnostic_code": "STACK_CONTEXT_UNAVAILABLE",
                "members": [],
            }
        ).to_dict()

        self.assertEqual(
            payload["diagnostic"],
            {"reason_code": "STACK_CONTEXT_UNAVAILABLE"},
        )
        self.assertNotIn("raw_response", payload)


if __name__ == "__main__":
    unittest.main()
