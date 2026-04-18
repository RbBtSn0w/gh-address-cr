import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import types
from unittest.mock import patch

from tests.helpers import CR_LOOP_PY, PythonScriptTestCase, SCRIPT


class CRLoopCLITest(PythonScriptTestCase):
    def artifacts_dir(self) -> Path:
        return super().artifacts_dir()

    def load_module(self):
        sys.path.insert(0, str(CR_LOOP_PY.parent))
        spec = importlib.util.spec_from_file_location("cr_loop_under_test", CR_LOOP_PY)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        try:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}, clear=False):
                spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def test_select_next_item_skips_active_claims(self):
        module = self.load_module()

        future = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(microsecond=0).isoformat()
        session = {
            "items": {
                "local-finding:claimed": {
                    "item_id": "local-finding:claimed",
                    "item_kind": "local_finding",
                    "blocking": True,
                    "needs_human": False,
                    "claimed_by": "agent-a",
                    "lease_expires_at": future,
                    "severity": "P1",
                    "path": "src/claimed.py",
                    "line": 1,
                },
                "local-finding:open": {
                    "item_id": "local-finding:open",
                    "item_kind": "local_finding",
                    "blocking": True,
                    "needs_human": False,
                    "claimed_by": None,
                    "lease_expires_at": None,
                    "severity": "P2",
                    "path": "src/open.py",
                    "line": 2,
                },
            }
        }

        selected = module.select_ready_batch(session)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["item_id"], "local-finding:open")

    def test_cr_loop_mixed_adapter_accepts_adapter_command_flags(self):
        adapter = Path(self.temp_dir.name) / "adapter_with_flags.py"
        adapter.write_text(
            (
                "import argparse\n"
                "import json\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--base', required=True)\n"
                "args = parser.parse_args()\n"
                "print(json.dumps([]))\n"
            ),
            encoding="utf-8",
        )

        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'tester'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "mixed",
                "adapter",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
                "--base",
                "main",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cr-loop PASSED", result.stdout)

    def test_detect_needs_human_uses_supplied_session_without_reload(self):
        module = self.load_module()
        item_id = "local-finding:loop-threshold"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "local_finding",
                    "blocking": True,
                    "needs_human": False,
                    "repeat_count": 2,
                    "reopen_count": 0,
                    "history": [],
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }

        with patch.object(module.engine, "load_session", side_effect=AssertionError("load_session should not be called")):
            needs_human, found_item_id = module.detect_needs_human(
                self.repo,
                self.pr,
                run_id="run-1",
                iteration=1,
                max_iterations=3,
                loop_threshold=2,
                session=session,
            )

        self.assertTrue(needs_human)
        self.assertEqual(found_item_id, item_id)
        updated = session["items"][item_id]
        self.assertTrue(updated["needs_human"])
        self.assertEqual(session["loop_state"]["status"], "NEEDS_HUMAN")

    def test_handle_batch_invalid_resolution_loads_session_once(self):
        module = self.load_module()
        item_id = "local-finding:bad-resolution"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "local_finding",
                    "origin_ref": item_id,
                    "title": "Bad resolution",
                    "body": "Invalid fixer output should escalate once.",
                    "path": "src/bad_resolution.py",
                    "line": 11,
                    "severity": "P2",
                    "status": "OPEN",
                    "decision": None,
                    "blocking": True,
                    "handled": False,
                    "handled_at": None,
                    "resolution_note": None,
                    "published": False,
                    "published_ref": None,
                    "url": None,
                    "first_url": None,
                    "latest_url": None,
                    "is_outdated": False,
                    "scan_id": None,
                    "introduced_in_sha": None,
                    "last_seen_in_sha": None,
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "repeat_count": 0,
                    "reopen_count": 0,
                    "evidence": [],
                    "history": [],
                    "auto_attempt_count": 0,
                    "last_auto_action": None,
                    "last_auto_failure": None,
                    "needs_human": False,
                    "reply_posted": False,
                    "reply_url": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        self.session_file().parent.mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(session), encoding="utf-8")

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "bogus",
                    "note": "This resolution is invalid.",
                    "validation_commands": [],
                },
                "",
            )

        module.run_fixer = fake_run_fixer
        module.emit = lambda _result: None
        args = types.SimpleNamespace(fixer_cmd="fixer", validation_cmd=[], max_iterations=3)

        real_load_session = module.engine.load_session
        real_save_session = module.engine.save_session
        counts = {"load": 0, "save": 0}

        def counted_load_session(repo: str, pr_number: str):
            counts["load"] += 1
            return real_load_session(repo, pr_number)

        def counted_save_session(updated_session: dict):
            counts["save"] += 1
            return real_save_session(updated_session)

        with patch.object(module.engine, "load_session", side_effect=counted_load_session), patch.object(
            module.engine, "save_session", side_effect=counted_save_session
        ), patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}):
            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-bad-resolution",
                iteration=1,
            )

        self.assertEqual(status, "needs_human")
        self.assertIn("Unsupported resolution", error)
        self.assertEqual(counts["load"], 1)
        self.assertEqual(counts["save"], 1)

    def test_handle_batch_keeps_item_open_when_batch_result_is_retryable(self):
        module = self.load_module()
        item_id = "github-thread:THREAD_RETRYABLE"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "github_thread",
                    "origin_ref": "THREAD_RETRYABLE",
                    "title": "Retry later",
                    "body": "Transient write failure should not close item.",
                    "path": "src/retry.py",
                    "line": 9,
                    "severity": "P2",
                    "status": "OPEN",
                    "decision": None,
                    "blocking": True,
                    "handled": False,
                    "handled_at": None,
                    "resolution_note": None,
                    "published": True,
                    "published_ref": "https://example.test/thread/retry",
                    "url": "https://example.test/thread/retry",
                    "first_url": "https://example.test/thread/retry",
                    "latest_url": "https://example.test/thread/retry",
                    "is_outdated": False,
                    "scan_id": None,
                    "introduced_in_sha": None,
                    "last_seen_in_sha": None,
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "repeat_count": 0,
                    "reopen_count": 0,
                    "evidence": [],
                    "history": [],
                    "auto_attempt_count": 0,
                    "last_auto_action": None,
                    "last_auto_failure": None,
                    "needs_human": False,
                    "reply_posted": False,
                    "reply_url": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        self.session_file().parent.mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(session), encoding="utf-8")

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "clarify",
                    "note": "Retry later.",
                    "reply_markdown": "Transient remote failure.",
                    "validation_commands": [],
                },
                "",
            )

        def fake_run_cmd(cmd, *, stdin=None):
            if Path(cmd[1]).name == "batch_github_execute.py":
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    json.dumps(
                        {
                            item_id: {
                                "status": "retryable",
                                "error": "graphql failed",
                                "reply_url": "https://example.test/reply/retryable",
                            }
                        }
                    ),
                    "",
                )
            if Path(cmd[1]).name == "session_engine.py" and cmd[2] == "update-items-batch":
                updates = json.loads(stdin or "[]")
                session = json.loads(self.session_file().read_text(encoding="utf-8"))
                for update in updates:
                    current = session["items"][update["item_id"]]
                    current.update(update)
                self.session_file().write_text(json.dumps(session), encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if Path(cmd[1]).name == "session_engine.py" and cmd[2] == "record-auto-attempt":
                session = json.loads(self.session_file().read_text(encoding="utf-8"))
                item = session["items"][cmd[5]]
                item["last_auto_failure"] = cmd[9]
                self.session_file().write_text(json.dumps(session), encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if Path(cmd[1]).name == "session_engine.py" and cmd[2] == "release-claim":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            raise AssertionError(f"unexpected command: {cmd}")

        module.run_fixer = fake_run_fixer
        module.run_cmd = fake_run_cmd
        module.emit = lambda _result: None

        args = types.SimpleNamespace(
            fixer_cmd="fixer",
            validation_cmd=[],
            max_iterations=10,
        )

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}):
            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-retryable",
                iteration=1,
            )

        self.assertEqual(status, "done")
        self.assertEqual(error, "")
        updated = json.loads(self.session_file().read_text(encoding="utf-8"))["items"][item_id]
        self.assertEqual(updated["status"], "OPEN")
        self.assertFalse(updated["handled"])
        self.assertTrue(updated["reply_posted"])
        self.assertEqual(updated["reply_url"], "https://example.test/reply/retryable")
        self.assertEqual(updated["last_auto_failure"], "graphql failed")

    def test_handle_batch_github_fix_generates_reply_from_structured_fix_payload(self):
        module = self.load_module()
        item_id = "github-thread:THREAD_FIX_TEMPLATE"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "github_thread",
                    "origin_ref": "THREAD_FIX_TEMPLATE",
                    "title": "Use template",
                    "body": "Fix replies must use the canonical template.",
                    "path": "src/template_fix.py",
                    "line": 21,
                    "severity": "P2",
                    "status": "OPEN",
                    "decision": None,
                    "blocking": True,
                    "handled": False,
                    "handled_at": None,
                    "resolution_note": None,
                    "published": True,
                    "published_ref": "https://example.test/thread/template-fix",
                    "url": "https://example.test/thread/template-fix",
                    "first_url": "https://example.test/thread/template-fix",
                    "latest_url": "https://example.test/thread/template-fix",
                    "is_outdated": False,
                    "scan_id": None,
                    "introduced_in_sha": None,
                    "last_seen_in_sha": None,
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "repeat_count": 0,
                    "reopen_count": 0,
                    "evidence": [],
                    "history": [],
                    "auto_attempt_count": 0,
                    "last_auto_action": None,
                    "last_auto_failure": None,
                    "needs_human": False,
                    "reply_posted": False,
                    "reply_url": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        self.session_file().parent.mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(session), encoding="utf-8")

        captured = {}

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "fix",
                    "note": "Applied the focused fix.",
                    "fix_reply": {
                        "commit_hash": "abc123",
                        "files": ["src/template_fix.py", "tests/test_template_fix.py"],
                        "why": "Aligned the reply flow with the canonical fix template.",
                    },
                    "validation_commands": ["python3 -m unittest tests.test_cr_loop"],
                },
                "",
            )

        def fake_run_validation(commands: list[str]):
            self.assertEqual(commands, ["python3 -m unittest tests.test_cr_loop"])
            return True, ""

        def fake_run_cmd(cmd, *, stdin=None):
            if Path(cmd[1]).name == "batch_github_execute.py":
                payload = json.loads(stdin or "[]")
                self.assertEqual(len(payload), 1)
                captured["reply_body"] = payload[0]["reply_body"]
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        {
                            item_id: {
                                "status": "succeeded",
                                "reply_url": "https://example.test/reply/template-fix",
                            }
                        }
                    ),
                    "",
                )
            if Path(cmd[1]).name == "session_engine.py" and cmd[2] == "update-items-batch":
                updates = json.loads(stdin or "[]")
                session_data = json.loads(self.session_file().read_text(encoding="utf-8"))
                for update in updates:
                    session_data["items"][update["item_id"]].update(update)
                self.session_file().write_text(json.dumps(session_data), encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            raise AssertionError(f"unexpected command: {cmd}")

        module.run_fixer = fake_run_fixer
        module.run_validation = fake_run_validation
        module.run_cmd = fake_run_cmd
        module.emit = lambda _result: None

        args = types.SimpleNamespace(
            fixer_cmd="fixer",
            validation_cmd=[],
            max_iterations=10,
        )

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}):
            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-fix-template",
                iteration=1,
            )

        self.assertEqual(status, "done")
        self.assertEqual(error, "")
        self.assertIn("Fixed in `abc123`.", captured["reply_body"])
        self.assertIn("Severity: `P2`", captured["reply_body"])
        self.assertIn("What I changed:", captured["reply_body"])
        self.assertIn("- `src/template_fix.py`: updated per CR scope", captured["reply_body"])
        self.assertIn("Why this addresses the CR:", captured["reply_body"])
        self.assertIn("Validation:", captured["reply_body"])
        self.assertIn("`python3 -m unittest tests.test_cr_loop`", captured["reply_body"])
        self.assertIn("Result: passed", captured["reply_body"])

        updated = json.loads(self.session_file().read_text(encoding="utf-8"))["items"][item_id]
        self.assertEqual(updated["status"], "CLOSED")
        self.assertTrue(updated["handled"])
        self.assertTrue(updated["reply_posted"])

    def test_handle_batch_github_fix_rejects_raw_reply_markdown_without_fix_template_payload(self):
        module = self.load_module()
        item_id = "github-thread:THREAD_RAW_FIX_REPLY"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "github_thread",
                    "origin_ref": "THREAD_RAW_FIX_REPLY",
                    "title": "Reject raw fix reply",
                    "body": "Raw fix replies should not bypass the template.",
                    "path": "src/raw_fix_reply.py",
                    "line": 8,
                    "severity": "P2",
                    "status": "OPEN",
                    "decision": None,
                    "blocking": True,
                    "handled": False,
                    "handled_at": None,
                    "resolution_note": None,
                    "published": True,
                    "published_ref": "https://example.test/thread/raw-fix",
                    "url": "https://example.test/thread/raw-fix",
                    "first_url": "https://example.test/thread/raw-fix",
                    "latest_url": "https://example.test/thread/raw-fix",
                    "is_outdated": False,
                    "scan_id": None,
                    "introduced_in_sha": None,
                    "last_seen_in_sha": None,
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "repeat_count": 0,
                    "reopen_count": 0,
                    "evidence": [],
                    "history": [],
                    "auto_attempt_count": 0,
                    "last_auto_action": None,
                    "last_auto_failure": None,
                    "needs_human": False,
                    "reply_posted": False,
                    "reply_url": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        self.session_file().parent.mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(session), encoding="utf-8")

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "fix",
                    "note": "Fixed it.",
                    "reply_markdown": "Custom reply that bypasses the template.",
                    "validation_commands": [],
                },
                "",
            )

        module.run_fixer = fake_run_fixer
        module.emit = lambda _result: None
        args = types.SimpleNamespace(fixer_cmd="fixer", validation_cmd=[], max_iterations=3)

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}):
            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-raw-fix-reply",
                iteration=1,
            )

        self.assertEqual(status, "needs_human")
        self.assertIn("fix_reply", error)
        updated = json.loads(self.session_file().read_text(encoding="utf-8"))["items"][item_id]
        self.assertTrue(updated["needs_human"])
        self.assertFalse(updated["reply_posted"])

    def test_build_github_fix_reply_normalizes_unknown_severity_to_p2(self):
        module = self.load_module()

        reply_markdown, error = module.build_github_fix_reply(
            {
                "fix_reply": {
                    "commit_hash": "abc123",
                    "files": ["src/example.py"],
                }
            },
            {
                "item_id": "github-thread:THREAD_UNKNOWN_SEVERITY",
                "severity": "P4",
            },
            ["python3 -m unittest tests.test_cr_loop"],
        )

        self.assertEqual(error, "")
        self.assertIsNotNone(reply_markdown)
        self.assertIn("Severity: `P2`", reply_markdown)
        self.assertIn("`python3 -m unittest tests.test_cr_loop`", reply_markdown)

    def test_handle_batch_github_fix_normalizes_string_validation_command(self):
        module = self.load_module()
        item_id = "github-thread:THREAD_FIX_STRING_VALIDATION"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "github_thread",
                    "origin_ref": "THREAD_FIX_STRING_VALIDATION",
                    "title": "Normalize string validation command",
                    "body": "String validation commands should not be split into characters.",
                    "path": "src/string_validation.py",
                    "line": 17,
                    "severity": "P2",
                    "status": "OPEN",
                    "decision": None,
                    "blocking": True,
                    "handled": False,
                    "handled_at": None,
                    "resolution_note": None,
                    "published": True,
                    "published_ref": "https://example.test/thread/string-validation",
                    "url": "https://example.test/thread/string-validation",
                    "first_url": "https://example.test/thread/string-validation",
                    "latest_url": "https://example.test/thread/string-validation",
                    "is_outdated": False,
                    "scan_id": None,
                    "introduced_in_sha": None,
                    "last_seen_in_sha": None,
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "repeat_count": 0,
                    "reopen_count": 0,
                    "evidence": [],
                    "history": [],
                    "auto_attempt_count": 0,
                    "last_auto_action": None,
                    "last_auto_failure": None,
                    "needs_human": False,
                    "reply_posted": False,
                    "reply_url": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        self.session_file().parent.mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(session), encoding="utf-8")

        captured = {}

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "fix",
                    "note": "Normalized string validation commands.",
                    "fix_reply": {
                        "commit_hash": "abc123",
                        "files": ["src/string_validation.py"],
                    },
                    "validation_commands": "python3 -m unittest tests.test_cr_loop",
                },
                "",
            )

        def fake_run_validation(commands: list[str]):
            captured["commands"] = commands
            return True, ""

        def fake_run_cmd(cmd, *, stdin=None):
            if Path(cmd[1]).name == "batch_github_execute.py":
                payload = json.loads(stdin or "[]")
                captured["reply_body"] = payload[0]["reply_body"]
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps({item_id: {"status": "succeeded", "reply_url": "https://example.test/reply/string-validation"}}),
                    "",
                )
            if Path(cmd[1]).name == "session_engine.py" and cmd[2] == "update-items-batch":
                updates = json.loads(stdin or "[]")
                session_data = json.loads(self.session_file().read_text(encoding="utf-8"))
                for update in updates:
                    session_data["items"][update["item_id"]].update(update)
                self.session_file().write_text(json.dumps(session_data), encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            raise AssertionError(f"unexpected command: {cmd}")

        module.run_fixer = fake_run_fixer
        module.run_validation = fake_run_validation
        module.run_cmd = fake_run_cmd
        module.emit = lambda _result: None

        args = types.SimpleNamespace(fixer_cmd="fixer", validation_cmd=[], max_iterations=10)

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}):
            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-string-validation",
                iteration=1,
            )

        self.assertEqual(status, "done")
        self.assertEqual(error, "")
        self.assertEqual(captured["commands"], ["python3 -m unittest tests.test_cr_loop"])
        self.assertIn("`python3 -m unittest tests.test_cr_loop`", captured["reply_body"])

    def test_handle_batch_github_fix_normalizes_mixed_validation_command_list(self):
        module = self.load_module()
        item_id = "github-thread:THREAD_FIX_MIXED_VALIDATION"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "github_thread",
                    "origin_ref": "THREAD_FIX_MIXED_VALIDATION",
                    "title": "Normalize mixed validation command list",
                    "body": "Validation commands should coerce list elements to strings and drop empties.",
                    "path": "src/mixed_validation.py",
                    "line": 23,
                    "severity": "P2",
                    "status": "OPEN",
                    "decision": None,
                    "blocking": True,
                    "handled": False,
                    "handled_at": None,
                    "resolution_note": None,
                    "published": True,
                    "published_ref": "https://example.test/thread/mixed-validation",
                    "url": "https://example.test/thread/mixed-validation",
                    "first_url": "https://example.test/thread/mixed-validation",
                    "latest_url": "https://example.test/thread/mixed-validation",
                    "is_outdated": False,
                    "scan_id": None,
                    "introduced_in_sha": None,
                    "last_seen_in_sha": None,
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "repeat_count": 0,
                    "reopen_count": 0,
                    "evidence": [],
                    "history": [],
                    "auto_attempt_count": 0,
                    "last_auto_action": None,
                    "last_auto_failure": None,
                    "needs_human": False,
                    "reply_posted": False,
                    "reply_url": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        self.session_file().parent.mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(session), encoding="utf-8")

        captured = {}

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "fix",
                    "note": "Normalized mixed validation commands.",
                    "fix_reply": {
                        "commit_hash": "def456",
                        "files": ["src/mixed_validation.py"],
                    },
                    "validation_commands": ["python3 -m unittest tests.test_cr_loop", 123, "  ", None],
                },
                "",
            )

        def fake_run_validation(commands: list[str]):
            captured["commands"] = commands
            return True, ""

        def fake_run_cmd(cmd, *, stdin=None):
            if Path(cmd[1]).name == "batch_github_execute.py":
                payload = json.loads(stdin or "[]")
                captured["reply_body"] = payload[0]["reply_body"]
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps({item_id: {"status": "succeeded", "reply_url": "https://example.test/reply/mixed-validation"}}),
                    "",
                )
            if Path(cmd[1]).name == "session_engine.py" and cmd[2] == "update-items-batch":
                updates = json.loads(stdin or "[]")
                session_data = json.loads(self.session_file().read_text(encoding="utf-8"))
                for update in updates:
                    session_data["items"][update["item_id"]].update(update)
                self.session_file().write_text(json.dumps(session_data), encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            raise AssertionError(f"unexpected command: {cmd}")

        module.run_fixer = fake_run_fixer
        module.run_validation = fake_run_validation
        module.run_cmd = fake_run_cmd
        module.emit = lambda _result: None

        args = types.SimpleNamespace(fixer_cmd="fixer", validation_cmd=[], max_iterations=10)

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}):
            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-mixed-validation",
                iteration=1,
            )

        self.assertEqual(status, "done")
        self.assertEqual(error, "")
        self.assertEqual(captured["commands"], ["python3 -m unittest tests.test_cr_loop", "123"])
        self.assertIn("`python3 -m unittest tests.test_cr_loop && 123`", captured["reply_body"])

    def test_handle_batch_github_fix_requires_test_result_when_only_test_command_is_provided(self):
        module = self.load_module()
        item_id = "github-thread:THREAD_FIX_MISSING_TEST_RESULT"
        session = {
            "schema_version": 1,
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "item_kind": "github_thread",
                    "origin_ref": "THREAD_FIX_MISSING_TEST_RESULT",
                    "title": "Require explicit test_result",
                    "body": "The fixer should not infer a passing result from a raw test command string alone.",
                    "path": "src/missing_test_result.py",
                    "line": 31,
                    "severity": "P2",
                    "status": "OPEN",
                    "decision": None,
                    "blocking": True,
                    "handled": False,
                    "handled_at": None,
                    "resolution_note": None,
                    "published": True,
                    "published_ref": "https://example.test/thread/missing-test-result",
                    "url": "https://example.test/thread/missing-test-result",
                    "first_url": "https://example.test/thread/missing-test-result",
                    "latest_url": "https://example.test/thread/missing-test-result",
                    "is_outdated": False,
                    "scan_id": None,
                    "introduced_in_sha": None,
                    "last_seen_in_sha": None,
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "repeat_count": 0,
                    "reopen_count": 0,
                    "evidence": [],
                    "history": [],
                    "auto_attempt_count": 0,
                    "last_auto_action": None,
                    "last_auto_failure": None,
                    "needs_human": False,
                    "reply_posted": False,
                    "reply_url": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        self.session_file().parent.mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(session), encoding="utf-8")

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "fix",
                    "note": "Updated the code path.",
                    "fix_reply": {
                        "commit_hash": "feed123",
                        "files": ["src/missing_test_result.py"],
                        "test_command": "python3 -m unittest tests.test_cr_loop",
                    },
                    "validation_commands": [],
                },
                "",
            )

        module.run_fixer = fake_run_fixer
        module.emit = lambda _result: None
        args = types.SimpleNamespace(fixer_cmd="fixer", validation_cmd=[], max_iterations=3)

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}):
            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-missing-test-result",
                iteration=1,
            )

        self.assertEqual(status, "needs_human")
        self.assertIn("test_result", error)
        updated = json.loads(self.session_file().read_text(encoding="utf-8"))["items"][item_id]
        self.assertTrue(updated["needs_human"])
        self.assertFalse(updated["reply_posted"])
    def test_cr_loop_local_json_fix_passes_gate(self):
        findings_file = Path(self.temp_dir.name) / "findings.json"
        findings_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Loop local finding",
                        "body": "Needs a local fix.",
                        "path": "src/local.py",
                        "line": 7,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            ),
            encoding="utf-8",
        )
        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            """#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read())
item = payload["item"]
print(json.dumps({
    "resolution": "fix",
    "note": f"Auto-fixed {item['item_id']}.",
    "validation_commands": []
}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "local",
                "json",
                "--input",
                str(findings_file),
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cr-loop PASSED", result.stdout)

        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        self.assertEqual(session["loop_state"]["status"], "PASSED")
        self.assertEqual(session["loop_state"]["iteration"], 1)

    def test_cr_loop_remote_clarify_passes_gate(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_state.json"
        state_file.write_text(json.dumps({"resolved": False}), encoding="utf-8")
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file)!r})
state = json.loads(state_file.read_text(encoding="utf-8"))
args = sys.argv[1:]

if args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'tester'}}))
elif args[:2] == ['api', 'graphql']:
    query = next(arg.split('=', 1)[1] for arg in args if arg.startswith('query='))
    if 'resolveReviewThread' in query and 'addPullRequestReviewThreadReply' in query:
        state['resolved'] = True
        state_file.write_text(json.dumps(state), encoding='utf-8')
        print(json.dumps({{
            'data': {{
                'reply0': {{'comment': {{'url': 'https://example.test/reply'}}}},
                'resolve0': {{'thread': {{'id': 'THREAD_REMOTE_LOOP', 'isResolved': True}}}},
            }}
        }}))
    elif 'resolveReviewThread' in query:
        state['resolved'] = True
        state_file.write_text(json.dumps(state), encoding='utf-8')
        print(json.dumps({{'data': {{'resolveReviewThread': {{'thread': {{'id': 'THREAD_REMOTE_LOOP', 'isResolved': True}}}}}}}}))
    elif 'addPullRequestReviewThreadReply' in query:
        print(json.dumps({{'data': {{'addPullRequestReviewThreadReply': {{'comment': {{'url': 'https://example.test/reply'}}}}}}}}))
    else:
        print(json.dumps({{
            'data': {{
                'repository': {{
                    'pullRequest': {{
                        'reviewThreads': {{
                            'pageInfo': {{'hasNextPage': False, 'endCursor': None}},
                            'nodes': [] if state['resolved'] else [{{
                                'id': 'THREAD_REMOTE_LOOP',
                                'isResolved': False,
                                'isOutdated': False,
                                'path': 'src/remote.py',
                                'line': 4,
                                'firstComment': {{'nodes': [{{'url': 'https://example.test/thread/remote', 'body': 'remote body'}}]}},
                                'latestComment': {{'nodes': [{{'url': 'https://example.test/thread/remote', 'body': 'remote body'}}]}},
                            }}]
                        }}
                    }}
                }}
            }}
        }}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith(f'repos/{self.repo}/pulls/{self.pr}/reviews'):
    if 'page=1' in args[1]:
        print('[]')
    else:
        print('[]')
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith(f'repos/{self.repo}/pulls/{self.pr}/reviews/1'):
    print('{{}}')
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            """#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read())
item = payload["item"]
print(json.dumps({
    "resolution": "clarify",
    "note": f"Clarified {item['item_id']}.",
    "reply_markdown": "Clarified in loop runner.",
    "validation_commands": []
}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "remote",
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cr-loop PASSED", result.stdout)

    def test_cr_loop_remote_reuses_run_once_snapshot_when_gate_runs_without_actions(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_remote_snapshot_state.json"
        state_file.write_text(json.dumps({"graphql_calls": 0}), encoding="utf-8")
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file)!r})
state = json.loads(state_file.read_text(encoding="utf-8"))
args = sys.argv[1:]

