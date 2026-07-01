from __future__ import annotations

import unittest

# TDD: This import is expected to fail initially
from gh_address_cr.core.telemetry_safety import safe_command_args


class TelemetrySafetyCommandArgsTestCase(unittest.TestCase):
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
