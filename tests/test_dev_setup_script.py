"""scripts/dev_setup.sh builds the dev venv without touching the system Python."""

from __future__ import annotations

import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dev_setup.sh"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=600)


class DevSetupScriptTests(unittest.TestCase):
    def test_fake_python_supports_interpreter_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            interpreter = root / "Python's Tools" / "python"
            interpreter.parent.mkdir()
            interpreter.symlink_to(sys.executable)
            for index, (existing, fail_step) in enumerate(
                ((False, ""), (True, ""), (True, "upgrade"), (True, "install"))
            ):
                with self.subTest(existing=existing, fail_step=fail_step):
                    run_root = root / f"run {index}"
                    venv = run_root / "venv with spaces"
                    fake = venv / "bin" / "python" if existing else run_root / "bootstrap"
                    log = run_root / "calls.jsonl"
                    with patch("sys.executable", str(interpreter)):
                        self.fake_python(fake, log, fail_step=fail_step)
                    result = run("--python", str(fake), "--venv", str(venv))
                    self.assertEqual(result.returncode, 17 if fail_step else 0, result.stderr)
                    self.assertEqual("dev_setup: ready." in result.stderr, not fail_step)
                    self.assertTrue(log.is_file())

    def fake_python(self, path, log, *, fail_step=""):
        path.parent.mkdir(parents=True, exist_ok=True)
        # The shell trampoline quotes interpreter paths that a shebang cannot represent.
        path.write_text(
            "#!/bin/sh\n"
            f"'''exec' {shlex.quote(sys.executable)} \"$0\" \"$@\"\n"
            "' '''\n"
            "import json, pathlib, shutil, sys\n"
            f"log = pathlib.Path({str(log)!r})\n"
            "with log.open('a') as out:\n"
            "    out.write(json.dumps({'executable': sys.argv[0], 'args': sys.argv[1:]}) + '\\n')\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['-m', 'venv']:\n"
            "    target = pathlib.Path(args[2]) / 'bin' / 'python'\n"
            "    target.parent.mkdir(parents=True)\n"
            "    shutil.copy2(sys.argv[0], target)\n"
            f"if args[:2] == ['-m', 'pip'] and ({fail_step!r} == 'upgrade' and '--upgrade' in args or {fail_step!r} == 'install' and '-e' in args):\n"
            "    raise SystemExit(17)\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def test_new_and_existing_venvs_install_dev_extras_with_the_target_python(self):
        import json

        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                venv = root / "venv"
                log = root / "calls.jsonl"
                interpreter = root / "python-bootstrap"
                self.fake_python(interpreter, log)
                if existing:
                    self.fake_python(venv / "bin" / "python", log)
                result = run("--python", str(interpreter), "--venv", str(venv))
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                pip_calls = [call for call in calls if call["args"][:2] == ["-m", "pip"]]
                self.assertEqual(pip_calls, [
                    {"executable": str(venv / "bin" / "python"), "args": ["-m", "pip", "install", "--quiet", "--upgrade", "pip"]},
                    {"executable": str(venv / "bin" / "python"), "args": ["-m", "pip", "install", "--quiet", "-e", f"{ROOT}[dev]"]},
                ])
                self.assertEqual(any(call["args"][:2] == ["-m", "venv"] for call in calls), not existing)
                self.assertIn("dev_setup: ready.", result.stderr)

    def test_pip_failures_propagate_without_reporting_ready(self):
        import json

        for step in ("upgrade", "install"):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                venv = root / "venv"
                log = root / "calls.jsonl"
                self.fake_python(venv / "bin" / "python", log, fail_step=step)
                result = run("--python", str(venv / "bin" / "python"), "--venv", str(venv))
                self.assertEqual(result.returncode, 17, result.stderr)
                self.assertNotIn("dev_setup: ready.", result.stderr)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual(any("-e" in call["args"] for call in calls), step == "install")

    def test_unknown_argument_is_rejected(self):
        result = run("--no-such-flag")

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unknown argument", result.stderr)

    def test_missing_interpreter_fails_before_creating_a_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            result = run("--python", "no-such-python-for-dev-setup", "--venv", str(venv))

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("interpreter not found", result.stderr)
            self.assertFalse(venv.exists())

    def test_existing_venv_with_an_old_python_is_rejected_before_pip_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            (venv / "bin").mkdir(parents=True)
            fake_python = venv / "bin" / "python"
            fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            fake_python.chmod(0o755)

            result = run("--venv", str(venv))

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("not a working virtual-environment Python 3.12+", result.stderr)
            self.assertIn("failed to run", result.stderr)
            self.assertIn("remove", result.stderr)

    def test_a_venv_path_holding_a_non_venv_interpreter_is_rejected(self):
        base_python = Path(getattr(sys, "_base_executable", sys.executable))
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "not-a-venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").symlink_to(base_python)

            result = run("--venv", str(venv))

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("not a venv", result.stderr)

    def test_explicit_python_is_reported_as_ignored_for_an_existing_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            (venv / "bin").mkdir(parents=True)
            fake_python = venv / "bin" / "python"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o755)

            result = run("--python", "python3", "--venv", str(venv))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("only applies to a new venv", result.stderr)

    def test_help_documents_why_a_venv_is_used(self):
        result = run("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--venv", result.stderr)
        self.assertIn("Why a venv", result.stderr)
        self.assertIn("brew link", result.stderr)


class DevSetupDocsTests(unittest.TestCase):
    def test_agents_md_directs_dev_install_to_the_venv_script(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("scripts/dev_setup.sh", text)
        self.assertIn("brew link", text)


if __name__ == "__main__":
    unittest.main()
