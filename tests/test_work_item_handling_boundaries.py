import json
import sys
import unittest
from pathlib import Path

from tests.helpers import ROOT, SRC_ROOT


sys.path.insert(0, str(SRC_ROOT))

from gh_address_cr.core.models import WorkItemHandlingBoundary  # noqa: E402
from gh_address_cr.core.work_item_handlers import (  # noqa: E402
    WorkItemBoundaryError,
    boundary_summary_for_item,
    select_handling_boundary,
)


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "runtime_complexity" / "work_items.json"


class WorkItemHandlingBoundaryTests(unittest.TestCase):
    def fixture(self, name: str) -> dict:
        return json.loads(Path(FIXTURE_PATH).read_text(encoding="utf-8"))[name]

    def test_selects_github_thread_fix_boundary_for_classified_thread(self):
        boundary = select_handling_boundary(self.fixture("migrated_github_thread_fix"), role="fixer")

        self.assertEqual(boundary.boundary_id, "github-thread-fix")
        self.assertEqual(boundary.item_kinds, ("github_thread",))
        self.assertIn("reply", boundary.required_evidence)
        self.assertIn("final_gate", boundary.completion_criteria)

    def test_unsupported_work_item_fails_fast_with_reason_code(self):
        with self.assertRaises(WorkItemBoundaryError) as caught:
            select_handling_boundary(self.fixture("unsupported_work_item"), role="fixer")

        self.assertEqual(caught.exception.reason_code, "UNSUPPORTED_WORK_ITEM")

    def test_conflicting_boundaries_fail_fast_without_deterministic_priority(self):
        first = WorkItemHandlingBoundary.from_dict(
            {
                "boundary_id": "github-thread-fix-a",
                "item_kinds": ["github_thread"],
                "applicability": "matched",
                "priority": 10,
                "required_evidence": ["classification"],
                "completion_criteria": ["accepted_evidence"],
                "terminal_failure_reasons": ["BOUNDARY_CONFLICT"],
                "next_actions": ["issue_action_request"],
            }
        )
        second = WorkItemHandlingBoundary.from_dict(
            {
                "boundary_id": "github-thread-fix-b",
                "item_kinds": ["github_thread"],
                "applicability": "matched",
                "priority": 10,
                "required_evidence": ["classification"],
                "completion_criteria": ["accepted_evidence"],
                "terminal_failure_reasons": ["BOUNDARY_CONFLICT"],
                "next_actions": ["issue_action_request"],
            }
        )

        with self.assertRaises(WorkItemBoundaryError) as caught:
            select_handling_boundary(
                self.fixture("migrated_github_thread_fix"),
                role="fixer",
                boundaries=(first, second),
            )

        self.assertEqual(caught.exception.reason_code, "BOUNDARY_CONFLICT")

    def test_boundary_summary_is_public_safe_and_machine_readable(self):
        summary = boundary_summary_for_item(self.fixture("migrated_github_thread_fix"), role="fixer")

        self.assertEqual(summary["boundary_id"], "github-thread-fix")
        self.assertEqual(summary["applicability"], "matched")
        self.assertIn("MISSING_REQUIRED_EVIDENCE", summary["terminal_failure_reasons"])
        self.assertNotIn("body", summary)
