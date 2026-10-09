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


class StackRevisionBindingContentTests(unittest.TestCase):
    """Evidence binds to the validated tree, not to commit identity or whole-stack topology (spec 040 R2)."""

    @staticmethod
    def _binding_and_compare(selected, before, after):
        from gh_address_cr.core.runtime_kernel.stack import (
            compare_revision_binding,
            project_stack_context,
            revision_binding_for_context,
        )

        binding = revision_binding_for_context(project_stack_context(stack_observation(selected_pr_number=selected, **before)))
        refreshed = project_stack_context(stack_observation(selected_pr_number=selected, **after))
        return binding, compare_revision_binding(binding, refreshed)

    @staticmethod
    def _members(**overrides):
        spec = {
            "101": dict(base="main", head="feature/base"),
            "102": dict(base="feature/base", head="feature/middle"),
            "103": dict(base="feature/middle", head="feature/top"),
        }
        return [
            stack_member(position, pr, **{**kwargs, **overrides.get(pr, {})})
            for position, (pr, kwargs) in enumerate(spec.items(), start=1)
        ]

    def test_binding_is_v2_and_carries_tree_for_gating(self):
        binding, _ = self._binding_and_compare(
            "102", {"members": self._members()}, {"members": self._members()}
        )

        self.assertEqual(binding["schema_version"], "revision_binding.v2")
        self.assertEqual(binding["head_tree_oid"], chr(ord("a") + 2) * 40)
        self.assertEqual(binding["head_oid"], "2" * 40)

    def test_rebase_with_unchanged_content_keeps_every_binding_current(self):
        rebased = self._members(
            **{pr: {"head_oid": "9" * 39 + str(i)} for i, pr in enumerate(("101", "102", "103"), start=1)}
        )
        for selected in ("101", "102", "103"):
            with self.subTest(selected=selected):
                _, result = self._binding_and_compare(
                    selected, {"members": self._members()}, {"members": rebased}
                )
                self.assertIsNone(result)

    def test_lower_layer_content_change_stales_upper_layer(self):
        changed = self._members(**{"101": {"head_tree_oid": "9" * 40}, "102": {"head_tree_oid": "8" * 40}})
        _, result = self._binding_and_compare("102", {"members": self._members()}, {"members": changed})

        self.assertEqual(result, "STALE_REQUEST_CONTEXT")

    def test_upper_layer_change_does_not_stale_lower_layer(self):
        changed = self._members(
            **{
                "102": {"head_oid": "9" * 40, "head_tree_oid": "8" * 40},
                "103": {"head_oid": "7" * 40, "head_tree_oid": "6" * 40},
            }
        )
        _, result = self._binding_and_compare("101", {"members": self._members()}, {"members": changed})

        self.assertIsNone(result)

    def test_position_renumbering_after_bottom_merge_keeps_binding_current(self):
        after_merge = [
            stack_member(1, 102, base="main", head="feature/middle", head_oid="9" * 40, head_tree_oid="c" * 40),
            stack_member(2, 103, base="feature/middle", head="feature/top", head_oid="8" * 40),
        ]
        _, result = self._binding_and_compare("102", {"members": self._members()}, {"members": after_merge})

        self.assertIsNone(result)

    def test_v1_binding_is_stale(self):
        from gh_address_cr.core.runtime_kernel.stack import compare_revision_binding, project_stack_context

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        v1 = {
            "schema_version": "revision_binding.v1",
            "pr_number": "102",
            "head_oid": context.selected_pr.head_oid,
            "stack_number": context.stack_number,
            "stack_position": 2,
            "topology_fingerprint": context.topology_fingerprint,
        }

        self.assertEqual(compare_revision_binding(v1, context), "STALE_REQUEST_CONTEXT")

    def test_member_without_tree_oid_projects_invalid_context(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        observation = stack_observation()
        del observation["members"][1]["head_tree_oid"]
        context = project_stack_context(observation)

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "missing_head_tree_oid")

    def test_merged_member_with_deleted_branch_does_not_need_a_tree(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        observation = stack_observation(
            selected_pr_number="102",
            members=[
                stack_member(1, 101, base="main", head="feature/base", state="MERGED", head_tree_oid=""),
                stack_member(2, 102, base="main", head="feature/middle"),
                stack_member(3, 103, base="feature/middle", head="feature/top"),
            ],
        )
        observation["members"][0].pop("head_tree_oid")

        self.assertEqual(project_stack_context(observation).availability, "present")


if __name__ == "__main__":
    unittest.main()
