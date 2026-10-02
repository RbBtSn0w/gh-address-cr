"""Agent journey contract tests (Spec 039, layer L1).

Each test drives the real CLI the way an agent does: it reads only machine
fields (`primary_action`, response skeletons, returned commands) and checks the
journey invariants that unit tests of individual surfaces cannot see:

- I1 every executed `primary_action.command` is accepted
- I2 a session completed through the documented path reports clean telemetry
- I3 the completion line names each problem operation once
- I4 a published fix reply never cites a commit outside the PR, and a blocked
  agent can recover
- I5 the lean path exposes the full review body or marks it truncated
- I6 a blocked final-gate prints its next action in the terminal report

GitHub is replaced by a stateful fake `gh` binary, so every runtime code path
above the subprocess boundary is the production one.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import unittest
from pathlib import Path

from gh_address_cr.commands.final_gate import build_completion_summary_line
from gh_address_cr.core import gate as core_gate
from gh_address_cr.core.telemetry_reporting import error_prone_flag
from tests.helpers import PythonScriptTestCase

FAKE_GH = Path(__file__).resolve().parents[1] / "fixtures" / "agent_journey" / "fake_gh.py"
AGENT_ID = "journey-agent"
MAX_STEPS = 12
# Longer than the 500-character lean excerpt so truncation is observable (I5).
REVIEW_BODY = (
    "The retry loop in `fetch` swallows the final exception, so callers see `None` "
    "instead of an error when every attempt fails. "
    + "Context: " + "the caller treats None as an empty cache hit and serves stale data. " * 6
    + "SUGGESTED FIX: re-raise the last exception after the final attempt."
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class AgentJourneyTestCase(PythonScriptTestCase):
    """Fake GitHub plus a git checkout whose feature branch is the PR head."""

    def setUp(self):
        super().setUp()
        root = Path(self.temp_dir.name)
        self.checkout = root / "checkout"
        self.checkout.mkdir()
        _git(self.checkout, "init", "-q", "-b", "main")
        _git(self.checkout, "config", "user.email", "journey@example.test")
        _git(self.checkout, "config", "user.name", "journey")
        (self.checkout / "app.py").write_text("def fetch():\n    return None\n", encoding="utf-8")
        _git(self.checkout, "add", "app.py")
        _git(self.checkout, "commit", "-q", "-m", "base")
        self.base_sha = _git(self.checkout, "rev-parse", "HEAD")
        _git(self.checkout, "checkout", "-q", "-b", "feature/journey")
        (self.checkout / "app.py").write_text("def fetch():\n    raise RuntimeError\n", encoding="utf-8")
        _git(self.checkout, "commit", "-q", "-am", "fix: re-raise")
        self.head_sha = _git(self.checkout, "rev-parse", "HEAD")

        self.gh_state = root / "gh-state.json"
        self.gh_calls = root / "gh-calls.jsonl"
        self.gh_state.write_text(
            json.dumps(
                {
                    "repo": self.repo,
                    "pr_number": self.pr,
                    "head_ref": "feature/journey",
                    "head_sha": self.head_sha,
                    "base_sha": self.base_sha,
                    # Commits that belong to the PR: only the fix, never the base.
                    "commits": [self.head_sha],
                    "files": [{"filename": "app.py", "status": "modified", "additions": 1, "deletions": 1, "changes": 2}],
                    "threads": [
                        {
                            "id": "PRRT_journey1",
                            "isResolved": False,
                            "path": "app.py",
                            "line": 2,
                            "comments": [
                                {"url": "https://github.test/c/1", "author": "reviewer-bot", "body": REVIEW_BODY}
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        gh = self.bin_dir / "gh"
        shutil.copy(FAKE_GH, gh)
        gh.chmod(0o755)
        self.env["FAKE_GH_STATE"] = str(self.gh_state)
        self.env["FAKE_GH_CALLS"] = str(self.gh_calls)
        self.gh_unhandled = root / "gh-unhandled.log"
        self.env["FAKE_GH_UNHANDLED"] = str(self.gh_unhandled)
        # The base class sets DISABLE_TELEMETRY=1; that only stops OTel export, and
        # the local session telemetry these invariants read stays on.

        # In-process runs use the process cwd; subprocess runs use self.cwd. Both
        # must be the checkout so `git rev-parse HEAD` never sees this repository.
        self.cwd = self.checkout
        self._previous_cwd = os.getcwd()
        os.chdir(self.checkout)
        self.addCleanup(os.chdir, self._previous_cwd)
        self.trace: list[dict] = []

    # -- runtime access -------------------------------------------------

    def runtime(self, *args: str) -> dict:
        result = self.run_runtime_module(*args)
        stdout = result.stdout.strip()
        payload = json.loads(stdout[stdout.find("{"):]) if "{" in stdout else {}
        payload["_exit_code"] = result.returncode
        payload["_stderr"] = result.stderr
        self.trace.append({"args": list(args), "status": payload.get("status"), "reason_code": payload.get("reason_code")})
        return payload

    def final_gate(self) -> dict:
        # final-gate prints a human report, not JSON; its machine diagnostics carry reason_code.
        result = self.run_runtime_module("final-gate", self.repo, self.pr)
        output = result.stdout + result.stderr
        passed = result.returncode == 0 and "reason_code=PASSED" in output
        status = "PASSED" if passed else "FAILED"
        self.trace.append({"args": ["final-gate", self.repo], "status": status, "reason_code": None})
        return {"status": status, "_exit_code": result.returncode, "_output": output}

    def placeholder_values(self) -> dict[str, str]:
        # What an agent knows after making its fix; any other placeholder is not fillable.
        return {
            "<agent_id>": AGENT_ID,
            "<sha>": self.head_sha,
            "<paths>": "app.py",
            "<text>": "Re-raise the last exception after the final retry.",
            "<why>": "Callers must see the failure instead of a stale-cache None.",
            "<cmd=passed>": "python3 -m unittest tests.test_app=passed",
        }

    def run_command_line(self, command: str) -> dict:
        for placeholder, value in self.placeholder_values().items():
            command = command.replace(placeholder, shlex.quote(value))
        self.assertNotRegex(command, r"<[a-z_=]+>", f"primary_action has a placeholder an agent cannot fill: {command}")
        argv = shlex.split(command)
        self.assertEqual(argv[0], "gh-address-cr", f"primary_action is not a runtime command: {command}")
        if argv[1] == "final-gate":
            return self.final_gate()
        return self.runtime(*argv[1:])

    def fill_fix_response(self, skeleton_path: str) -> Path:
        response = json.loads(Path(skeleton_path).read_text(encoding="utf-8"))
        response["files"] = ["app.py"]
        response["note"] = "Re-raise the final exception."
        response["fix_reply"] = {
            "files": ["app.py"],
            "summary": "Re-raise the last exception after the final retry.",
            "why": "Callers must see the failure instead of a stale-cache None.",
            "test_command": "python3 -m unittest tests.test_app",
            "test_result": "passed",
        }
        response["validation_commands"] = [{"command": "python3 -m unittest tests.test_app", "result": "passed"}]
        path = Path(self.temp_dir.name) / "response.json"
        path.write_text(json.dumps(response), encoding="utf-8")
        return path

    def assert_fake_github_covered_every_call(self):
        unhandled = self.gh_unhandled.read_text(encoding="utf-8") if self.gh_unhandled.exists() else ""
        self.assertEqual(unhandled, "", "the runtime made gh calls the fake does not model")

    def published_replies(self) -> list[str]:
        state = json.loads(self.gh_state.read_text(encoding="utf-8"))
        return [row["body"] for thread in state["threads"] for row in thread["comments"] if row["author"] == "agent-login"]

    def efficiency_report(self, gate: dict) -> dict:
        # A passing final-gate archives the workspace, so take the path it reports.
        marker = "Efficiency report path: "
        line = next((row for row in gate["_output"].splitlines() if row.startswith(marker)), None)
        self.assertIsNotNone(line, "final-gate did not report an efficiency report path")
        return json.loads(Path(line[len(marker):].strip()).read_text(encoding="utf-8"))

    def describe_trace(self) -> str:
        return "\n".join(f"  {row['args'][:2]} -> {row['status']} / {row['reason_code']}" for row in self.trace)

    # -- agent policies ---------------------------------------------------

    def literal_follower(self) -> dict:
        """Run the README loop: execute a non-null `primary_action.command`, then
        rerun `address`. Skeletons and placeholders are filled with the agent's fix."""
        summary = self.runtime("address", self.repo, self.pr, "--lean")
        for _ in range(MAX_STEPS):
            action = summary.get("primary_action") or {}
            kind = action.get("kind")
            if kind == "complete":
                return summary
            if action.get("command"):
                result = self.run_command_line(action["command"])
                if result.get("status") == "REQUEST_REJECTED":
                    return result
                if result.get("response_skeleton_path"):
                    response = self.fill_fix_response(result["response_skeleton_path"])
                    self.runtime("agent", "submit", self.repo, self.pr, "--input", str(response))
                if kind == "run_final_gate":
                    return result
                summary = self.runtime("address", self.repo, self.pr, "--lean")
                continue
            self.fail(f"primary_action kind {kind!r} is not actionable by an agent:\n{self.describe_trace()}")
        self.fail(f"journey did not finish in {MAX_STEPS} steps:\n{self.describe_trace()}")

    def skill_follower(self) -> dict:
        """Follow SKILL.md: `agent resolve` per thread, then publish and final-gate."""
        summary = self.runtime("address", self.repo, self.pr, "--lean")
        item_id = summary["primary_action"]["item_id"]
        self.runtime(
            "agent", "resolve", self.repo, self.pr, item_id,
            "--commit", self.head_sha,
            "--files", "app.py",
            "--summary", "Re-raise the last exception after the final retry.",
            "--why", "Callers must see the failure instead of a stale-cache None.",
            "--validation", "python3 -m unittest tests.test_app=passed",
            "--agent-id", AGENT_ID,
        )
        self.runtime("agent", "publish", self.repo, self.pr)
        return self.final_gate()


