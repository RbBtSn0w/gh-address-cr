import importlib.util
import sys
from pathlib import Path

from tests.helpers import BATCH_RESOLVE_PY, CLEAN_STATE_PY, GENERATE_REPLY_PY, PYTHON_COMMON_PY, PythonScriptTestCase, RUN_ONCE_PY


class AuxiliaryScriptsTest(PythonScriptTestCase):
    def test_run_once_helper_parses_each_snapshot_line_once(self):
        spec = importlib.util.spec_from_file_location("run_once_module", RUN_ONCE_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(PYTHON_COMMON_PY.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        snapshot_text = '\n'.join(
            [
                '{"id":"THREAD_1","isResolved":false}',
                '{"id":"THREAD_2","isResolved":true}',
                '{"id":"THREAD_3","isResolved":false}',
                "",
            ]
        )
        self.assertEqual(module.unresolved_ids_from_snapshot_text(snapshot_text), ["THREAD_1", "THREAD_3"])

    def test_generate_reply_fix_mode_writes_markdown(self):
        output = Path(self.temp_dir.name) / "reply.md"
        result = self.run_cmd(
            [
                sys.executable,
                str(GENERATE_REPLY_PY),
                "--severity",
                "P1",
                str(output),
                "abc123",
                "src/a.py, src/b.py",
                "pytest",
                "passed",
                "Fixed the root cause.",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        body = output.read_text(encoding="utf-8")
        self.assertIn("Fixed in `abc123`.", body)
        self.assertIn("- `src/a.py`: updated per CR scope", body)
        self.assertIn("- Fixed the root cause.", body)

    def test_generate_reply_rejects_invalid_severity(self):
        output = Path(self.temp_dir.name) / "reply.md"
        result = self.run_cmd(
            [
                sys.executable,
                str(GENERATE_REPLY_PY),
                "--severity",
                "P9",
                str(output),
                "abc123",
                "src/a.py",
                "pytest",
                "passed",
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid severity", result.stderr)

    def test_batch_resolve_python_processes_approved_lines(self):
        approved = Path(self.temp_dir.name) / "approved.txt"
        approved.write_text("# comment\nAPPROVED THREAD_1\n\nAPPROVED THREAD_2\n", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(BATCH_RESOLVE_PY),
                "--dry-run",
                str(approved),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run] Would resolve thread: THREAD_1", result.stdout)
        self.assertIn("[dry-run] Would resolve thread: THREAD_2", result.stdout)

    def test_batch_resolve_rejects_invalid_lines(self):
        approved = Path(self.temp_dir.name) / "approved.txt"
        approved.write_text("NOPE THREAD_1\n", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(BATCH_RESOLVE_PY),
                "--dry-run",
                str(approved),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected format: APPROVED <thread_id>", result.stderr)

    def test_clean_state_removes_pr_scoped_files(self):
        repo_key = self.repo.replace("/", "__")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        session_file = self.state_dir / f"{repo_key}__pr{self.pr}__session.json"
        audit_file = self.state_dir / f"{repo_key}__pr{self.pr}__audit.jsonl"
        summary_file = self.state_dir / f"{repo_key}__pr{self.pr}__audit_summary.md"
        artifacts_dir = self.state_dir / f"{repo_key}__pr{self.pr}__artifacts"
        session_file.write_text("{}", encoding="utf-8")
        audit_file.write_text("{}\n", encoding="utf-8")
        summary_file.write_text("summary", encoding="utf-8")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "request.json").write_text("{}", encoding="utf-8")

        result = self.run_cmd(
            [
                sys.executable,
                str(CLEAN_STATE_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(session_file.exists())
        self.assertFalse(audit_file.exists())
        self.assertFalse(summary_file.exists())
        self.assertFalse(artifacts_dir.exists())
