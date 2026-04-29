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


if __name__ == "__main__":
    unittest.main()
