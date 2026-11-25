"""PR wheel identity and reviewer delivery contracts."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from shutil import which
from unittest.mock import patch
from zipfile import ZipFile

import yaml
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from scripts.release import pr_preview
from scripts.release.pr_preview import card, check_wheel, seal, verify, version_for

HEAD = "0123456" + "a" * 33
VERSION = "3.22.0.dev421+g0123456"
IDENTITY = {"pr": "421", "head": HEAD, "runId": "7", "attempt": "1"}
WHEEL = f"gh_address_cr-{VERSION}-py3-none-any.whl"


class PreviewWheelTests(unittest.TestCase):
    def test_pep440_version_keeps_full_source_in_the_receipt(self):
        self.assertEqual(version_for("3.22.0rc1", "421", HEAD), VERSION)
        self.assertEqual(version_for("2!3.22.0", "421", HEAD), f"2!{VERSION}")
        with self.assertRaises(ValueError):
            version_for("3.22.0", "421", HEAD[:7])

    def test_check_installed_archive_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            wheel = directory / WHEEL

            def pack(name, version):
                with ZipFile(wheel, "w") as contents:
                    contents.writestr("gh_address_cr.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n")

            pack("gh-address-cr", VERSION)
            receipt = seal(directory, VERSION, IDENTITY)
            self.assertEqual(verify(directory, IDENTITY), receipt)
            panel = card(receipt, "RbBtSn0w/gh-address-cr", "123")
            self.assertIn(HEAD, panel)
            self.assertIn("123/zip", panel)
            self.assertIn("packaging attempt `1`", panel)
            self.assertIn(receipt["sha256"], panel)
            self.assertIn(f'"$preview_dir/{WHEEL}"', panel)
            with self.assertRaisesRegex(ValueError, "expected source"):
                verify(directory, {**IDENTITY, "head": "b" * 40})
            with self.assertRaisesRegex(ValueError, "expected source"):
                verify(directory, {**IDENTITY, "attempt": "2"})
            with self.assertRaisesRegex(ValueError, "Wheel filename"):
                check_wheel(wheel, "3.22.0.dev420")
            pack("wrong-name", VERSION)
            with self.assertRaisesRegex(ValueError, "METADATA"):
                check_wheel(wheel, VERSION)
            pack("gh-address-cr", "3.22.0.dev420")
            with self.assertRaisesRegex(ValueError, "METADATA"):
                check_wheel(wheel, VERSION)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify(directory, IDENTITY)

    def test_preview_helper_uses_release_span_lifecycle(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        with (
            patch.object(pr_preview.shared, "initialize_telemetry", return_value=provider.get_tracer("test")),
            patch.object(pr_preview.shared, "shutdown_telemetry"),
            patch("builtins.print"),
            patch("sys.argv", ["pr_preview.py", "version", "/private/preview-fixture"]),
            patch.dict(os.environ, {
                "PR_NUMBER": "421", "PR_HEAD": HEAD, "GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1",
            }),
        ):
            self.assertEqual(pr_preview.shared.traced_main(pr_preview.main), 0)
            with patch.dict(os.environ, {"PR_HEAD": "invalid"}), self.assertRaises(ValueError):
                pr_preview.shared.traced_main(pr_preview.main)
        success, failure = exporter.get_finished_spans()
        self.assertEqual(success.kind, SpanKind.INTERNAL)
        self.assertEqual(success.attributes["process.exit.code"], 0)
        self.assertEqual(success.attributes["process.pid"], os.getpid())
        self.assertTrue(success.attributes["process.executable.name"])
        self.assertEqual(success.events[0].attributes["release.phase"], "version")
        self.assertEqual(failure.status.status_code, StatusCode.ERROR)
        self.assertIn("error.type", failure.attributes)
        self.assertNotIn("/private/preview-fixture", str([success.attributes, failure.attributes]))
        provider.shutdown()

    @unittest.skipUnless(which("node"), "Node is required to exercise the actual Actions script")
    def test_wheel_workflow_requires_matching_successful_python_ci(self):
        workflow = yaml.safe_load(Path(".github/workflows/pr-preview.yml").read_text())
        job = workflow["jobs"]["pr-preview"]
        self.assertEqual(job["needs"], "verify-ci")
        self.assertEqual(job["steps"][0]["with"]["ref"], "${{ github.event.pull_request.head.sha }}")
        self.assertEqual(job["steps"][1]["with"]["ref"], "${{ github.workflow_sha }}")
        self.assertIn('helper="$tools/scripts/release/pr_preview.py"', job["steps"][4]["run"])
        source = workflow["jobs"]["verify-ci"]["steps"][0]["with"]["script"]
        harness = r"""
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(0, 'utf8');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const runScript = new AsyncFunction('github', 'context', 'core', 'setTimeout', source);
const head = { sha: 'a'.repeat(40), ref: 'feature/wheel', repo: { id: 2 } };
const created_at = '2026-11-25T05:00:00Z';
const matching = {
  id: 10, head_sha: head.sha, head_branch: head.ref, head_repository: { id: 2 },
  created_at, pull_requests: [], status: 'completed', conclusion: 'success',
};
let result = matching;
let polls = 0;
const outputs = {};
const execute = () => runScript({
  rest: { actions: {
    getWorkflowRun: async () => ({ data: { created_at } }),
    listWorkflowRuns: async options => {
      assert.equal(options.workflow_id, 'ci.yml');
      assert.equal(options.event, 'pull_request');
      assert.equal(options.head_sha, head.sha);
      return { data: { workflow_runs: [
        { ...matching, id: 9, head_repository: { id: 3 } },
        { ...matching, id: 8, created_at: '2026-11-22T05:00:00Z' },
        ++polls === 1 ? { ...result, status: 'in_progress' } : result,
      ] } };
    },
  } },
}, { repo: { owner: 'RbBtSn0w', repo: 'gh-address-cr' }, payload: {
  pull_request: { head, number: 421 },
}, runId: 11 }, { setOutput: (key, value) => { outputs[key] = value; } }, callback => callback());

