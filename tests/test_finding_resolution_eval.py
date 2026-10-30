"""Offline control for the finding-resolution eval (scripts/eval_finding_resolution.py).

The eval scores LLM agents, so its fake GitHub and graders must be proven before
any agent run: the scripted reference agent passes every sample, each oracle
fails before the fix, and the graders reject a run that stops early or writes
to GitHub around the runtime.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
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
    def test_parallel_fake_reads_preserve_a_coherent_pr_head(self):
        fixture = self.fixture("malformed-report-fields")
        slow_reader = fixture.run_dir / "slow-reader.py"
        writing = fixture.run_dir / "writing"
        # Make an in-progress state write observable without relying on scheduler luck.
        slow_reader.write_text(
            "import builtins, os, pathlib, runpy, sys, time\n"
            "original_open = builtins.open\n"
            "def slow_open(path, mode='r', *args, **kwargs):\n"
            "    handle = original_open(path, mode, *args, **kwargs)\n"
            "    if str(path) == os.environ['FAKE_GH_STATE'] and mode == 'w':\n"
            f"        marker = pathlib.Path({str(writing)!r})\n"
            "        if not marker.exists():\n"
            "            marker.touch()\n"
            "            time.sleep(1)\n"
            "    return handle\n"
            "builtins.open = slow_open\n"
            "fake = sys.argv.pop(1)\n"
            "runpy.run_path(fake, run_name='__main__')\n", encoding="utf-8",
        )

        def read_head(_):
            return subprocess.run(
                [sys.executable, str(slow_reader), str(fixture.run_dir / "bin" / "gh"),
                 "pr", "view", "--json", "headRefOid"], cwd=fixture.checkout, env=fixture.env,
                capture_output=True, text=True, timeout=30,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            first = pool.submit(read_head, 0)
            deadline = time.monotonic() + 5
            while not writing.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(writing.exists(), "the first writer did not reach the controlled write boundary")
            following = [pool.submit(read_head, index) for index in range(1, 24)]
            results = [future.result() for future in [first, *following]]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["headRefOid"], fixture.pr_commits[-1])
        self.assertEqual(fixture.gh_state()["head_sha"], fixture.pr_commits[-1])

    def test_external_steps_accept_public_environment_diagnostics(self):
        value = {"schema_version": "finding-eval-result.v1", "identity": "local-test",
                 "steps": [{"command": "doctor", "codes": [], "exit_code": 0}]}
        self.assertEqual(EVAL.validate_runner_result(value), value)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def fixture(self, sample_id):
        return EVAL.build_fixture(EVAL.load_sample(sample_id), self.root / sample_id, f"eval-test-{sample_id}")

    def external_options(self, source, *, timeout=5):
        runner = self.root / "runner.py"
        runner.write_text(source, encoding="utf-8")
        return argparse.Namespace(runner_command=[sys.executable, str(runner)], timeout=timeout)

    def test_external_runner_receives_neutral_request_and_cannot_vouch_for_grade(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "private-test-token", "GIT_DIR": "/invalid/override"}):
            fixture = self.fixture("nonfinite-shutdown-wait")
        options = self.external_options(
            "import json, os, pathlib, sys\n"
            "request = json.load(sys.stdin)\n"
            "assert request['schema_version'] == 'finding-eval-request.v1'\n"
            "assert request['repo'] == 'eval-fixture/nonfinite-shutdown-wait'\n"
            "assert request['pr'] == '351'\n"
            "assert request['task'] == 'address'\n"
            "assert request['skill_path'] == '.eval/skill'\n"
            "assert pathlib.Path(request['skill_path'], 'SKILL.md').is_file()\n"
            "assert pathlib.Path('.git').is_dir()\n"
            "assert not pathlib.Path('.claude').exists()\n"
            "assert os.environ['DISABLE_TELEMETRY'] == '1'\n"
            "assert 'GH_TOKEN' not in os.environ\n"
            "print(json.dumps({'schema_version':'finding-eval-result.v1','identity':'local-test',"
            "'steps':[{'command':'final-gate','codes':['PASSED'],'exit_code':0}],'cost_usd':0.0}))\n"
        )
        out = self.root / "output"
        out.mkdir()
        result = EVAL.run_external(fixture, options, out)
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(EVAL.git(fixture.checkout, "status", "--porcelain", env=fixture.env), "")
        self.assertEqual(result["steps"], [{"command": "final-gate", "codes": ["PASSED"], "exit_code": 0}])
        self.assertFalse(EVAL.grade(fixture)["legal_state"]["passed"])

    def test_five_samples_cover_the_attribution_axes(self):
        axes = {EVAL.load_sample(sample_id)["axis"] for sample_id in EVAL.sample_ids()}
        self.assertEqual(axes, {"baseline", "lease", "classification", "recovery", "verification"})

    def test_reference_agent_passes_every_sample(self):
        for sample_id in EVAL.sample_ids():
            with self.subTest(sample=sample_id):
                fixture = self.fixture(sample_id)
                steps = EVAL.run_scripted(fixture)["steps"]
                result = EVAL.grade(fixture)
                for name in EVAL.CRITERIA:
                    self.assertTrue(result[name]["passed"], (name, result[name], steps))
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

    def test_flags_oracle_rejects_a_fix_that_only_skips_strings(self):
        fixture = self.fixture("malformed-report-fields")
        clone = EVAL.clone_pushed_head(fixture, "strings-only")
        module = clone / "app" / "compare_reports.py"
        original = module.read_text(encoding="utf-8")
        patched = original.replace(
            '            kinds.update({flag_kind(str(flag)) for flag in row.get("inefficiency_flags") or []})',
            '            flags = row.get("inefficiency_flags") or []\n'
            '            if not isinstance(flags, str):\n'
            '                kinds.update({flag_kind(str(flag)) for flag in flags})',
        )
        self.assertNotEqual(patched, original, "the replacement anchor no longer matches the sample")
        module.write_text(patched, encoding="utf-8")
        flags_thread = next(t for t in fixture.sample["threads"] if t["id"] == "PRRT_eval327flags")

        self.assertFalse(EVAL.run_oracle(fixture, clone, flags_thread["oracle_tests"]),
                         "a fix that still counts dict keys must not pass the flags finding")

    def two_finding_run(self, *, flags_commit):
        """Fix `malformed-report-fields` in two commits: A fixes the flags finding, B the count finding."""
        fixture = self.fixture("malformed-report-fields")
        sample = fixture.sample
        module = fixture.checkout / "app" / "compare_reports.py"
        flags_only = module.read_text(encoding="utf-8").replace(
            '            kinds.update({flag_kind(str(flag)) for flag in row.get("inefficiency_flags") or []})',
            '            flags = row.get("inefficiency_flags")\n'
            '            if isinstance(flags, list):\n'
            '                kinds.update({flag_kind(str(flag)) for flag in flags})',
        )
        commits = {}
        for name, text in (("a", flags_only),
                           ("b", (sample["dir"] / "solution" / "app" / "compare_reports.py").read_text(encoding="utf-8"))):
            module.write_text(text, encoding="utf-8")
            EVAL.git(fixture.checkout, "commit", "-q", "-am", f"fix: part {name}", env=fixture.env)
            commits[name] = EVAL.git(fixture.checkout, "rev-parse", "HEAD", env=fixture.env)
        EVAL.git(fixture.checkout, "push", "-q", "origin", "HEAD", env=fixture.env)
        cited = {"PRRT_eval327flags": commits["a"] if flags_commit == "a" else fixture.pr_commits[0],
                 "PRRT_eval327needs": commits["b"]}
        EVAL.run_runtime(fixture, "address", fixture.repo, fixture.pr, "--lean")
        for item in sample["reference"]["items"]:
            EVAL.run_runtime(fixture, *EVAL.scripted_resolve_args(fixture, item, cited[item["thread"]],
                                                                  ["app/compare_reports.py"]))
        EVAL.run_runtime(fixture, "agent", "publish", fixture.repo, fixture.pr)
        EVAL.run_runtime(fixture, "final-gate", fixture.repo, fixture.pr)
        return EVAL.grade(fixture)

    def test_sequential_fixes_each_citing_their_own_commit_pass(self):
        result = self.two_finding_run(flags_commit="a")

        self.assertTrue(result["legal_state"]["passed"], result["legal_state"])
        self.assertTrue(result["consistent_evidence"]["passed"], result["consistent_evidence"])

    def test_one_wrong_citation_fails_even_when_another_cites_a_later_commit(self):
        result = self.two_finding_run(flags_commit="introducing")

        evidence = result["consistent_evidence"]
        self.assertTrue(evidence["checks"]["fix_commits_in_pr"])
        self.assertFalse(evidence["checks"]["oracle_passes_at_cited_commit"])
        self.assertEqual(evidence["oracle_at_cited_commit"], {"github-thread:PRRT_eval327flags": False,
                                                              "github-thread:PRRT_eval327needs": True})

    def test_an_earlier_passed_gate_does_not_vouch_for_the_current_session(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        EVAL.run_scripted(fixture)
        # A new review arrives after the passing gate archived the first session.
        state = fixture.gh_state()
        state["threads"].append({"id": "PRRT_late", "isResolved": False, "isOutdated": False, "path": "app/__init__.py",
                                 "line": 1, "comments": [{"url": "https://github.test/review/late",
                                                          "author": "reviewer-bot", "body": "Late finding."}]})
        fixture.state_path.write_text(json.dumps(state), encoding="utf-8")
        EVAL.run_runtime(fixture, "address", fixture.repo, fixture.pr, "--lean")
        EVAL.run_runtime(fixture, "final-gate", fixture.repo, fixture.pr)

        checks = EVAL.grade(fixture)["legal_state"]["checks"]

        self.assertFalse(checks["final_gate_passed"])

    def test_rerunning_final_gate_after_it_passed_keeps_the_handling_evidence(self):
        # Seen in a real run: the agent reran final-gate only to print its summary; the
        # passing gate had archived the workspace, so the rerun opened an empty session.
        fixture = self.fixture("malformed-report-fields")
        EVAL.run_scripted(fixture)
        EVAL.run_runtime(fixture, "final-gate", fixture.repo, fixture.pr)

        result = EVAL.grade(fixture)

        for name in EVAL.CRITERIA:
            self.assertTrue(result[name]["passed"], (name, result[name]))
        self.assertTrue(result["legal_state"]["checks"]["handling_session_gated"])

    def test_eval_runs_read_one_skill_snapshot(self):
        # Seen in a real run: the checkout switched branches mid-eval, so later runs read other guidance.
        live = self.root / "live-skill"
        shutil.copytree(EVAL.SKILL_PAYLOAD, live)
        before = EVAL.payload_digest(live)
        installed = []
        build = EVAL.build_fixture

        def capture(sample, run_dir, conversation_id, skill_payload=EVAL.SKILL_PAYLOAD):
            fixture = build(sample, run_dir, conversation_id, skill_payload)
            installed.append(EVAL.payload_digest(fixture.checkout / ".eval" / "skill"))
            (live / "SKILL.md").write_text("edited mid-eval\n", encoding="utf-8")
            return fixture

        options = argparse.Namespace(agent="scripted", repeats=2, samples=["preflight-timeout-claim"],
                                     output_root=self.root / "results", run_id="snapshot", keep=False)
        with mock.patch.object(EVAL, "SKILL_PAYLOAD", live), \
                mock.patch.object(EVAL, "build_fixture", side_effect=capture):
            summary = EVAL.run_eval(options)

        self.assertEqual(installed, [before, before], "an edit to skill/ mid-eval reached a later run")
        self.assertEqual(summary["skill_sha256"], before)

    def test_checkout_state_tracks_live_inputs_only(self):
        repo = self.root / "repo"
        for name in ("src/app.py", "docs/notes.md"):
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text("one\n", encoding="utf-8")
        # A git location override inherited from the host (a hook, say) must not redirect the eval's git calls.
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.root / "elsewhere.git")}), \
                mock.patch.object(EVAL, "ROOT", repo):
            for args in (("init", "-q"), ("add", "-A"),
                         ("-c", "user.name=eval", "-c", "user.email=eval@example.test", "commit", "-q", "-m", "init")):
                EVAL.git(repo, *args)
            self.assertFalse((self.root / "elsewhere.git").exists())
            clean = EVAL.checkout_state()
            (repo / "docs" / "notes.md").write_text("two\n", encoding="utf-8")
            self.assertEqual(EVAL.checkout_state(), clean, "a change outside the live inputs is not flagged")
            (repo / "src" / "app.py").write_text("two\n", encoding="utf-8")
            edited = EVAL.checkout_state()
            self.assertNotEqual(edited, clean)
            (repo / "src" / "app.py").write_text("three\n", encoding="utf-8")
            self.assertNotEqual(EVAL.checkout_state(), edited, "a second edit to an already modified file counts")

    def test_runs_after_a_checkout_change_are_flagged(self):
        options = argparse.Namespace(agent="scripted", repeats=2, samples=["preflight-timeout-claim"],
                                     output_root=self.root / "results", run_id="switched", keep=False)
        # Read once when the eval starts, then after each run.
        with mock.patch.object(EVAL, "checkout_state", side_effect=["start", "start", "switched"]):
            summary = EVAL.run_eval(options)

        self.assertEqual(summary["checkout_changed_runs"], ["preflight-timeout-claim#2"])
        self.assertEqual(summary["passed"], 2, "a checkout change is a validity warning, not an agent failure")
        self.assertIn("checkout changed during preflight-timeout-claim#2", EVAL.render_markdown(summary))

    def test_push_after_the_gate_leaves_the_pushed_head_unproven(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        EVAL.run_scripted(fixture)
        (fixture.checkout / "README.md").write_text("changed after the gate\n", encoding="utf-8")
        EVAL.git(fixture.checkout, "commit", "-q", "-am", "docs: after gate", env=fixture.env)
        EVAL.git(fixture.checkout, "push", "-q", "origin", "HEAD", env=fixture.env)

        checks = EVAL.grade(fixture)["legal_state"]["checks"]

        self.assertTrue(checks["final_gate_passed"])
        self.assertFalse(checks["gate_saw_pushed_head"])

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

    def test_reporting_uses_stored_steps_without_vendor_log_parsing(self):
        record = {"agent": {"steps": [{"command": "address", "codes": [], "exit_code": 0}]}}
        path = self.root / "run.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        (self.root / "transcript.jsonl").write_text("not a vendor transcript", encoding="utf-8")
        self.assertEqual(EVAL.load_record(path), record)

    def test_runner_config_rejects_unsupported_and_unsafe_shapes(self):
        path = self.root / "config.json"
        good = {"schema_version": "finding-eval-runner.v1", "command": [sys.executable, "runner.py"]}
        path.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(EVAL.load_runner_config(path), good["command"])
        for bad in ({**good, "schema_version": "future"}, {**good, "extra": True},
                    {**good, "command": "echo x"}, {**good, "command": []},
                    {**good, "command": [True]}, {**good, "command": ["a\0b"]},
                    {**good, "command": ["x" * 8193]}):
            with self.subTest(bad=bad):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(EVAL.EvalError):
                    EVAL.load_runner_config(path)
        path.write_text(" " * (EVAL.RUNNER_CONFIG_LIMIT + 1), encoding="utf-8")
        with self.assertRaisesRegex(EVAL.EvalError, "too_large"):
            EVAL.load_runner_config(path)

    def test_external_result_validation_is_strict_and_bounded(self):
        good = {"schema_version": "finding-eval-result.v1", "identity": "local-test", "steps": []}
        bad_values = [None, [], {}, {**good, "schema_version": "future"}, {**good, "extra": 1},
                      {**good, "identity": "a" * 65}, {**good, "identity": "private/path"},
                      {**good, "steps": "address"}, {**good, "steps": [{}] * 1001}]
        for cost in (float("nan"), float("inf"), -1, True, "1"):
            bad_values.append({**good, "cost_usd": cost})
        step = {"command": "address", "codes": [], "exit_code": 0}
        for bad_step in ({**step, "extra": 1}, {**step, "command": "address /private/path"},
                         {**step, "command": []}, {**step, "codes": ["private/path"]},
                         {**step, "codes": ["X"] * 17}, {**step, "exit_code": True},
                         {**step, "exit_code": 256}):
            bad_values.append({**good, "steps": [bad_step]})
        self.assertEqual(EVAL.validate_runner_result(good), good)
        for bad in bad_values:
            with self.subTest(bad=bad), self.assertRaises(EVAL.EvalError):
                EVAL.validate_runner_result(bad)

    def test_external_failures_keep_local_output_without_leaking_it(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        cases = [("print('secret-token-not-json')", "runner_invalid_json"),
                 ("print('x' * 1048577)", "runner_output_too_large"),
                 ("import sys; print('secret-token'); sys.exit(7)", "runner_nonzero_exit"),
                 ("pass", "runner_invalid_json")]
        for number, (source, error) in enumerate(cases):
            with self.subTest(error=error):
                options = self.external_options(source)
                out = self.root / f"out-{number}"
                out.mkdir()
                result = EVAL.run_external(fixture, options, out)
                self.assertFalse(result["succeeded"])
                self.assertEqual(result["error"], error)
                self.assertNotIn("secret-token", json.dumps(result))
                self.assertTrue((out / "runner.stdout").is_file())
                self.assertTrue((out / "runner.stderr").is_file())
        raw = self.root / "duplicate.json"
        raw.write_text('{"x":1,"x":2}', encoding="utf-8")
        with self.assertRaisesRegex(EVAL.EvalError, "duplicate"):
            EVAL.bounded_json(raw, 100)

    def test_external_process_spans_are_observed_and_public_safe(self):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry.trace import SpanKind

        from gh_address_cr import otel_tracing

        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("external-eval-test")
        fixture = self.fixture("nonfinite-shutdown-wait")
        with mock.patch.object(otel_tracing, "_tracer", tracer), tracer.start_as_current_span("test-parent"):
            for code in (0, 7):
                source = ("import json, sys\n"
                          "print(json.dumps({'schema_version':'finding-eval-result.v1',"
                          "'identity':'private-identity','steps':[]}))\n"
                          f"sys.exit({code})\n")
                options = self.external_options(source)
                out = self.root / f"spans-{code}"
                out.mkdir()
                result = EVAL.run_external(fixture, options, out)
                self.assertEqual(result["succeeded"], code == 0)
        spans = [span for span in exporter.get_finished_spans() if span.kind == SpanKind.CLIENT]
        self.assertEqual(len(spans), 2)
        for span, code in zip(spans, (0, 7), strict=True):
            self.assertEqual(span.name, Path(sys.executable).name)
            self.assertEqual(span.attributes["process.executable.name"], Path(sys.executable).name)
            self.assertGreater(span.attributes["process.pid"], 0)
            self.assertEqual(span.attributes["process.exit.code"], code)
            self.assertNotIn("private-identity", str(span.attributes))
            self.assertNotIn(str(self.root), str(span.attributes))
            self.assertNotIn("process.command_args", span.attributes)
        self.assertEqual(spans[1].attributes["error.type"], "runner_nonzero_exit")
        parent = next(span for span in exporter.get_finished_spans() if span.name == "test-parent")
        self.assertEqual([dict(event.attributes)["succeeded"] for event in parent.events], [True, False])
        provider.shutdown()

    def test_failed_external_process_cannot_pass_even_when_grader_passes(self):
        options = self.external_options(
            "import json, sys\n"
            "print(json.dumps({'schema_version':'finding-eval-result.v1','identity':'local-test',"
            "'steps':[],'cost_usd':0.25}))\n"
            "sys.exit(7)\n")
        options.agent = "external"
        options.keep = False
        grade = {criterion: {"passed": True, "checks": {}} for criterion in EVAL.CRITERIA}
        with mock.patch.object(EVAL, "grade", return_value=grade):
            record = EVAL.run_one("nonfinite-shutdown-wait", 1, options, self.root / "out", self.root)
        self.assertFalse(record["passed"])
        self.assertEqual(record["agent"]["error"], "runner_nonzero_exit")
        self.assertEqual(record["agent"]["cost_usd"], 0.25)
        summary = EVAL.aggregate([record], {"agent": "external"})
        self.assertEqual(summary["fix_attempt_success"]["of"], 1)
        self.assertEqual(summary["total_cost_usd"], 0.25)
        self.assertEqual(summary["samples"]["nonfinite-shutdown-wait"]["errors"], ["runner_nonzero_exit"])

    def test_external_cli_and_report_preserve_normalized_stored_observations(self):
        options = self.external_options(
            "import json\n"
            "print(json.dumps({'schema_version':'finding-eval-result.v1','identity':'local-test',"
            "'steps':[{'command':'address','codes':['NO_ACTIVE_SESSION'],'exit_code':5}]}))\n")
        config = self.root / "runner.json"
        config.write_text(json.dumps({"schema_version": "finding-eval-runner.v1",
                                      "command": options.runner_command}), encoding="utf-8")
        output = self.root / "results"
        load_config = EVAL.load_runner_config

        def load_then_change(path):
            command = load_config(path)
            path.write_text("config changed after load", encoding="utf-8")
            return command

        with mock.patch("sys.stdout", new_callable=io.StringIO), \
                mock.patch.object(EVAL, "load_runner_config", side_effect=load_then_change) as loaded:
            code = EVAL.main(["run", "--agent", "external", "--runner", str(config),
                              "--sample", "preflight-timeout-claim", "--output-root", str(output),
                              "--run-id", "external-local", "--repeats", "2", "--timeout", "37"])
        self.assertEqual(code, 1, "a self-reported step cannot complete an untouched fixture")
        loaded.assert_called_once_with(config)
        run_dir = output / "external-local"
        snapshot = run_dir / "runner-config.json"
        self.assertEqual(json.loads(snapshot.read_text(encoding="utf-8"))["command"], options.runner_command)
        expected_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        path = run_dir / "preflight-timeout-claim" / "run-1" / "run.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["agent"]["steps"][0]["codes"], ["NO_ACTIVE_SESSION"])
        (path.parent / "runner.stdout").write_text("invalid replacement raw log", encoding="utf-8")
        (path.parent / "transcript.jsonl").write_text("invalid vendor log", encoding="utf-8")
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(EVAL.main(["report", str(run_dir)]), 1)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertIn("NO_ACTIVE_SESSION", summary["deviations"])
        self.assertNotIn("model", summary)
        self.assertEqual(summary["runner_config_sha256"], expected_digest)
        self.assertEqual(summary["timeout_s"], 37)
        self.assertNotIn("local-test", json.dumps(summary))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), stored)

    def test_cli_rejects_old_vendor_options_and_missing_runner(self):
        cases = [["--agent", "claude"], ["--agent", "external"],
                 ["--agent", "scripted", "--runner", "config.json"]]
        for option in ("--model", "--max-turns", "--max-budget-usd", "--allowed-tools"):
            cases.append(["--agent", "scripted", option, "x"])
        for args in cases:
            with self.subTest(args=args), mock.patch("sys.stderr"), self.assertRaises(SystemExit) as result:
                EVAL.main(["run", *args])
            self.assertEqual(result.exception.code, 2)

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
            {"run_id": "t", "agent": "scripted", "repeats": 2},
        )

        self.assertEqual(summary["evidence_consistency"], {"count": 3, "of": 3, "rate": 1.0})
        self.assertEqual(summary["evidence_rerunnability"], {"count": 1, "of": 2, "rate": 0.5})
        # A decline run has no fix to verify, so it is outside the denominator.
        self.assertEqual(summary["verified_remediation"], {"count": 1, "of": 2, "rate": 0.5})
        self.assertEqual(list(summary["deviations"]), ["RESOLVE_AXIS_CONFLICT"])
        conflict_row = summary["deviations"]["RESOLVE_AXIS_CONFLICT"]
        self.assertEqual((conflict_row["runs"], conflict_row["next_steps"]), (["b#1"], {"agent resolve": 1}))
        self.assertIn("Verified remediation", EVAL.render_markdown(summary))

    def test_fix_attempt_success_counts_runs_that_failed_before_a_fix(self):
        def record(repeat, fixes, passed):
            evidence = {"passed": passed, "checks": {}, "fix_count": fixes, "fixes_with_rerunnable_validation": fixes}
            return {"sample": "a", "axis": "baseline", "repeat": repeat, "passed": passed, "expects_fix": True,
                    "agent": {"steps": []}, "consistent_evidence": evidence}

        summary = EVAL.aggregate([record(1, 1, True)] + [record(n, 0, False) for n in range(2, 6)],
                                 {"run_id": "t", "agent": "scripted", "repeats": 5})

        self.assertEqual(summary["verified_remediation"], {"count": 1, "of": 1, "rate": 1.0})
        self.assertEqual(summary["fix_attempt_success"], {"count": 1, "of": 5, "rate": 0.2})

    def test_scripted_step_with_an_off_path_code_reaches_the_summary(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        steps = EVAL.run_scripted(fixture)["steps"]
        self.assertEqual([step["command"] for step in steps], ["address", "agent resolve", "agent publish", "final-gate"])
        # The scripted shape: string label, scalar reason_code. A failed control must still summarize.
        steps[-1]["reason_code"] = "FINAL_GATE_MISSING_REPLY_EVIDENCE"
        record = {"sample": "s", "axis": "baseline", "repeat": 1, "passed": False, "agent": {"steps": steps}}

        summary = EVAL.aggregate([record], {"run_id": "t", "agent": "scripted", "repeats": 1})

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

    def test_agent_timeout_stops_tool_processes_before_grading(self):
        fixture = self.fixture("nonfinite-shutdown-wait")
        pid_file = self.root / "tool.pid"
        options = self.external_options(
            "import pathlib, subprocess, time\n"
            "tool = subprocess.Popen(['sleep', '30'])\n"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(tool.pid))\n"
            "time.sleep(30)\n", timeout=0.5)
        out_dir = self.root / "agent-out"
        out_dir.mkdir()

        agent = EVAL.run_external(fixture, options, out_dir)

        tool_pid = int(pid_file.read_text(encoding="utf-8"))
        self.addCleanup(self.kill_quietly, tool_pid)
        self.assertEqual(agent["exit_code"], 124)
        self.assertEqual(agent["error"], "runner_timeout")
        self.assertFalse(self.alive(tool_pid), "a tool process outlived the timed-out agent into grading")

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    @staticmethod
    def kill_quietly(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def test_grading_failure_keeps_the_agent_result(self):
        options = argparse.Namespace(agent="scripted", keep=False)
        out_dir = self.root / "out"
        with mock.patch.object(EVAL, "grade", side_effect=EVAL.EvalError("git clone timed out")):
            record = EVAL.run_one("nonfinite-shutdown-wait", 1, options, out_dir, self.root)

        self.assertEqual((record["passed"], record["error"]), (False, "git clone timed out"))
        self.assertEqual([step["command"] for step in record["agent"]["steps"]],
                         ["address", "agent resolve", "agent publish", "final-gate"])
        self.assertTrue(record["expects_fix"])

    def test_reason_codes_map_to_attribution_axes(self):
        self.assertEqual(EVAL.reason_axis("LEASE_CONFLICT"), "lease")
        self.assertEqual(EVAL.reason_axis("MISSING_VALIDATION_EVIDENCE"), "verification")
        self.assertEqual(EVAL.reason_axis("FINAL_GATE_MISSING_REPLY_EVIDENCE"), "recovery")
        self.assertEqual(EVAL.reason_axis("MISSING_CLASSIFICATION"), "classification")
        self.assertEqual(EVAL.reason_axis("PARTIAL_PR_SCOPE"), "input")


if __name__ == "__main__":
    unittest.main()
