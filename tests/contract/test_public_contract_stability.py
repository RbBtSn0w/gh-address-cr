"""Public-contract non-regression for the reduced core CLI surface."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from gh_address_cr import cli


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class PublicContractStabilityTests(unittest.TestCase):
    def test_existing_commands_still_parse(self) -> None:
        for command in ("review", "threads", "address", "agent", "final-gate"):
            args = cli.parse_args([command, "owner/repo", "123"])
            self.assertEqual(args.command, command)

    def test_unknown_command_still_lists_supported_commands(self) -> None:
        rc, _, err = _run(["definitely-not-a-command"])
        self.assertEqual(rc, 2)
        self.assertIn("review", err)  # existing commands still listed
        self.assertNotIn("consolidation", err)
        self.assertNotIn("evaluation", err)

    def test_help_mentions_conversation_id_session_correlation(self) -> None:
        """G-7: --help must surface the GH_ADDRESS_CR_CONVERSATION_ID guidance
        for agents that invoke the CLI directly and never load the skill."""
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            cli.parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        help_text = out.getvalue()
        self.assertIn("GH_ADDRESS_CR_CONVERSATION_ID", help_text)
        # Must document it as optional/fail-open — never implies it's required.
        self.assertIn("Optional", help_text)

    def test_layered_workflow_contract_documents_first_slice_child_span_names(self) -> None:
        text = Path("specs/027-otel-layered-model/contracts/workflow-layering-contract.md").read_text(encoding="utf-8")
        self.assertIn("gh_address_cr.adapter", text)
        self.assertIn("gh_address_cr.command_session.operation", text)

    def test_layered_workflow_contract_keeps_high_level_phases_event_first(self) -> None:
        text = Path("specs/027-otel-layered-model/contracts/workflow-layering-contract.md").read_text(encoding="utf-8")
        self.assertIn("preflight", text)
        self.assertIn("session", text)
        self.assertIn("ingest", text)
        self.assertIn("gate", text)


if __name__ == "__main__":
    unittest.main()
