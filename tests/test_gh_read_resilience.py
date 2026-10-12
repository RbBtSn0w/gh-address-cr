from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from gh_address_cr import cli
from gh_address_cr.github.client import GH_COMMAND_TIMEOUT_SECONDS, GitHubClient
from gh_address_cr.github.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubTransientError,
)
from gh_address_cr.github.transient_failures import backoff_seconds, is_transient_github_failure_text


def _result(returncode: int = 0, stdout: str = "{}", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


class ScriptedRunner:
    def __init__(self, *results: subprocess.CompletedProcess):
        self._results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


class TransientDetectionTests(unittest.TestCase):
    def test_http_5xx_statuses_are_transient(self) -> None:
        for status in ("500", "502", "503", "504"):
            with self.subTest(status=status):
                self.assertTrue(is_transient_github_failure_text(f"gh: HTTP {status}: Server Error"))

    def test_bare_digits_inside_identifiers_are_not_transient(self) -> None:
        self.assertFalse(is_transient_github_failure_text("PRRT_kwDO5025abc not accessible"))
        self.assertFalse(is_transient_github_failure_text("https://github.com/o/r/pull/502"))
        self.assertFalse(is_transient_github_failure_text("HTTP 404: Not Found"))

    def test_gateway_wording_is_transient(self) -> None:
        self.assertTrue(is_transient_github_failure_text("Bad Gateway"))
        self.assertTrue(is_transient_github_failure_text("Gateway Time-out"))

    def test_backoff_is_jittered_and_exponential(self) -> None:
        for attempt in range(3):
            value = backoff_seconds(attempt)
            self.assertGreaterEqual(value, (2**attempt) * 0.5)
            self.assertLessEqual(value, 2**attempt)


@patch("gh_address_cr.github.client.time.sleep")
class ReadRetryTests(unittest.TestCase):
    def test_transient_read_failure_is_retried_until_success(self, sleep) -> None:
        runner = ScriptedRunner(
            _result(1, "", "HTTP 502: Bad Gateway"),
            _result(1, "", "HTTP 504: Gateway Timeout"),
            _result(0, json.dumps({"login": "octo"})),
        )
        self.assertEqual(GitHubClient(runner=runner).viewer_login(), "octo")
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_exit_zero_graphql_transient_errors_are_retried(self, sleep) -> None:
        errors = json.dumps({"errors": [{"message": "GraphQL error: something went wrong"}]})
        runner = ScriptedRunner(_result(0, errors), _result(0, json.dumps({"login": "octo"})))
        self.assertEqual(GitHubClient(runner=runner).viewer_login(), "octo")
        self.assertEqual(len(runner.calls), 2)
        sleep.assert_called_once()

    def test_gives_up_after_bounded_attempts(self, sleep) -> None:
        runner = ScriptedRunner(_result(1, "", "HTTP 503: Service Unavailable"))
        with self.assertRaises(GitHubTransientError):
            GitHubClient(runner=runner).viewer_login()
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_deterministic_failures_are_not_retried(self, sleep) -> None:
        cases = (
            (GitHubAuthError, "gh: Bad credentials (HTTP 401)"),
            (GitHubNotFoundError, "HTTP 404: Not Found"),
            (GitHubRateLimitError, "API rate limit exceeded (secondary rate limit)"),
            (GitHubError, "Field 'stack' doesn't exist on type 'PullRequest'"),
        )
        for expected, stderr in cases:
            with self.subTest(stderr=stderr):
                runner = ScriptedRunner(_result(1, "", stderr))
                with self.assertRaises(expected):
                    GitHubClient(runner=runner).viewer_login()
                self.assertEqual(len(runner.calls), 1)
        sleep.assert_not_called()

    def test_retry_emits_bounded_span_event(self, sleep) -> None:
        runner = ScriptedRunner(_result(1, "", "HTTP 502: Bad Gateway"), _result(0, json.dumps({"login": "octo"})))
        with patch("gh_address_cr.otel_tracing.add_current_span_event") as event:
            GitHubClient(runner=runner).viewer_login()
        event.assert_called_once_with(
            "gh_address_cr.github.retry",
            {"gh_address_cr.github.retry.attempt": 1, "gh_address_cr.github.retry.reason_code": "GITHUB_TRANSIENT_ERROR"},
        )

    def test_graphql_error_wording_on_stack_probe_is_not_retried(self, sleep) -> None:
        runner = ScriptedRunner(_result(1, "", "GraphQL error: Field 'stack' doesn't exist on type 'PullRequest'"))
        with self.assertRaises(GitHubError):
            GitHubClient(runner=runner).viewer_login()
        self.assertEqual(len(runner.calls), 1)

    def test_mutations_are_never_retried(self, sleep) -> None:
        for name, call in (
            ("reply", lambda client: client.post_reply("o/r", "1", "T1", "body")),
            ("resolve", lambda client: client.resolve_thread("o/r", "1", "T1")),
        ):
            with self.subTest(mutation=name):
                runner = ScriptedRunner(_result(1, "", "HTTP 502: Bad Gateway"))
                with self.assertRaises(GitHubTransientError):
                    call(GitHubClient(runner=runner))
                self.assertEqual(len(runner.calls), 1)
        sleep.assert_not_called()


class TimeoutTests(unittest.TestCase):
    def test_default_runner_bounds_every_gh_call(self) -> None:
        with patch("gh_address_cr.core.command_runner.run_cmd") as run_cmd:
            run_cmd.return_value = _result()
            GitHubClient._default_runner(["gh", "api", "user"])
        run_cmd.assert_called_once_with(["gh", "api", "user"], retries=1, timeout=GH_COMMAND_TIMEOUT_SECONDS)


class PreflightAuthTests(unittest.TestCase):
    def test_hung_auth_status_times_out_and_retries_once(self) -> None:
        with (
            patch("gh_address_cr.cli.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 30)) as run,
            patch("gh_address_cr.cli.time.sleep") as sleep,
        ):
            result = cli._run_gh_auth_status(["gh", "auth", "status"])
        self.assertEqual(result.returncode, 124)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once()
        self.assertEqual(run.call_args.kwargs["timeout"], 30.0)

    def test_auth_failure_is_not_retried(self) -> None:
        with (
            patch(
                "gh_address_cr.cli.subprocess.run",
                return_value=_result(1, "", "You are not logged into any GitHub hosts."),
            ) as run,
            patch("gh_address_cr.cli.time.sleep") as sleep,
        ):
            result = cli._run_gh_auth_status(["gh", "auth", "status"])
        self.assertEqual(result.returncode, 1)
        run.assert_called_once()
        sleep.assert_not_called()

    def test_server_error_is_reported_as_network_not_auth(self) -> None:
        diagnostics = {"stderr_category": "api", "stderr_excerpt": "HTTP 502: Bad Gateway"}
        self.assertEqual(cli._preflight_gh_failure_response(diagnostics)[0], "GH_NETWORK_FAILED")
        auth = {"stderr_category": "auth", "stderr_excerpt": "not logged in"}
        self.assertEqual(cli._preflight_gh_failure_response(auth)[0], "GH_AUTH_FAILED")


if __name__ == "__main__":
    unittest.main()
