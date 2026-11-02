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
        release = (WORKFLOWS / "release.yml").read_text()
        publish = job(release, "publish-plugin-marketplace")
        self.assertIn("needs: [build-release-package, publish-pypi]", publish)
        self.assertIn("outputs.publish_target == 'pypi'", publish)
        self.assertIn("outputs.released == 'true'", publish)
        self.assertIn("ref: ${{ needs.build-release-package.outputs.source_sha }}", publish)
        self.assertIn("fetch-depth: 0", publish)
        self.assertIn("persist-credentials: true", publish)
        self.assertIn("permissions:\n      contents: write", publish)
        self.assertNotIn("id-token:", publish)
        self.assertNotIn("secrets.", publish)
        self.assertIn("python -m scripts.release.plugin_release publish", publish)
        self.assertIn("GH_TOKEN: ${{ github.token }}", publish)
        self.assertIn("python -m pip install .", publish)
        build = job(release, "build-release-package")
        self.assertIn("source_sha: ${{ steps.plugin-source.outputs.sha }}", build)
        self.assertIn('test "$(git rev-parse HEAD)" = "$(git rev-parse "v${PACKAGE_VERSION}^{commit}")"', build)
        self.assertIn("python -m scripts.release.plugin_release prepare", build)
        artifact = build.split("- name: Upload plugin payload artifact", 1)[1]
        self.assertIn("dist/plugin-release/", artifact)
        self.assertIn("if-no-files-found: error", artifact)
        self.assertNotIn("path: dist/plugin/gh-address-cr", artifact)

    def test_recovery_is_version_only_trusted_and_serialized_with_release(self):
        recovery = (WORKFLOWS / "plugin-marketplace.yml").read_text()
        release = job((WORKFLOWS / "release.yml").read_text(), "publish-plugin-marketplace")
        recover = job(recovery, "recover-plugin-marketplace")
        triggers = recovery.split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        self.assertIn("version:", triggers)
        self.assertNotIn("push:", triggers)
        self.assertIn("if: github.ref == format('refs/heads/{0}', github.event.repository.default_branch)", recover)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", recover)
        self.assertIn("persist-credentials: true", recover)
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

    def test_builder_and_release_jobs_install_yaml_and_runtime_dependencies(self):
        release = (WORKFLOWS / "release.yml").read_text()
        recovery = (WORKFLOWS / "plugin-marketplace.yml").read_text()
        ci = (WORKFLOWS / "ci.yml").read_text()
        for content, name in (
            (release, "build-release-package"),
            (release, "publish-plugin-marketplace"),
            (recovery, "recover-plugin-marketplace"),
            (ci, "plugin-marketplace-smoke"),
        ):
            with self.subTest(job=name):
                self.assertIn("python -m pip install . 'PyYAML>=6'", job(content, name))
        self.assertIn("mypy 'PyYAML>=6'", job(ci, "lint-and-test"))
        self.assertIn("-e . 'PyYAML>=6'", job(ci, "otel-minimum-versions"))
