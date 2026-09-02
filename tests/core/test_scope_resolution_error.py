import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gh_address_cr.commands.common import emit_scope_resolution_error


class TestEmitScopeResolutionError(unittest.TestCase):
    def _run(self, payload):
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = emit_scope_resolution_error(payload)
        return exit_code, json.loads(buffer.getvalue())

    def test_pr_scope_errors_now_carry_remediation(self):
        # NO_ACTIVE_PR_SCOPE / AMBIGUOUS_PR_SCOPE / PARTIAL_PR_SCOPE are emitted here as
        # plain dicts, never through WorkflowError, so remediation_for() used to be
        # unreachable for this whole family despite _PR_SCOPE_CODES existing for it.
        payload = {
            "status": "PR_SCOPE_UNRESOLVED",
            "reason_code": "NO_ACTIVE_PR_SCOPE",
            "waiting_on": "pr_scope",
            "next_action": "Pass <owner/repo> <pr_number> explicitly or create exactly one cached PR session.",
            "candidates": [],
            "exit_code": 2,
        }

        exit_code, emitted = self._run(payload)

        self.assertEqual(exit_code, 2)
        self.assertIn("remediation", emitted)
        self.assertTrue(emitted["remediation"]["summary"])
        self.assertTrue(emitted["remediation"]["command"])

    def test_remediation_command_uses_literal_placeholders_not_broken_values(self):
        # repo/pr_number are unknown at this point -- that's the failure -- so the
        # command must render literal <owner/repo> <pr_number> placeholders rather
        # than a nonsensical filled-in command built from missing values.
        payload = {
            "status": "PR_SCOPE_UNRESOLVED",
            "reason_code": "AMBIGUOUS_PR_SCOPE",
            "waiting_on": "pr_scope",
            "next_action": "Multiple cached PR sessions exist. Pass <owner/repo> <pr_number> explicitly.",
            "candidates": [],
            "exit_code": 2,
        }

        _exit_code, emitted = self._run(payload)

        self.assertEqual(emitted["remediation"]["command"], "gh-address-cr address <owner/repo> <pr_number> --lean")

    def test_existing_payload_fields_are_preserved(self):
        payload = {
            "status": "PR_SCOPE_UNRESOLVED",
            "reason_code": "PARTIAL_PR_SCOPE",
            "waiting_on": "pr_scope",
            "next_action": "Pass both <owner/repo> and <pr_number>, or omit both to use the single cached PR session.",
            "candidates": [],
            "exit_code": 2,
        }

        exit_code, emitted = self._run(payload)

        self.assertEqual(exit_code, 2)
        self.assertEqual(emitted["status"], "PR_SCOPE_UNRESOLVED")
        self.assertEqual(emitted["reason_code"], "PARTIAL_PR_SCOPE")
        self.assertEqual(emitted["waiting_on"], "pr_scope")


if __name__ == "__main__":
    unittest.main()