class AgentJourneyHarnessTests(AgentJourneyTestCase):
    """Green control: proves the harness can complete a journey, so the RED
    invariant tests below fail for product reasons, not a broken fake."""

    def test_skill_follower_completes_the_journey_against_the_fake(self):
        result = self.skill_follower()

        self.assertEqual(result.get("status"), "PASSED", self.describe_trace())
        state = json.loads(self.gh_state.read_text(encoding="utf-8"))
        self.assertTrue(all(thread["isResolved"] for thread in state["threads"]))
        replies = self.published_replies()
        self.assertEqual(len(replies), 1, replies)
        self.assertIn(self.head_sha[:7], replies[0])
        self.assert_fake_github_covered_every_call()


class AgentJourneyContractTests(AgentJourneyTestCase):
    def test_i1_every_primary_action_command_is_accepted(self):
        result = self.literal_follower()

        rejected = [row for row in self.trace if row["status"] == "REQUEST_REJECTED"]
        self.assertEqual(rejected, [], f"primary_action led to a rejection:\n{self.describe_trace()}")
        self.assertEqual(result.get("status"), "PASSED", self.describe_trace())

    def test_i2_skill_path_session_reports_clean_telemetry(self):
        result = self.skill_follower()
        self.assertEqual(result.get("status"), "PASSED", self.describe_trace())

        report = self.efficiency_report(result)
        self.assertEqual(report["success_rate"], 100.0, report.get("error_prone_operations"))
        self.assertEqual(report["inefficiency_flags"], [])
        # The fake PR has no check runs, like a repository without CI: that is a PR
        # state, not a GitHub failure.
        summary = self.runtime("address", self.repo, self.pr, "--lean")
        self.assertEqual(summary["context"]["checks"], {"availability": "present", "counts": {}})
        # The opening `address` blocked on the open thread: counted, not hidden.
        self.assertGreaterEqual(report["needs_action_count"], 1)

    def test_i2_status_checks_before_the_fix_are_needs_action_not_failures(self):
        # Seen in real 3.16.0 sessions: inspect threads and try the gate before fixing.
        self.runtime("threads", self.repo, self.pr)
        early_gate = self.final_gate()
        self.assertEqual(early_gate["status"], "FAILED")

        result = self.skill_follower()
        self.assertEqual(result.get("status"), "PASSED", self.describe_trace())

        report = self.efficiency_report(result)
        self.assertEqual(report["success_rate"], 100.0, report.get("error_prone_operations"))
        self.assertEqual(report["inefficiency_flags"], [])
        self.assertGreaterEqual(report["needs_action_count"], 3)

    def test_i4_publish_blocks_a_fallback_commit_outside_the_pr_and_recovers(self):
        # The agent submits through the skeleton without a commit and publishes from a
        # checkout that is not on the PR branch, so the fallback would cite the base.
        summary = self.runtime("address", self.repo, self.pr, "--lean")
        item_id = summary["primary_action"]["item_id"]
        self.runtime("agent", "classify", self.repo, self.pr, item_id, "--classification", "fix", "--note", "valid")
        claimed = self.runtime("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", AGENT_ID, "--item-id", item_id)
        response = self.fill_fix_response(claimed["response_skeleton_path"])
        self.runtime("agent", "submit", self.repo, self.pr, "--input", str(response))

        _git(self.checkout, "checkout", "-q", "main")
        blocked = self.runtime("agent", "publish", self.repo, self.pr)

        self.assertEqual(blocked.get("reason_code"), "COMMIT_NOT_IN_PR", self.describe_trace())
        self.assertEqual(self.published_replies(), [], "nothing may be posted with a commit outside the PR")
        self.assertIn("feature/journey", blocked.get("next_action") or "")

        # Recovery the message names: check out the PR branch, then publish again.
        _git(self.checkout, "checkout", "-q", "feature/journey")
        published = self.runtime("agent", "publish", self.repo, self.pr)

        self.assertEqual(published.get("status"), "PUBLISH_COMPLETE", self.describe_trace())
        replies = self.published_replies()
        self.assertEqual(len(replies), 1, replies)
        self.assertIn(self.head_sha[:7], replies[0])
        self.assertNotIn(self.base_sha[:7], replies[0])

    def test_i4_explicit_commit_outside_the_pr_is_rejected_before_acceptance(self):
        summary = self.runtime("address", self.repo, self.pr, "--lean")
        item_id = summary["primary_action"]["item_id"]
        resolve_args = (
            "--files", "app.py",
            "--summary", "Re-raise the last exception after the final retry.",
            "--why", "Callers must see the failure instead of a stale-cache None.",
            "--validation", "python3 -m unittest tests.test_app=passed",
            "--agent-id", AGENT_ID,
        )

        rejected = self.runtime("agent", "resolve", self.repo, self.pr, item_id, "--commit", self.base_sha, *resolve_args)
        self.assertEqual(rejected.get("reason_code"), "COMMIT_NOT_IN_PR", self.describe_trace())

        # Rejected before acceptance, so the agent can resubmit with the right commit.
        accepted = self.runtime("agent", "resolve", self.repo, self.pr, item_id, "--commit", self.head_sha, *resolve_args)
        self.assertEqual(accepted.get("status"), "FAST_FIX_ACCEPTED", self.describe_trace())
        self.runtime("agent", "publish", self.repo, self.pr)
        replies = self.published_replies()
        self.assertEqual(len(replies), 1, replies)
        self.assertIn(self.head_sha[:7], replies[0])

    def test_i5_lean_path_exposes_full_body_or_marks_truncation(self):
        summary = self.runtime("address", self.repo, self.pr, "--lean")
        selected = summary["context"]["selected_item"]

        if selected["comment_excerpt"] == REVIEW_BODY:
            return
        self.assertTrue(
            selected.get("comment_excerpt_truncated"),
            "lean excerpt is shorter than the review body but not marked truncated; "
            "the agent classifies without the reviewer's suggested fix",
        )
        command = selected.get("full_comment_command")
        self.assertIsNotNone(command, "a truncated excerpt must name the command that returns the full body")

        full = self.run_command_line(command)

        bodies = [row.get("body") for row in full.get("threads", []) if row.get("item_id") == selected["item_id"]]
        self.assertEqual(bodies, [REVIEW_BODY])


