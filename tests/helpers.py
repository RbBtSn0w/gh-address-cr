import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
SKILL_ROOT = ROOT / "skill"
RUNTIME_PACKAGE_DIR = SRC_ROOT / "gh_address_cr"
IMPLEMENTATIONS_DIR = RUNTIME_PACKAGE_DIR / "commands"
SCRIPTS_DIR = IMPLEMENTATIONS_DIR
CORE_DIR = RUNTIME_PACKAGE_DIR / "core"

CLI_PY = RUNTIME_PACKAGE_DIR / "cli.py"
SCRIPT = CORE_DIR / "session_engine.py"
RUN_LOCAL_REVIEW_PY = IMPLEMENTATIONS_DIR / "run_local_review.py"
INGEST_FINDINGS_PY = IMPLEMENTATIONS_DIR / "ingest_findings.py"
RUN_ONCE_PY = IMPLEMENTATIONS_DIR / "run_once.py"
FINAL_GATE_PY = IMPLEMENTATIONS_DIR / "final_gate.py"
POST_REPLY_PY = IMPLEMENTATIONS_DIR / "post_reply.py"
CONTROL_PLANE_PY = CORE_DIR / "control_plane.py"
CR_LOOP_PY = CORE_DIR / "cr_loop.py"
CODE_REVIEW_ADAPTER_PY = IMPLEMENTATIONS_DIR / "code_review_adapter.py"
REVIEW_TO_FINDINGS_PY = IMPLEMENTATIONS_DIR / "review_to_findings.py"
PYTHON_COMMON_PY = IMPLEMENTATIONS_DIR / "python_common.py"
SUBMIT_FEEDBACK_PY = IMPLEMENTATIONS_DIR / "submit_feedback.py"


class SessionEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.cwd = ROOT
        self.repo = "octo/example"
        self.pr = "42"
        self.original_process_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        self.env = os.environ.copy()
        self.env["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        self.env["GH_ADDRESS_CR_DISABLE_OTLP_EXPORT"] = "1"
        self.env["PYTHONPATH"] = str(SRC_ROOT)

    def tearDown(self):
        if self.original_process_state_dir is None:
            os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
        else:
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = self.original_process_state_dir
        self.temp_dir.cleanup()

    def run_engine(self, *args, stdin=None, check=False):
        cmd = [sys.executable, "-m", "gh_address_cr.core.session_engine", *args]
        return subprocess.run(
            cmd,
            input=stdin,
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=self.env,
            check=check,
        )

    def workspace_dir(self):
        return self.state_dir / "octo__example" / f"pr-{self.pr}"

    def session_file(self):
        return self.workspace_dir() / "session.json"

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))


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
        self.env["GH_ADDRESS_CR_DISABLE_OTLP_EXPORT"] = "1"
        self.env["PATH"] = f"{self.bin_dir}:{self.env['PATH']}"
        self.env["PYTHONPATH"] = str(SRC_ROOT)

    def tearDown(self):
        if self.original_process_state_dir is None:
            os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
        else:
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = self.original_process_state_dir
        self.temp_dir.cleanup()

    def run_cmd(self, cmd, check=False, stdin=None):
        cmd = self._normalize_python_module_command(list(cmd))
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
            CORE_DIR / "session_engine.py": "gh_address_cr.core.session_engine",
            CORE_DIR / "control_plane.py": "gh_address_cr.core.control_plane",
            CORE_DIR / "cr_loop.py": "gh_address_cr.core.cr_loop",
            IMPLEMENTATIONS_DIR / "run_once.py": "gh_address_cr.commands.run_once",
            IMPLEMENTATIONS_DIR / "run_local_review.py": "gh_address_cr.commands.run_local_review",
            IMPLEMENTATIONS_DIR / "ingest_findings.py": "gh_address_cr.commands.ingest_findings",
            IMPLEMENTATIONS_DIR / "final_gate.py": "gh_address_cr.commands.final_gate",
            IMPLEMENTATIONS_DIR / "code_review_adapter.py": "gh_address_cr.commands.code_review_adapter",
            IMPLEMENTATIONS_DIR / "review_to_findings.py": "gh_address_cr.commands.review_to_findings",
            IMPLEMENTATIONS_DIR / "submit_action.py": "gh_address_cr.commands.submit_action",
            IMPLEMENTATIONS_DIR / "submit_feedback.py": "gh_address_cr.commands.submit_feedback",
            IMPLEMENTATIONS_DIR / "post_reply.py": "gh_address_cr.commands.post_reply",
        }
        module = module_by_path.get(path)
        if module is None:
            return cmd
        return [cmd[0], "-m", module, *cmd[2:]]

    def run_runtime_module(self, *args, check=False, stdin=None):
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
