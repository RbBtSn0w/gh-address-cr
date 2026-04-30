import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.helpers import PythonScriptTestCase, ROOT, SRC_ROOT


HELPER_SCRIPTS = (
    ROOT / "skill" / "scripts" / "submit_action.py",
    SRC_ROOT / "gh_address_cr" / "legacy_scripts" / "submit_action.py",
)


def runtime_request(**overrides):
    payload = {
        "schema_version": "1.0",
        "request_id": "req_123",
        "session_id": "session_123",
        "lease_id": "lease_123",
        "agent_role": "fixer",
        "item": {
            "item_id": "github-thread:abc",
            "item_kind": "github_thread",
            "title": "Example thread",
            "body": "Please fix this.",
            "state": "claimed",
        },
        "allowed_actions": ["fix", "clarify", "defer", "reject"],
        "required_evidence": ["note", "files", "validation_commands", "fix_reply"],
        "repository_context": {"repo": "octo/example", "pr_number": "77"},
        "forbidden_actions": ["post_github_reply", "resolve_github_thread"],
        "resume_command": "gh-address-cr agent submit octo/example 77 --input response.json",
    }
    payload.update(overrides)
    return payload


class SubmitActionHelperTest(PythonScriptTestCase):
    def write_request(self, name, payload):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        path = self.workspace_dir() / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def run_helper(self, script: Path, *args):
        return subprocess.run(
            [sys.executable, str(script), *args],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=self.env,
        )

    def test_runtime_action_request_repository_context_generates_action_response(self):
        for script in HELPER_SCRIPTS:
            with self.subTest(script=script):
                request_path = self.write_request("action-request.json", runtime_request())

                result = self.run_helper(
                    script,
                    str(request_path),
                    "--agent-id",
                    "codex-1",
                    "--resolution",
                    "fix",
                    "--note",
                    "Fixed the thread.",
                    "--commit-hash",
                    "abc123",
                    "--files",
                    "src/example.py",
                    "--why",
                    "The guarded path now handles this case.",
                    "--test-command",
                    "python3 -m unittest tests.test_example",
                    "--test-result",
                    "passed",
                    "--validation-cmd",
                    "python3 -m unittest tests.test_example=passed",
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                response_path = self.workspace_dir() / "action-response-github-thread_abc.json"
                response = json.loads(response_path.read_text(encoding="utf-8"))
                self.assertEqual(response["request_id"], "req_123")
                self.assertEqual(response["lease_id"], "lease_123")
                self.assertEqual(response["agent_id"], "codex-1")
                self.assertEqual(response["resolution"], "fix")
                self.assertEqual(response["files"], ["src/example.py"])
                self.assertEqual(
                    response["validation_commands"],
                    [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                )
                self.assertEqual(response["fix_reply"]["commit_hash"], "abc123")
                self.assertIn("gh-address-cr agent submit octo/example 77 --input", result.stdout)

    def test_runtime_action_request_reject_generates_reply_response(self):
        for script in HELPER_SCRIPTS:
            with self.subTest(script=script):
                request_path = self.write_request(
                    "reject-action-request.json",
                    runtime_request(
                        item={
                            "item_id": "local-finding:abc",
                            "item_kind": "local_finding",
                            "title": "Not a defect",
                            "body": "The suggested change would break compatibility.",
                            "state": "claimed",
                        },
                        required_evidence=["note", "reply_markdown", "validation_commands"],
                    ),
                )

                result = self.run_helper(
                    script,
                    str(request_path),
                    "--agent-id",
                    "codex-1",
                    "--resolution",
                    "reject",
                    "--note",
                    "Rejected because the current behavior is intentional.",
                    "--reply-markdown",
                    "The current behavior is intentional and covered by the compatibility contract.",
                    "--validation-cmd",
                    "python3 -m unittest tests.test_example=passed",
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                response_path = self.workspace_dir() / "action-response-local-finding_abc.json"
                response = json.loads(response_path.read_text(encoding="utf-8"))
                self.assertEqual(response["resolution"], "reject")
                self.assertEqual(response["agent_id"], "codex-1")
                self.assertEqual(
                    response["reply_markdown"],
                    "The current behavior is intentional and covered by the compatibility contract.",
                )
                self.assertEqual(
                    response["validation_commands"],
                    [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                )

    def test_runtime_resume_command_replaces_placeholder_input_path(self):
        for script in HELPER_SCRIPTS:
            with self.subTest(script=script):
                request_path = self.write_request("resume-action-request.json", runtime_request())
                verifier = (
                    "import json, pathlib, sys; "
                    "input_path = pathlib.Path(sys.argv[sys.argv.index('--input') + 1]); "
                    "assert input_path.name == 'action-response-github-thread_abc.json', input_path; "
                    "payload = json.loads(input_path.read_text(encoding='utf-8')); "
                    "assert payload['request_id'] == 'req_123'"
                )

                result = self.run_helper(
                    script,
                    str(request_path),
                    "--agent-id",
                    "codex-1",
                    "--resolution",
                    "fix",
                    "--note",
                    "Fixed the thread.",
                    "--commit-hash",
                    "abc123",
                    "--files",
                    "src/example.py",
                    "--validation-cmd",
                    "python3 -m unittest tests.test_example=passed",
                    "--",
                    sys.executable,
                    "-c",
                    verifier,
                    "agent",
                    "submit",
                    "octo/example",
                    "77",
                    "--input",
                    "response.json",
                )

                self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_top_level_loop_request_still_generates_loop_action_payload(self):
        for script in HELPER_SCRIPTS:
            with self.subTest(script=script):
                request_path = self.write_request(
                    "loop-request.json",
                    {
                        "repo": "octo/example",
                        "pr_number": "77",
                        "item": {"item_id": "local-finding:abc", "item_kind": "local_finding"},
                    },
                )

                result = self.run_helper(
                    script,
                    str(request_path),
                    "--resolution",
                    "fix",
                    "--note",
                    "Fixed local finding.",
                    "--files",
                    "src/example.py",
                    "--validation-cmd",
                    "python3 -m unittest tests.test_example",
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                payload_path = self.workspace_dir() / "fixer-payload-local-finding_abc.json"
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                self.assertNotIn("request_id", payload)
                self.assertEqual(payload["resolution"], "fix")
                self.assertEqual(payload["note"], "Fixed local finding.")

    def test_runtime_action_request_missing_repository_context_fails_loudly_without_artifact(self):
        for script in HELPER_SCRIPTS:
            with self.subTest(script=script):
                request = runtime_request(repository_context={})
                request_path = self.write_request("missing-repository-context.json", request)

                result = self.run_helper(script, str(request_path), "--resolution", "fix", "--note", "Fixed.")

                self.assertEqual(result.returncode, 2)
                self.assertIn("repository_context.repo", result.stderr)
                self.assertFalse((self.workspace_dir() / "action-response-github-thread_abc.json").exists())

    def test_runtime_action_request_missing_identity_fails_loudly_without_artifact(self):
        for script in HELPER_SCRIPTS:
            with self.subTest(script=script):
                request = runtime_request()
                request.pop("request_id")
                request_path = self.write_request("missing-request-id.json", request)

                result = self.run_helper(script, str(request_path), "--resolution", "fix", "--note", "Fixed.")

                self.assertEqual(result.returncode, 2)
                self.assertIn("request_id", result.stderr)
                self.assertFalse((self.workspace_dir() / "action-response-github-thread_abc.json").exists())


if __name__ == "__main__":
    unittest.main()
