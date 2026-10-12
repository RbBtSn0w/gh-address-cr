"""Contract tests for the root-span invocation kind (docs/rfcs/043-telemetry-invocation-kind)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr import __version__
from tests.helpers import run_cli_under_memory_exporter

KIND = "gh_address_cr.invocation.kind"
ALLOWED_KINDS = {"command", "help", "version", "usage_error"}


class InvocationKindTests(unittest.TestCase):
    def test_invocations_that_exit_during_argument_parsing_are_classified(self) -> None:
        for argv, kind, exit_code in (
            (["--help"], "help", 0),
            (["-h"], "help", 0),
            (["--he"], "help", 0),
            (["--version"], "version", 0),
            (["-v"], "version", 0),
            (["--vers"], "version", 0),
            (["-vh"], "version", 0),
            (["-hv"], "help", 0),
            (["-v", "--help"], "version", 0),
            (["--help", "-v"], "help", 0),
            (["--human", "--help"], "help", 0),
            (["--human", "-v"], "version", 0),
            ([], "usage_error", 2),
            (["--no-such-flag"], "usage_error", 2),
            (["--h"], "usage_error", 2),
            (["-V"], "usage_error", 2),
        ):
            with self.subTest(argv=argv):
                result, root, _, _ = run_cli_under_memory_exporter(argv)

                self.assertEqual(result, exit_code)
                self.assertEqual(root.attributes["process.exit.code"], exit_code)
                self.assertEqual(root.attributes[KIND], kind)

    def test_version_flags_still_print_the_version_and_help_still_prints_usage(self) -> None:
        for argv in (["--version"], ["-v"], ["-vh"]):
            with self.subTest(argv=argv):
                _, _, _, stdout = run_cli_under_memory_exporter(argv)

                self.assertEqual(stdout, f"gh-address-cr {__version__}\n")
        for argv in (["--help"], ["-h"]):
            with self.subTest(argv=argv):
                _, _, _, stdout = run_cli_under_memory_exporter(argv)

                self.assertTrue(stdout.startswith("usage: gh-address-cr"), stdout[:80])
                self.assertIn("--version, -v", stdout)

    def test_invocations_that_reach_dispatch_are_commands(self) -> None:
        for argv, exit_code in (
            (["version"], 0),
            (["address", "-h"], 0),
            (["agent", "manifest"], 0),
            (["bogus"], 2),
        ):
            with self.subTest(argv=argv):
                result, root, _, _ = run_cli_under_memory_exporter(argv)

                self.assertEqual(result, exit_code)
                self.assertEqual(root.attributes["process.exit.code"], exit_code)
                self.assertEqual(root.attributes[KIND], "command")

    def test_kind_is_always_one_of_the_bounded_values(self) -> None:
        for argv in (["--help"], [], ["version"], ["my-token-ghp_FAKE123456"], ["/Users/someone/private/path"]):
            with self.subTest(argv=argv):
                _, root, _, _ = run_cli_under_memory_exporter(argv)

                self.assertIn(root.attributes[KIND], ALLOWED_KINDS)

    def test_only_dispatched_invocations_carry_command_path(self) -> None:
        for argv, dispatched in ((["--help"], False), (["-v"], False), ([], False), (["version"], True)):
            with self.subTest(argv=argv):
                _, root, _, _ = run_cli_under_memory_exporter(argv)

                self.assertEqual("gh_address_cr.command.path" in root.attributes, dispatched)
                self.assertEqual(root.attributes[KIND] == "command", dispatched)

    def test_command_session_operations_classify_themselves_without_changing_the_root(self) -> None:
        operations = [
            {"id": "a", "argv": ["version"]},
            {"id": "b", "argv": ["--help"]},
            {"id": "c", "argv": ["-vh"]},
            {"id": "d", "argv": []},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            session_file = Path(tmp) / "commands.json"
            session_file.write_text(json.dumps({"operations": operations}), encoding="utf-8")

            _, root, spans, _ = run_cli_under_memory_exporter(["command-session", "--input", str(session_file)])

        self.assertEqual(root.attributes[KIND], "command")
        operation_kinds = [
            span.attributes[KIND] for span in spans if span.name == "gh_address_cr.command_session.operation"
        ]
        self.assertEqual(operation_kinds, ["command", "help", "version", "usage_error"])

    def test_a_failing_span_write_never_changes_the_exit_or_the_command(self) -> None:
        from gh_address_cr import otel_tracing

        original = otel_tracing.set_current_span_attributes

        def failing_for_kind(attributes):
            if KIND in attributes:
                raise RuntimeError("telemetry backend failure")
            return original(attributes)

        with patch.object(otel_tracing, "set_current_span_attributes", failing_for_kind):
            for argv, exit_code in ((["--help"], 0), (["-v"], 0), ([], 2), (["version"], 0)):
                with self.subTest(argv=argv):
                    result, root, _, _ = run_cli_under_memory_exporter(argv)

                    self.assertEqual(result, exit_code)
                    self.assertEqual(root.attributes["process.exit.code"], exit_code)
                    self.assertNotIn(KIND, root.attributes)


if __name__ == "__main__":
    unittest.main()
