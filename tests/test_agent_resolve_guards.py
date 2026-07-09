"""CR fixes for the unified `agent resolve` surface: published flag + trivial guard."""

import argparse
import json
import unittest

from gh_address_cr.commands.agent import _resolve_published_flag
from gh_address_cr.core.errors import WorkflowError
from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import github_thread


class ResolvePublishedFlagTest(unittest.TestCase):
    def test_nested_submit_publish_counts_as_published(self):
        # #5/#7: single-item resolve --publish tucks the result under submit.publish.
        payload = {"status": "FAST_FIX_COMPLETE", "submit": {"publish": {"published_count": 1}}}
        self.assertTrue(_resolve_published_flag(payload))

    def test_top_level_publish_counts_as_published(self):
        self.assertTrue(_resolve_published_flag({"publish": {"published_count": 2}}))

    def test_zero_published_count_is_false(self):
        self.assertFalse(_resolve_published_flag({"publish": {"published_count": 0}}))

    def test_no_publish_is_false(self):
        self.assertFalse(_resolve_published_flag({"status": "FAST_FIX_ACCEPTED", "submit": {}}))


class TrivialResolveGuardTest(unittest.TestCase):
    def _ns(self, **kw):
        base = dict(
            repo="o/r", pr_number="1", item_id=None, agent_id="a", commit=None, files=None, file=[],
            summary=None, why=None, severity=None, severity_note=None, review_priority=None, validation=[],
            input=None, batch=False, trivial=False, stale=False, reject=False, clarify=False,
            disposition=None, homogeneous_reason=None, concern_label=None,
            match_files=False, include_stale=False, publish=False, now=None,
        )
        base.update(kw)
        ns = argparse.Namespace(**base)
        from gh_address_cr.commands.agent import _normalize_disposition

        _normalize_disposition(ns)
        return ns

    def test_trivial_without_item_id_is_rejected(self):
        # #9: --trivial must require a single item_id, not fall into match-all.
        from gh_address_cr.commands.agent import _validate_resolve_mode

        with self.assertRaises(WorkflowError) as ctx:
            _validate_resolve_mode(self._ns(trivial=True, commit="abc", homogeneous_reason="x"))
        self.assertEqual(ctx.exception.reason_code, "TRIVIAL_REQUIRES_ITEM_ID")

    def test_item_id_with_batch_is_rejected(self):
        # spec 029: <item_id> + a competing selection source (batch/--input)
        # must still fail fast — this is a genuine same-axis conflict.
        from gh_address_cr.commands.agent import _validate_resolve_axes

        with self.assertRaises(WorkflowError) as ctx:
            _validate_resolve_axes(self._ns(item_id="github-thread:abc", batch=True, input="b.json"))
        self.assertEqual(ctx.exception.reason_code, "RESOLVE_AXIS_CONFLICT")

    def test_item_id_with_stale_or_homogeneous_reason_is_now_valid(self):
        # spec 029 / #204: item_id + --stale and item_id + --homogeneous-reason
        # (a decline-reason alias) are NOT selection conflicts — disposition
        # and condition axes compose freely with a single-item selection.
        from gh_address_cr.commands.agent import _validate_resolve_axes

        for kw in (
            {"stale": True, "reject": True, "why": "x"},
            {"homogeneous_reason": "x", "reject": True},
        ):
            with self.subTest(kw=kw):
                # Must not raise.
                _validate_resolve_axes(self._ns(item_id="github-thread:abc", **kw))


