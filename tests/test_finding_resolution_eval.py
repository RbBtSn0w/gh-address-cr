"""Offline control for the finding-resolution eval (scripts/eval_finding_resolution.py).

The eval scores LLM agents, so its fake GitHub and graders must be proven before
any agent run: the scripted reference agent passes every sample, each oracle
fails before the fix, and the graders reject a run that stops early or writes
to GitHub around the runtime.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT


def load_script():
    path = ROOT / "scripts" / "eval_finding_resolution.py"
    spec = importlib.util.spec_from_file_location("eval_finding_resolution", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EVAL = load_script()
DECLINES = {"reject", "clarify", "defer"}


class FindingResolutionEvalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def fixture(self, sample_id):
        return EVAL.build_fixture(EVAL.load_sample(sample_id), self.root / sample_id, f"eval-test-{sample_id}")

    def test_five_samples_cover_the_attribution_axes(self):
        axes = {EVAL.load_sample(sample_id)["axis"] for sample_id in EVAL.sample_ids()}
        self.assertEqual(axes, {"baseline", "lease", "classification", "recovery", "verification"})

    def test_reference_agent_passes_every_sample(self):
        for sample_id in EVAL.sample_ids():
            with self.subTest(sample=sample_id):
                fixture = self.fixture(sample_id)
                EVAL.run_scripted(fixture)
                result = EVAL.grade(fixture)
                for name in EVAL.CRITERIA:
                    self.assertTrue(result[name]["passed"], (name, result[name]))
                self.assertIsNotNone((result["runtime"] or {}).get("version"))
                self.assertEqual(result["agent_gh_calls"], [])

    def test_oracles_fail_before_the_fix(self):
        for sample_id in EVAL.sample_ids():
            sample = EVAL.load_sample(sample_id)
            declined = all(set(thread["expected"]) <= DECLINES for thread in sample["threads"])
            with self.subTest(sample=sample_id):
                fixture = self.fixture(sample_id)
                clone = EVAL.clone_pushed_head(fixture, "unfixed")
                if sample["reference"].get("cite_commit"):
                    # A later PR commit fixed it; the oracle must fail where the thread was raised.
                    EVAL.git(clone, "checkout", "-q", fixture.pr_commits[0], env=fixture.env)
                self.assertEqual(EVAL.run_oracle(fixture, clone), declined)

    def test_runtime_sees_the_recovery_sample_thread_as_outdated(self):
        fixture = self.fixture("stale-unused-parameter")
        EVAL.run_scripted(fixture)

        observed = EVAL.grade(fixture)["runtime_observed"]

        self.assertEqual(observed["outdated_items"], ["github-thread:PRRT_eval324agentid"])

    def test_citing_the_commit_that_introduced_the_defect_fails_evidence(self):
        sample = copy.deepcopy(EVAL.load_sample("stale-unused-parameter"))
        sample["reference"]["cite_commit"] = 1
        fixture = EVAL.build_fixture(sample, self.root / "wrong-citation", "eval-test-wrong-citation")
        EVAL.run_scripted(fixture)

        result = EVAL.grade(fixture)

        self.assertTrue(result["legal_state"]["passed"], "the runtime accepts any commit in the PR")
        self.assertTrue(result["consistent_evidence"]["checks"]["fix_commits_in_pr"])
        self.assertFalse(result["consistent_evidence"]["checks"]["oracle_passes_at_cited_commit"])

    def test_unfinished_run_fails_every_criterion_that_needs_the_fix(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        EVAL.run_runtime(fixture, "address", fixture.repo, fixture.pr, "--lean")

        result = EVAL.grade(fixture)

        self.assertFalse(result["legal_state"]["checks"]["final_gate_passed"])
        self.assertFalse(result["legal_state"]["checks"]["all_threads_resolved"])
        self.assertFalse(result["effective_fix"]["checks"]["oracle_passes"])

    def test_direct_gh_reply_is_attributed_to_the_agent(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        query = (
            "mutation($threadId:ID!,$body:String!){ addPullRequestReviewThreadReply("
            "input:{pullRequestReviewThreadId:$threadId,body:$body}) { comment { url } } }"
        )
        subprocess.run(
            ["/bin/sh", "-c", 'gh api graphql -f "query=$QUERY" -F threadId=PRRT_eval351nonfinite -F body=done'],
            cwd=fixture.checkout,
            env={**fixture.env, "QUERY": query},
            check=True,
            capture_output=True,
        )

        checks = EVAL.grade(fixture)["legal_state"]["checks"]

        self.assertFalse(checks["no_direct_gh_writes"])
        self.assertFalse(checks["replies_ledger_backed"])

    def test_claude_transcript_yields_runtime_steps_without_arguments(self):
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {
                "command": "cd /private/work && gh-address-cr agent resolve eval-fixture/x 351 github-thread:PRRT_1"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content":
                '{"status": "REQUEST_REJECTED", "reason_code": "COMMIT_NOT_IN_PR"}'}]}},
            # Mentions the runtime only in a path; it is not a runtime step.
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t3", "name": "Bash", "input": {
                "command": "grep -n disposition .claude/skills/gh-address-cr/references/agent-protocol.md"}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {
                "command": "gh-address-cr final-gate eval-fixture/x 351"}}]}},
            # Tool results arrive either as a string or as a list of text blocks.
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content":
                [{"type": "text", "text": "Final gate passed\nreason_code=PASSED\n"}]}]}},
            {"type": "result", "subtype": "success", "num_turns": 7, "total_cost_usd": 0.42},
        ]
        transcript = self.root / "transcript.jsonl"
        transcript.write_text("\n".join(map(json.dumps, events)) + "\n", encoding="utf-8")

        trace = EVAL.claude_trace(transcript)

        self.assertEqual(
            trace["commands"],
            [{"command": "agent resolve", "codes": ["COMMIT_NOT_IN_PR"]}, {"command": "final-gate", "codes": ["PASSED"]}],
        )
        self.assertEqual(trace["result"]["total_cost_usd"], 0.42)
        self.assertEqual(EVAL.friction_codes({"agent": {"steps": trace["commands"]}}), ["COMMIT_NOT_IN_PR"])

    def test_recorded_validation_is_rerunnable_only_when_it_names_a_command(self):
        python = sys.executable
        self.assertEqual(EVAL.runnable_validation("python3 -m unittest discover -s tests"),
                         [python, "-m", "unittest", "discover", "-s", "tests"])
        # Seen in a real run: the agent ran `python3 -m unittest X` and recorded `unittest X`.
        self.assertEqual(EVAL.runnable_validation("unittest tests.test_app"), [python, "-m", "unittest", "tests.test_app"])
        self.assertIsNone(EVAL.runnable_validation("unit-tests"))

    def test_summary_separates_consistency_rerunnability_and_verified_remediation(self):
        def record(sample, repeat, validations, rerunnable, steps):
            return {
                "sample": sample, "axis": "baseline", "repeat": repeat, "passed": True,
                "agent": {"steps": steps},
                **{name: {"passed": True, "checks": {}} for name in EVAL.CRITERIA},
                "consistent_evidence": {"passed": True, "checks": {}, "fix_count": validations,
                                        "fixes_with_rerunnable_validation": rerunnable},
            }

        conflict = [{"command": "agent resolve", "codes": ["RESOLVE_AXIS_CONFLICT"]},
                    {"command": "agent resolve", "codes": []}]
        summary = EVAL.aggregate(
            [
                record("a", 1, 1, 1, [{"command": "threads", "codes": ["BLOCKING_ITEMS_REMAIN"]}]),
                record("a", 2, 1, 0, []),
                record("b", 1, 0, 0, conflict),
            ],
            {"run_id": "t", "agent": "scripted", "model": None, "repeats": 2},
        )

        self.assertEqual(summary["evidence_consistency"], {"count": 3, "of": 3, "rate": 1.0})
        self.assertEqual(summary["evidence_rerunnability"], {"count": 1, "of": 2, "rate": 0.5})
        # A decline run has no fix to verify, so it is outside the denominator.
        self.assertEqual(summary["verified_remediation"], {"count": 1, "of": 2, "rate": 0.5})
        self.assertEqual(list(summary["deviations"]), ["RESOLVE_AXIS_CONFLICT"])
        conflict_row = summary["deviations"]["RESOLVE_AXIS_CONFLICT"]
        self.assertEqual((conflict_row["runs"], conflict_row["next_steps"]), (["b#1"], {"agent resolve": 1}))
        self.assertIn("Verified remediation", EVAL.render_markdown(summary))

    def test_scripted_step_with_an_off_path_code_reaches_the_summary(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        steps = EVAL.run_scripted(fixture)["steps"]
        self.assertEqual([step["command"] for step in steps], ["address", "agent resolve", "agent publish", "final-gate"])
        # The scripted shape: string label, scalar reason_code. A failed control must still summarize.
        steps[-1]["reason_code"] = "FINAL_GATE_MISSING_REPLY_EVIDENCE"
        record = {"sample": "s", "axis": "baseline", "repeat": 1, "passed": False, "agent": {"steps": steps}}

        summary = EVAL.aggregate([record], {"run_id": "t", "agent": "scripted", "model": None, "repeats": 1})

        row = summary["deviations"]["FINAL_GATE_MISSING_REPLY_EVIDENCE"]
        self.assertEqual((row["steps"], row["next_steps"], row["runs_passed"]), ({"final-gate": 1}, {"none": 1}, 0))

    def test_pushed_binary_file_does_not_break_the_fake(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        (fixture.checkout / "app" / "blob.bin").write_bytes(b"\x00\x01\x02")
        EVAL.git(fixture.checkout, "add", "app/blob.bin", env=fixture.env)
        EVAL.git(fixture.checkout, "commit", "-q", "-m", "add blob", env=fixture.env)
        EVAL.git(fixture.checkout, "push", "-q", "origin", "HEAD", env=fixture.env)

        EVAL.run_runtime(fixture, "address", fixture.repo, fixture.pr, "--lean")

        files = {row["filename"]: row for row in fixture.gh_state()["files"]}
        self.assertEqual(files["app/blob.bin"]["changes"], 0)
        self.assertTrue(all(call["handled"] for call in fixture.gh_calls()))

    def test_fixture_setup_failure_becomes_a_failed_run_record(self):
        options = argparse.Namespace(agent="scripted", keep=False)
        out_dir = self.root / "out"
        with mock.patch.object(EVAL, "build_fixture", side_effect=EVAL.EvalError("git clone timed out")):
            record = EVAL.run_one("nonfinite-shutdown-wait", 1, options, out_dir, self.root)

        self.assertEqual((record["passed"], record["error"]), (False, "git clone timed out"))
        self.assertTrue((out_dir / "nonfinite-shutdown-wait" / "run-1" / "run.json").is_file())

    def test_reason_codes_map_to_attribution_axes(self):
        self.assertEqual(EVAL.reason_axis("LEASE_CONFLICT"), "lease")
        self.assertEqual(EVAL.reason_axis("MISSING_VALIDATION_EVIDENCE"), "verification")
        self.assertEqual(EVAL.reason_axis("FINAL_GATE_MISSING_REPLY_EVIDENCE"), "recovery")
        self.assertEqual(EVAL.reason_axis("MISSING_CLASSIFICATION"), "classification")
        self.assertEqual(EVAL.reason_axis("PARTIAL_PR_SCOPE"), "input")


if __name__ == "__main__":
    unittest.main()
