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
        self.assertIn("  pull_request:\n    types: [opened, synchronize, reopened]", content)
        self.assertIn("  pull_request_target:\n    types: [edited]", content)
        block = content.split("  validate-base:\n", 1)[1]
        self.assertIn("github.event_name == 'pull_request_target'", block)
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

    def test_metadata_event_never_executes_source_or_produces_preview(self):
        ci = (WORKFLOWS / "ci.yml").read_text()
        target = ci.split("  validate-base:\n", 1)[1].split("  lint-and-test:\n", 1)[0]
        self.assertIn("permissions: {}", target)
        self.assertNotIn("uses:", target)
        self.assertNotIn("secrets.", target)
        for job in ("lint-and-test", "otel-minimum-versions"):
            block = ci.split(f"  {job}:\n", 1)[1].split("    steps:", 1)[0]
            self.assertIn("if: github.event_name != 'pull_request_target'", block)
        preview = ci.split("  pr-dev-preview:\n", 1)[1].split("    steps:", 1)[0]
        self.assertIn("github.event_name == 'pull_request'", preview)
        consumer = (WORKFLOWS / "homebrew-preview.yml").read_text()
        self.assertIn("github.event.workflow_run.event == 'pull_request'", consumer)

    def test_ineligible_completions_cannot_displace_pending_preview_publication(self):
        preview = (WORKFLOWS / "homebrew-preview.yml").read_text()
        group = preview.split("  group: ", 1)[1].splitlines()[0]
        # Queue admission happens before inspect.if, so both must use the same predicate.
        predicate = preview.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
        predicate = " ".join(predicate.split())
        self.assertIn(predicate, group)
        self.assertIn("'publication' || github.run_id", group)
        self.assertTrue(group.startswith("homebrew-preview-${{"))