if args[:2] == ['api', 'graphql']:
    state['graphql_calls'] += 1
    state_file.write_text(json.dumps(state), encoding='utf-8')
    print(json.dumps({{
        'data': {{
            'repository': {{
                'pullRequest': {{
                    'reviewThreads': {{
                        'pageInfo': {{'hasNextPage': False, 'endCursor': None}},
                        'nodes': []
                    }}
                }}
            }}
        }}
    }}))
elif args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'tester'}}))
elif args[:2] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CR_LOOP_PY), "remote", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(state["graphql_calls"], 1)

    def test_cr_loop_does_not_repost_reply_after_resolve_failure(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_state_reply_retry.json"
        state_file.write_text(json.dumps({"reply_calls": 0, "resolve_attempts": 0, "resolved": False}), encoding="utf-8")
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file)!r})
state = json.loads(state_file.read_text(encoding="utf-8"))
args = sys.argv[1:]

if args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'tester'}}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith(f'repos/{self.repo}/pulls/{self.pr}/reviews'):
    if 'page=2' in args[1]:
        print('[]')
    else:
        print('[]')
elif args[:2] == ['api', 'graphql']:
    query = next(arg.split('=', 1)[1] for arg in args if arg.startswith('query='))
    is_reply = 'addPullRequestReviewThreadReply' in query
    is_resolve = 'resolveReviewThread' in query
    if is_reply or is_resolve:
        reply_data = None
        resolve_data = None
        resolve_error = None
        if is_reply:
            state['reply_calls'] += 1
            reply_data = {{'comment': {{'url': 'https://example.test/reply'}}}}
        if is_resolve:
            state['resolve_attempts'] += 1
            if state['resolve_attempts'] > 1:
                state['resolved'] = True
            if not state['resolved']:
                resolve_error = 'temporary resolve failure'
            else:
                resolve_data = {{'thread': {{'id': 'THREAD_REPLY_RETRY', 'isResolved': True}}}}

        state_file.write_text(json.dumps(state), encoding='utf-8')
        if resolve_error:
            data = {{}}
            if reply_data:
                data['reply0'] = reply_data
                data['addPullRequestReviewThreadReply'] = reply_data
            print(json.dumps({{'data': data, 'errors': [{{'message': resolve_error}}]}}))
            raise SystemExit(1)

        data = {{}}
        if reply_data:
            data['reply0'] = reply_data
            data['addPullRequestReviewThreadReply'] = reply_data
        if resolve_data:
            data['resolve0'] = resolve_data
            data['resolveReviewThread'] = resolve_data
        print(json.dumps({{'data': data}}))
    else:
        print(json.dumps({{
            'data': {{
                'repository': {{
                    'pullRequest': {{
                        'reviewThreads': {{
                            'pageInfo': {{'hasNextPage': False, 'endCursor': None}},
                            'nodes': [{{
                                'id': 'THREAD_REPLY_RETRY',
                                'isResolved': state['resolved'],
                                'isOutdated': False,
                                'path': 'src/reply_retry.py',
                                'line': 5,
                                'firstComment': {{'nodes': [{{'url': 'https://example.test/thread/reply-retry', 'body': 'needs reply'}}]}},
                                'latestComment': {{'nodes': [{{'url': 'https://example.test/thread/reply-retry', 'body': 'needs reply'}}]}},
                            }}]
                        }}
                    }}
                }}
            }}
        }}))
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            """#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read())
item = payload["item"]
print(json.dumps({
    "resolution": "clarify",
    "note": f"Clarified {item['item_id']}.",
    "reply_markdown": "Reply once, then retry resolve only.",
    "validation_commands": []
}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        first = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "remote",
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(first.returncode, 0, first.stderr)

        state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(state["reply_calls"], 1)
        self.assertGreaterEqual(state["resolve_attempts"], 2)
        self.assertIn("cr-loop PASSED", first.stdout)

    def test_cr_loop_needs_human_after_repeated_validation_failure(self):
        findings_file = Path(self.temp_dir.name) / "findings.json"
        findings_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Loop local finding",
                        "body": "Needs a local fix.",
                        "path": "src/local.py",
                        "line": 7,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            ),
            encoding="utf-8",
        )
        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            """#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read())
