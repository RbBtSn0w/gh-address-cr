import json
import subprocess
import unittest


def completed(cmd, payload, returncode=0, stderr=""):
    stdout = json.dumps(payload) if not isinstance(payload, str) else payload
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


class RecordingRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if not self.responses:
            raise AssertionError(f"Unexpected command: {cmd}")
        response = self.responses.pop(0)
        return response(list(cmd)) if callable(response) else response


class NativeGitHubClientTests(unittest.TestCase):
    def test_evaluation_observations_are_read_only_correlated_and_privacy_safe(self):
        from gh_address_cr.github.client import GitHubClient

        runner = RecordingRunner(
            [
                lambda cmd: completed(cmd, {"head": {"sha": "abc"}}),
                lambda cmd: completed(cmd, [{"id": 7, "state": "APPROVED", "submitted_at": "2099-01-01T00:00:00Z", "user": {"login": "reviewer"}}]),
                lambda cmd: completed(cmd, {"login": "agent"}),
                lambda cmd: completed(cmd, {"data": {"repository": {"pullRequest": {"reviewThreads": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [{"id": "THREAD_1", "isResolved": True, "comments": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}, "firstComment": {"nodes": [{"author": {"login": "reviewer"}}]}, "latestComment": {"nodes": []}}]}}}}}),
            ]
        )

        rows = GitHubClient(runner=runner).evaluation_observations("owner/repo", "12", "run-1")

        self.assertEqual(rows[0]["item_id"], "github-thread:THREAD_1")
        self.assertEqual(rows[0]["reviewer_relation"], "original_concern_author")
        self.assertNotIn("username", rows[0])
        self.assertTrue(all("mutation" not in " ".join(call).lower() for call in runner.calls))

    def test_default_runner_uses_central_measured_command_boundary(self):
        from unittest.mock import patch

        from gh_address_cr.github.client import GitHubClient

        expected = completed(["gh", "api", "user"], {"login": "octocat"})
        with patch("gh_address_cr.core.command_runner.run_cmd", return_value=expected) as run_cmd:
            result = GitHubClient._default_runner(["gh", "api", "user"])

        self.assertIs(result, expected)
        run_cmd.assert_called_once_with(["gh", "api", "user"], retries=1)

    def test_list_threads_formats_graphql_request_and_enriches_viewer_reply_evidence(self):
        from gh_address_cr.github.client import GitHubClient

        runner = RecordingRunner(
            [
                lambda cmd: completed(cmd, {"login": "octocat"}),
                lambda cmd: completed(
                    cmd,
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                                        "nodes": [
                                            {
                                                "id": "THREAD_1",
                                                "isResolved": False,
                                                "isOutdated": False,
                                                "path": "src/example.py",
                                                "line": 12,
                                                "comments": {
                                                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                                                    "nodes": [
                                                        {
                                                            "url": "https://github.test/original",
                                                            "author": {"login": "reviewer"},
                                                        }
                                                    ],
                                                },
                                                "firstComment": {
                                                    "nodes": [
                                                        {
                                                            "url": "https://github.test/original",
                                                            "body": "Please fix.",
                                                            "author": {"login": "reviewer"},
                                                        }
                                                    ]
                                                },
                                                "latestComment": {
                                                    "nodes": [
                                                        {
                                                            "url": "https://github.test/original",
                                                            "body": "Please fix.",
                                                            "author": {"login": "reviewer"},
                                                        }
                                                    ]
                                                },
                                            }
                                        ],
                                    }
                                }
                            }
                        }
                    },
                ),
                lambda cmd: completed(
                    cmd,
                    {
                        "data": {
                            "node": {
                                "comments": {
                                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                                    "nodes": [{"url": "https://github.test/reply", "author": {"login": "octocat"}}],
                                }
                            }
                        }
                    },
                ),
            ]
        )

        rows = GitHubClient(runner=runner).list_threads("owner/repo", "123")

        self.assertEqual(rows[0]["id"], "THREAD_1")
        self.assertEqual(rows[0]["body"], "Please fix.")
        self.assertEqual(rows[0]["first_author_login"], "reviewer")
        self.assertTrue(rows[0]["viewer_reply_checked"])
        self.assertTrue(rows[0]["viewer_replied"])
        self.assertEqual(rows[0]["viewer_reply_url"], "https://github.test/reply")
        self.assertIn("api", runner.calls[1])
        self.assertIn("graphql", runner.calls[1])
        self.assertTrue(any("reviewThreads(first:100" in part for part in runner.calls[1]))
        self.assertIn("owner=owner", runner.calls[1])
        self.assertIn("name=repo", runner.calls[1])
        self.assertIn("number=123", runner.calls[1])
        self.assertTrue(any("node(id:$threadId)" in part for part in runner.calls[2]))

    def test_post_reply_returns_created_comment_url(self):
        from gh_address_cr.github.client import GitHubClient

        runner = RecordingRunner(
            [
                lambda cmd: completed(
                    cmd,
                    {"data": {"addPullRequestReviewThreadReply": {"comment": {"url": "https://github.test/reply"}}}},
                )
            ]
        )

        reply_url = GitHubClient(runner=runner).post_reply("owner/repo", "123", "THREAD_1", "Fixed.")

        self.assertEqual(reply_url, "https://github.test/reply")
        self.assertTrue(any("addPullRequestReviewThreadReply" in part for part in runner.calls[0]))
        self.assertIn("threadId=THREAD_1", runner.calls[0])
        self.assertIn("body=Fixed.", runner.calls[0])

    def test_resolve_thread_returns_true_only_for_resolved_thread(self):
        from gh_address_cr.github.client import GitHubClient

        runner = RecordingRunner(
            [
                lambda cmd: completed(
                    cmd,
                    {"data": {"resolveReviewThread": {"thread": {"id": "THREAD_1", "isResolved": True}}}},
                )
            ]
        )

        resolved = GitHubClient(runner=runner).resolve_thread("owner/repo", "123", "THREAD_1")

        self.assertTrue(resolved)
        self.assertTrue(any("resolveReviewThread" in part for part in runner.calls[0]))
        self.assertIn("threadId=THREAD_1", runner.calls[0])

    def test_github_failures_are_classified_from_gh_output(self):
        from gh_address_cr.github.client import GitHubClient
        from gh_address_cr.github.errors import GitHubAuthError, GitHubRateLimitError, GitHubTransientError

        with self.assertRaises(GitHubAuthError):
            GitHubClient(
                runner=RecordingRunner([completed(["gh"], {}, returncode=1, stderr="authentication required")])
            ).post_reply("owner/repo", "123", "THREAD_1", "body")

        with self.assertRaises(GitHubRateLimitError):
            GitHubClient(
                runner=RecordingRunner([completed(["gh"], {"errors": [{"message": "API rate limit exceeded"}]})])
            ).resolve_thread("owner/repo", "123", "THREAD_1")

        with self.assertRaises(GitHubTransientError):
            GitHubClient(
                runner=RecordingRunner(
                    [
                        completed(["gh"], {"login": "octocat"}),
                        completed(["gh"], {}, returncode=1, stderr="503 Service Unavailable"),
                    ]
                )
            ).list_threads("owner/repo", "123")

    def test_list_pr_checks_raises_when_lookup_fails_without_json(self):
        from gh_address_cr.github.client import GitHubClient
        from gh_address_cr.github.errors import GitHubError

        runner = RecordingRunner([subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="not found")])

        with self.assertRaises(GitHubError):
            GitHubClient(runner=runner).list_pr_checks("owner/repo", "123")

    def test_list_pr_checks_accepts_failed_checks_json(self):
        from gh_address_cr.github.client import GitHubClient

        runner = RecordingRunner([completed(["gh"], [{"name": "unit", "bucket": "fail"}], returncode=1)])

        checks = GitHubClient(runner=runner).list_pr_checks("owner/repo", "123")

        self.assertEqual(checks, [{"name": "unit", "bucket": "fail"}])


if __name__ == "__main__":
    unittest.main()
