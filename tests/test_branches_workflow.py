"""Exercise the event-routing boundary before proposal jobs can mint tokens."""

import ast
import itertools
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def job_block(content, job):
    return content.split(f"\n  {job}:\n", 1)[1].split("\n  sync:\n", 1)[0]


def accepts(block, *, event, operation="", conclusion="", branch="", workflow="Release"):
    expression = re.search(r"^    if: (.+)$", block, re.MULTILINE).group(1)
    inputs = {
        "github.event_name": event,
        "inputs.operation": operation,
        "github.event.workflow_run.conclusion": conclusion,
        "github.event.workflow_run.head_branch": branch,
        "github.event.workflow_run.name": workflow,
    }
    for key, value in inputs.items():
        expression = expression.replace(key, repr(value))
    expression = expression.replace("&&", " and ").replace("||", " or ")
    tree = ast.parse(expression, mode="eval")
    permitted = (ast.Expression, ast.BoolOp, ast.Compare, ast.Constant, ast.And, ast.Or, ast.Eq)
    if any(not isinstance(node, permitted) for node in ast.walk(tree)):
        raise AssertionError("Job routing must remain a bounded boolean expression")
    return eval(compile(tree, "<job routing>", "eval"), {"__builtins__": {}})


class BranchesWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.content = (WORKFLOWS / "branches.yml").read_text()

    def test_event_matrix_never_routes_an_unintended_write_job(self):
        for event, operation, conclusion, branch in itertools.product(
            ("schedule", "workflow_dispatch", "workflow_run", "push", "pull_request"),
            ("", "propose-release", "propose-sync", "unknown"),
            ("success", "failure", "cancelled", "skipped", ""),
            ("main", "develop", "feature"),
        ):
            with self.subTest(event=event, operation=operation, conclusion=conclusion, branch=branch):
                inputs = dict(event=event, operation=operation, conclusion=conclusion, branch=branch)
                release = accepts(job_block(self.content, "create-release-pr"), **inputs)
                sync = accepts(job_block(self.content, "sync"), **inputs)
                self.assertEqual(release, event == "schedule" or (event == "workflow_dispatch" and operation == "propose-release"))
                self.assertEqual(sync, (event == "workflow_dispatch" and operation == "propose-sync") or (event == "workflow_run" and conclusion == "success" and branch == "main"))
                self.assertFalse(release and sync)

    def test_triggers_preserve_weekly_proposal_and_both_publish_names(self):
        triggers = self.content.split("\npermissions:", 1)[0]
        self.assertIn("name: Branches\n", triggers)
        self.assertIn("cron: '0 7 * * 5'", triggers)
        self.assertIn('workflows: ["Release / 2 Publish", "Release", "ci", "Checks / Python"]', triggers)
        self.assertIn("types: [completed]", triggers)
        dispatch = triggers.split("  workflow_dispatch:\n", 1)[1].split("  workflow_run:\n", 1)[0]
        self.assertIn("type: choice", dispatch)
        self.assertIn("required: true", dispatch)
        self.assertIn("default: propose-release", dispatch)
        self.assertEqual(re.findall(r"^          - (.+)$", dispatch.split("      pr_number:", 1)[0], re.MULTILINE), ["propose-release", "propose-sync", "readiness", "merge"])
        for retired in ("scheduled-release-pr.yml", "sync-main-to-develop.yml"):
            self.assertFalse((WORKFLOWS / retired).exists())

    def test_job_permissions_and_concurrency_remain_independent(self):
        self.assertIn("\npermissions:\n  contents: read\n", self.content)
        for job, contents, group in (
            ("create-release-pr", "read", "scheduled-release-pr"),
            ("sync", "write", "reviewed-main-develop-sync"),
        ):
            with self.subTest(job=job):
                block = job_block(self.content, job)
                self.assertIn(f"    permissions:\n      contents: {contents}\n      pull-requests: write\n", block)
                self.assertIn(f"    concurrency:\n      group: {group}\n      cancel-in-progress: false\n", block)
                self.assertLess(block.index("    if:"), block.index("    steps:"))