item = payload["item"]
print(json.dumps({
    "resolution": "fix",
    "note": f"Attempted fix for {item['item_id']}.",
    "validation_commands": ["python3 -c \\"raise SystemExit(1)\\""]
}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "local",
                "json",
                "--input",
                str(findings_file),
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                "--max-iterations",
                "3",
                self.repo,
                self.pr,
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_HUMAN", result.stdout + result.stderr)

        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item = next(value for value in session["items"].values() if value["item_kind"] == "local_finding")
        self.assertTrue(item["needs_human"])
        self.assertEqual(session["loop_state"]["status"], "NEEDS_HUMAN")

    def test_cr_loop_sync_requires_explicit_source(self):
        findings_file = Path(self.temp_dir.name) / "findings.json"
        findings_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Scoped finding",
                        "body": "This should be namespaced to one producer.",
                        "path": "src/scoped.py",
                        "line": 2,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            ),
            encoding="utf-8",
        )
        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            """#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read())
print(json.dumps({
    "resolution": "fix",
    "note": "No-op.",
    "validation_commands": []
}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "local",
                "json",
                "--input",
                str(findings_file),
                "--sync",
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                self.repo,
                self.pr,
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --source", result.stderr)

    def test_cr_loop_local_code_review_uses_adapter_backed_intake(self):
        findings_file = Path(self.temp_dir.name) / "findings.json"
        findings_file.write_text(
            json.dumps(
                [
                    {
                        "check": "adapter-backed",
                        "description": "Imported through code-review adapter.",
                        "filename": "src/local_code_review.py",
                        "position": 9,
                        "severity": "P2",
                    }
                ]
            ),
            encoding="utf-8",
        )
        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            """#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read())
