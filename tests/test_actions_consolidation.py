"""Contracts for the six operator-facing Actions entry points."""

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


class ActionsConsolidationTests(unittest.TestCase):
    def test_six_operational_workflows(self):
        self.assertEqual({p.name for p in WORKFLOWS.glob("*.yml")}, {
            "ci.yml", "homebrew.yml", "release.yml", "plugin-marketplace.yml", "pr-commit-semantics.yml",
        })

    def test_target_guard_runs_for_base_edits_and_rejects_other_main_sources(self):
        content = (WORKFLOWS / "ci.yml").read_text()
        self.assertIn("  pull_request:\n    types: [opened, synchronize, reopened]", content)
        self.assertIn("  pull_request_target:\n    types: [edited]", content)
        block = content.split("  validate-base:\n", 1)[1]
        self.assertIn("github.event_name == 'pull_request_target'", block)
        guard = block.split("        run: |\n", 1)[1]
        # The guard is a real executable step, rather than a duplicated policy.
        import textwrap
        guard = textwrap.dedent(guard.split("\n  lint-and-test:", 1)[0])
        for base, head, expected in (("main", "develop", 0), ("main", "feature", 0),
                                     ("develop", "feature", 1)):
            with self.subTest(base=base, head=head):
                env = dict(os.environ, BASE_REF=base, HEAD_REF=head)
                result = subprocess.run(["bash", "-c", guard], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_publication_boundaries_remain_independently_retryable(self):
        release = (WORKFLOWS / "release.yml").read_text()
        brew = (WORKFLOWS / "homebrew.yml").read_text()
        self.assertTrue(release.startswith("name: Release\n"))
        self.assertTrue(brew.startswith("name: Homebrew\n"))
        self.assertIn("uses: ./.github/workflows/homebrew.yml", release)
        self.assertIn("workflow_dispatch:", brew)
        self.assertIn("needs: [publish-bottles, verify-bottles]", brew)
        for target in ("macos-15", "macos-15-intel", "macos-26", "macos-26-intel"):
            self.assertIn(target, brew)

    def test_metadata_event_never_executes_source_or_produces_preview(self):
        ci = (WORKFLOWS / "ci.yml").read_text()
        target = ci.split("  validate-base:\n", 1)[1].split("  lint-and-test:\n", 1)[0]
        self.assertIn("permissions: {}", target)
        self.assertNotIn("uses:", target)
        self.assertNotIn("secrets.", target)
        for job in ("lint-and-test", "otel-minimum-versions"):
            block = ci.split(f"  {job}:\n", 1)[1].split("    steps:", 1)[0]
            self.assertIn("if: github.event_name != 'pull_request_target'", block)
        self.assertNotIn('pr-dev-preview:', ci)
