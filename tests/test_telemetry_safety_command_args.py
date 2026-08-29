from __future__ import annotations

import unittest

from gh_address_cr.core.telemetry_safety import (
    sanitize_cli_argv,
    subprocess_operation,
)


class TelemetrySafetyCommandArgsTestCase(unittest.TestCase):
    def test_cli_argv_retains_only_the_bounded_command_skeleton(self) -> None:
        sanitized, _ = sanitize_cli_argv(
            [
                "/private/bin/gh-address-cr",
                "review",
                "--identifier-private-123",
                "owner/private",
                "123",
            ],
            command_argv=[
                "review",
                "--identifier-private-123",
                "owner/private",
                "123",
            ],
        )

        self.assertEqual(
            sanitized,
            [
                "gh-address-cr",
                "review",
                "[redacted]",
                "[redacted]",
                "[redacted]",
            ],
        )
        unknown, _ = sanitize_cli_argv(
            ["private-command", "--identifier-private-123", "secret"],
            command_argv=["private-command", "--identifier-private-123", "secret"],
            includes_executable=False,
        )
        self.assertEqual(unknown, ["[redacted]", "[redacted]", "[redacted]"])

        root_path, _ = sanitize_cli_argv(
            ["/", "review", "owner/repo", "42"],
            command_argv=["review", "owner/repo", "42"],
        )
        self.assertEqual(
            root_path,
            ["gh-address-cr", "review", "[redacted]", "[redacted]"],
        )

    def test_subprocess_operation_uses_bounded_taxonomy_without_argument_values(self) -> None:
        cases = [
            (["gh", "api", "graphql", "-f", "query=private"], "github.graphql"),
            (["gh", "api", "user"], "github.rest"),
            (["gh", "auth", "status"], "github.auth"),
            (["gh", "pr", "view", "owner/repo"], "github.cli"),
            (["git", "config", "--get", "remote.origin.url"], "git"),
            (["python3", "/Users/private/script.py"], "python3"),
            (["private-tool", "secret"], "subprocess.other"),
            ([], "subprocess.other"),
        ]

        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(subprocess_operation(argv), expected)


if __name__ == "__main__":
    unittest.main()