item = payload["item"]
print(json.dumps({
    "resolution": "fix",
    "note": f"Auto-fixed {item['item_id']}.",
    "validation_commands": []
}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "local",
                "code-review",
                "--input",
                str(findings_file),
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created 1 local item", result.stdout)
        self.assertIn("cr-loop PASSED", result.stdout)

    def test_cr_loop_validation_commands_are_not_executed_through_shell(self):
        findings_file = Path(self.temp_dir.name) / "findings.json"
        findings_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Shell validation",
                        "body": "Validation should be argv-based.",
                        "path": "src/validation.py",
                        "line": 5,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            ),
            encoding="utf-8",
        )
        bad_file = Path(self.temp_dir.name) / "validation-bad.txt"
        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            f"""#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read())
print(json.dumps({{
    "resolution": "fix",
    "note": "Try argv validation.",
    "validation_commands": ["python3 -c \\"import sys; sys.exit(0)\\" && python3 -c \\"from pathlib import Path; Path({str(bad_file)!r}).write_text('bad')\\""]
}}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "local",
                "json",
                "--input",
                str(findings_file),
                "--source",
                "local-agent:test",
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(bad_file.exists())
        self.assertIn("cr-loop PASSED", result.stdout)

    def test_handle_batch_blocks_when_batch_github_helper_fails(self):
        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}, clear=False):
            sys.path.insert(0, str(CR_LOOP_PY.parent))
            spec = importlib.util.spec_from_file_location("cr_loop_under_test", CR_LOOP_PY)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            try:
                spec.loader.exec_module(module)
            finally:
                sys.path.pop(0)

            init_result = self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
            self.assertEqual(init_result.returncode, 0, init_result.stderr)
            session = json.loads(self.session_file().read_text(encoding="utf-8"))
            thread_id = "THREAD_BATCH_FAIL"
            item_id = f"github-thread:{thread_id}"
            session["items"][item_id] = {
                "item_id": item_id,
                "item_kind": "github_thread",
                "source": "github",
                "origin_ref": thread_id,
                "path": "src/batch_fail.py",
                "line": 9,
                "title": "Batch helper failure",
                "body": "Needs reply and resolve.",
                "severity": "P2",
                "status": "OPEN",
                "decision": None,
                "blocking": True,
                "handled": False,
                "handled_at": None,
                "resolution_note": None,
                "published": True,
                "published_ref": "https://example.test/thread/batch-fail",
                "url": "https://example.test/thread/batch-fail",
                "first_url": "https://example.test/thread/batch-fail",
                "latest_url": "https://example.test/thread/batch-fail",
                "is_outdated": False,
                "scan_id": None,
                "introduced_in_sha": None,
                "last_seen_in_sha": None,
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "repeat_count": 0,
                "reopen_count": 0,
                "evidence": [],
                "history": [],
                "auto_attempt_count": 0,
                "last_auto_action": None,
                "last_auto_failure": None,
                "needs_human": False,
                "reply_posted": False,
                "reply_url": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
            self.session_file().write_text(json.dumps(session), encoding="utf-8")

        def fake_run_fixer(_cmd: str, _payload: dict):
            return (
                {
                    "resolution": "clarify",
                    "note": "Reply once and resolve once.",
                    "reply_markdown": "Batch helper should not swallow failures.",
                    "validation_commands": [],
                },
                "",
            )

        def fake_run_cmd(cmd, *, stdin=None):
            if Path(cmd[1]).name == "batch_github_execute.py":
                return subprocess.CompletedProcess(cmd, 1, "", "batch helper failed")
            if Path(cmd[1]).name == "session_engine.py" and cmd[2] == "update-items-batch":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            raise AssertionError(f"unexpected command: {cmd}")

            module.run_fixer = fake_run_fixer
            module.run_cmd = fake_run_cmd
            module.emit = lambda _result: None

            args = types.SimpleNamespace(
                fixer_cmd="fixer",
                validation_cmd=[],
                max_iterations=10,
            )

            status, error = module.handle_batch(
                args,
                self.repo,
                self.pr,
                [session["items"][item_id]],
                run_id="batch-failure",
                iteration=1,
            )

            self.assertEqual(status, "blocked")
            self.assertIn("batch helper failed", error)

            updated = json.loads(self.session_file().read_text(encoding="utf-8"))
            item = updated["items"][item_id]
            self.assertEqual(item["status"], "OPEN")
            self.assertFalse(item["handled"])
            self.assertFalse(item["reply_posted"])

    def test_cr_loop_does_not_mark_github_thread_needs_human_from_loop_warning_threshold(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_LOOP_THRESHOLD',
                            'isResolved': False,
                            'isOutdated': False,
                            'path': 'src/remote.py',
                            'line': 17,
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/loop-threshold', 'body': 'Remote thread still open.'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/loop-threshold', 'body': 'Remote thread still open.'}]},
                        }]
                    }
                }
            }
        }
    }))
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        gh_payload = json.dumps(
            [
                {
                    "id": "THREAD_LOOP_THRESHOLD",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/remote.py",
                    "line": 17,
                    "body": "Remote thread still open.",
                    "url": "https://example.test/thread/loop-threshold",
                }
            ]
        )
        self.run_cmd([sys.executable, str(SCRIPT), "sync-github", self.repo, self.pr], stdin=gh_payload, check=True)
        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item = session["items"]["github-thread:THREAD_LOOP_THRESHOLD"]
        item["repeat_count"] = 3
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = self.run_cmd([sys.executable, str(CR_LOOP_PY), "remote", self.repo, self.pr])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cr-loop PAUSED: Interaction Required", result.stdout + result.stderr)
        self.assertIn("INTERNAL_FIXER_REQUIRED", result.stdout + result.stderr)

        updated = json.loads(self.session_file().read_text(encoding="utf-8"))["items"]["github-thread:THREAD_LOOP_THRESHOLD"]
        self.assertFalse(updated["needs_human"])

    def test_cr_loop_mixed_code_review_requires_findings_json(self):
        fixer = Path(self.temp_dir.name) / "fixer.py"
        fixer.write_text(
            """#!/usr/bin/env python3
