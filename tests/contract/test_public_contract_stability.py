"""Public-contract non-regression for the `consolidation` group (FR-009 / SC-009).

Registering the advanced `consolidation` family must be strictly additive: it
must not drift the parsing, routing, exit codes, or output-flag semantics of the
existing public commands (`review`, `threads`, `agent`, `evaluation`, ...).
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from gh_address_cr import cli


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class PublicContractStabilityTests(unittest.TestCase):
    def test_consolidation_is_additive_public_command(self) -> None:
        self.assertIn("consolidation", cli.PUBLIC_COMMANDS)
        # Advanced command: it must NOT join the agent-facing high-level surface.
        self.assertNotIn("consolidation", cli.NATIVE_HIGH_LEVEL_COMMANDS)
        self.assertNotIn("consolidation", cli.HIGH_LEVEL_COMMANDS)

    def test_existing_commands_still_parse(self) -> None:
        for command in ("review", "threads", "address", "agent", "evaluation"):
            args = cli.parse_args([command, "owner/repo", "123"])
            self.assertEqual(args.command, command)

    def test_unknown_command_still_lists_supported_commands(self) -> None:
        rc, _, err = _run(["definitely-not-a-command"])
        self.assertEqual(rc, 2)
        self.assertIn("consolidation", err)  # additive: surfaced in the supported set
        self.assertIn("review", err)  # existing commands still listed

    def test_evaluation_root_flag_rejection_unchanged(self) -> None:
        # Existing advanced-command output-flag contract is untouched.
        rc, _, err = _run(["--machine", "evaluation", "rebuild"])
        self.assertEqual(rc, 2)
        self.assertIn("not supported", err)


if __name__ == "__main__":
    unittest.main()
