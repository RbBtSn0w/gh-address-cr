import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from gh_address_cr import __version__ as RUNTIME_VERSION
from gh_address_cr.agent.manifests import validate_capability_manifest
from tests.helpers import ROOT, RUNTIME_PACKAGE_DIR, SRC_ROOT, PythonScriptTestCase

PYPROJECT = ROOT / "pyproject.toml"
RELEASE_CONFIG = ROOT / "release.config.cjs"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
README = ROOT / "README.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
VERSION_SYNC_SCRIPT = ROOT / "scripts" / "set_package_version.py"
HOMEBREW_FORMULA_RENDERER = ROOT / "scripts" / "release" / "render_homebrew_formula.py"
PYPI_JSON_FIXTURE = ROOT / "tests" / "fixtures" / "release" / "pypi_gh_address_cr_1_2_3.json"


class RuntimePackagingTest(PythonScriptTestCase):
    def test_runtime_package_imports_from_src(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [sys.executable, "-c", "import gh_address_cr, gh_address_cr.cli; print(gh_address_cr.__version__)"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((RUNTIME_PACKAGE_DIR / "cli.py").exists())
        self.assertIn(RUNTIME_VERSION, result.stdout)

    def test_installed_runtime_does_not_carry_legacy_command_scripts(self):
        install_root = Path(self.temp_dir.name) / "installed"
        shutil.copytree(RUNTIME_PACKAGE_DIR, install_root / "gh_address_cr")

        self.assertFalse((install_root / "gh_address_cr" / "legacy_scripts").exists())
        self.assertFalse((install_root / "gh_address_cr" / "legacy_handlers").exists())
        self.assertFalse((install_root / "gh_address_cr" / "command_handlers").exists())
        self.assertTrue((install_root / "gh_address_cr" / "commands").exists())

    def test_runtime_cli_has_no_legacy_or_handler_script_dispatcher(self):
        import gh_address_cr.cli as cli

        self.assertFalse(hasattr(cli, "COMMAND_TO_SCRIPT"))
        self.assertFalse(hasattr(cli, "SCRIPT_DIR"))
        self.assertFalse(hasattr(cli, "run_script"))

    def test_current_runtime_commands_are_not_handler_package_named(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util\n"
                    "print(importlib.util.find_spec('gh_address_cr.commands') is not None)\n"
                    "print(importlib.util.find_spec('gh_address_cr.command_handlers') is None)\n"
                    "print(importlib.util.find_spec('gh_address_cr.legacy_handlers') is None)\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines(), ["True", "True", "True"])

    def test_legacy_core_session_engine_module_is_removed(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util\n"
                    "print(importlib.util.find_spec('gh_address_cr.core.session_engine') is None)\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")

    def test_legacy_core_cr_loop_module_is_removed(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util\n"
                    "print(importlib.util.find_spec('gh_address_cr.core.cr_loop') is None)\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")

    def test_legacy_core_control_plane_module_is_removed(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util\n"
                    "print(importlib.util.find_spec('gh_address_cr.core.control_plane') is None)\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")

    def test_runtime_module_help_lists_public_commands(self):
        result = self.run_runtime_module("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("review", result.stdout)
        self.assertIn("address", result.stdout)
        self.assertIn("threads", result.stdout)
        self.assertIn("findings", result.stdout)
        self.assertIn("final-gate", result.stdout)

    def test_runtime_unknown_command_fails_loudly(self):
        result = self.run_runtime_module("unknown-command")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown command", result.stderr.lower())

    def test_runtime_public_command_help_parity(self):
        commands = [
            ("active-pr", "--help"),
            ("address", "--help"),
            ("review", "--help"),
            ("threads", "--help"),
            ("findings", "--help"),
            ("adapter", "--help"),
            ("review-to-findings", "--help"),
            ("final-gate", "--help"),
        ]

        for command in commands:
            with self.subTest(command=command):
                result = self.run_runtime_module(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)
                if command[0] == "final-gate":
                    self.assertIn("GH_ADDRESS_CR_HOST_TELEMETRY_INPUT", result.stdout)
                    self.assertIn("GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE", result.stdout)

    def test_legacy_root_commands_fail_without_session_mutation(self):
        legacy_commands = ["cr-loop", "session-engine", "clean-state"]

        for command in legacy_commands:
            with self.subTest(command=command):
                result = self.run_runtime_module(command, "--help")

                self.assertEqual(result.returncode, 2)
                self.assertIn("unsupported legacy command", result.stderr.lower())
                self.assertIn("gh-address-cr review", result.stderr)
                self.assertFalse(self.session_file().exists())

    def test_agent_manifest_outputs_runtime_capabilities(self):
        result = self.run_runtime_module("agent", "manifest")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "MANIFEST_READY")
        self.assertIn("address", payload["public_commands"])
        self.assertIn("review-to-findings", payload["public_commands"])
        self.assertIn("submit-feedback", payload["public_commands"])
        self.assertIn("agent", payload["public_commands"])
        self.assertIn("version", payload["public_commands"])

        self.assertNotIn("superpowers", payload["public_commands"])
        validate_capability_manifest(payload)
        self.assertIn("coordinator", payload["roles"])
        self.assertIn("triage", payload["roles"])
        self.assertIn("fixer", payload["roles"])
        self.assertIn("verify", payload["actions"])
        self.assertEqual(payload["constraints"]["max_parallel_claims"], 2)
        self.assertIn("action_request.v1", payload["input_formats"])
        self.assertIn("batch_action_response.v1", payload["output_formats"])
        self.assertIn("work_item_boundary.v1", payload["output_formats"])

    def test_agent_resolve_help_documents_batch_contract(self):
        result = self.run_runtime_module("agent", "resolve", "--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: gh-address-cr agent resolve", result.stdout)
        self.assertIn("BatchActionResponse", result.stdout)

    def test_missing_gh_preflight_fails_before_session_mutation(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)
        env["PATH"] = str(self.bin_dir)

        result = subprocess.run(
            [sys.executable, "-m", "gh_address_cr", "review", self.repo, self.pr],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "GH_NOT_FOUND")
        self.assertFalse(self.session_file().exists())

    def test_unauthenticated_gh_preflight_fails_before_session_mutation(self):
        gh = self.bin_dir / "gh"
        gh.write_text('#!/bin/sh\nif [ "$1" = "auth" ]; then exit 1; fi\nexit 0\n', encoding="utf-8")
        gh.chmod(0o755)
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"

        result = subprocess.run(
            [sys.executable, "-m", "gh_address_cr", "review", self.repo, self.pr],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "GH_AUTH_FAILED")
        self.assertFalse(self.session_file().exists())

    def test_network_gh_preflight_is_not_reported_as_auth_failure(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            '#!/bin/sh\nif [ "$1" = "auth" ]; then echo "error connecting to api.github.com" >&2; exit 1; fi\nexit 0\n',
            encoding="utf-8",
        )
        gh.chmod(0o755)
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"

        result = subprocess.run(
            [sys.executable, "-m", "gh_address_cr", "review", self.repo, self.pr],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "GH_NETWORK_FAILED")
        self.assertEqual(payload["waiting_on"], "github_network")
        self.assertEqual(payload["diagnostics"]["stderr_category"], "network")
        self.assertEqual(payload["diagnostics"]["command"], ["gh", "auth", "status"])
        self.assertIn("api.github.com", payload["diagnostics"]["stderr_excerpt"])
        self.assertFalse(self.session_file().exists())

    def test_runtime_compatibility_preflight(self):
        result = self.run_runtime_module("adapter", "check-runtime")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "compatible")
        self.assertEqual(payload["runtime_package"], "gh-address-cr")

    def test_pyproject_declares_distribution_metadata_and_runtime_dependencies(self):
        text = PYPROJECT.read_text(encoding="utf-8")

        self.assertIn('name = "gh-address-cr"', text)
        self.assertIn('requires-python = ">=3.10"', text)
        self.assertIn('readme = "README.md"', text)
        self.assertIn('license = "MIT"', text)
        self.assertIn('license-files = ["LICENSE"]', text)
        self.assertIn('"packaging>=24"', text)
        self.assertIn('"opentelemetry-api>=1.30"', text)
        self.assertIn('"opentelemetry-sdk>=1.30"', text)
        self.assertIn('"opentelemetry-exporter-otlp-proto-http>=1.30"', text)
        self.assertIn('"requests>=2.7"', text)
        self.assertIn("Programming Language :: Python :: 3.10", text)
        self.assertIn("Operating System :: OS Independent", text)
        self.assertIn('Homepage = "https://github.com/RbBtSn0w/gh-address-cr"', text)
        self.assertIn('Source = "https://github.com/RbBtSn0w/gh-address-cr"', text)
        self.assertIn('Issues = "https://github.com/RbBtSn0w/gh-address-cr/issues"', text)

    def test_changelog_top_entry_is_not_future_release_without_version_bump(self):
        changelog_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        pyproject_text = PYPROJECT.read_text(encoding="utf-8")

        version_match = re.search(r'^version = "([^"]+)"$', pyproject_text, re.MULTILINE)
        self.assertIsNotNone(version_match)
        package_version = version_match.group(1)
        first_heading = next(line for line in changelog_text.splitlines() if line.startswith("## "))

        if first_heading != "## Unreleased":
            self.assertIn(f"[{package_version}]", first_heading)

    def test_version_sync_script_updates_pyproject_and_runtime_version(self):
        pyproject = Path(self.temp_dir.name) / "pyproject.toml"
        init_file = Path(self.temp_dir.name) / "__init__.py"
        pyproject.write_text(
            '[project]\nname = "gh-address-cr"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        init_file.write_text('__version__ = "0.1.0"\nPROTOCOL_VERSION = "1.0"\n', encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(VERSION_SYNC_SCRIPT),
                "--version",
                "1.2.3",
                "--pyproject",
                str(pyproject),
                "--init-file",
                str(init_file),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["version"], "1.2.3")
        self.assertIn('version = "1.2.3"', pyproject.read_text(encoding="utf-8"))
        self.assertIn('__version__ = "1.2.3"', init_file.read_text(encoding="utf-8"))

    def test_semantic_release_prepares_python_package_version(self):
        text = RELEASE_CONFIG.read_text(encoding="utf-8")

        self.assertIn("@semantic-release/exec", text)
        self.assertIn("scripts/set_package_version.py ${nextRelease.version}", text)
        self.assertIn("@semantic-release/git", text)
        self.assertIn('"pyproject.toml"', text)
        self.assertIn('"src/gh_address_cr/__init__.py"', text)
        self.assertIn("@semantic-release/commit-analyzer", text)
        self.assertIn("@semantic-release/release-notes-generator", text)
        self.assertIn('repositoryUrl: "https://github.com/RbBtSn0w/gh-address-cr.git"', text)
        self.assertIn("parserOpts: releaseParserOpts", text)
        self.assertIn(r"(\\S.*)", text)

    def test_ci_workflow_has_build_install_and_installed_smoke_gates(self):
        text = CI_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Package build", text)
        self.assertIn("Package install", text)
        self.assertIn("Installed CLI smoke", text)
        self.assertIn("python -m build", text)
        self.assertIn("python -m pip install dist/*.whl", text)
        self.assertIn("PYTHONPATH: src", text)
        self.assertIn("ModuleNotFoundError", text)
        self.assertIn("Final gate failed to evaluate", text)
        self.assertIn("error connecting to api.github.com", text)
        for command in (
            "gh-address-cr --help",
            "python -m gh_address_cr --help",
            "gh-address-cr agent manifest",
            "gh-address-cr agent orchestrate status owner/repo 123",
            "gh-address-cr final-gate owner/repo 123",
        ):
            self.assertIn(command, text)

    def test_ci_installs_project_dependencies_before_source_tests(self):
        text = CI_WORKFLOW.read_text(encoding="utf-8")

        install_index = text.index("python -m pip install -e .")
        self.assertLess(install_index, text.index("- name: Ruff"))
        self.assertLess(install_index, text.index("- name: Mypy (blocking)"))
        self.assertLess(install_index, text.index("- name: Unit tests (with coverage)"))

    def test_release_workflow_has_trusted_publishing_version_and_staging_gates(self):
        text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", text)
        self.assertIn("publish_target", text)
        self.assertIn("id-token: write", text)
        self.assertIn("scripts/set_package_version.py", text)
        self.assertIn("python -m build", text)
        self.assertIn("twine check dist/*", text)
        self.assertIn("Verify package version", text)
        self.assertIn("Render Homebrew formula from local sdist", text)
        self.assertIn("scripts/release/render_homebrew_formula.py", text)
        self.assertIn("pypa/gh-action-pypi-publish", text)
        self.assertIn("repository-url: https://test.pypi.org/legacy/", text)
        self.assertNotIn("environment: pypi", text)
        self.assertNotIn("confirm_pypi_publish", text)
        self.assertRegex(
            text,
            re.compile(
                r"publish-pypi:.*needs\.build-release-package\.outputs\.publish_target == 'pypi'",
                re.DOTALL,
            ),
        )

    def test_release_workflow_updates_homebrew_tap_after_pypi_publish(self):
        text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("publish-homebrew:", text)
        self.assertIn("needs: [build-release-package, publish-pypi]", text)
        self.assertIn("needs.build-release-package.outputs.publish_target == 'pypi'", text)
        self.assertIn("actions/create-github-app-token@v3", text)
        self.assertIn("app-id: ${{ vars.RELEASE_BOT_APP_ID }}", text)
        self.assertIn("private-key: ${{ secrets.RELEASE_BOT_PRIVATE_KEY }}", text)
        self.assertIn("token: ${{ steps.homebrew-tap-token.outputs.token }}", text)
        self.assertIn("repositories: homebrew-tap", text)
        self.assertNotIn("HOMEBREW_TAP_TOKEN", text)
        self.assertNotIn("HOMEBREW_APP_PRIVATE_KEY", text)
        self.assertIn("RbBtSn0w/homebrew-tap", text)
        self.assertIn("Formula/gh-address-cr.rb", text)
        self.assertIn('HOMEBREW_NO_INSTALL_FROM_API: "1"', text)
        self.assertIn("Sync rendered Homebrew formula into tapped clone", text)
        self.assertNotIn("brew update-python-resources", text)
        self.assertIn("brew audit --formula --strict RbBtSn0w/tap/gh-address-cr", text)
        self.assertIn("brew install --build-from-source RbBtSn0w/tap/gh-address-cr", text)
        self.assertIn("brew test RbBtSn0w/tap/gh-address-cr", text)
        self.assertIn("git status --short -- Formula/gh-address-cr.rb", text)

    def test_homebrew_formula_renderer_uses_pypi_sdist_contract(self):
        output = Path(self.temp_dir.name) / "gh-address-cr.rb"

        result = subprocess.run(
            [
                sys.executable,
                str(HOMEBREW_FORMULA_RENDERER),
                "--version",
                "1.2.3",
                "--pypi-json",
                str(PYPI_JSON_FIXTURE),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "RENDERED")
        self.assertEqual(payload["version"], "1.2.3")
        self.assertEqual(payload["sha256"], "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
        self.assertEqual(
            payload["resources"],
            [
                "certifi",
                "charset-normalizer",
                "googleapis-common-protos",
                "idna",
                "opentelemetry-api",
                "opentelemetry-exporter-otlp-proto-common",
                "opentelemetry-exporter-otlp-proto-http",
                "opentelemetry-proto",
                "opentelemetry-sdk",
                "opentelemetry-semantic-conventions",
                "packaging",
                "protobuf",
                "requests",
                "typing-extensions",
                "urllib3",
            ],
        )

        formula = output.read_text(encoding="utf-8")
        self.assertIn("class GhAddressCr < Formula", formula)
        self.assertIn("include Language::Python::Virtualenv", formula)
        self.assertIn('url "https://files.pythonhosted.org/packages/source/g/gh-address-cr/gh_address_cr-1.2.3.tar.gz"', formula)
        self.assertIn('sha256 "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"', formula)
        self.assertIn('depends_on "python@3.14"', formula)
        self.assertIn('resource "requests" do', formula)
        self.assertIn('resource "certifi" do', formula)
        self.assertIn('resource "opentelemetry-exporter-otlp-proto-http" do', formula)
        self.assertIn('resource "packaging" do', formula)
        self.assertIn('url "https://files.pythonhosted.org/packages/d7/f1/e7a6dd94a8d4a5626c03e4e99c87f241ba9e350cd9e6d75123f992427270/packaging-26.2.tar.gz"', formula)
        self.assertIn('sha256 "ff452ff5a3e828ce110190feff1178bb1f2ea2281fa2075aadb987c2fb221661"', formula)
        self.assertIn("virtualenv_install_with_resources", formula)
        self.assertIn('virtualenv_install_with_resources using: "python3.14"', formula)
        self.assertIn('shell_output("#{bin}/gh-address-cr --version")', formula)
        self.assertIn('shell_output("#{bin}/gh-address-cr agent manifest")', formula)
        self.assertNotIn('resource "coverage" do', formula)
        self.assertNotIn("whl", formula)

    def test_homebrew_formula_renderer_prefers_tar_gz_when_pypi_lists_multiple_sdists(self):
        fixture = Path(self.temp_dir.name) / "multiple-sdists.json"
        output = Path(self.temp_dir.name) / "gh-address-cr.rb"
        fixture.write_text(
            json.dumps(
                {
                    "info": {"name": "gh-address-cr", "version": "1.2.3"},
                    "urls": [
                        {
                            "filename": "gh_address_cr-1.2.3.zip",
                            "packagetype": "sdist",
                            "url": "https://files.pythonhosted.org/packages/source/g/gh-address-cr/gh_address_cr-1.2.3.zip",
                            "digests": {
                                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            },
                        },
                        {
                            "filename": "gh_address_cr-1.2.3.tar.gz",
                            "packagetype": "sdist",
                            "url": "https://files.pythonhosted.org/packages/source/g/gh-address-cr/gh_address_cr-1.2.3.tar.gz",
                            "digests": {
                                "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(HOMEBREW_FORMULA_RENDERER),
                "--version",
                "1.2.3",
                "--pypi-json",
                str(fixture),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["url"].endswith(".tar.gz"))
        self.assertEqual(payload["sha256"], "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    def test_readme_documents_runtime_distribution_paths_separately_from_skill_install(self):
        text = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")

        self.assertIn("Install the released runtime CLI", text)
        self.assertIn("pipx install gh-address-cr", text)
        self.assertIn("uv tool install gh-address-cr", text)
        self.assertIn("Install with Homebrew", text)
        self.assertIn("brew tap RbBtSn0w/tap", text)
        self.assertIn("brew install gh-address-cr", text)
        self.assertIn("brew upgrade gh-address-cr", text)
        self.assertIn("brew test gh-address-cr", text)
        self.assertIn("GitHub-direct runtime validation install", text)
        self.assertIn("pipx install git+https://github.com/RbBtSn0w/gh-address-cr.git", text)
        self.assertIn("Local editable development install", text)
        self.assertIn("python3 -m pip install -e .", text)
        self.assertIn("Packaged skill install", text)
        self.assertIn("npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill skill", text)
        self.assertNotIn("--skill gh-address-cr", text)
        self.assertIn("does not install the runtime CLI package", text)
        self.assertIn("Upgrade from skill-shim usage", text)
        self.assertIn("Install the runtime CLI with `pipx` or `uv tool`", text)
        self.assertIn("Homebrew tap", text)

    def test_contributing_documents_homebrew_release_policy(self):
        text = CONTRIBUTING.read_text(encoding="utf-8")

        self.assertIn("Homebrew tap update to `RbBtSn0w/homebrew-tap`", text)
        self.assertIn("after the PyPI sdist is available", text)
        self.assertIn("RELEASE_BOT_PRIVATE_KEY", text)
        self.assertIn("RELEASE_BOT_APP_ID", text)
        self.assertIn("GitHub App", text)
        self.assertIn("Contents: Read and write", text)
        self.assertIn("dry-run` and `testpypi` targets validate package build and Homebrew formula rendering", text)
        self.assertIn("both PyPI and Homebrew publishing must skip explicitly", text)


if __name__ == "__main__":
    unittest.main()
