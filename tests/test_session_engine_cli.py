import json

from tests.helpers import PythonScriptTestCase


class NativeSessionCLITest(PythonScriptTestCase):
    def test_findings_command_creates_native_session_and_local_item(self):
        payload = json.dumps(
            [
                {
                    "title": "Native session item",
                    "body": "Ensure public findings ingestion owns session mutation.",
                    "path": "src/native_session.py",
                    "line": 12,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )

        result = self.run_runtime_module(
            "findings",
            self.repo,
            self.pr,
            "--source",
            "local-agent:native",
            "--input",
            "-",
            stdin=payload,
        )

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "WAITING_FOR_FIX")

        session = self.load_session()
        self.assertEqual(session["repo"], self.repo)
        self.assertEqual(session["pr_number"], self.pr)
        item = next(iter(session["items"].values()))
        self.assertEqual(item["item_kind"], "local_finding")
        self.assertEqual(item["title"], "Native session item")
        self.assertEqual(item["status"], "OPEN")
        self.assertTrue(item["blocking"])
        self.assertEqual(session["metrics"]["blocking_items_count"], 1)

    def test_findings_sync_closes_missing_source_scoped_items(self):
        first_payload = json.dumps(
            [
                {
                    "title": "First finding",
                    "body": "Will be absent from the next scan.",
                    "path": "src/first.py",
                    "line": 1,
                }
            ]
        )
        second_payload = json.dumps(
            [
                {
                    "title": "Second finding",
                    "body": "Still present in the producer output.",
                    "path": "src/second.py",
                    "line": 2,
                }
            ]
        )

        first = self.run_runtime_module(
            "findings",
            self.repo,
            self.pr,
            "--source",
            "local-agent:native-sync",
            "--input",
            "-",
            stdin=first_payload,
        )
        second = self.run_runtime_module(
            "findings",
            self.repo,
            self.pr,
            "--source",
            "local-agent:native-sync",
            "--sync",
            "--input",
            "-",
            stdin=second_payload,
        )

        self.assertEqual(first.returncode, 5, first.stderr)
        self.assertEqual(second.returncode, 5, second.stderr)
        session = self.load_session()
        first_item = next(item for item in session["items"].values() if item["path"] == "src/first.py")
        second_item = next(item for item in session["items"].values() if item["path"] == "src/second.py")
        self.assertEqual(first_item["status"], "CLOSED")
        self.assertFalse(first_item["blocking"])
        self.assertEqual(second_item["status"], "OPEN")
        self.assertTrue(second_item["blocking"])
