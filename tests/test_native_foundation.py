import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints
from unittest.mock import patch


class NativeFoundationTests(unittest.TestCase):
    def test_paths_resolve_pr_workspace_without_legacy_imports(self):
        from gh_address_cr.core import paths

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.assertEqual(paths.normalize_repo("owner/repo"), "owner__repo")
                self.assertEqual(paths.state_dir(), Path(tmp))
                self.assertEqual(paths.workspace_dir("owner/repo", "123"), Path(tmp) / "owner__repo" / "pr-123")
                self.assertEqual(paths.session_file("owner/repo", "123").name, "session.json")
                self.assertEqual(paths.audit_log_file("owner/repo", "123").name, "audit.jsonl")
                self.assertEqual(paths.audit_summary_file("owner/repo", "123").name, "audit_summary.md")

    def test_core_types_define_session_item_lease_and_finding_shapes(self):
        from gh_address_cr.core.types import Finding, Item, Lease, Session

        self.assertEqual(get_type_hints(Session)["items"], dict[str, Item])
        self.assertEqual(get_type_hints(Session)["leases"], dict[str, Lease])
        self.assertEqual(get_type_hints(Finding)["path"], str)
        self.assertEqual(get_type_hints(Item)["blocking"], bool)
        self.assertEqual(get_type_hints(Lease)["lease_id"], str)

    def test_atomic_json_writer_replaces_file_and_leaves_valid_json(self):
        from gh_address_cr.core.io import read_json_object, write_json_atomic

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "session.json"
            write_json_atomic(path, {"status": "OPEN", "items": {"one": 1}})
            write_json_atomic(path, {"status": "CLOSED", "items": {}})

            self.assertEqual(read_json_object(path), {"status": "CLOSED", "items": {}})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "CLOSED")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_audit_ledger_appends_jsonl_events_with_exact_shape(self):
        from gh_address_cr.core.ledger import AuditLedger

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            ledger = AuditLedger(path)

            ledger.append("claim", "ok", "owner/repo", "123", message="Claimed item", details={"item_id": "local:1"})
            ledger.append("gate", "fail", "owner/repo", "123", message="Blocking item")

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["action"], "claim")
            self.assertEqual(rows[0]["status"], "ok")
            self.assertEqual(rows[0]["repo"], "owner/repo")
            self.assertEqual(rows[0]["pr_number"], "123")
            self.assertEqual(rows[0]["message"], "Claimed item")
            self.assertEqual(rows[0]["details"], {"item_id": "local:1"})
            self.assertEqual(rows[1]["details"], {})

    def test_github_errors_are_classified_and_fail_loudly(self):
        from gh_address_cr.github.errors import GitHubAuthError, GitHubError, GitHubRateLimitError

        generic = GitHubError("GRAPHQL_FAILED", "GraphQL request failed")
        rate_limit = GitHubRateLimitError("rate limited")
        auth = GitHubAuthError("not logged in")

        self.assertEqual(generic.reason_code, "GRAPHQL_FAILED")
        self.assertFalse(generic.retryable)
        self.assertEqual(rate_limit.reason_code, "GITHUB_RATE_LIMITED")
        self.assertTrue(rate_limit.retryable)
        self.assertEqual(auth.reason_code, "GITHUB_AUTH_FAILED")
        self.assertFalse(auth.retryable)

    def test_github_client_errors_include_command_and_stderr_category(self):
        import subprocess

        from gh_address_cr.github.client import GitHubClient
        from gh_address_cr.github.errors import GitHubNetworkError

        def runner(cmd):
            return subprocess.CompletedProcess(
                cmd,
                1,
                "",
                "error connecting to api.github.com",
            )

        client = GitHubClient(runner=runner)

        with self.assertRaises(GitHubNetworkError) as caught:
            client.viewer_login()

        self.assertEqual(caught.exception.reason_code, "GITHUB_NETWORK_FAILED")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.diagnostics["stderr_category"], "network")
        self.assertEqual(caught.exception.diagnostics["command"], ["gh", "api", "user"])
        self.assertIn("api.github.com", caught.exception.diagnostics["stderr_excerpt"])

    def test_github_api_urls_do_not_make_http_errors_network_failures(self):
        import subprocess

        from gh_address_cr.github.client import GitHubClient
        from gh_address_cr.github.errors import GitHubError, GitHubNotFoundError

        def not_found_runner(cmd):
            return subprocess.CompletedProcess(
                cmd,
                1,
                "",
                "HTTP 404: Not Found (https://api.github.com/repos/owner/repo)",
            )

        with self.assertRaises(GitHubNotFoundError) as not_found:
            GitHubClient(runner=not_found_runner).viewer_login()

        self.assertEqual(not_found.exception.reason_code, "GITHUB_NOT_FOUND")
        self.assertFalse(not_found.exception.retryable)
        self.assertEqual(not_found.exception.diagnostics["stderr_category"], "not_found")

        def forbidden_runner(cmd):
            return subprocess.CompletedProcess(
                cmd,
                1,
                "",
                "HTTP 403: Resource not accessible by integration (https://api.github.com/graphql)",
            )

        with self.assertRaises(GitHubError) as forbidden:
            GitHubClient(runner=forbidden_runner).viewer_login()

        self.assertEqual(forbidden.exception.reason_code, "GITHUB_API_FAILED")
        self.assertFalse(forbidden.exception.retryable)
        self.assertEqual(forbidden.exception.diagnostics["stderr_category"], "api")

    def test_github_invalid_json_errors_include_redacted_diagnostics(self):
        import subprocess

        from gh_address_cr.github.client import GitHubClient
        from gh_address_cr.github.errors import GitHubError

        def runner(cmd):
            return subprocess.CompletedProcess(
                cmd,
                0,
                "not-json token=ghp_abcdefghijklmnopqrstuvwxyz12 user=alice@example.com",
                "",
            )

        with self.assertRaises(GitHubError) as caught:
            GitHubClient(runner=runner).viewer_login()

        diagnostics = caught.exception.diagnostics
        self.assertEqual(caught.exception.reason_code, "GITHUB_INVALID_JSON")
        self.assertEqual(diagnostics["command"], ["gh", "api", "user"])
        self.assertEqual(diagnostics["returncode"], 0)
        self.assertIn("[redacted-token]", diagnostics["stderr_excerpt"])
        self.assertIn("[redacted]", diagnostics["stderr_excerpt"])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz12", diagnostics["stderr_excerpt"])
        self.assertNotIn("alice@example.com", diagnostics["stderr_excerpt"])

    def test_github_waiting_on_uses_shared_diagnostic_mapping(self):
        from gh_address_cr.github.diagnostics import github_waiting_on

        self.assertEqual(github_waiting_on({"stderr_category": "auth"}), "github_auth")
        self.assertEqual(github_waiting_on({"stderr_category": "network"}), "github_network")
        self.assertEqual(github_waiting_on({"stderr_category": "sandbox"}), "github_environment")
        self.assertEqual(github_waiting_on({"stderr_category": "rate_limit"}), "github_rate_limit")
        self.assertEqual(github_waiting_on({"stderr_category": "unknown"}), "github")


if __name__ == "__main__":
    unittest.main()
