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
            input=None, stale=False, closed=False, disposition=None, publish=False, now=None,
        )
        base.update(kw)
        return argparse.Namespace(**base)

    def test_trivial_without_item_id_is_rejected(self):
        # A trivial disposition must require a single item_id, not fall into match-all.
        from gh_address_cr.commands.agent import _validate_resolve_mode

        with self.assertRaises(WorkflowError) as ctx:
            _validate_resolve_mode(self._ns(disposition="trivial", commit="abc", why="x"))
        self.assertEqual(ctx.exception.reason_code, "TRIVIAL_REQUIRES_ITEM_ID")

    def test_item_id_with_batch_is_rejected(self):
        # spec 029: <item_id> + a competing selection source (batch/--input)
        # must still fail fast — this is a genuine same-axis conflict.
        from gh_address_cr.commands.agent import _validate_resolve_axes

        with self.assertRaises(WorkflowError) as ctx:
            _validate_resolve_axes(self._ns(item_id="github-thread:abc", input="b.json"))
        self.assertEqual(ctx.exception.reason_code, "RESOLVE_AXIS_CONFLICT")

    def test_item_id_with_stale_and_non_fix_disposition_is_valid(self):
        from gh_address_cr.commands.agent import _validate_resolve_axes

        for disposition in ("reject", "clarify", "defer"):
            kw = {"stale": True, "disposition": disposition, "why": "x"}
            with self.subTest(kw=kw):
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
        # Resolve-axis contract: item_id + --disposition reject with
        # no --why must fail fast with a decline-specific message, not submit silently.
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
        # PR #206 CR: this is a decline-specific failure, not a fix-input one —
        # waiting_on must route recovery to decline_input, not fast_fix_input.
        self.assertEqual(payload["waiting_on"], "decline_input")

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


class RemovedResolveFlagTest(PythonScriptTestCase):
    def test_removed_flags_are_unknown_arguments(self):
        for flag in (
            "--batch",
            "--trivial",
            "--reject",
            "--clarify",
            "--homogeneous-reason",
            "--concern-label",
            "--match-files",
            "--include-stale",
        ):
            with self.subTest(flag=flag):
                result = self.run_runtime_module(
                    "agent", "resolve", self.repo, self.pr,
                    "github-thread:removed",
                    flag,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("unrecognized arguments", result.stderr)
                self.assertNotIn("RESOLVE_FLAG_DEPRECATED", result.stdout + result.stderr)


class BatchDispositionCoherenceTest(PythonScriptTestCase):
    """Batch input owns each item's decision; top-level disposition is invalid."""

    def test_input_with_decline_disposition_is_rejected(self):
        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--input", "batch-response.json",
            "--disposition", "reject",
            "--why", "Style preference only; not a defect.",
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "RESOLVE_EVIDENCE_INCOHERENT")
        self.assertIn("does not accept a top-level --disposition", payload["next_action"])

    def test_input_rejects_ignored_top_level_flags(self):
        cases = (
            ("--agent-id", "worker"),
            ("--commit", "abc123"),
            ("--files", "src/example.py"),
            ("--file", "src/example.py"),
            ("--summary", "summary"),
            ("--why", "reason"),
            ("--severity", "P2"),
            ("--severity-note", "override"),
            ("--review-priority", "high"),
            ("--validation", "unit=passed"),
            ("--stale", None),
        )
        for flag, value in cases:
            with self.subTest(flag=flag):
                args = ["agent", "resolve", self.repo, self.pr, "--input", "batch-response.json", flag]
                if value is not None:
                    args.append(value)
                result = self.run_runtime_module(*args)

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["reason_code"], "RESOLVE_EVIDENCE_INCOHERENT")
                self.assertIn(flag, payload["next_action"])


class DeclineItemResolutionValidationTest(unittest.TestCase):
    """PR #206 CR: decline_item must fail fast on an unsupported resolution
    instead of recording classification for a value it doesn't support."""

    def test_unsupported_resolution_is_rejected(self):
        from gh_address_cr.core import workflow

        with self.assertRaises(WorkflowError) as ctx:
            workflow.decline_item(
                "o/r", "1",
                item_id="github-thread:abc",
                agent_id="agent",
                resolution="archive",
                why="some reason",
            )
        self.assertEqual(ctx.exception.reason_code, "UNSUPPORTED_DECLINE_RESOLUTION")


class ResolveMultiFileFlagsTest(PythonScriptTestCase):
    """Documented multi-file forms: repeated --file == quoted comma --files."""

    def test_repeated_file_and_quoted_files_parse_identically(self):
        from gh_address_cr.commands.agent import _parse_agent_files

        repeated = _parse_agent_files(None, ["src/a.py", "src/b.py"])
        quoted = _parse_agent_files("src/a.py, src/b.py")
        self.assertEqual(repeated, ["src/a.py", "src/b.py"])
        self.assertEqual(repeated, quoted)

    def test_unquoted_space_separated_files_fail_argument_parsing(self):
        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:multi",
            "--files", "src/a.py", "src/b.py",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: src/b.py", result.stderr)


if __name__ == "__main__":
    unittest.main()
