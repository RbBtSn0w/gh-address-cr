import json

from tests.helpers import PythonScriptTestCase


class NativeWorkflowReplacementTest(PythonScriptTestCase):
    def test_legacy_cr_loop_command_is_unsupported_without_session_mutation(self):
        result = self.run_runtime_module("cr-loop", "remote", self.repo, self.pr)

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsupported legacy command: cr-loop", result.stderr)
        self.assertFalse(self.session_file().exists())

    def test_native_review_with_findings_uses_public_waiting_for_fix_contract(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['auth', 'status']:
    raise SystemExit(0)
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
    raise SystemExit(0)
raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        payload = json.dumps(
            [
                {
                    "title": "Native review finding",
                    "body": "The native review path should own local item state.",
                    "path": "src/native_review.py",
                    "line": 4,
                    "severity": "P2",
                }
            ]
        )

        result = self.run_runtime_module("review", self.repo, self.pr, "--input", "-", stdin=payload)

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "WAITING_FOR_FIX")
        self.assertEqual(summary["waiting_on"], "human_fix")
        session = self.load_session()
        item = next(iter(session["items"].values()))
        self.assertEqual(item["item_kind"], "local_finding")
        self.assertTrue(item["blocking"])