(async () => {
  await execute();
  assert.deepEqual(outputs, { 'run-id': 10 });
  assert.equal(polls, 2);
  result = { ...matching, conclusion: 'failure' };
  await assert.rejects(execute(), /Python CI failed/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(
            ["node", "-e", harness], input=source, capture_output=True, text=True, timeout=15, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(which("node"), "Node is required to exercise the actual Actions script")
    def test_resolver_uses_successful_upload_after_comment_only_rerun(self):
        workflow = yaml.safe_load(Path(".github/workflows/pr-preview.yml").read_text())
        comment = workflow["jobs"]["pr-preview-comment"]
        source = comment["steps"][0]["with"]["script"]
        self.assertTrue(comment["steps"][1]["with"]["merge-multiple"])
        harness = r"""
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(0, 'utf8');
const runScript = new Function('github', 'context', 'core', 'process',
  'return (async () => {' + source + '\n})();');
const head = 'a'.repeat(40);
const run = {
  id: 7, path: '.github/workflows/pr-preview.yml@refs/pull/421/merge', event: 'pull_request', run_attempt: 2,
  repository: { id: 2 }, head_repository: { id: 2 }, head_sha: head,
};
const pr = {
  number: 421, state: 'open', head: { sha: head, repo: { id: 2 } }, base: { ref: 'main', repo: { id: 2 } },
};
const artifact = { name: 'pr-preview-421-' + head + '-attempt-1', id: 123, expired: false };
let listed = [artifact];
let outputs = {};
const github = {
  rest: {
    actions: {
      getWorkflowRun: async () => ({ data: run }),
      listJobsForWorkflowRun: async () => [1, 2].map(run_attempt => ({
        name: 'PR preview package', run_id: 7, run_attempt, conclusion: 'success',
        steps: [{ name: 'Upload verified preview', conclusion: 'success' }],
      })),
      listWorkflowRunArtifacts: async () => listed,
    },
    pulls: { get: async () => ({ data: pr }) },
  },
  paginate: (fn, args) => fn(args),
};
const execute = () => runScript(github, {
  repo: { owner: 'RbBtSn0w', repo: 'gh-address-cr' },
  payload: { pull_request: { number: 421, head: { sha: head } } },
}, { setOutput: (key, value) => { outputs[key] = value; }, notice() {} }, { env: { SOURCE_RUN_ID: '7' } });
(async () => {
  await execute();
  assert.deepEqual(outputs, { pr: 421, head, attempt: 1, artifact: 123 });
  for (const unavailable of [[], [{ ...artifact, expired: true }]]) {
    listed = unavailable;
    await assert.rejects(execute(), /unexpired/);
  }
  outputs = {};
  pr.head.sha = 'b'.repeat(40);
  await execute();
  assert.deepEqual(outputs, {});
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(
            ["node", "-e", harness], input=source, capture_output=True, text=True, timeout=15, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
