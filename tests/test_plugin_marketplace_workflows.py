"""Protect publication authority and the recovery-only distribution lane."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def job(text, name):
    block = text.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"\n  [a-z][a-z0-9-]*:\n", block, maxsplit=1)[0]


class PluginMarketplaceWorkflowTests(unittest.TestCase):
    def test_stable_publication_waits_for_pypi_and_uses_exact_source(self):
        release = (WORKFLOWS / 'release.yml').read_text()
        publish = job(release, 'publish-plugin-marketplace')
        for expected in ('needs: [verify, publish-pypi]', "vars.RELEASE_ENABLED == 'true'",
                         'ref: ${{ needs.verify.outputs.source_sha }}', 'fetch-depth: 0',
                         'persist-credentials: false', 'contents: write', 'artifact-ids:',
                         'python -m scripts.release.plugin_release publish', 'handoff verify'):
            self.assertIn(expected, publish)
        self.assertNotIn('id-token:', publish)
        self.assertNotIn('python -m build', publish)
        self.assertIn('plugin_release prepare', job(release, 'verify'))

    def test_recovery_is_version_only_trusted_and_serialized_with_release(self):
        recovery = (WORKFLOWS / "plugin-marketplace.yml").read_text()
        release = job((WORKFLOWS / "release.yml").read_text(), "publish-plugin-marketplace")
        recover = job(recovery, "recover-plugin-marketplace")
        triggers = recovery.split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        self.assertIn("version:", triggers)
        self.assertNotIn("push:", triggers)
        self.assertIn("if: vars.RELEASE_ENABLED == 'true' && github.ref == 'refs/heads/main'", recover)
        self.assertIn("ref: ${{ github.sha }}", recover)
        self.assertIn("persist-credentials: false", recover)
        self.assertIn("permissions:\n      contents: write", recover)
        self.assertIn("python -m scripts.release.plugin_release recover", recover)
        self.assertIn('VERSION: ${{ inputs.version }}', recover)
        for text in (release, recover):
            self.assertIn("group: plugin-marketplace-publication", text)
            self.assertIn("cancel-in-progress: false", text)
        for forbidden in ("semantic-release", "pypa/", "secrets.", "id-token:", "python -m build"):
            self.assertNotIn(forbidden, recovery)

    def test_codex_compatibility_runs_once_without_secrets_or_write_token(self):
        ci = (WORKFLOWS / "ci.yml").read_text()
        smoke = job(ci, "plugin-marketplace-smoke")
        self.assertIn("if: github.event_name != 'pull_request_target'", smoke)
        self.assertIn("contents: read", smoke)
        self.assertIn("persist-credentials: false", smoke)
        self.assertNotIn("matrix:", smoke)
        self.assertNotIn("secrets.", smoke)
        self.assertIn("@openai/codex@0.166.0", smoke)
        self.assertIn("python -m scripts.release.plugin_marketplace_smoke --codex", smoke)
        self.assertIn("actions/setup-node@v4", smoke)

    def test_readonly_builder_has_runtime_dependencies(self):
        release = (WORKFLOWS / 'release.yml').read_text()
        self.assertIn("python -m pip install -e '.[dev]' build twine", job(release, 'verify'))
        self.assertNotIn('pip install .', job(release, 'publish'))
