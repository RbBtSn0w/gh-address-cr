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

    def test_prefers_fetch_url_even_when_push_line_comes_first(self):
        # A dedupe that just keeps "whichever line was seen first" silently picks the
        # push URL whenever git happens to list it before the fetch URL, even though
        # fetch and push can genuinely differ (HTTPS fetch, SSH push, say).
        with patch.object(
            active_pr,
            "_git_output",
            return_value=(
                "upstream\thttps://push.example.com/houjoe0829/example.git (push)\n"
                "upstream\thttps://fetch.example.com/houjoe0829/example.git (fetch)\n"
            ),
        ):
            remotes = active_pr._other_git_remotes()

        self.assertEqual(remotes, {"upstream": "https://fetch.example.com/houjoe0829/example.git"})

    def test_strips_embedded_credentials_from_remote_urls(self):
        # This URL reaches next_action, which is written to stdout/stderr -- an
        # embedded token must not be echoed back out.
        with patch.object(
            active_pr,
            "_git_output",
            return_value="upstream\thttps://ghp_secrettoken123@github.com/houjoe0829/example.git (fetch)\n",
        ):
            remotes = active_pr._other_git_remotes()

        self.assertEqual(remotes, {"upstream": "https://github.com/houjoe0829/example.git"})
        self.assertNotIn("ghp_secrettoken123", remotes["upstream"])

    def test_leaves_ssh_scp_style_remotes_unchanged(self):
        # `git@host:path` carries no embedded secret -- it's always the fixed "git"
        # SSH login name, not a credential -- and isn't a "scheme://" URL to begin with.
        with patch.object(
            active_pr,
            "_git_output",
            return_value="upstream\tgit@github.com:houjoe0829/example.git (fetch)\n",
        ):
            remotes = active_pr._other_git_remotes()

        self.assertEqual(remotes, {"upstream": "git@github.com:houjoe0829/example.git"})


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
            {
                "repo": "owner/repo",
                "head": "feature",
                "pr_number": "77",
                "repo_source": "--repo",
                "head_source": "--head",
            },
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
            payload["resolved"],
            {"repo": "RbBtSn0w/example", "head": "feature-x", "repo_source": "--repo", "head_source": "--head"},
        )
        self.assertIn("Other remotes:", payload["next_action"])
        self.assertIn("upstream", payload["next_action"])
        self.assertIn("houjoe0829/example.git", payload["next_action"])
        # --repo was already passed explicitly here, so telling the user to "pass
        # --repo explicitly" would be self-contradictory; it must ask for a
        # *different* value instead.
        self.assertIn("different --repo value", payload["next_action"])
        self.assertNotIn("Pass --repo explicitly", payload["next_action"])

    def test_no_active_pr_with_derived_repo_still_suggests_passing_repo_explicitly(self):
        with (
            patch.object(active_pr.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(
                active_pr,
                "run_cmd",
                return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr=""),
            ),
            patch.object(
                active_pr,
                "_derive_current_repo",
                return_value="RbBtSn0w/example",
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
            exit_code, payload = self._run(["--head", "feature-x"])

        self.assertEqual(exit_code, 4)
        self.assertEqual(payload["resolved"]["repo_source"], "remote.origin.url")
        self.assertEqual(payload["resolved"]["head_source"], "--head")
        # No --repo was passed here, so this guidance is still actionable as written.
        self.assertIn("Pass --repo explicitly", payload["next_action"])
        self.assertNotIn("different --repo value", payload["next_action"])

    def test_resolved_repo_and_head_sources_are_derived_independently(self):
        # repo_source and head_source used to collapse into one `source` field even
        # though --repo and --head are independently either passed or derived.
        with (
            patch.object(active_pr.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(
                active_pr,
                "run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(
                        [{"number": 5, "url": "https://github.test/pull/5", "headRefName": "feature", "state": "OPEN"}]
                    ),
                    stderr="",
                ),
            ),
            patch.object(active_pr, "_derive_current_branch", return_value="feature"),
        ):
            exit_code, payload = self._run(["--repo", "owner/repo"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["resolved"]["repo_source"], "--repo")
        self.assertEqual(payload["resolved"]["head_source"], "git branch --show-current")

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
