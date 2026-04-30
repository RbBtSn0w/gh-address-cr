import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gh_address_cr.core.models import ActionRequest

from tests.helpers import PythonScriptTestCase


NOW = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)


def load_multi_agent_session():
    path = Path(__file__).parent / "fixtures" / "thin_skill_orchestration" / "multi_agent_session.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def open_item(item_id="local-finding:1", **overrides):
    payload = {
        "item_id": item_id,
        "item_kind": "local_finding",
        "source": "json",
        "title": "Missing validation",
        "body": "Validate the input before use.",
        "path": "src/example.py",
        "line": 42,
        "state": "open",
        "blocking": True,
        "allowed_actions": ["fix", "clarify", "defer", "reject"],
    }
    payload.update(overrides)
    return payload


class ControlPlaneWorkflowCLITest(PythonScriptTestCase):
    def write_session(self, *, items, leases=None):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_77",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": leases or {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))

    def ledger_rows(self):
        ledger = self.workspace_dir() / "evidence.jsonl"
        if not ledger.exists():
            return []
        return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]

    def test_adapter_check_runtime_reports_compatible_runtime(self):
        result = self.run_runtime_module("adapter", "check-runtime")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "compatible")
        self.assertEqual(payload["runtime_package"], "gh-address-cr")
        self.assertIn("1.0", payload["supported_protocol_versions"])

    def test_agent_next_rejects_fixer_without_classification_before_lease(self):
        self.write_session(items=[open_item()])

        result = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer")

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "REQUEST_REJECTED")
        self.assertEqual(payload["reason_code"], "MISSING_CLASSIFICATION")
        session = self.load_session()
        self.assertEqual(session["leases"], {})
        self.assertEqual(session["items"]["local-finding:1"]["state"], "open")
        self.assertIn("request_rejected", [row["event_type"] for row in self.ledger_rows()])

    def test_agent_classify_records_evidence_and_allows_fixer_lease(self):
        self.write_session(items=[open_item()])

        classified = self.run_runtime_module(
            "agent",
            "classify",
            self.repo,
            self.pr,
            "local-finding:1",
            "--classification",
            "fix",
            "--agent-id",
            "triage-1",
            "--note",
            "Real defect.",
        )
        requested = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer")

        self.assertEqual(classified.returncode, 0, classified.stderr)
        self.assertEqual(json.loads(classified.stdout)["status"], "CLASSIFICATION_RECORDED")
        self.assertEqual(requested.returncode, 0, requested.stderr)
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["classification_evidence"]["classification"], "fix")
        self.assertIn("classification_recorded", [row["event_type"] for row in self.ledger_rows()])

    def test_agent_next_issues_request_and_claim_lease_for_classified_item(self):
        self.write_session(
            items=[
                open_item(
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified",
                    }
                )
            ]
        )

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1", "--now", NOW.isoformat()
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTION_REQUESTED")
        self.assertEqual(payload["item_id"], "local-finding:1")
        self.assertTrue(payload["resume_token"].startswith("resume:"))
        request_path = payload["request_path"]
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        self.assertEqual(request["lease_id"], payload["lease_id"])
        self.assertEqual(request["agent_role"], "fixer")
        self.assertIn("post_github_reply", request["forbidden_actions"])
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["state"], "claimed")
        self.assertEqual(session["leases"][payload["lease_id"]]["status"], "active")
        self.assertEqual(session["leases"][payload["lease_id"]]["request_id"], request["request_id"])
        self.assertEqual(
            session["leases"][payload["lease_id"]]["request_hash"], ActionRequest.from_dict(request).stable_hash()
        )

    def test_agent_submit_accepts_fix_response_with_active_lease(self):
        self.write_session(
            items=[
                open_item(
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified",
                    }
                )
            ]
        )
        issued = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1"
        )
        self.assertEqual(issued.returncode, 0, issued.stderr)
        issued_payload = json.loads(issued.stdout)
        request = json.loads(Path(issued_payload["request_path"]).read_text(encoding="utf-8"))
        response_path = self.workspace_dir() / "action-response.json"
        response_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": request["request_id"],
                    "lease_id": request["lease_id"],
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "note": "Fixed validation.",
                    "files": ["src/example.py"],
                    "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit", self.repo, self.pr, "--input", str(response_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTION_ACCEPTED")
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["state"], "fixed")
        self.assertEqual(session["items"]["local-finding:1"]["status"], "CLOSED")
        self.assertFalse(session["items"]["local-finding:1"]["blocking"])
        self.assertTrue(session["items"]["local-finding:1"]["handled"])
        self.assertEqual(session["leases"][request["lease_id"]]["status"], "accepted")
        self.assertIn("response_accepted", [row["event_type"] for row in self.ledger_rows()])

    def test_agent_submit_rejects_response_with_stale_request_id(self):
        self.write_session(
            items=[
                open_item(
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified",
                    }
                )
            ]
        )
        issued = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1"
        )
        self.assertEqual(issued.returncode, 0, issued.stderr)
        issued_payload = json.loads(issued.stdout)
        request = json.loads(Path(issued_payload["request_path"]).read_text(encoding="utf-8"))
        response_path = self.workspace_dir() / "stale-action-response.json"
        response_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": "req_stale_or_fabricated",
                    "lease_id": request["lease_id"],
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "note": "This response belongs to a different request.",
                    "files": ["src/example.py"],
                    "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit", self.repo, self.pr, "--input", str(response_path))

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTION_REJECTED")
        self.assertEqual(payload["reason_code"], "STALE_REQUEST_CONTEXT")
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["state"], "claimed")
        self.assertEqual(session["leases"][request["lease_id"]]["status"], "active")
        self.assertIn("response_rejected", [row["event_type"] for row in self.ledger_rows()])

    def test_agent_submit_moves_github_thread_fix_to_publish_ready_without_side_effects(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified",
                    },
                    thread_id="PRRT_abc",
                )
            ]
        )
        issued = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1"
        )
        self.assertEqual(issued.returncode, 0, issued.stderr)
        issued_payload = json.loads(issued.stdout)
        request = json.loads(Path(issued_payload["request_path"]).read_text(encoding="utf-8"))
        response_path = self.workspace_dir() / "github-thread-response.json"
        response_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": request["request_id"],
                    "lease_id": request["lease_id"],
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "note": "Fixed thread issue.",
                    "files": ["src/example.py"],
                    "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                    "fix_reply": {
                        "summary": "Fixed thread issue.",
                        "commit_hash": "abc123",
                        "files": ["src/example.py"],
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit", self.repo, self.pr, "--input", str(response_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["next_action"],
            f"Run `gh-address-cr agent publish {self.repo} {self.pr}` to publish accepted evidence.",
        )
        session = self.load_session()
        item = session["items"]["github-thread:abc"]
        self.assertEqual(item["state"], "publish_ready")
        self.assertTrue(item["blocking"])
        self.assertEqual(item["publish_resolution"], "fix")
        self.assertNotIn("side_effect_attempt", [row["event_type"] for row in self.ledger_rows()])

    def test_agent_submit_batch_accepts_common_evidence_for_github_threads(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/example_one.py",
                    line=10,
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified_1",
                    },
                    thread_id="PRRT_abc",
                ),
                open_item(
                    "github-thread:def",
                    item_kind="github_thread",
                    source="github",
                    path="src/example_two.py",
                    line=20,
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified_2",
                    },
                    thread_id="PRRT_def",
                ),
            ]
        )
        first = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        second = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_request = json.loads(Path(json.loads(first.stdout)["request_path"]).read_text(encoding="utf-8"))
        second_request = json.loads(Path(json.loads(second.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "batch-action-response.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/example_one.py", "src/example_two.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_examples", "result": "passed"}
                        ],
                        "fix_reply": {
                            "commit_hash": "abc123",
                            "test_command": "python3 -m unittest tests.test_examples",
                            "test_result": "passed",
                        },
                    },
                    "items": [
                        {
                            "request_id": first_request["request_id"],
                            "lease_id": first_request["lease_id"],
                            "item_id": "github-thread:abc",
                            "summary": "Fixed first thread.",
                            "why": "The first thread now validates the input before use.",
                        },
                        {
                            "request_id": second_request["request_id"],
                            "lease_id": second_request["lease_id"],
                            "item_id": "github-thread:def",
                            "summary": "Fixed second thread.",
                            "why": "The second thread now shares the same guarded path.",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit-batch", self.repo, self.pr, "--input", str(batch_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "BATCH_ACTION_ACCEPTED")
        self.assertEqual(payload["accepted_count"], 2)
        self.assertEqual(
            payload["next_action"],
            f"Run `gh-address-cr agent publish {self.repo} {self.pr}` to publish accepted evidence.",
        )
        session = self.load_session()
        first_item = session["items"]["github-thread:abc"]
        second_item = session["items"]["github-thread:def"]
        self.assertEqual(first_item["state"], "publish_ready")
        self.assertEqual(second_item["state"], "publish_ready")
        self.assertEqual(first_item["accepted_response"]["fix_reply"]["commit_hash"], "abc123")
        self.assertEqual(second_item["accepted_response"]["fix_reply"]["commit_hash"], "abc123")
        self.assertEqual(
            first_item["accepted_response"]["fix_reply"]["why"],
            "The first thread now validates the input before use.",
        )
        self.assertEqual(
            second_item["accepted_response"]["fix_reply"]["why"],
            "The second thread now shares the same guarded path.",
        )
        self.assertEqual(session["leases"][first_request["lease_id"]]["status"], "accepted")
        self.assertEqual(session["leases"][second_request["lease_id"]]["status"], "accepted")
        self.assertEqual([row["event_type"] for row in self.ledger_rows()].count("response_accepted"), 2)

    def test_agent_submit_batch_rejects_local_findings_without_mutation(self):
        self.write_session(
            items=[
                open_item(
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified",
                    }
                )
            ]
        )
        issued = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1"
        )
        self.assertEqual(issued.returncode, 0, issued.stderr)
        request = json.loads(Path(json.loads(issued.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "local-batch-action-response.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/example.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_example", "result": "passed"}
                        ],
                        "fix_reply": {"commit_hash": "abc123"},
                    },
                    "items": [
                        {
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "item_id": "local-finding:1",
                            "summary": "Fixed validation.",
                            "why": "The input is now validated.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit-batch", self.repo, self.pr, "--input", str(batch_path))

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "BATCH_ACTION_REJECTED")
        self.assertEqual(payload["reason_code"], "BATCH_UNSUPPORTED_ITEM_KIND")
        self.assertEqual(payload["waiting_on"], "batch_action_response")
        self.assertIn("BatchActionResponse rejected", payload["next_action"])
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["state"], "claimed")
        self.assertEqual(session["leases"][request["lease_id"]]["status"], "active")
        self.assertIn("response_rejected", [row["event_type"] for row in self.ledger_rows()])

    def test_agent_submit_batch_missing_file_reports_batch_waiting_on(self):
        self.write_session(items=[])
        missing_path = self.workspace_dir() / "missing-batch-action-response.json"

        result = self.run_runtime_module("agent", "submit-batch", self.repo, self.pr, "--input", str(missing_path))

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "BATCH_ACTION_REJECTED")
        self.assertEqual(payload["reason_code"], "BATCH_RESPONSE_FILE_NOT_FOUND")
        self.assertEqual(payload["waiting_on"], "batch_action_response")
        self.assertIn("BatchActionResponse file does not exist", payload["next_action"])

    def test_agent_submit_batch_rejects_expired_later_lease_without_partial_acceptance(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/example_one.py",
                    line=10,
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified_1",
                    },
                    thread_id="PRRT_abc",
                ),
                open_item(
                    "github-thread:def",
                    item_kind="github_thread",
                    source="github",
                    path="src/example_two.py",
                    line=20,
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified_2",
                    },
                    thread_id="PRRT_def",
                ),
            ]
        )
        first = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1", "--now", NOW.isoformat()
        )
        second = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1", "--now", NOW.isoformat()
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_request = json.loads(Path(json.loads(first.stdout)["request_path"]).read_text(encoding="utf-8"))
        second_request = json.loads(Path(json.loads(second.stdout)["request_path"]).read_text(encoding="utf-8"))
        session = self.load_session()
        session["leases"][second_request["lease_id"]]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")
        batch_path = self.workspace_dir() / "expired-batch-action-response.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/example_one.py", "src/example_two.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_examples", "result": "passed"}
                        ],
                        "fix_reply": {
                            "commit_hash": "abc123",
                            "test_command": "python3 -m unittest tests.test_examples",
                            "test_result": "passed",
                        },
                    },
                    "items": [
                        {
                            "request_id": first_request["request_id"],
                            "lease_id": first_request["lease_id"],
                            "item_id": "github-thread:abc",
                            "summary": "Fixed first thread.",
                            "why": "The first thread now validates the input before use.",
                        },
                        {
                            "request_id": second_request["request_id"],
                            "lease_id": second_request["lease_id"],
                            "item_id": "github-thread:def",
                            "summary": "Fixed second thread.",
                            "why": "The second thread now shares the same guarded path.",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module(
            "agent", "submit-batch", self.repo, self.pr, "--input", str(batch_path), "--now", NOW.isoformat()
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "BATCH_ACTION_REJECTED")
        self.assertEqual(payload["reason_code"], "EXPIRED_LEASE")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "claimed")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "claimed")
        self.assertEqual(session["leases"][first_request["lease_id"]]["status"], "active")
        self.assertEqual(session["leases"][second_request["lease_id"]]["status"], "active")
        event_types = [row["event_type"] for row in self.ledger_rows()]
        self.assertNotIn("response_accepted", event_types)
        self.assertIn("response_rejected", event_types)

    def test_agent_publish_reports_no_work_when_no_thread_is_publish_ready(self):
        self.write_session(items=[open_item()])

        result = self.run_runtime_module("agent", "publish", self.repo, self.pr)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "NO_PUBLISH_READY_ITEMS")
        self.assertEqual(payload["published_count"], 0)

    def test_agent_submit_verifier_rejection_reopens_item_without_side_effects(self):
        self.write_session(
            items=[
                open_item(
                    state="fixed",
                    blocking=False,
                    validation_evidence=[{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                )
            ],
            leases={
                "lease-verifier": {
                    "lease_id": "lease-verifier",
                    "item_id": "local-finding:1",
                    "agent_id": "verifier-1",
                    "role": "verifier",
                    "status": "active",
                    "created_at": NOW.isoformat(),
                    "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                    "resume_token": None,
                    "request_hash": "verify-req",
                    "conflict_keys": ["item:local-finding:1"],
                }
            },
        )
        response_path = self.workspace_dir() / "verification-response.json"
        response_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": "verify-req",
                    "lease_id": "lease-verifier",
                    "agent_id": "verifier-1",
                    "resolution": "reject",
                    "note": "The supplied validation does not cover the changed path.",
                    "reply_markdown": "Please add coverage for the changed path.",
                    "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "failed"}],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module(
            "agent", "submit", self.repo, self.pr, "--input", str(response_path), "--now", NOW.isoformat()
        )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["status"], "VERIFICATION_REJECTED")
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["state"], "open")
        self.assertTrue(session["items"]["local-finding:1"]["blocking"])
        event_types = [row["event_type"] for row in self.ledger_rows()]
        self.assertIn("verification_rejected", event_types)
        self.assertNotIn("side_effect_attempt", event_types)

    def test_agent_leases_lists_and_reclaim_expires_stale_leases(self):
        self.write_session(
            items=[open_item()],
            leases={
                "lease-stale": {
                    "lease_id": "lease-stale",
                    "item_id": "local-finding:1",
                    "agent_id": "codex-old",
                    "role": "fixer",
                    "status": "active",
                    "created_at": (NOW - timedelta(hours=2)).isoformat(),
                    "expires_at": (NOW - timedelta(hours=1)).isoformat(),
                    "resume_token": None,
                    "request_hash": "req-old",
                    "conflict_keys": ["item:local-finding:1", "file:src/example.py"],
                }
            },
        )

        listed = self.run_runtime_module("agent", "leases", self.repo, self.pr)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)["leases"][0]["lease_id"], "lease-stale")

        reclaimed = self.run_runtime_module("agent", "reclaim", self.repo, self.pr, "--now", NOW.isoformat())
        self.assertEqual(reclaimed.returncode, 0, reclaimed.stderr)
        payload = json.loads(reclaimed.stdout)
        self.assertEqual(payload["status"], "LEASES_RECLAIMED")
        self.assertEqual(payload["expired_count"], 1)
        session = self.load_session()
        self.assertEqual(session["leases"]["lease-stale"]["status"], "expired")
