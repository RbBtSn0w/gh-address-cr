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
    def test_bound_request_becomes_stale_when_pr_leaves_stack(self):
        from gh_address_cr.core.runtime_kernel.stack import (
            compare_revision_binding,
            project_stack_context,
            revision_binding_for_context,
        )

        original = project_stack_context(stack_observation(selected_pr_number="102"))
        binding = revision_binding_for_context(original)
        absent = stack_observation(selected_pr_number="102")
        absent.update(
            {
                "availability": "absent",
                "selected_pr": absent["members"][1],
                "members": [],
            }
        )

        self.assertEqual(
            compare_revision_binding(binding, project_stack_context(absent)),
            "STALE_REQUEST_CONTEXT",
        )

    def test_absent_observation_clears_prior_stack_safety_hint(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context
        from gh_address_cr.core.session import cache_pull_request_context, has_observed_stack_membership

        session = {"metadata": {}}
        cache_pull_request_context(
            session,
            project_stack_context(stack_observation(selected_pr_number="102")).to_dict(),
        )
        absent = stack_observation(selected_pr_number="102")
        absent.update(
            {
                "availability": "absent",
                "selected_pr": absent["members"][1],
                "members": [],
            }
        )
        cache_pull_request_context(session, project_stack_context(absent).to_dict())

        self.assertFalse(has_observed_stack_membership(session))

    def test_known_stacked_unbound_publish_blocks_when_refresh_is_unavailable(self):
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.publisher import _verify_publish_revision_bindings
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context
        from gh_address_cr.core.session import cache_pull_request_context

        cached = project_stack_context(stack_observation(selected_pr_number="102")).to_dict()

        class Client:
            def get_stack_context(self, repo, pr_number):
                return project_stack_context(
                    {
                        "schema_version": "stack_observation.v1",
                        "availability": "unavailable",
                        "repo": repo,
                        "selected_pr_number": pr_number,
                        "observed_at": "2026-08-01T12:01:00Z",
                        "members": [],
                    }
                )

        session = {"metadata": {}}
        cache_pull_request_context(session, cached)
        cache_pull_request_context(
            session,
            project_stack_context(
                {
                    "schema_version": "stack_observation.v1",
                    "availability": "unavailable",
                    "repo": "octo/example",
                    "selected_pr_number": "102",
                    "observed_at": "2026-08-01T12:00:30Z",
                    "members": [],
                }
            ).to_dict(),
        )
        item = {"accepted_response": {"validation_commands": [{"command": "unit", "result": "passed"}]}}

        with self.assertRaises(WorkflowError) as caught:
            _verify_publish_revision_bindings(
                "octo/example",
                "102",
                session,
                [("github-thread:abc", item)],
                Client(),
            )

        self.assertEqual(caught.exception.reason_code, "STACK_CONTEXT_UNAVAILABLE")

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
    def test_present_context_rejects_duplicate_member_pr_number(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        observation = stack_observation(selected_pr_number="103")
        observation["members"][1]["pr_number"] = "101"

        context = project_stack_context(observation)

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "duplicate_member_pr_number")

    def test_absent_context_rejects_selected_member_mismatch(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        observation = stack_observation(selected_pr_number="102")
        observation.update(
            {
                "availability": "absent",
                "selected_pr": observation["members"][2],
                "members": [],
            }
        )

        context = project_stack_context(observation)

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "selected_member_mismatch")

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
