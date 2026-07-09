"""Canonical disposition/terminal-resolution vocabulary contract (spec 029).

T025 widens this to the 5-site cross-command equality check: `agent resolve`'s
`--disposition` choices, `submit_action`'s `--resolution` choices (T029,
constant-sourced), `agent.roles.TERMINAL_RESOLUTIONS`,
`core.agent_protocol_evidence.TERMINAL_RESOLUTIONS`, and
`agent.responses.WORKFLOW_DECISIONS`. `agent evidence add` is explicitly NOT
a 6th site (SC-004a) — it has no disposition/resolution surface.
"""

from __future__ import annotations

import unittest

from gh_address_cr.agent.roles import TERMINAL_RESOLUTIONS


class DispositionVocabularyBaselineTest(unittest.TestCase):
    def test_terminal_resolutions_is_non_empty(self):
        self.assertTrue(TERMINAL_RESOLUTIONS)

    def test_terminal_resolutions_is_exactly_the_canonical_set(self):
        self.assertEqual(TERMINAL_RESOLUTIONS, {"fix", "clarify", "defer", "reject"})


class FiveSiteVocabularyAlignmentTest(unittest.TestCase):
    """T025: all five sites agree, modulo the two documented exceptions."""

    SHARED_INTERSECTION = {"fix", "reject", "clarify"}

    def _agent_resolve_disposition_choices(self) -> set[str]:
        import re

        from gh_address_cr.commands.agent import handle_agent_resolve

        with self.assertRaises(SystemExit):
            handle_agent_resolve(None, ["o/r", "1", "--disposition", "__not_a_real_choice__"])
        stderr = self._captured_stderr
        match = re.search(r"invalid choice: '__not_a_real_choice__' \(choose from ([^)]+)\)", stderr)
        self.assertIsNotNone(match, stderr)
        return {token.strip().strip("'") for token in match.group(1).split(",")}

    def setUp(self):
        import contextlib
        import io

        self._stderr_buf = io.StringIO()
        self._stderr_cm = contextlib.redirect_stderr(self._stderr_buf)
        self._stderr_cm.__enter__()

    def tearDown(self):
        self._stderr_cm.__exit__(None, None, None)

    @property
    def _captured_stderr(self) -> str:
        return self._stderr_buf.getvalue()

    def test_agent_resolve_disposition_is_subset_of_shared_intersection_plus_trivial(self):
        choices = self._agent_resolve_disposition_choices()
        self.assertEqual(choices, self.SHARED_INTERSECTION | {"trivial"})
        self.assertNotIn("defer", choices)

    def test_submit_action_resolution_matches_terminal_resolutions(self):
        from gh_address_cr.commands.submit_action import parse_args as submit_parse_args

        # Exercise the real argparse choices list, not just the source constant,
        # so a drift between the two would fail this test.
        for value in TERMINAL_RESOLUTIONS:
            parsed = submit_parse_args(["req.json", "--resolution", value, "--note", "n"])
            self.assertEqual(parsed.resolution, value)
        self.assertIn("defer", TERMINAL_RESOLUTIONS)

    def test_agent_protocol_evidence_terminal_resolutions_matches(self):
        from gh_address_cr.core.agent_protocol_evidence import TERMINAL_RESOLUTIONS as evidence_set

        self.assertEqual(evidence_set, TERMINAL_RESOLUTIONS)

    def test_workflow_decisions_matches(self):
        from gh_address_cr.agent.responses import WORKFLOW_DECISIONS

        self.assertEqual(WORKFLOW_DECISIONS, TERMINAL_RESOLUTIONS)

    def test_shared_intersection_is_present_in_all_five_sites(self):
        from gh_address_cr.agent.responses import WORKFLOW_DECISIONS
        from gh_address_cr.core.agent_protocol_evidence import TERMINAL_RESOLUTIONS as evidence_set

        agent_resolve_choices = self._agent_resolve_disposition_choices()
        for value in self.SHARED_INTERSECTION:
            self.assertIn(value, agent_resolve_choices)
            self.assertIn(value, TERMINAL_RESOLUTIONS)
            self.assertIn(value, evidence_set)
            self.assertIn(value, WORKFLOW_DECISIONS)

    def test_agent_classify_classification_matches_terminal_resolutions(self):
        # Convergence T043 / FR-006b: --classification hardcoded its own copy
        # of the disposition list instead of drawing from TERMINAL_RESOLUTIONS
        # (same triplication pattern T003 consolidated elsewhere in this file).
        import re

        from gh_address_cr.commands.agent import handle_agent_classify

        with self.assertRaises(SystemExit):
            handle_agent_classify(None, ["o/r", "1", "item", "--classification", "__not_a_real_choice__"])
        match = re.search(
            r"invalid choice: '__not_a_real_choice__' \(choose from ([^)]+)\)", self._captured_stderr
        )
        self.assertIsNotNone(match, self._captured_stderr)
        choices = {token.strip().strip("'") for token in match.group(1).split(",")}
        self.assertEqual(choices, TERMINAL_RESOLUTIONS)


if __name__ == "__main__":
    unittest.main()