class SingleItemDeclineCLIRegressionTest(PythonScriptTestCase):
    """T010: full-CLI regression for the item_id + decline cells."""

    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_regress",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def test_missing_reason_is_rejected(self):
        # spec 029 / /speckit-analyze U1: item_id + --disposition reject with
        # no --why (and no deprecated --homogeneous-reason alias) must fail
        # fast with a decline-specific message, not submit silently.
        self.write_session(items=[github_thread("github-thread:noreason")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:noreason",
            "--disposition", "reject",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "MISSING_RESOLVE_ARGS")
        self.assertIn("--why", payload["next_action"])

    def test_legacy_boolean_spellings_still_work(self):
        # --reject/--clarify booleans remain a valid alias for --disposition
        # until T028's visible-deprecation-notice layer lands.
        self.write_session(
            items=[
                github_thread("github-thread:legacy1"),
                github_thread("github-thread:legacy2"),
            ]
        )

        reject_result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:legacy1",
            "--reject",
            "--why", "Style preference only; not a defect.",
        )
        self.assertEqual(reject_result.returncode, 0, reject_result.stdout + reject_result.stderr)
        self.assertEqual(json.loads(reject_result.stdout)["item_id"], "github-thread:legacy1")

        clarify_result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:legacy2",
            "--clarify",
            "--why", "Needs the author's intent before this can be actioned.",
        )
        self.assertEqual(clarify_result.returncode, 0, clarify_result.stdout + clarify_result.stderr)
        self.assertEqual(json.loads(clarify_result.stdout)["item_id"], "github-thread:legacy2")

    def test_stale_and_disposition_clarify_together_is_accepted(self):
        # The false-conflict case: --stale (condition axis) and
        # --disposition clarify (disposition axis) used to trip the flat
        # selected_modes gate as if they were competing "modes".
        self.write_session(
            items=[
                {
                    "item_id": "github-thread:stalefalseconflict",
                    "item_kind": "github_thread",
                    "source": "github",
                    "thread_id": "stalefalseconflict",
                    "title": "Stale review thread",
                    "body": "Please add a null check.",
                    "path": "src/example.py",
                    "line": 10,
                    "state": "stale",
                    "status": "STALE",
                    "blocking": True,
                    "is_outdated": True,
                    "allowed_actions": ["fix", "clarify", "defer", "reject"],
                }
            ]
        )

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:stalefalseconflict",
            "--disposition", "clarify",
            "--stale",
            "--why", "Needs the author's intent before this can be actioned.",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["item_id"], "github-thread:stalefalseconflict")


class DeprecatedFlagNoticeTest(PythonScriptTestCase):
    """T024: legacy flags still resolve the same way, but emit a visible
    stderr deprecation notice; machine-summary stdout is byte-stable."""

    REASON = "Style preference only; not a defect."

    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_deprecation",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def test_legacy_reject_boolean_emits_deprecation_notice(self):
        self.write_session(items=[github_thread("github-thread:notice1")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:notice1",
            "--reject",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("deprecated", result.stderr.lower())
        self.assertIn("--reject", result.stderr)
        self.assertIn("--disposition reject", result.stderr)

    def test_match_files_and_homogeneous_reason_and_include_stale_emit_notices(self):
        self.write_session(items=[github_thread("github-thread:notice2")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--disposition", "reject",
            "--files", "src/shared.py",
            "--match-files",
            "--homogeneous-reason", self.REASON,
            "--include-stale",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for flag in ("--match-files", "--homogeneous-reason", "--include-stale"):
            self.assertIn(flag, result.stderr)
        self.assertIn("deprecated", result.stderr.lower())

    def test_machine_summary_is_stable_between_legacy_and_axis_forms(self):
        # FR-010/N3: deprecation notice goes to stderr only; stdout JSON
        # shape and exit code are identical for equivalent invocations.
        self.write_session(
            items=[
                github_thread("github-thread:stable_legacy"),
                github_thread("github-thread:stable_axis"),
            ]
        )

        legacy = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:stable_legacy",
            "--reject",
            "--why", self.REASON,
        )
        axis = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:stable_axis",
            "--disposition", "reject",
            "--why", self.REASON,
        )

        self.assertEqual(legacy.returncode, axis.returncode)
        legacy_payload = json.loads(legacy.stdout)
        axis_payload = json.loads(axis.stdout)
        legacy_payload.pop("item_id")
        axis_payload.pop("item_id")
        self.assertEqual(sorted(legacy_payload.keys()), sorted(axis_payload.keys()))
        self.assertEqual(legacy_payload["status"], axis_payload["status"])


class RemovalWindowFailLoudTest(PythonScriptTestCase):
    """T027: once the deprecation window is closed, legacy flags fail loudly
    with RESOLVE_FLAG_DEPRECATED instead of silently aliasing."""

    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_window_closed",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def test_legacy_flag_after_window_close_is_rejected(self):
        from unittest.mock import patch as mock_patch

        self.write_session(items=[github_thread("github-thread:windowclosed")])

        with mock_patch("gh_address_cr.commands.agent.RESOLVE_DEPRECATION_WINDOW_OPEN", False):
            result = self.run_runtime_module(
                "agent", "resolve", self.repo, self.pr,
                "github-thread:windowclosed",
                "--reject",
                "--why", "Style preference only; not a defect.",
            )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "RESOLVE_FLAG_DEPRECATED")

    def test_axis_form_still_works_after_window_close(self):
        from unittest.mock import patch as mock_patch

        self.write_session(items=[github_thread("github-thread:windowclosedaxis")])

        with mock_patch("gh_address_cr.commands.agent.RESOLVE_DEPRECATION_WINDOW_OPEN", False):
            result = self.run_runtime_module(
                "agent", "resolve", self.repo, self.pr,
                "github-thread:windowclosedaxis",
                "--disposition", "reject",
                "--why", "Style preference only; not a defect.",
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
