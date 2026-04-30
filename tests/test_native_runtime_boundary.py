import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr import cli


class NativeRuntimeBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.state_dir = self.root / "state"
        self.repo = "octo/example"
        self.pr_number = "42"
        self.original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)

    def tearDown(self):
        if self.original_state_dir is None:
            os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
        else:
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = self.original_state_dir
        self.temp_dir.cleanup()

    def run_cli_without_legacy_scripts(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(cli, "SCRIPT_DIR", self.root / "missing-legacy-scripts"),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            rc = cli.main(list(args))
        return rc, stdout.getvalue(), stderr.getvalue()

    def write_findings(self, payload):
        path = self.root / "findings.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def install_fake_gh(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if args[:2] == ['auth', 'status']:",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'user']:",
                    "    print(json.dumps({'login': 'codex'}))",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'graphql']:",
                    "    print(json.dumps({'data': {'repository': {'pullRequest': {'reviewThreads': {'nodes': [], 'pageInfo': {'hasNextPage': False}}}}}}))",
                    "    raise SystemExit(0)",
                    "print('unhandled gh args: ' + ' '.join(args), file=sys.stderr)",
                    "raise SystemExit(1)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def test_findings_command_runs_without_legacy_scripts(self):
        findings = self.write_findings(
            [
                {
                    "title": "Fix edge case",
                    "body": "The boundary test should create a blocking local finding.",
                    "path": "src/example.py",
                    "line": 12,
                }
            ]
        )

        rc, stdout, stderr = self.run_cli_without_legacy_scripts(
            "findings",
            self.repo,
            self.pr_number,
            "--input",
            str(findings),
        )

        self.assertEqual(rc, 5)
        self.assertNotIn("Required gh-address-cr runtime script is missing", stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "WAITING_FOR_FIX")
        self.assertEqual(summary["counts"]["open_local_findings_count"], 1)

    def test_review_with_input_runs_without_legacy_scripts(self):
        findings = self.write_findings([])
        bin_dir = self.install_fake_gh()

        with patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}, clear=False):
            rc, stdout, stderr = self.run_cli_without_legacy_scripts(
                "review",
                self.repo,
                self.pr_number,
                "--input",
                str(findings),
            )

        self.assertEqual(rc, 0)
        self.assertNotIn("Required gh-address-cr runtime script is missing", stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["reason_code"], "PASSED")

    def test_threads_command_runs_without_legacy_scripts(self):
        bin_dir = self.install_fake_gh()

        with patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}, clear=False):
            rc, stdout, stderr = self.run_cli_without_legacy_scripts(
                "threads",
                self.repo,
                self.pr_number,
            )

        self.assertEqual(rc, 0)
        self.assertNotIn("Required gh-address-cr runtime script is missing", stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["reason_code"], "PASSED")

    def test_address_command_runs_without_legacy_scripts(self):
        bin_dir = self.install_fake_gh()

        with patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}, clear=False):
            rc, stdout, stderr = self.run_cli_without_legacy_scripts(
                "address",
                self.repo,
                self.pr_number,
            )

        self.assertEqual(rc, 0)
        self.assertNotIn("Required gh-address-cr runtime script is missing", stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["reason_code"], "PASSED")

    def test_adapter_command_runs_without_legacy_scripts(self):
        adapter = self.root / "adapter.py"
        adapter.write_text("import json\nprint(json.dumps([]))\n", encoding="utf-8")
        bin_dir = self.install_fake_gh()

        with patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}, clear=False):
            rc, stdout, stderr = self.run_cli_without_legacy_scripts(
                "adapter",
                self.repo,
                self.pr_number,
                sys.executable,
                str(adapter),
            )

        self.assertEqual(rc, 0)
        self.assertNotIn("Required gh-address-cr runtime script is missing", stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["reason_code"], "PASSED")

    def test_core_public_commands_are_not_legacy_script_mapped(self):
        for command in ("review", "findings", "threads", "adapter", "address"):
            self.assertNotIn(command, cli.COMMAND_TO_SCRIPT)


if __name__ == "__main__":
    unittest.main()
