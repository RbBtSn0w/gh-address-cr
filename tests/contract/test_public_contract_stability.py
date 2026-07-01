"""Public-contract non-regression for the reduced core CLI surface."""

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


if __name__ == "__main__":
    unittest.main()
