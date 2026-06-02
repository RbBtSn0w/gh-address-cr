import json
import re
import subprocess
import sys
import unittest

from tests.helpers import ROOT


PLUGIN_ROOT = ROOT / "plugin" / "gh-address-cr"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
PLUGIN_ROOT_MANIFEST = PLUGIN_ROOT / "plugin.json"
PLUGIN_SKILLS_ROOT = PLUGIN_ROOT / "skills"
PLUGIN_SKILL_ROOT = PLUGIN_SKILLS_ROOT / "gh-address-cr"
PLUGIN_BUILDER = ROOT / "scripts" / "build_plugin_payload.py"
PYPROJECT = ROOT / "pyproject.toml"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
README = ROOT / "README.md"
RELEASE_CONFIG = ROOT / "release.config.cjs"


def _pyproject_version() -> str:
    match = re.search(r'^version = "([^"]+)"$', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise AssertionError("pyproject.toml version not found")
    return match.group(1)


class PluginPackagingTest(unittest.TestCase):
    def test_plugin_manifest_has_codex_plugin_contract(self):
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        root_manifest = json.loads(PLUGIN_ROOT_MANIFEST.read_text(encoding="utf-8"))

        self.assertEqual(root_manifest, manifest)

        self.assertEqual(manifest["name"], "gh-address-cr")
        self.assertEqual(manifest["version"], _pyproject_version())
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)
        self.assertEqual(manifest["repository"], "https://github.com/RbBtSn0w/gh-address-cr")
        self.assertEqual(manifest["license"], "MIT")

        interface = manifest["interface"]
        self.assertEqual(interface["displayName"], "GH Address CR")
        self.assertEqual(interface["category"], "Developer Tools")
        self.assertEqual(interface["capabilities"], ["Read", "Write"])
        self.assertTrue(interface["privacyPolicyURL"].endswith("/PRIVACY.md"))
        self.assertTrue(interface["termsOfServiceURL"].endswith("/TERMS.md"))

        relative_paths = [
            manifest["skills"],
            interface["composerIcon"],
            interface["logo"],
            *interface["screenshots"],
        ]
        for raw_path in relative_paths:
            with self.subTest(path=raw_path):
                self.assertTrue(raw_path.startswith("./"))
                self.assertTrue((PLUGIN_ROOT / raw_path[2:]).exists(), raw_path)

    def test_plugin_payload_contains_one_skill_and_no_generated_artifacts(self):
        skill_manifests = sorted(PLUGIN_SKILLS_ROOT.glob("*/SKILL.md"))
        self.assertEqual(skill_manifests, [PLUGIN_SKILL_ROOT / "SKILL.md"])

        forbidden_names = {".pytest_cache", ".ruff_cache", "__pycache__", "dist", ".state"}
        for path in PLUGIN_ROOT.rglob("*"):
            relative_path = path.relative_to(PLUGIN_ROOT)
            with self.subTest(path=relative_path):
                self.assertTrue(forbidden_names.isdisjoint(relative_path.parts))
                self.assertNotEqual(relative_path.suffix, ".pyc")
                self.assertNotEqual(relative_path.suffix, ".log")

    def test_plugin_payload_check_is_reproducible(self):
        result = subprocess.run(
            [sys.executable, str(PLUGIN_BUILDER), "--check"],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("plugin payload is up to date", result.stdout)


    def test_community_compliance_docs_exist(self):
        privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
        terms = (ROOT / "TERMS.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

        self.assertIn("local GitHub CLI", privacy)
        self.assertIn("GitHub side effects", privacy)
        self.assertIn("Telemetry is opt-in", privacy)
        self.assertIn("not a ChatGPT Apps SDK app", terms)
        self.assertIn("Responsible Disclosure", security)

    def test_repo_marketplace_exposes_plugin_as_local_path_in_git_marketplace(self):
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))

        self.assertEqual(marketplace["name"], "gh-address-cr-community")
        self.assertEqual(marketplace["interface"]["displayName"], "GH Address CR Community")
        self.assertEqual(len(marketplace["plugins"]), 1)

        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "gh-address-cr")
        self.assertEqual(plugin["category"], "Developer Tools")
        self.assertEqual(plugin["policy"]["installation"], "AVAILABLE")
        self.assertEqual(plugin["policy"]["authentication"], "ON_INSTALL")

        source = plugin["source"]
        self.assertEqual(source["source"], "local")
        self.assertEqual(source["path"], "./plugin/gh-address-cr")
        self.assertTrue((ROOT / source["path"][2:] / ".codex-plugin" / "plugin.json").exists())

    def test_ci_and_release_gate_plugin_payload_check(self):
        ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
        release_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Plugin payload check", ci_text)
        self.assertIn("python scripts/build_plugin_payload.py --check", ci_text)
        self.assertNotIn("sync_scripts.py", ci_text)
        self.assertIn("Plugin payload check", release_text)
        self.assertIn("python scripts/build_plugin_payload.py --check", release_text)
        self.assertNotIn("sync_scripts.py", release_text)

    def test_release_version_prepare_regenerates_plugin_payload(self):
        release_config = RELEASE_CONFIG.read_text(encoding="utf-8")
        release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("scripts/set_package_version.py ${nextRelease.version}", release_config)
        self.assertIn("scripts/build_plugin_payload.py", release_config)
        self.assertIn("plugin/gh-address-cr/.codex-plugin/plugin.json", release_config)
        self.assertIn("plugin/gh-address-cr/plugin.json", release_config)
        self.assertIn("python3 scripts/build_plugin_payload.py", release_workflow)

    def test_readme_documents_codex_marketplace_install_path(self):
        readme = README.read_text(encoding="utf-8")

        self.assertIn(".agents/plugins/marketplace.json", readme)
        self.assertIn("codex plugin marketplace add RbBtSn0w/gh-address-cr --ref main", readme)
        self.assertIn("codex plugin marketplace upgrade", readme)
        self.assertIn("plugin/gh-address-cr", readme)
        self.assertIn("curated Plugin Directory is not a self-service publish target", readme)
