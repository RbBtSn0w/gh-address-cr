import importlib.util
import json
import os
import sys
from pathlib import Path

from tests.helpers import BATCH_RESOLVE_PY, CLEAN_STATE_PY, GENERATE_REPLY_PY, PYTHON_COMMON_PY, PythonScriptTestCase, RUN_ONCE_PY


class AuxiliaryScriptsTest(PythonScriptTestCase):
    def _load_python_common_module(self):
        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                str(approved),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run] Would resolve thread: THREAD_1", result.stdout)
        self.assertIn("[dry-run] Would resolve thread: THREAD_2", result.stdout)

    def test_batch_resolve_requires_explicit_repo_and_pr(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:3] == ['repo', 'view', '--json']:
    print(json.dumps({'nameWithOwner': 'octo/example'}))
elif args[:3] == ['pr', 'view', '--json']:
    print(json.dumps({'number': 77}))
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        approved = Path(self.temp_dir.name) / "approved.txt"
        approved.write_text("APPROVED THREAD_1\n", encoding="utf-8")
        result = self.run_cmd([sys.executable, str(BATCH_RESOLVE_PY), "--dry-run", str(approved)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--repo and --pr are required", result.stderr)

    def test_python_common_gh_read_cmd_retries_transient_failure(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_retry_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

payload = json.loads(state_file.read_text())
payload["calls"] += 1
state_file.write_text(json.dumps(payload))
if payload["calls"] == 1:
    sys.stderr.write("graphql error\\n")
    raise SystemExit(1)
print(json.dumps({{"data": {{"ok": True}}}}))
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            spec.loader.exec_module(module)
            result = module.gh_read_cmd(["gh", "api", "graphql"])
        finally:
            os.environ["PATH"] = original_path

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 2)

    def test_python_common_gh_write_cmd_does_not_retry_transient_failure(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_write_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

payload = json.loads(state_file.read_text())
payload["calls"] += 1
state_file.write_text(json.dumps(payload))
sys.stderr.write("graphql error\\n")
raise SystemExit(1)
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            spec.loader.exec_module(module)
            result = module.gh_write_cmd(["gh", "api", "graphql"], check=False)
        finally:
            os.environ["PATH"] = original_path

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 1)

    def test_python_common_run_cmd_retries_transient_gh_failure_when_requested(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_run_cmd_retry_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

payload = json.loads(state_file.read_text())
payload["calls"] += 1
state_file.write_text(json.dumps(payload))
if payload["calls"] == 1:
    sys.stderr.write("graphql failed\\n")
    raise SystemExit(1)
print("ok")
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            spec.loader.exec_module(module)
            result = module.run_cmd(["gh", "api", "graphql"], retries=2)
        finally:
            os.environ["PATH"] = original_path

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 2)

    def test_python_common_pull_request_read_cache_reuses_files_for_same_head(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            cache = module.PullRequestReadCache(self.repo, self.pr)
            calls = {"count": 0}

            def loader():
                calls["count"] += 1
                return [{"filename": "src/example.py"}]

            first = cache.get_or_load_files("deadbeef", loader)
            second = cache.get_or_load_files("deadbeef", loader)
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(first, [{"filename": "src/example.py"}])
        self.assertEqual(second, first)
        self.assertEqual(calls["count"], 1)

    def test_python_common_pull_request_read_cache_replaces_files_when_head_changes(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            cache = module.PullRequestReadCache(self.repo, self.pr)
            calls = {"count": 0}

            def load_first():
                calls["count"] += 1
                return [{"filename": "src/first.py"}]

            def load_second():
                calls["count"] += 1
                return [{"filename": "src/second.py"}]

            cache.get_or_load_files("deadbeef", load_first)
            second = cache.get_or_load_files("cafebabe", load_second)
            cache_path = module.github_pr_cache_file(self.repo, self.pr)
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(second, [{"filename": "src/second.py"}])
        self.assertEqual(calls["count"], 2)
        self.assertEqual(payload["head_sha"], "cafebabe")
        self.assertEqual(payload["files_by_head"], {"cafebabe": [{"filename": "src/second.py"}]})

    def test_python_common_threads_snapshot_helpers_round_trip_rows(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            rows = [
                {"id": "THREAD_1", "isResolved": False, "path": "src/a.py", "line": 1},
                {"id": "THREAD_2", "isResolved": True, "path": "src/b.py", "line": 2},
            ]
            snapshot = module.write_threads_snapshot(self.repo, self.pr, rows)
            loaded = module.load_threads_snapshot_rows(snapshot)
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(loaded, rows)

    def test_python_common_copy_threads_snapshot_reuses_existing_snapshot_text(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            source = Path(self.temp_dir.name) / "source_snapshot.jsonl"
            source.write_text(
                '{"id":"THREAD_1","isResolved":false,"path":"src/a.py","line":1}\n',
                encoding="utf-8",
            )
            copied = module.copy_threads_snapshot(self.repo, self.pr, source)
            loaded = module.load_threads_snapshot_rows(copied)
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(loaded, [{"id": "THREAD_1", "isResolved": False, "path": "src/a.py", "line": 1}])

    def test_python_common_github_viewer_login_caches_value_within_process(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_user_cache_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

state = json.loads(state_file.read_text(encoding='utf-8'))
args = sys.argv[1:]
if args[:2] == ['api', 'user']:
    state['calls'] += 1
    state_file.write_text(json.dumps(state), encoding='utf-8')
    print(json.dumps({{"login": "tester"}}))
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        module = self._load_python_common_module()
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            first = module.github_viewer_login()
            second = module.github_viewer_login()
        finally:
            os.environ["PATH"] = original_path

        self.assertEqual(first, "tester")
        self.assertEqual(second, "tester")
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 1)

    def test_batch_resolve_rejects_invalid_lines(self):
        approved = Path(self.temp_dir.name) / "approved.txt"
        approved.write_text("NOPE THREAD_1\n", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(BATCH_RESOLVE_PY),
                "--dry-run",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                str(approved),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected format: APPROVED <thread_id>", result.stderr)

    def test_clean_state_removes_pr_scoped_files(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        session_file = self.session_file()
        audit_file = self.audit_log_file()
        summary_file = self.audit_summary_file()
        artifacts_dir = self.artifacts_dir()
        session_file.parent.mkdir(parents=True, exist_ok=True)
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.parent.mkdir(parents=True, exist_ok=True)
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

    def test_clean_state_accepts_legacy_clean_tmp_flag(self):
        result = self.run_cmd([sys.executable, str(CLEAN_STATE_PY), "--clean-tmp"])
        self.assertEqual(result.returncode, 0, result.stderr)