class FinalGateNextActionContractTests(AgentJourneyTestCase):
    """I6: a blocked final-gate tells the agent what to run next in its own output.

    Agents read the terminal report, not `last-machine-summary.json`; a remediation
    computed but not printed leaves them to discover the command (issue #308).
    """

    def resolve_thread_remotely_without_reply(self):
        state = json.loads(self.gh_state.read_text(encoding="utf-8"))
        for thread in state["threads"]:
            thread["isResolved"] = True
        self.gh_state.write_text(json.dumps(state), encoding="utf-8")

    def next_action_line(self, gate: dict) -> str | None:
        return next((row for row in gate["_output"].splitlines() if row.startswith("Next action: ")), None)

    def test_i6_thread_closed_remotely_without_reply_prints_evidence_command(self):
        self.runtime("address", self.repo, self.pr, "--lean")
        self.resolve_thread_remotely_without_reply()

        gate = self.final_gate()

        self.assertEqual(gate["status"], "FAILED")
        self.assertIn("reason_code=FINAL_GATE_MISSING_REPLY_EVIDENCE", gate["_output"])
        line = self.next_action_line(gate)
        self.assertIsNotNone(line, "blocked final-gate printed no Next action line")
        self.assertIn(f"gh-address-cr agent evidence add {self.repo} {self.pr} --item-id github-thread:PRRT_journey1", line)

    def test_i6_unresolved_thread_prints_next_action(self):
        self.runtime("address", self.repo, self.pr, "--lean")

        gate = self.final_gate()

        self.assertEqual(gate["status"], "FAILED")
        line = self.next_action_line(gate)
        self.assertIsNotNone(line, "blocked final-gate printed no Next action line")
        self.assertIn(f"gh-address-cr address {self.repo} {self.pr} --lean", line)


class CompletionSummaryLineContractTests(unittest.TestCase):
    def test_i3_completion_line_names_each_problem_operation_once(self):
        operation = "github.graphql"
        row = {"operation": operation, "failures": 1, "timeouts": 0, "retries": 0}
        slow_flag = "run unit tests exceeded 60s threshold."
        report = {
            "coverage_label": "runtime-only",
            "total_events": 4,
            "success_rate": 75.0,
            # As build_efficiency_report produces them: one flag per error-prone row.
            "inefficiency_flags": [slow_flag, error_prone_flag(row)],
            "error_prone_operations": [row],
        }
        result = core_gate.GateResult(repo="octo/example", pr_number="77", counts={}, failure_codes=[])

        line = build_completion_summary_line(result, report)

        self.assertEqual(line.count(operation), 1, line)
        self.assertIn(f"{operation} failures=1 timeouts=0 retries=0", line)
        self.assertIn(slow_flag, line, "flags not derived from an error-prone row must stay")


if __name__ == "__main__":
    unittest.main()
