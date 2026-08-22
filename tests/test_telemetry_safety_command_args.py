from __future__ import annotations

import unittest

from gh_address_cr.core.telemetry_safety import (
    safe_command_args,
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

    def test_safe_command_args_preserves_safe_arguments(self) -> None:
        argv = ["gh-address-cr", "agent", "resolve", "owner/repo", "123", "--batch", "--trivial=False"]
        expected = ["gh-address-cr", "agent", "resolve", "owner/repo", "123", "--batch", "--trivial=False"]
        self.assertEqual(safe_command_args(argv), expected)

    def test_safe_command_args_redacts_tokens(self) -> None:
        argv = [
            "gh-address-cr",
            "ghp_1234567890abcdef",
            "github_pat_123456",
            "xoxb-1234",
            "bearer abc",
            "sk-abc",
        ]
        expected = [
            "gh-address-cr",
            "[redacted]",
            "[redacted]",
            "[redacted]",
            "[redacted]",
            "[redacted]",
        ]
        self.assertEqual(safe_command_args(argv), expected)

    def test_safe_command_args_redacts_private_identifiers(self) -> None:
        argv = [
            "gh-address-cr",
            "my-username-is-snow",
            "machine_id_123",
            "host-name-localhost",
        ]
        expected = [
            "gh-address-cr",
            "[redacted]",
            "[redacted]",
            "[redacted]",
        ]
        self.assertEqual(safe_command_args(argv), expected)

    def test_safe_command_args_redacts_absolute_paths(self) -> None:
        argv = [
            "gh-address-cr",
            "/Users/snow/Documents/GitHub/gh-address-cr-skill",
            "/tmp/test.log",
            "c:\\users\\snow\\file.txt",
            "/var/folders/something",
        ]
        expected = [
            "gh-address-cr",
            "[redacted]",
            "[redacted]",
            "[redacted]",
            "[redacted]",
        ]
        self.assertEqual(safe_command_args(argv), expected)

    def test_safe_command_args_redacts_space_separated_values(self) -> None:
        argv = [
            "gh-address-cr",
            "--token",
            "ghp_1234",
            "--password",
            "mysecret",
            "--secret-key",
            "abc",
            "--normal-flag",
            "safe-value",
        ]
        expected = [
            "gh-address-cr",
            "--token",
            "[redacted]",
            "--password",
            "[redacted]",
            "--secret-key",
            "[redacted]",
            "--normal-flag",
            "safe-value",
        ]
        self.assertEqual(safe_command_args(argv), expected)

    def test_safe_command_args_redacts_flag_value_half(self) -> None:
        argv = [
            "gh-address-cr",
            "--token=ghp_1234",
            "--password=mysecret",
            "--path=/Users/snow/tmp",
            "--username=snow",
            "--secret-key=abc",
            "--normal-flag=safe-value",
        ]
        expected = [
            "gh-address-cr",
            "--token=[redacted]",
            "--password=[redacted]",
            "--path=[redacted]",
            "--username=[redacted]",
            "--secret-key=[redacted]",
            "--normal-flag=safe-value",
        ]
        self.assertEqual(safe_command_args(argv), expected)

    def test_safe_command_args_preserves_positions_and_lengths(self) -> None:
        argv = [
            "gh-address-cr",
            "ghp_123",
            "safe-arg",
            "/Users/snow/path",
            "--token=abc",
            "another-safe-arg",
        ]
        expected = [
            "gh-address-cr",
            "[redacted]",
            "safe-arg",
            "[redacted]",
            "--token=[redacted]",
            "another-safe-arg",
        ]
        result = safe_command_args(argv)
        self.assertEqual(len(result), len(argv))
        self.assertEqual(result, expected)

    def test_safe_command_args_does_not_mutate_original_list(self) -> None:
        argv = ["cmd", "ghp_123"]
        original = list(argv)
        result = safe_command_args(argv)
        self.assertEqual(argv, original)
        self.assertEqual(result, ["cmd", "[redacted]"])


if __name__ == "__main__":
    unittest.main()