import json, sys
payload = json.loads(sys.stdin.read() or "{}")
print(json.dumps({
    "resolution": "clarify",
    "note": "No-op.",
    "reply_markdown": "No-op.",
    "validation_commands": []
}))
""",
            encoding="utf-8",
        )
        fixer.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "mixed",
                "code-review",
                "--fixer-cmd",
                f"{sys.executable} {fixer}",
                self.repo,
                self.pr,
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires findings JSON", result.stderr)

    def test_cr_loop_local_json_without_external_fixer_writes_internal_request_artifact(self):
        findings_file = Path(self.temp_dir.name) / "findings.json"
        findings_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Loop local finding",
                        "body": "Needs a local fix.",
                        "path": "src/internal.py",
                        "line": 13,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "local",
                "json",
                "--input",
                str(findings_file),
                self.repo,
                self.pr,
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cr-loop PAUSED: Interaction Required", result.stdout + result.stderr)
        self.assertIn("INTERNAL_FIXER_REQUIRED", result.stdout + result.stderr)

        artifacts = sorted(self.artifacts_dir().glob("loop-request-*.json"))
        self.assertEqual(len(artifacts), 1)
        payload = json.loads(artifacts[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["repo"], self.repo)
        self.assertEqual(payload["pr_number"], self.pr)
        self.assertEqual(payload["item"]["path"], "src/internal.py")

    def test_cr_loop_remote_without_external_fixer_passes_when_gate_is_clean(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]

if args[:2] == ['api', 'graphql']:
    print(json.dumps({{
        'data': {{
            'repository': {{
                'pullRequest': {{
                    'reviewThreads': {{
                        'pageInfo': {{'hasNextPage': False, 'endCursor': None}},
                        'nodes': []
                    }}
                }}
            }}
        }}
    }}))
elif args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'tester'}}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith(f'repos/{self.repo}/pulls/{self.pr}/reviews'):
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CR_LOOP_PY),
                "remote",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cr-loop PASSED", result.stdout)
