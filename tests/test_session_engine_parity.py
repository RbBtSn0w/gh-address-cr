import json

from tests.helpers import PythonScriptTestCase


class NativeSessionContractTest(PythonScriptTestCase):
    def test_native_session_shape_is_stable_after_public_findings_ingest(self):
        payload = json.dumps(
            [
                {
                    "title": "Contract finding",
                    "body": "The native session contract should be self-contained.",
                    "path": "src/contract.py",
                    "line": 7,
                    "severity": "P1",
                }
            ]
        )

        result = self.run_runtime_module(
            "findings",
            self.repo,
            self.pr,
            "--source",
            "local-agent:contract",
            "--scan-id",
            "scan-contract",
            "--handoff-sha256",
            "handoff-contract",
            "--input",
            "-",
            stdin=payload,
        )

        self.assertEqual(result.returncode, 5, result.stderr)
        session = self.load_session()
        self.assertEqual(session["schema_version"], 1)
        self.assertEqual(session["session_id"], f"{self.repo}#{self.pr}")
        self.assertEqual(session["current_scan_id"], "scan-contract")
        self.assertIn("loop_state", session)
        self.assertIn("metrics", session)
        self.assertIn("handoff", session)
        item = next(iter(session["items"].values()))
        self.assertEqual(item["source"], "local-agent:contract")
        self.assertEqual(item["severity"], "P1")
        self.assertEqual(item["severity_evidence"]["source"], "producer_payload")
