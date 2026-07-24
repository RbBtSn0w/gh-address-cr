import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
SKILL_ROOT = ROOT / "skill"
WORKFLOW_GAP_FIXTURE = ROOT / "tests" / "fixtures" / "session_engine" / "workflow_gap_recovery.json"
RUNTIME_PACKAGE_DIR = SRC_ROOT / "gh_address_cr"
IMPLEMENTATIONS_DIR = RUNTIME_PACKAGE_DIR / "commands"
SCRIPTS_DIR = IMPLEMENTATIONS_DIR
CORE_DIR = RUNTIME_PACKAGE_DIR / "core"

CLI_PY = RUNTIME_PACKAGE_DIR / "cli.py"
REVIEW_TO_FINDINGS_PY = IMPLEMENTATIONS_DIR / "review_to_findings.py"
SUBMIT_FEEDBACK_PY = IMPLEMENTATIONS_DIR / "submit_feedback.py"
SUBMIT_ACTION_PY = IMPLEMENTATIONS_DIR / "submit_action.py"


def load_workflow_gap_fixture(name: str) -> Any:
    payload = json.loads(WORKFLOW_GAP_FIXTURE.read_text(encoding="utf-8"))
    value = payload[name]
    return dict(value) if isinstance(value, dict) else value



class PythonScriptTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.bin_dir = Path(self.temp_dir.name) / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.cwd = ROOT
        self.repo = "octo/example"
        self.pr = "77"
        self.original_process_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        self.env = os.environ.copy()
        self.env["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        self.env["DISABLE_TELEMETRY"] = "1"
        self.env["PATH"] = f"{self.bin_dir}:{self.env['PATH']}"
        self.env["PYTHONPATH"] = str(SRC_ROOT)

    def tearDown(self):
        if self.original_process_state_dir is None:
            os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
        else:
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = self.original_process_state_dir
        self.temp_dir.cleanup()

    def run_cmd(self, cmd, check=False, stdin=None):
        cmd = list(cmd)
        in_process = os.environ.get("GH_ADDRESS_CR_TEST_IN_PROCESS", "1") == "1"
        if in_process and len(cmd) >= 2 and cmd[0] == sys.executable:
            is_m = cmd[1] == "-m" and len(cmd) >= 3
            target = cmd[2] if is_m else cmd[1]
            args_start = 3 if is_m else 2
            try:
                if is_m:
                    if target in ("gh_address_cr", "gh_address_cr.cli"):
                        return self.run_runtime_module(*cmd[args_start:], check=check, stdin=stdin)
                    elif target == "gh_address_cr.commands.submit_feedback":
                        return self.run_runtime_module("submit-feedback", *cmd[args_start:], check=check, stdin=stdin)
                    elif target == "gh_address_cr.commands.review_to_findings":
                        return self.run_runtime_module("review-to-findings", *cmd[args_start:], check=check, stdin=stdin)
                    elif target == "gh_address_cr.commands.submit_action":
                        return self.run_runtime_module("submit-action", *cmd[args_start:], check=check, stdin=stdin)
                else:
                    path = Path(target).resolve()
                    if path == CLI_PY.resolve():
                        return self.run_runtime_module(*cmd[args_start:], check=check, stdin=stdin)
                    elif path == SUBMIT_FEEDBACK_PY.resolve():
                        return self.run_runtime_module("submit-feedback", *cmd[args_start:], check=check, stdin=stdin)
                    elif path == REVIEW_TO_FINDINGS_PY.resolve():
                        return self.run_runtime_module("review-to-findings", *cmd[args_start:], check=check, stdin=stdin)
                    elif path == SUBMIT_ACTION_PY.resolve():
                        return self.run_runtime_module("submit-action", *cmd[args_start:], check=check, stdin=stdin)
            except (ValueError, OSError):
                pass


        cmd = self._normalize_python_module_command(cmd)
        return subprocess.run(
            cmd,
            input=stdin,
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=self.env,
            check=check,
        )

    def _normalize_python_module_command(self, cmd):
        if len(cmd) < 2 or cmd[0] != sys.executable:
            return cmd
        path = Path(cmd[1]).resolve()
        module_by_path = {
            IMPLEMENTATIONS_DIR / "review_to_findings.py": "gh_address_cr.commands.review_to_findings",
            IMPLEMENTATIONS_DIR / "submit_action.py": "gh_address_cr.commands.submit_action",
            IMPLEMENTATIONS_DIR / "submit_feedback.py": "gh_address_cr.commands.submit_feedback",
        }
        module = module_by_path.get(path)
        if module is None:
            return cmd
        return [cmd[0], "-m", module, *cmd[2:]]

    def run_runtime_module(self, *args, check=False, stdin=None):
        in_process = os.environ.get("GH_ADDRESS_CR_TEST_IN_PROCESS", "1") == "1"
        if in_process:
            import contextlib
            import io
            from unittest.mock import patch

            from gh_address_cr.cli import main

            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            stdin_buf = io.StringIO(stdin or "")

            old_env = os.environ.copy()
            os.environ.clear()
            os.environ.update(self.env)

            old_argv = sys.argv
            sys.argv = ["gh-address-cr", *args]
            old_cwd = os.getcwd()
            
            exit_code = 0
            try:
                import subprocess
                original_run = subprocess.run

                def patched_run(*run_args, **run_kwargs):
                    return _patched_subprocess_run(original_run, *run_args, **run_kwargs)

                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf), patch("sys.stdin", stdin_buf), patch("subprocess.run", patched_run):
                    exit_code = main(list(args))
            except SystemExit as exc:
                if exc.code is None:
                    exit_code = 0
                elif isinstance(exc.code, int):
                    exit_code = exc.code
                else:
                    exit_code = 1
            except Exception as exc:
                import traceback
                stderr_buf.write(f"In-process execution failed: {exc}\n")
                traceback.print_exc(file=stderr_buf)
                exit_code = 2
            finally:
                sys.argv = old_argv
                os.environ.clear()
                os.environ.update(old_env)
                os.chdir(old_cwd)

            class CompletedProcessEmulation:
                def __init__(self, returncode, stdout, stderr):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            res = CompletedProcessEmulation(exit_code, stdout_buf.getvalue(), stderr_buf.getvalue())
            if check and exit_code != 0:
                raise subprocess.CalledProcessError(exit_code, ["gh-address-cr", *args], output=res.stdout, stderr=res.stderr)
            return res
        else:
            env = self.env.copy()
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = str(SRC_ROOT) if not existing else f"{SRC_ROOT}:{existing}"
            return subprocess.run(
                [sys.executable, "-m", "gh_address_cr", *args],
                input=stdin,
                text=True,
                capture_output=True,
                cwd=self.cwd,
                env=env,
                check=check,
            )


    def workspace_dir(self):
        return self.state_dir / "octo__example" / f"pr-{self.pr}"

    def session_file(self):
        return self.workspace_dir() / "session.json"

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))

    def audit_log_file(self):
        return self.workspace_dir() / "audit.jsonl"

    def trace_log_file(self):
        return self.workspace_dir() / "trace.jsonl"

    def audit_summary_file(self):
        return self.workspace_dir() / "audit_summary.md"

    def archive_root(self):
        return self.state_dir / "archive" / "octo__example" / f"pr-{self.pr}"

    def github_dir(self):
        return self.workspace_dir()

    def artifacts_dir(self):
        return self.workspace_dir()


