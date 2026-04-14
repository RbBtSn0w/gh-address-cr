import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "gh-address-cr" / "scripts"
CLI_PY = SCRIPTS_DIR / "cli.py"
SCRIPT = SCRIPTS_DIR / "session_engine.py"
RUN_LOCAL_REVIEW_PY = SCRIPTS_DIR / "run_local_review.py"
INGEST_FINDINGS_PY = SCRIPTS_DIR / "ingest_findings.py"
PUBLISH_FINDING_PY = SCRIPTS_DIR / "publish_finding.py"
RUN_ONCE_PY = SCRIPTS_DIR / "run_once.py"
FINAL_GATE_PY = SCRIPTS_DIR / "final_gate.py"
LIST_THREADS_PY = SCRIPTS_DIR / "list_threads.py"
POST_REPLY_PY = SCRIPTS_DIR / "post_reply.py"
RESOLVE_THREAD_PY = SCRIPTS_DIR / "resolve_thread.py"
GENERATE_REPLY_PY = SCRIPTS_DIR / "generate_reply.py"
BATCH_RESOLVE_PY = SCRIPTS_DIR / "batch_resolve.py"
CLEAN_STATE_PY = SCRIPTS_DIR / "clean_state.py"
CONTROL_PLANE_PY = SCRIPTS_DIR / "control_plane.py"
CR_LOOP_PY = SCRIPTS_DIR / "cr_loop.py"
PREPARE_CODE_REVIEW_PY = SCRIPTS_DIR / "prepare_code_review.py"
CODE_REVIEW_ADAPTER_PY = SCRIPTS_DIR / "code_review_adapter.py"
REVIEW_TO_FINDINGS_PY = SCRIPTS_DIR / "review_to_findings.py"
PYTHON_COMMON_PY = SCRIPTS_DIR / "python_common.py"


class SessionEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.cwd = ROOT
        self.repo = "octo/example"
        self.pr = "42"
        self.env = os.environ.copy()
        self.env["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_engine(self, *args, stdin=None, check=False):
        cmd = [sys.executable, str(SCRIPT), *args]
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
        self.env = os.environ.copy()
        self.env["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        self.env["PATH"] = f"{self.bin_dir}:{self.env['PATH']}"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cmd(self, cmd, check=False, stdin=None):
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

    def audit_log_file(self):
        return self.workspace_dir() / "audit.jsonl"

    def audit_summary_file(self):
        return self.workspace_dir() / "audit_summary.md"

    def github_dir(self):
        return self.workspace_dir()

    def artifacts_dir(self):
        return self.workspace_dir()
