import json
import sys



from pathlib import Path
from tests.helpers import (
    CLI_PY,
    PythonScriptTestCase,
)

class TestSubmitAction(PythonScriptTestCase):
    def test_submit_action_help(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "submit-action", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: cli.py submit-action", result.stdout)
        self.assertIn("High-level manual action entrypoint.", result.stdout)

    def test_submit_action_workflow(self):
        # 1. Create a dummy loop-request JSON
        tmp_dir = Path(self.temp_dir.name)
        loop_req_path = tmp_dir / "loop-request.json"
        loop_req = {
            "repo": "owner/repo",
            "pr_number": "123",
            "item": {
                "item_id": "test-item:1",
                "item_kind": "local_finding"
            }
        }
        loop_req_path.write_text(json.dumps(loop_req), encoding="utf-8")

        # 2. Run submit-action
        result = self.run_cmd([
            sys.executable, str(CLI_PY), "submit-action",
            "--resolution", "fix",
            "--note", "Fixed it",
            str(loop_req_path)
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Action 'fix' formulated", result.stdout)

        # 3. Verify files created
        payload_path = tmp_dir / "fixer-payload-test-item_1.json"
        script_path = tmp_dir / "fixer-test-item_1.sh"
        self.assertTrue(payload_path.is_file())
        self.assertTrue(script_path.is_file())

        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["resolution"], "fix")
        self.assertEqual(payload["note"], "Fixed it")

        # 4. Test resume branch (mock)
        # We'll use a simple echo as the resume command
        result = self.run_cmd([
            sys.executable, str(CLI_PY), "submit-action",
            "--resolution", "clarify",
            "--note", "Explained",
            str(loop_req_path),
            "--", sys.executable, "-c", "import sys; print(sys.argv)"
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Resuming loop", result.stdout)
        # Check that --fixer-cmd was appended
        self.assertIn("--fixer-cmd", result.stdout)
        self.assertIn("fixer-test-item_1.sh", result.stdout)

    def test_submit_action_validation_github_thread(self):
        tmp_dir = Path(self.temp_dir.name)
        loop_req_path = tmp_dir / "loop-request-gh.json"
        loop_req = {
            "repo": "owner/repo",
            "pr_number": "123",
            "item": {
                "item_id": "github-thread:1",
                "item_kind": "github_thread"
            }
        }
        loop_req_path.write_text(json.dumps(loop_req), encoding="utf-8")

        # Fix requires commit_hash/files
        result = self.run_cmd([
            sys.executable, str(CLI_PY), "submit-action",
            "--resolution", "fix",
            "--note", "fixed",
            str(loop_req_path)
        ])
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --commit-hash and --files", result.stderr)

        # Success with details
        result = self.run_cmd([
            sys.executable, str(CLI_PY), "submit-action",
            "--resolution", "fix",
            "--note", "fixed",
            "--commit-hash", "abc",
            "--files", "file.py",
            str(loop_req_path)
        ])
        self.assertEqual(result.returncode, 0)
