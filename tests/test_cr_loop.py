import json
import sys
from pathlib import Path

from tests.helpers import CR_LOOP_PY, PythonScriptTestCase


class CRLoopCLITest(PythonScriptTestCase):
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

        session_file = self.state_dir / "octo__example__pr77__session.json"
        session = json.loads(session_file.read_text(encoding="utf-8"))
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
    if 'resolveReviewThread' in query:
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
elif args[:2] == ['api', f'repos/{self.repo}/pulls/{self.pr}/reviews']:
    print('[]')
elif args[:3] == ['api', f'repos/{self.repo}/pulls/{self.pr}/reviews/1']:
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

        session_file = self.state_dir / "octo__example__pr77__session.json"
        session = json.loads(session_file.read_text(encoding="utf-8"))
        item = next(value for value in session["items"].values() if value["item_kind"] == "local_finding")
        self.assertTrue(item["needs_human"])
        self.assertEqual(session["loop_state"]["status"], "NEEDS_HUMAN")

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
