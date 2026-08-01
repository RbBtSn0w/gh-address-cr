import copy
import unittest

from tests.helpers import load_stacked_pr_fixture, stack_member, stack_observation


class StackKernelTestIntent:
    risk = "Malformed or stale stack topology could produce a false aggregate completion claim."
    why_automation = "Stack facts, projections, fingerprints, and policies are deterministic and replayable."
    chosen_layer = "Unit tests exercise the pure runtime kernel without GitHub or filesystem IO."


class StackKernelTests(unittest.TestCase):
    def test_valid_stack_projects_selected_position_and_stable_fingerprint(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        observation = stack_observation()
        first = project_stack_context(observation)
        replay = project_stack_context(copy.deepcopy(observation))

        self.assertEqual(first.availability, "present")
        self.assertEqual(first.selected_position, 2)
        self.assertEqual([member.pr_number for member in first.members], ["101", "102", "103"])
        self.assertEqual(first.topology_fingerprint, replay.topology_fingerprint)
        self.assertTrue(first.topology_fingerprint.startswith("sha256:"))

    def test_observation_time_does_not_change_topology_fingerprint(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        earlier = stack_observation()
        later = copy.deepcopy(earlier)
        later["observed_at"] = "2026-08-01T12:05:00Z"

        self.assertEqual(
            project_stack_context(earlier).topology_fingerprint,
            project_stack_context(later).topology_fingerprint,
        )

    def test_head_revision_change_changes_topology_fingerprint(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        before = stack_observation()
        after = copy.deepcopy(before)
        after["members"][2]["head_oid"] = "f" * 40

        self.assertNotEqual(
            project_stack_context(before).topology_fingerprint,
            project_stack_context(after).topology_fingerprint,
        )

    def test_merged_prefix_selects_only_active_members_through_anchor(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context, project_stack_segment

        context = project_stack_context(load_stacked_pr_fixture("merged_prefix.json"))
        segment = project_stack_segment(context)

        self.assertEqual([member.pr_number for member in segment.merged_prefix], ["101"])
        self.assertEqual([member.pr_number for member in segment.included_members], ["102", "103"])
        self.assertEqual(segment.excluded_upper_members, ())

    def test_selected_middle_excludes_upper_members(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context, project_stack_segment

        context = project_stack_context(stack_observation(selected_pr_number=102))
        segment = project_stack_segment(context)

        self.assertEqual([member.pr_number for member in segment.included_members], ["101", "102"])
        self.assertEqual([member.pr_number for member in segment.excluded_upper_members], ["103"])

    def test_malformed_positions_project_invalid_context(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        context = project_stack_context(load_stacked_pr_fixture("malformed.json"))

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.diagnostic_code, "STACK_CONTEXT_INVALID")
        self.assertEqual(context.invalid_invariant, "reported_size_mismatch")

    def test_unstacked_explicit_stack_policy_is_one_member_scope(self):
        from gh_address_cr.core.runtime_kernel.stack import evaluate_stack_context_policy, project_stack_context

        observation = {
            "schema_version": "stack_observation.v1",
            "availability": "absent",
            "repo": "octo/example",
            "selected_pr_number": "101",
            "observed_at": "2026-08-01T12:00:00Z",
            "selected_pr": stack_member(1, 101, base="main", head="feature/standalone"),
            "members": [],
        }
        context = project_stack_context(observation)
        decision = evaluate_stack_context_policy(context, explicit_stack=True)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.completion_scope, "stack_segment")
        self.assertEqual(decision.covered_pr_numbers, ("101",))

    def test_unavailable_policy_allows_layer_but_blocks_explicit_stack(self):
        from gh_address_cr.core.runtime_kernel.stack import evaluate_stack_context_policy, project_stack_context

        context = project_stack_context(
            {
                "schema_version": "stack_observation.v1",
                "availability": "unavailable",
                "repo": "octo/example",
                "selected_pr_number": "101",
                "observed_at": "2026-08-01T12:00:00Z",
                "diagnostic_code": "STACK_CONTEXT_UNAVAILABLE",
                "members": [],
            }
        )

        self.assertTrue(evaluate_stack_context_policy(context, explicit_stack=False).allowed)
        blocked = evaluate_stack_context_policy(context, explicit_stack=True)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason_code, "STACK_CONTEXT_UNAVAILABLE")
        self.assertEqual(blocked.waiting_on, "stack_context")


if __name__ == "__main__":
    unittest.main()
