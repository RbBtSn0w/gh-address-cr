"""Contract tests for the command-name vocabulary (docs/rfcs/044-command-vocabulary)."""

from __future__ import annotations

import ast
import contextlib
import io
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import RUNTIME_PACKAGE_DIR, run_cli_under_memory_exporter

# The 14 top-level commands, in the order the argparse command list has always shown them,
# with `agent` (which the list used to omit) placed after `active-pr`.
EXPECTED_PUBLIC_COMMAND_ORDER = (
    "active-pr",
    "agent",
    "address",
    "review",
    "threads",
    "findings",
    "adapter",
    "doctor",
    "command-session",
    "final-gate",
    "review-to-findings",
    "submit-feedback",
    "submit-action",
    "version",
)
LEGACY_HELP_COMMAND_ORDER = tuple(name for name in EXPECTED_PUBLIC_COMMAND_ORDER if name != "agent")
EXPECTED_AGENT_SUBCOMMANDS = (
    "manifest",
    "classify",
    "next",
    "submit",
    "resolve",
    "evidence",
    "publish",
    "leases",
    "reclaim",
    "orchestrate",
)


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """Run `cli.main` in-process and return (exit code, stdout, stderr)."""
    from gh_address_cr.cli import main

    stdout, stderr = io.StringIO(), io.StringIO()
    code: int | str | None = 0
    with (
        tempfile.TemporaryDirectory() as tmp,
        patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp, "DISABLE_TELEMETRY": "1"}),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        try:
            code = main(argv)
        except SystemExit as exc:
            code = exc.code
    return int(code or 0), stdout.getvalue(), stderr.getvalue()


class VocabularyModuleTests(unittest.TestCase):
    def test_the_module_holds_the_documented_names(self) -> None:
        from gh_address_cr.core import command_names

        self.assertEqual(command_names.PUBLIC_COMMAND_NAMES, EXPECTED_PUBLIC_COMMAND_ORDER)
        self.assertEqual(command_names.PUBLIC_COMMANDS, frozenset(EXPECTED_PUBLIC_COMMAND_ORDER))
        self.assertEqual(len(command_names.PUBLIC_COMMAND_NAMES), len(command_names.PUBLIC_COMMANDS))
        self.assertEqual(command_names.AGENT_SUBCOMMANDS, EXPECTED_AGENT_SUBCOMMANDS)

    def test_the_module_does_not_depend_on_cli_or_commands(self) -> None:
        tree = ast.parse((RUNTIME_PACKAGE_DIR / "core" / "command_names.py").read_text(encoding="utf-8"))
        imported = [
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [None])
        ]
        self.assertEqual([name for name in imported if name and name != "__future__"], [])

    def test_cli_agent_and_telemetry_share_the_vocabulary(self) -> None:
        from gh_address_cr import cli
        from gh_address_cr.commands import agent
        from gh_address_cr.core import command_names, telemetry_safety

        self.assertIs(cli.PUBLIC_COMMANDS, command_names.PUBLIC_COMMANDS)
        self.assertIs(agent.PUBLIC_COMMANDS, command_names.PUBLIC_COMMANDS)
        self.assertIs(agent.AGENT_SUBCOMMANDS, command_names.AGENT_SUBCOMMANDS)
        self.assertLessEqual(telemetry_safety._PR_SCOPED_COMMANDS, command_names.PUBLIC_COMMANDS)
        for name in command_names.PUBLIC_COMMANDS:
            with self.subTest(command=name):
                self.assertEqual(telemetry_safety.derive_tool_name([name]), name)

    def test_every_cli_behavior_set_is_a_subset_of_the_public_commands(self) -> None:
        from gh_address_cr import cli

        for name in (
            "OUTPUT_MODE_COMMANDS",
            "NATIVE_REVIEW_COMMANDS",
            "UTILITY_COMMANDS",
            "PR_SCOPED_IMPLICIT_COMMANDS",
            "GITHUB_PRECHECK_COMMANDS",
            "INPUT_REQUIRED_COMMANDS",
        ):
            with self.subTest(behavior_set=name):
                self.assertLessEqual(set(getattr(cli, name)), set(cli.PUBLIC_COMMANDS))


class PublicSurfaceTests(unittest.TestCase):
    def test_agent_manifest_public_commands_are_unchanged(self) -> None:
        from gh_address_cr.commands.agent import build_agent_manifest

        self.assertEqual(build_agent_manifest()["public_commands"], sorted(EXPECTED_PUBLIC_COMMAND_ORDER))

    def test_help_lists_every_command_and_differs_from_before_only_by_agent(self) -> None:
        _, _, _, stdout = run_cli_under_memory_exporter(["--help"])

        match = re.search(r"\{(active-pr[^}]*)\}", stdout)
        self.assertIsNotNone(match, stdout)
        listed = tuple(match.group(1).split(","))
        self.assertEqual(listed, EXPECTED_PUBLIC_COMMAND_ORDER)
        self.assertEqual(tuple(name for name in listed if name != "agent"), LEGACY_HELP_COMMAND_ORDER)

    def test_unknown_command_message_and_exit_code_are_unchanged(self) -> None:
        code, stdout, stderr = run_main(["bogus"])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            "Unknown command. Supported commands: "
            + ", ".join(sorted(EXPECTED_PUBLIC_COMMAND_ORDER))
            + ".\n",
        )

    def test_agent_usage_and_unknown_subcommand_messages_derive_from_the_vocabulary(self) -> None:
        names = ",".join(EXPECTED_AGENT_SUBCOMMANDS)

        code, stdout, _ = run_main(["agent"])
        self.assertEqual((code, stdout), (0, f"usage: gh-address-cr agent {{{names}}} ...\n\nAgent protocol utilities.\n"))

        for argv in (["agent", "not-an-agent-subcommand"], ["agent", "manifest", "owner/repo", "1"]):
            with self.subTest(argv=argv):
                code, stdout, stderr = run_main(argv)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr,
                    "Unknown agent command. Supported commands: " + ", ".join(EXPECTED_AGENT_SUBCOMMANDS) + ".\n",
                )


class TelemetryVocabularyTests(unittest.TestCase):
    def test_version_is_exported_by_name_like_every_other_public_command(self) -> None:
        from gh_address_cr.core.telemetry_safety import derive_tool_name

        self.assertEqual(derive_tool_name(["version"]), "version")
        _, root, _, _ = run_cli_under_memory_exporter(["version"])
        self.assertEqual(root.attributes["gen_ai.tool.name"], "version")
        self.assertIn("version", root.attributes["process.command_args"])

    def test_unrecognized_text_is_still_not_exported(self) -> None:
        from gh_address_cr.core.telemetry_safety import derive_tool_name

        for raw in ("bogus", "my-token-ghp_FAKE123456", "--token=ghp_FAKE123456"):
            with self.subTest(raw=raw):
                self.assertEqual(derive_tool_name([raw]), "gh-address-cr")
                _, root, spans, _ = run_cli_under_memory_exporter([raw])
                exported = [str(value) for span in spans for value in span.attributes.values()]
                self.assertFalse([value for value in exported if "ghp_FAKE123456" in value or value == raw])


if __name__ == "__main__":
    unittest.main()
