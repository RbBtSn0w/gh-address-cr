import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_plugin_payload as builder
from tests.helpers import ROOT

GENERATED_PLUGIN_ROOT = ROOT / "dist" / "plugin" / "gh-address-cr"
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
    def build_generated_payload(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        payload_root = Path(temp_dir.name) / "gh-address-cr"
        result = subprocess.run(
            [sys.executable, str(PLUGIN_BUILDER), "--output", str(payload_root)],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return temp_dir, payload_root

    def test_plugin_manifest_has_codex_plugin_contract(self):
        _, payload_root = self.build_generated_payload()
        manifest = json.loads((payload_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        root_manifest = json.loads((payload_root / "plugin.json").read_text(encoding="utf-8"))

        self.assertEqual(root_manifest["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertNotIn("interface", root_manifest)
        self.assertNotIn("skills", root_manifest)
        self.assertNotIn("com.openai.interface", root_manifest["extensions"])
        self.assertEqual(root_manifest["extensions"]["com.openai"]["interface"], manifest["interface"])
        self.assertEqual(manifest["interface"]["shortDescription"], "Resolve PR reviews safely")
        for key, value in root_manifest.items():
            self.assertEqual(manifest[key], value)

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
                self.assertTrue((payload_root / raw_path[2:]).exists(), raw_path)

    def test_archive_is_complete_deterministic_and_preserves_skill_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archives = [root / "first.zip", root / "second.zip"]
            for archive in archives:
                result = subprocess.run(
                    [sys.executable, str(PLUGIN_BUILDER), "--output", str(root / "payload"),
                     "--archive", str(archive)], capture_output=True, text=True, cwd=ROOT,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(archives[0].read_bytes(), archives[1].read_bytes())
            with zipfile.ZipFile(archives[0]) as archive:
                names = archive.namelist()
                self.assertEqual(names, sorted(names))
                self.assertIn("gh-address-cr/.codex-plugin/plugin.json", names)
                expected = {
                    "gh-address-cr/" + path.relative_to(root / "payload").as_posix()
                    for path in (root / "payload").rglob("*") if path.is_file()
                }
                self.assertEqual(set(names), expected)
                for info in archive.infolist():
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(info.external_attr >> 16, 0o100644)
                for source in (ROOT / "skill").rglob("*"):
                    if source.is_file() and not builder.should_exclude(source.relative_to(ROOT / "skill")):
                        self.assertEqual(archive.read("gh-address-cr/skills/gh-address-cr/" +
                                                     source.relative_to(ROOT / "skill").as_posix()),
                                         source.read_bytes())

    def test_builder_rejects_unsafe_source_files_and_metadata(self):
        cases = {
            "secret.md": "token: ghp_" + "a" * 36,
            ".env": "API_KEY=secret",
            "helper.sh": "echo unsafe",
            "absolute.md": "Private location: /Users/private/project",
            "bad.json": "{broken",
            "bad.yaml": "interface: [broken",
            "metadata.yaml": "path: /private/tmp/private-key",
            "credentials.json": '{"api_key": "private-value"}',
            "duplicate.json": '{"path": "../secret", "path": "ok"}',
            "alias.yaml": "loop: &loop [*loop]",
            "windows.yaml": 'path: "C:\\\\Users\\\\private"',
            "traversal.yaml": "path: ../private-key",
            "windows.json": '{"path": "C:/private/key"}',
            "..\\escape.md": "unsafe name",
        }
        for name, content in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                source = root / "skill"
                shutil.copytree(ROOT / "skill", source)
                (source / name).write_text(content)
                with patch.object(builder, "SKILL_ROOT", source), self.assertRaises(ValueError):
                    builder.build_payload(root / "output")

    def test_builder_rejects_symlinks_even_under_excluded_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "skill"
            shutil.copytree(ROOT / "skill", source)
            (source / "__pycache__").symlink_to(ROOT / "skill", target_is_directory=True)
            with patch.object(builder, "SKILL_ROOT", source), self.assertRaises(ValueError):
                builder.build_payload(root / "output")

    def test_builder_excludes_dependency_and_cache_trees(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "skill"
            shutil.copytree(ROOT / "skill", source)
            for name in ("node_modules", ".venv", "__pycache__", ".git"):
                directory = source / name
                directory.mkdir()
                (directory / "ignored.txt").write_text("unrelated")
            with patch.object(builder, "SKILL_ROOT", source):
                builder.build_payload(root / "output")
            for name in ("node_modules", ".venv", "__pycache__", ".git"):
                self.assertFalse((root / "output" / "skills" / "gh-address-cr" / name).exists())

    def test_archive_rejects_unexpected_files_and_output_inside_payload(self):
        _, payload_root = self.build_generated_payload()
        with self.assertRaises(ValueError):
            builder.write_archive(payload_root, payload_root / "payload.zip")
        (payload_root / "unrelated.md").write_text("unrelated")
        with self.assertRaises(ValueError):
            builder.validate_payload(payload_root)

    def test_builder_refuses_source_overwrite_and_check_archive_combination(self):
        for args in (("--output", "skill"), ("--output", "assets/plugin"),
                     ("--check", "--archive", "dist/plugin/check.zip")):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(PLUGIN_BUILDER), *args],
                                        capture_output=True, text=True, cwd=ROOT)
                self.assertNotEqual(result.returncode, 0)
        self.assertTrue((ROOT / "skill" / "SKILL.md").is_file())

    def test_builder_accepts_explicit_source_and_version_without_global_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "skill"
            shutil.copytree(ROOT / "skill", source)
            version_file = root / "pyproject.toml"
            version_file.write_text('version = "99.1.0"\n')
            builder.build_payload(root / "output", source_root=source, pyproject_path=version_file)
            builder.write_archive(root / "output", root / "payload.zip", pyproject_path=version_file)
            self.assertEqual(json.loads((root / "output" / "plugin.json").read_text())["version"], "99.1.0")

    def test_output_preserves_arbitrary_repository_relative_directory_support(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="packaging-test-") as temp_dir:
            destination = Path(temp_dir) / "plugin"
            result = subprocess.run([sys.executable, str(PLUGIN_BUILDER), "--output",
                                     str(destination.relative_to(ROOT))], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((destination / "plugin.json").is_file())

    def test_archival_validation_uses_explicit_version_and_preserves_historic_metadata(self):
        _, payload_root = self.build_generated_payload()
        root_path = payload_root / "plugin.json"
        root = json.loads(root_path.read_text())
        root["version"] = "1.2.3"
        root["description"] = "Previously published description"
        root["extensions"]["com.openai"]["interface"]["shortDescription"] = "Previous description"
        root_path.write_text(json.dumps(root))
        overlay_path = payload_root / ".codex-plugin" / "plugin.json"
        overlay = {**root, "skills": "./skills/", "interface": root["extensions"]["com.openai"]["interface"]}
        overlay_path.write_text(json.dumps(overlay))
        builder.validate_payload(payload_root, expected_version="1.2.3")
        builder.write_archive(payload_root, payload_root.parent / "historic.zip", expected_version="1.2.3")
        with self.assertRaises(ValueError):
            builder.validate_payload(payload_root, expected_version="1.2.4")
        overlay["interface"] = {**overlay["interface"], "shortDescription": "Diverged"}
        overlay_path.write_text(json.dumps(overlay))
        with self.assertRaises(ValueError):
            builder.validate_payload(payload_root, expected_version="1.2.3")
        root["extensions"] = {"com.openai.interface": overlay["interface"]}
        root_path.write_text(json.dumps(root))
        with self.assertRaises(ValueError):
            builder.validate_payload(payload_root, expected_version="1.2.3")

    def test_plugin_payload_contains_one_skill_and_no_generated_artifacts(self):
        _, payload_root = self.build_generated_payload()
        plugin_skills_root = payload_root / "skills"
        plugin_skill_root = plugin_skills_root / "gh-address-cr"

        skill_manifests = sorted(plugin_skills_root.glob("*/SKILL.md"))
        self.assertEqual(skill_manifests, [plugin_skill_root / "SKILL.md"])

        forbidden_names = {".pytest_cache", ".ruff_cache", "__pycache__", "dist", ".state"}
        for path in payload_root.rglob("*"):
            relative_path = path.relative_to(payload_root)
            with self.subTest(path=relative_path):
                self.assertTrue(forbidden_names.isdisjoint(relative_path.parts))
                self.assertNotEqual(relative_path.suffix, ".pyc")
                self.assertNotEqual(relative_path.suffix, ".log")

    def test_default_build_generates_ignored_dist_payload(self):
        shutil.rmtree(GENERATED_PLUGIN_ROOT.parent, ignore_errors=True)
        result = subprocess.run(
            [sys.executable, str(PLUGIN_BUILDER)],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("built plugin payload at dist/plugin/gh-address-cr", result.stdout)
        self.assertTrue((GENERATED_PLUGIN_ROOT / ".codex-plugin" / "plugin.json").exists())
        self.assertTrue((GENERATED_PLUGIN_ROOT / "skills" / "gh-address-cr" / "SKILL.md").exists())

    def test_relative_output_is_resolved_from_repo_root(self):
        output_root = ROOT / "dist" / "plugin" / "from-subdir"
        shutil.rmtree(output_root, ignore_errors=True)
        result = subprocess.run(
            [sys.executable, str(PLUGIN_BUILDER), "--output", "dist/plugin/from-subdir"],
            text=True,
            capture_output=True,
            cwd=ROOT / "tests",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("built plugin payload at dist/plugin/from-subdir", result.stdout)
        self.assertTrue((output_root / ".codex-plugin" / "plugin.json").exists())
        self.assertFalse((ROOT / "tests" / "dist" / "plugin" / "from-subdir").exists())

    def test_repo_does_not_commit_duplicated_skill_payload_tree(self):
        tracked_payload = subprocess.run(
            ["git", "ls-files", "plugin/gh-address-cr"],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(tracked_payload.returncode, 0, tracked_payload.stderr)
        self.assertEqual(
            tracked_payload.stdout.strip(),
            "",
            "plugin/gh-address-cr is deprecated; CI/release generate dist/plugin/gh-address-cr instead",
        )

    def test_plugin_payload_check_is_reproducible(self):
        result = subprocess.run(
            [sys.executable, str(PLUGIN_BUILDER), "--check"],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("plugin payload can be generated", result.stdout)

    def test_runtime_requirements_are_synchronized(self):
        src_req = ROOT / "src" / "gh_address_cr" / "runtime-requirements.json"
        skill_req = ROOT / "skill" / "runtime-requirements.json"
        self.assertTrue(src_req.exists())
        self.assertTrue(skill_req.exists())
        self.assertEqual(
            src_req.read_text(encoding="utf-8"),
            skill_req.read_text(encoding="utf-8"),
            "src/gh_address_cr/runtime-requirements.json and skill/runtime-requirements.json must be identical"
        )

    def test_community_compliance_docs_exist(self):
        privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
        terms = (ROOT / "TERMS.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

        self.assertIn("local GitHub CLI", privacy)
        self.assertIn("GitHub side effects", privacy)
        self.assertIn("DISABLE_TELEMETRY=1", privacy)
        self.assertIn("DO_NOT_TRACK=1", privacy)
        self.assertIn("no API key or backend credential", privacy)
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
        self.assertEqual(source["path"], "./dist/plugin/gh-address-cr")
        ignore_check = subprocess.run(
            ["git", "check-ignore", "-q", source["path"][2:]],
            cwd=ROOT,
        )
        self.assertEqual(ignore_check.returncode, 0, "dist plugin path must remain an ignored generated artifact")
        generated_path = ROOT / source["path"][2:]
        if generated_path.exists():
            self.assertTrue((generated_path / ".codex-plugin" / "plugin.json").exists())

    def test_ci_and_release_generate_plugin_payload_artifacts(self):
        ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
        release_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Generate plugin payload", ci_text)
        self.assertIn("python scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr", ci_text)
        self.assertNotIn("sync_scripts.py", ci_text)
        self.assertIn("plugin_release prepare", release_text)
        self.assertIn("--candidate", release_text)
        self.assertIn("name: release-main-verified", release_text)
        self.assertNotIn("sync_scripts.py", release_text)

    def test_release_version_prepare_regenerates_plugin_payload(self):
        release_config = RELEASE_CONFIG.read_text(encoding="utf-8")
        release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertNotIn("@semantic-release/exec", release_config)
        self.assertNotIn("scripts/build_plugin_payload.py", release_config)
        self.assertNotIn("plugin/gh-address-cr/.codex-plugin/plugin.json", release_config)
        self.assertNotIn("plugin/gh-address-cr/plugin.json", release_config)
        self.assertIn("python -m scripts.release.plugin_release prepare", release_workflow)

    def test_readme_documents_codex_marketplace_install_path(self):
        readme = README.read_text(encoding="utf-8")

        self.assertIn(".agents/plugins/marketplace.json", readme)
        self.assertIn("python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr", readme)
        self.assertIn("dist/plugin/gh-address-cr", readme)
        self.assertNotIn("plugin/gh-address-cr/`", readme)
        self.assertIn("curated Plugin Directory is not a self-service publish target", readme)


    def test_duplicate_yaml_keys_cannot_hide_unsafe_values(self):
        for text in ("path: ../secret\npath: ok\n", "interface:\n  name: first\n  name: second\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Duplicate YAML"):
                builder.load_yaml(text)

    def test_plugin_assets_are_source_bytes_independent_of_compression_library(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "assets"
            with patch("zlib.compress", side_effect=AssertionError("Asset encoding must not run during packaging")):
                builder.write_assets(output)
            for name in ("icon.png", "logo.png", "screenshot-1.png"):
                self.assertEqual((output / name).read_bytes(), (ROOT / "assets" / "plugin" / name).read_bytes())

    def test_explicit_asset_source_is_used_without_default_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "assets"
            shutil.copytree(ROOT / "assets" / "plugin", source)
            with patch.object(builder, "ASSETS_ROOT", root / "missing"):
                builder.build_payload(root / "output", assets_root=source)
            for asset in source.iterdir():
                self.assertEqual((root / "output" / "assets" / asset.name).read_bytes(), asset.read_bytes())
            (source / "unexpected.png").write_bytes(b"unexpected")
            with self.assertRaises(ValueError):
                builder.write_assets(root / "rejected", source)

    def test_asset_source_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "assets"
            source.mkdir()
            for name in ("icon.png", "logo.png", "screenshot-1.png"):
                (source / name).symlink_to(ROOT / "assets" / "plugin" / name)
            with self.assertRaises(ValueError):
                builder.write_assets(root / "rejected", source)
