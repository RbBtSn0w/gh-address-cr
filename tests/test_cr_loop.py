import json
import sys
from pathlib import Path

from tests.helpers import CR_LOOP_PY, PythonScriptTestCase, SCRIPT


class CRLoopCLITest(PythonScriptTestCase):
    def artifacts_dir(self) -> Path:
        return super().artifacts_dir()

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
    if 'addPullRequestReviewThreadReply' in query:
        state['reply_calls'] += 1
        state_file.write_text(json.dumps(state), encoding='utf-8')
        print(json.dumps({{'data': {{'addPullRequestReviewThreadReply': {{'comment': {{'url': 'https://example.test/reply'}}}}}}}}))
    elif 'resolveReviewThread' in query:
        state['resolve_attempts'] += 1
        if state['resolve_attempts'] > 1:
            state['resolved'] = True
        state_file.write_text(json.dumps(state), encoding='utf-8')
        if not state['resolved']:
            print(json.dumps({{'errors': [{{'message': 'temporary resolve failure'}}]}}))
            raise SystemExit(1)
        print(json.dumps({{'data': {{'resolveReviewThread': {{'thread': {{'id': 'THREAD_REPLY_RETRY', 'isResolved': True}}}}}}}}))
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
        self.assertNotEqual(first.returncode, 0, first.stderr)

        second = self.run_cmd(
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
        self.assertEqual(second.returncode, 0, second.stderr)
        state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(state["reply_calls"], 1)
        self.assertEqual(state["resolve_attempts"], 2)
        self.assertIn("cr-loop PASSED", second.stdout)

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
elif args[:2] == ['api', f'repos/{self.repo}/pulls/{self.pr}/reviews']:
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
