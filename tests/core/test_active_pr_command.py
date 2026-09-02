import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from gh_address_cr.commands import active_pr


class TestOtherGitRemotes(unittest.TestCase):
    def test_excludes_origin_and_dedupes_fetch_push_pairs(self):
        with patch.object(
            active_pr,
            "_git_output",
            return_value=(
                "origin\thttps://github.com/RbBtSn0w/example.git (fetch)\n"
                "origin\thttps://github.com/RbBtSn0w/example.git (push)\n"
                "upstream\thttps://github.com/houjoe0829/example.git (fetch)\n"
                "upstream\thttps://github.com/houjoe0829/example.git (push)\n"
            ),
        ):
            remotes = active_pr._other_git_remotes()

        self.assertEqual(remotes, {"upstream": "https://github.com/houjoe0829/example.git"})

    def test_returns_empty_when_git_remote_fails(self):
        with patch.object(active_pr, "_git_output", side_effect=RuntimeError("not a git repo")):
            self.assertEqual(active_pr._other_git_remotes(), {})


class TestHandleActivePrCommand(unittest.TestCase):
    def _run(self, argv):
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = active_pr.handle_active_pr_command(argv)
        return exit_code, json.loads(buffer.getvalue())

    def test_active_pr_found_echoes_resolved_repo_and_source(self):
        with (
            patch.object(active_pr.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(
                active_pr,
                "run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(
                        [{"number": 77, "url": "https://github.test/pull/77", "headRefName": "feature", "state": "OPEN"}]
                    ),
                    stderr="",
                ),
            ),
        ):
            exit_code, payload = self._run(["--repo", "owner/repo", "--head", "feature"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ACTIVE_PR_FOUND")
        self.assertEqual(
            payload["resolved"],
            {"repo": "owner/repo", "head": "feature", "pr_number": "77", "source": "explicit"},
        )

    def test_no_active_pr_lists_other_remotes_instead_of_silence(self):
        with (
            patch.object(active_pr.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(
                active_pr,
                "run_cmd",
                return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr=""),
            ),
            patch.object(
                active_pr,
                "_git_output",
                return_value=(
                    "origin\thttps://github.com/RbBtSn0w/example.git (fetch)\n"
                    "upstream\thttps://github.com/houjoe0829/example.git (fetch)\n"
                ),
            ),
        ):
            exit_code, payload = self._run(["--repo", "RbBtSn0w/example", "--head", "feature-x"])

        self.assertEqual(exit_code, 4)
        self.assertEqual(payload["status"], "NO_ACTIVE_PR")
        self.assertEqual(
            payload["resolved"], {"repo": "RbBtSn0w/example", "head": "feature-x", "source": "explicit"}
        )
        self.assertIn("Other remotes:", payload["next_action"])
        self.assertIn("upstream", payload["next_action"])
        self.assertIn("houjoe0829/example.git", payload["next_action"])
        self.assertIn("--repo explicitly", payload["next_action"])

    def test_no_active_pr_falls_back_to_generic_hint_without_other_remotes(self):
        with (
            patch.object(active_pr.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(
                active_pr,
                "run_cmd",
                return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr=""),
            ),
            patch.object(active_pr, "_git_output", return_value="origin\thttps://github.com/RbBtSn0w/example.git (fetch)\n"),
        ):
            exit_code, payload = self._run(["--repo", "RbBtSn0w/example", "--head", "feature-x"])

        self.assertEqual(exit_code, 4)
        self.assertNotIn("Other remotes:", payload["next_action"])
        self.assertIn("--state open", payload["next_action"])


if __name__ == "__main__":
    unittest.main()
