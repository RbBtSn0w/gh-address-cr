"""Regression test for #115: stdin `-` must fail loud on a TTY, not hang."""

import io
import unittest
from unittest import mock

from gh_address_cr.commands.high_level import _read_findings_input
from gh_address_cr.intake.findings import EMPTY_FINDINGS_INPUT_MESSAGE, FindingsFormatError


class FindingsInputGuardTest(unittest.TestCase):
    def test_dash_on_tty_fails_loud_instead_of_blocking(self):
        fake = io.StringIO("")
        fake.isatty = lambda: True  # type: ignore[assignment]
        with mock.patch("gh_address_cr.commands.high_level.sys.stdin", fake):
            with self.assertRaises(FindingsFormatError) as ctx:
                _read_findings_input("-")
        self.assertEqual(str(ctx.exception), EMPTY_FINDINGS_INPUT_MESSAGE)

    def test_dash_with_piped_input_is_read(self):
        fake = io.StringIO("[]")
        fake.isatty = lambda: False  # type: ignore[assignment]
        with mock.patch("gh_address_cr.commands.high_level.sys.stdin", fake):
            self.assertEqual(_read_findings_input("-"), "[]")


if __name__ == "__main__":
    unittest.main()
