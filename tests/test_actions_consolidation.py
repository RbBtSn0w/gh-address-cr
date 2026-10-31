"""Contracts for the five operator-facing Actions entry points."""

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


class ActionsConsolidationTests(unittest.TestCase):
    def test_five_operational_workflows(self):
        self.assertEqual({p.name for p in WORKFLOWS.glob("*.yml")}, {
            "ci.yml", "homebrew-preview.yml", "homebrew.yml", "release.yml", "branches.yml",
        })

    def test_target_guard_runs_for_base_edits_and_rejects_other_main_sources(self):
        content = (WORKFLOWS / "ci.yml").read_text()
        self.assertIn("types: [opened, edited, synchronize, reopened]", content)
        block = content.split("  validate-base:\n", 1)[1]
        self.assertIn("github.event_name == 'pull_request'", block)
        guard = block.split("        run: |\n", 1)[1]
        # The guard is a real executable step, rather than a duplicated policy.
        import textwrap
        guard = textwrap.dedent(guard.split("\n  lint-and-test:", 1)[0])
        for base, head, expected in (("main", "develop", 0), ("main", "feature", 1),
                                     ("develop", "feature", 0)):
            with self.subTest(base=base, head=head):
                env = dict(os.environ, BASE_REF=base, HEAD_REF=head)
                result = subprocess.run(["bash", "-c", guard], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_preview_trust_boundary_and_transition_names(self):
        ci = (WORKFLOWS / "ci.yml").read_text()
        preview = (WORKFLOWS / "homebrew-preview.yml").read_text()
        self.assertTrue(ci.startswith("name: Checks / Python\n"))
        self.assertIn('workflows: ["ci", "Checks / Python"]', preview)
        self.assertNotIn("pull_request_target:", ci)
        self.assertIn("path", (ROOT / "scripts/release/homebrew_preview.py").read_text())
        self.assertIn('".github/workflows/ci.yml"', (ROOT / "scripts/release/homebrew_support.py").read_text())

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