def _decode_stream(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def _handle_subprocess_error(exc, capture_out, capture_err):
    if capture_out and getattr(exc, "output", None) is not None:
        sys.stdout.write(_decode_stream(exc.output))
        try:
            object.__setattr__(exc, "output", None)
            if hasattr(exc, "stdout"):
                object.__setattr__(exc, "stdout", None)
        except AttributeError:
            pass
    if capture_err and getattr(exc, "stderr", None) is not None:
        sys.stderr.write(_decode_stream(exc.stderr))
        try:
            object.__setattr__(exc, "stderr", None)
        except AttributeError:
            pass


def _patched_subprocess_run(original_run, *run_args, **run_kwargs):
    import subprocess
    capture_out = False
    capture_err = False
    if not run_kwargs.get("capture_output") and run_kwargs.get("stdout") is None:
        run_kwargs["stdout"] = subprocess.PIPE
        capture_out = True
    if not run_kwargs.get("capture_output") and run_kwargs.get("stderr") is None:
        run_kwargs["stderr"] = subprocess.PIPE
        capture_err = True

    try:
        res = original_run(*run_args, **run_kwargs)
    except subprocess.SubprocessError as exc:
        _handle_subprocess_error(exc, capture_out, capture_err)
        raise

    if capture_out and res.stdout is not None:
        sys.stdout.write(_decode_stream(res.stdout))
        object.__setattr__(res, "stdout", None)
    if capture_err and res.stderr is not None:
        sys.stderr.write(_decode_stream(res.stderr))
        object.__setattr__(res, "stderr", None)
    return res
