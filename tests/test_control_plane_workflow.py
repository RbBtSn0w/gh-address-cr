import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from gh_address_cr import cli
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


def github_thread(item_id: str, *, path: str = "src/shared.py", body: str = "Please fix this.", **overrides):
    return open_item(
        item_id,
        item_kind="github_thread",
        source="github",
        path=path,
        body=body,
        thread_id=item_id.removeprefix("github-thread:"),
        **overrides,
    )


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
        self.assertIn("triage classification", payload["next_action"])
        self.assertIn("gh-address-cr agent classify", payload["next_action"])
        self.assertNotIn("scripts/cli.py", payload["next_action"])
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

    def test_agent_next_restores_recorded_decision_as_classification_evidence(self):
        self.write_session(items=[open_item("github-thread:abc", item_kind="github_thread", decision="fix")])

        requested = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer")

        self.assertEqual(requested.returncode, 0, requested.stderr)
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["classification_evidence"]["classification"], "fix")

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
        skeleton_path = payload["response_skeleton_path"]
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        skeleton = json.loads(Path(skeleton_path).read_text(encoding="utf-8"))
        self.assertEqual(request["lease_id"], payload["lease_id"])
        self.assertEqual(request["agent_role"], "fixer")
        self.assertEqual(request["response_skeleton_path"], skeleton_path)
        self.assertEqual(skeleton["request_id"], request["request_id"])
        self.assertEqual(skeleton["lease_id"], request["lease_id"])
        self.assertEqual(skeleton["agent_id"], "codex-1")
        self.assertEqual(skeleton["validation_commands"][0]["command"], "")
        self.assertIn("post_github_reply", request["forbidden_actions"])
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["state"], "claimed")
        self.assertEqual(session["leases"][payload["lease_id"]]["status"], "active")
        self.assertEqual(session["leases"][payload["lease_id"]]["request_id"], request["request_id"])
        self.assertEqual(
            session["leases"][payload["lease_id"]]["request_hash"], ActionRequest.from_dict(request).stable_hash()
        )

    def test_agent_next_response_skeleton_matches_non_fixer_role_shape(self):
        self.write_session(items=[open_item("github-thread:abc", item_kind="github_thread", source="github")])

        result = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "triage", "--agent-id", "triage-1")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        request = json.loads(Path(payload["request_path"]).read_text(encoding="utf-8"))
        skeleton = json.loads(Path(payload["response_skeleton_path"]).read_text(encoding="utf-8"))
        self.assertEqual(request["required_evidence"], ["note", "reply_markdown"])
        self.assertEqual(skeleton["resolution"], "<fix|clarify|defer|reject>")
        self.assertIn("reply_markdown", skeleton)
        self.assertNotIn("validation_commands", skeleton)
        self.assertNotIn("fix_reply", skeleton)
        self.assertNotIn("files", skeleton)

    def test_agent_next_fixer_for_clarify_classification_requires_reply_markdown(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    classification_evidence={"classification": "clarify", "record_id": "ev_classified"},
                    thread_id="PRRT_abc",
                )
            ]
        )

        result = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        request = json.loads(Path(payload["request_path"]).read_text(encoding="utf-8"))
        skeleton = json.loads(Path(payload["response_skeleton_path"]).read_text(encoding="utf-8"))
        self.assertEqual(request["required_evidence"], ["note", "reply_markdown"])
        self.assertEqual(skeleton["resolution"], "clarify")
        self.assertIn("reply_markdown", skeleton)
        self.assertNotIn("validation_commands", skeleton)
        self.assertNotIn("fix_reply", skeleton)
        self.assertNotIn("files", skeleton)

    def test_agent_next_response_skeleton_for_github_fix_uses_empty_required_fields(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    classification_evidence={"classification": "fix", "record_id": "ev_classified"},
                    thread_id="PRRT_abc",
                )
            ]
        )

        result = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        skeleton = json.loads(Path(payload["response_skeleton_path"]).read_text(encoding="utf-8"))
        self.assertEqual(skeleton["files"], [])
        self.assertEqual(skeleton["validation_commands"], [{"command": "", "result": ""}])
        self.assertEqual(skeleton["fix_reply"]["commit_hash"], "")
        self.assertEqual(skeleton["fix_reply"]["files"], [])
        self.assertNotIn("evidence_ref", skeleton)

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

    def test_agent_submit_accepts_clarify_response_without_validation_commands(self):
        self.write_session(items=[open_item()])
        issued = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "triage", "--agent-id", "triage-1"
        )
        self.assertEqual(issued.returncode, 0, issued.stderr)
        request = json.loads(Path(json.loads(issued.stdout)["request_path"]).read_text(encoding="utf-8"))
        response_path = self.workspace_dir() / "clarify-action-response.json"
        response_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": request["request_id"],
                    "lease_id": request["lease_id"],
                    "agent_id": "triage-1",
                    "resolution": "clarify",
                    "note": "Needs product confirmation rather than a code change.",
                    "reply_markdown": "Please confirm the intended behavior before changing this path.",
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit", self.repo, self.pr, "--input", str(response_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTION_ACCEPTED")
        session = self.load_session()
        self.assertEqual(session["items"]["local-finding:1"]["state"], "clarify")
        self.assertEqual(session["items"]["local-finding:1"]["status"], "CLARIFIED")
        self.assertFalse(session["items"]["local-finding:1"]["blocking"])

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

    def test_agent_submit_missing_resolution_guides_fixer_response_payload(self):
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
        response_path = self.workspace_dir() / "missing-resolution-response.json"
        response_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": request["request_id"],
                    "lease_id": request["lease_id"],
                    "agent_id": "codex-1",
                    "note": "Fixed validation.",
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
        self.assertEqual(payload["reason_code"], "MISSING_RESOLUTION")
        self.assertIn("fixer response", payload["next_action"])
        self.assertIn('"resolution"', payload["next_action"])
        self.assertIn("gh-address-cr agent submit", payload["next_action"])

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

    def test_agent_submit_rejects_github_thread_fix_reply_as_string_at_submit_time(self):
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
        request = json.loads(Path(json.loads(issued.stdout)["request_path"]).read_text(encoding="utf-8"))
        response_path = self.workspace_dir() / "string-fix-reply-response.json"
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
                    "fix_reply": "This is a plain string, not a dict.",
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit", self.repo, self.pr, "--input", str(response_path))

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTION_REJECTED")
        self.assertEqual(payload["reason_code"], "INVALID_FIX_REPLY")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "claimed")
        self.assertEqual(session["leases"][request["lease_id"]]["status"], "active")
        self.assertIn("response_rejected", [row["event_type"] for row in self.ledger_rows()])

    def test_agent_submit_rejects_github_thread_fix_reply_missing_commit_hash(self):
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
        request = json.loads(Path(json.loads(issued.stdout)["request_path"]).read_text(encoding="utf-8"))
        response_path = self.workspace_dir() / "no-commit-hash-response.json"
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
                        "summary": "Fixed it.",
                        "files": ["src/example.py"],
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit", self.repo, self.pr, "--input", str(response_path))

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTION_REJECTED")
        self.assertEqual(payload["reason_code"], "MISSING_FIX_REPLY_COMMIT_HASH")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "claimed")
        self.assertEqual(session["leases"][request["lease_id"]]["status"], "active")
        self.assertIn("response_rejected", [row["event_type"] for row in self.ledger_rows()])

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
        self.assertEqual(first_item["accepted_response"]["fix_reply"]["summary"], "Fixed first thread.")
        self.assertEqual(second_item["accepted_response"]["fix_reply"]["summary"], "Fixed second thread.")
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

    def test_agent_next_allows_same_agent_same_file_github_thread_leases_for_batch(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/shared.py",
                    classification_evidence={"classification": "fix", "record_id": "ev_1"},
                    thread_id="PRRT_abc",
                ),
                open_item(
                    "github-thread:def",
                    item_kind="github_thread",
                    source="github",
                    path="src/shared.py",
                    classification_evidence={"classification": "fix", "record_id": "ev_2"},
                    thread_id="PRRT_def",
                ),
            ]
        )

        first = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        second = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(first.stdout)["item_id"], "github-thread:abc")
        self.assertEqual(json.loads(second.stdout)["item_id"], "github-thread:def")

    def test_agent_submit_expands_reusable_evidence_profile(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/example.py",
                    classification_evidence={"classification": "fix", "record_id": "ev_classified"},
                    thread_id="PRRT_abc",
                )
            ]
        )
        added = self.run_runtime_module(
            "agent",
            "evidence",
            "add",
            self.repo,
            self.pr,
            "--name",
            "local-verified",
            "--commit",
            "abc123",
            "--files",
            "src/example.py,tests/test_example.py",
            "--validation",
            "python3 -m unittest tests.test_example=passed",
            "--test-command",
            "python3 -m unittest tests.test_example",
            "--test-result",
            "passed",
        )
        issued = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertEqual(issued.returncode, 0, issued.stderr)
        request = json.loads(Path(json.loads(issued.stdout)["request_path"]).read_text(encoding="utf-8"))
        response_path = self.workspace_dir() / "profile-response.json"
        response_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": request["request_id"],
                    "lease_id": request["lease_id"],
                    "agent_id": "codex-1",
                    "item_id": "github-thread:abc",
                    "resolution": "fix",
                    "note": "Fixed via shared evidence.",
                    "evidence_ref": "local-verified",
                    "fix_reply": {
                        "summary": "Fixed via shared evidence.",
                        "why": "The verified change covers this review thread.",
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit", self.repo, self.pr, "--input", str(response_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        session = self.load_session()
        accepted = session["items"]["github-thread:abc"]["accepted_response"]
        self.assertEqual(accepted["evidence_ref"], "local-verified")
        self.assertEqual(accepted["fix_reply"]["commit_hash"], "abc123")
        self.assertEqual(accepted["files"], ["src/example.py", "tests/test_example.py"])

    def test_agent_evidence_validation_parser_preserves_env_assignment_without_result(self):
        self.write_session(items=[open_item()])

        result = self.run_runtime_module(
            "agent",
            "evidence",
            "add",
            self.repo,
            self.pr,
            "--name",
            "env-validation",
            "--commit",
            "abc123",
            "--files",
            "src/example.py",
            "--validation",
            "PYENV_VERSION=3.10.19 python -m unittest tests.test_example",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual(
            profile["validation_commands"],
            [{"command": "PYENV_VERSION=3.10.19 python -m unittest tests.test_example", "result": "passed"}],
        )

    def test_agent_fix_fast_path_classifies_claims_and_accepts_single_thread(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/example.py",
                    thread_id="PRRT_abc",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix",
            self.repo,
            self.pr,
            "github-thread:abc",
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/example.py",
            "--summary",
            "Added the guard.",
            "--why",
            "The guarded path now covers the review case.",
            "--validation",
            "python3 -m unittest tests.test_example=passed",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ACCEPTED")
        session = self.load_session()
        item = session["items"]["github-thread:abc"]
        self.assertEqual(item["classification_evidence"]["classification"], "fix")
        self.assertEqual(item["state"], "publish_ready")
        self.assertEqual(item["accepted_response"]["fix_reply"]["commit_hash"], "abc123")

    def test_agent_fix_fast_path_records_raw_review_priority(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/example.py",
                    thread_id="PRRT_abc",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix",
            self.repo,
            self.pr,
            "github-thread:abc",
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/example.py",
            "--summary",
            "Added the guard.",
            "--why",
            "The guarded path now covers the review case.",
            "--review-priority",
            "high",
            "--validation",
            "python3 -m unittest tests.test_example=passed",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.load_session()["items"]["github-thread:abc"]
        self.assertEqual(
            item["review_priority_evidence"],
            {
                "value": "high",
                "source": "agent_fix",
                "raw_marker": "high",
            },
        )

    def test_agent_fix_fast_path_accepts_explicit_severity_override(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/example.py",
                    thread_id="PRRT_abc",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix",
            self.repo,
            self.pr,
            "github-thread:abc",
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/example.py",
            "--summary",
            "Added the guard.",
            "--why",
            "The guarded path now covers the review case.",
            "--severity",
            "P1",
            "--validation",
            "python3 -m unittest tests.test_example=passed",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        session = self.load_session()
        item = session["items"]["github-thread:abc"]
        self.assertEqual(item["accepted_response"]["fix_reply"]["severity"], "P1")

    def test_agent_fix_rejects_conflicting_severity_without_override_note(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/example.py",
                    thread_id="PRRT_abc",
                    severity="P2",
                    severity_evidence={
                        "value": "P2",
                        "source": "github_first_comment",
                        "raw_marker": "P2",
                        "observed_from": "https://example.test/thread/abc",
                    },
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix",
            self.repo,
            self.pr,
            "github-thread:abc",
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/example.py",
            "--summary",
            "Added the guard.",
            "--why",
            "The guarded path now covers the review case.",
            "--severity",
            "P1",
            "--validation",
            "python3 -m unittest tests.test_example=passed",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "SEVERITY_OVERRIDE_NOTE_REQUIRED")

    def test_agent_fix_all_batches_matching_thread_files_with_explicit_severity(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/shared.py",
                    thread_id="PRRT_abc",
                ),
                open_item(
                    "github-thread:def",
                    item_kind="github_thread",
                    source="github",
                    path="src/shared.py",
                    thread_id="PRRT_def",
                ),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
            "--homogeneous-reason",
            "Both threads report the same repeated nit and the shared patch addresses that repeated concern.",
            "--severity",
            "P3",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["accepted_response"]["fix_reply"]["severity"], "P3")
        self.assertEqual(session["items"]["github-thread:def"]["accepted_response"]["fix_reply"]["severity"], "P3")
        self.assertEqual(
            session["items"]["github-thread:abc"]["accepted_response"]["fix_reply"]["why"],
            "Both threads report the same repeated nit and the shared patch addresses that repeated concern.",
        )

    def test_agent_fix_all_batches_matching_thread_files(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/shared.py",
                    thread_id="PRRT_abc",
                ),
                open_item(
                    "github-thread:def",
                    item_kind="github_thread",
                    source="github",
                    path="src/shared.py",
                    thread_id="PRRT_def",
                ),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
            "--homogeneous-reason",
            "Both comments ask for the same repeated typo correction.",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_ACCEPTED")
        self.assertEqual(payload["matched_count"], 2)
        self.assertEqual(payload["accepted_count"], 2)
        self.assertEqual(payload["batches"][0]["status"], "BATCH_ACTION_ACCEPTED")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "publish_ready")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "publish_ready")
        self.assertEqual(session["items"]["github-thread:abc"]["accepted_response"]["fix_reply"]["commit_hash"], "abc123")
        self.assertEqual(
            session["items"]["github-thread:def"]["accepted_response"]["fix_reply"]["why"],
            "Both comments ask for the same repeated typo correction.",
        )

    def test_agent_fix_all_rejects_generic_mixed_threads_without_per_item_evidence(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    body="Why does this branch skip nil validation?",
                    classification_evidence={"classification": "fix", "record_id": "ev_abc"},
                ),
                github_thread(
                    "github-thread:def",
                    body="Can this log expose private data?",
                    classification_evidence={"classification": "fix", "record_id": "ev_def"},
                ),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "PER_THREAD_EVIDENCE_REQUIRED")
        self.assertEqual(payload["waiting_on"], "batch_action_response")
        self.assertIn("agent submit-batch", payload["next_action"])
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "open")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "open")

    def test_agent_fix_all_rejects_distinct_thread_bodies_with_homogeneous_reason(self):
        self.write_session(
            items=[
                github_thread("github-thread:abc", body="Why does this branch skip nil validation?"),
                github_thread("github-thread:def", body="Can this log expose private data?"),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
            "--homogeneous-reason",
            "Both comments are covered by the same shared patch.",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "PER_THREAD_EVIDENCE_REQUIRED")
        self.assertIn("distinct thread bodies", payload["next_action"])
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "open")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "open")

    def test_agent_fix_all_homogeneous_reason_compares_original_thread_bodies(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    body="Fixed in `abc123`.",
                    first_body="Why does this branch skip nil validation?",
                ),
                github_thread(
                    "github-thread:def",
                    body="Fixed in `abc123`.",
                    first_body="Can this log expose private data?",
                ),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
            "--homogeneous-reason",
            "Both comments are covered by the same shared patch.",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "PER_THREAD_EVIDENCE_REQUIRED")
        self.assertIn("distinct thread bodies", payload["next_action"])

    def test_agent_fix_all_homogeneous_reason_rejects_latest_only_bodies_without_first_body(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    body="Fixed in `abc123`.",
                    comment_source="latest",
                    first_body="",
                ),
                github_thread(
                    "github-thread:def",
                    body="Fixed in `abc123`.",
                    comment_source="latest",
                    first_body="",
                ),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
            "--homogeneous-reason",
            "Both comments are covered by the same shared patch.",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "PER_THREAD_EVIDENCE_REQUIRED")
        self.assertIn("distinct thread bodies", payload["next_action"])

    def test_agent_fix_all_input_rejects_common_only_reply_evidence(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    classification_evidence={"classification": "fix", "record_id": "ev_abc"},
                ),
                github_thread(
                    "github-thread:def",
                    classification_evidence={"classification": "fix", "record_id": "ev_def"},
                ),
            ]
        )
        first = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        second = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_request = json.loads(Path(json.loads(first.stdout)["request_path"]).read_text(encoding="utf-8"))
        second_request = json.loads(Path(json.loads(second.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "common-only-fix-all-input.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/shared.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_shared", "result": "passed"}
                        ],
                        "fix_reply": {
                            "commit_hash": "abc123",
                            "summary": "Fixed shared issues.",
                            "why": "The shared patch covers every thread.",
                        },
                    },
                    "items": [
                        {
                            "request_id": first_request["request_id"],
                            "lease_id": first_request["lease_id"],
                            "item_id": "github-thread:abc",
                            "note": "Accepted common evidence for first thread.",
                        },
                        {
                            "request_id": second_request["request_id"],
                            "lease_id": second_request["lease_id"],
                            "item_id": "github-thread:def",
                            "note": "Accepted common evidence for second thread.",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "fix-all", self.repo, self.pr, "--input", str(batch_path))

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "MISSING_FIX_ALL_ITEM_REPLY_EVIDENCE")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "claimed")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "claimed")

    def test_agent_fix_all_input_rejects_stale_or_outdated_threads(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:stale",
                    path="src/stale.py",
                    state="stale",
                    status="STALE",
                    is_outdated=True,
                    classification_evidence={"classification": "fix", "record_id": "ev_stale"},
                )
            ]
        )

        claimed = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        request = json.loads(Path(json.loads(claimed.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "stale-fix-all-input.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/stale.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_stale", "result": "passed"}
                        ],
                        "fix_reply": {
                            "commit_hash": "abc123",
                            "summary": "Resolved stale thread.",
                            "why": "Shared patch handles stale thread updates.",
                        },
                    },
                    "items": [
                        {
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "item_id": "github-thread:stale",
                            "note": "Provided stale thread fix evidence.",
                            "summary": "Resolved stale thread.",
                            "why": "Shared patch handles stale thread updates.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "fix-all", self.repo, self.pr, "--input", str(batch_path))

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "STALE_THREADS_REQUIRE_RESOLVE_STALE")
        self.assertIn("agent resolve-stale", payload["next_action"])

    def test_agent_fix_all_input_rejects_conflicting_commit_argument(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        batch_path = self.workspace_dir() / "empty-batch.json"
        batch_path.write_text("{}", encoding="utf-8")

        result = self.run_runtime_module(
            "agent", "fix-all", self.repo, self.pr, "--input", str(batch_path), "--commit", "abc123"
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "CONFLICTING_FIX_ALL_INPUT")

    def test_agent_fix_all_input_rejects_conflicting_evidence_arguments(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        batch_path = self.workspace_dir() / "empty-batch.json"
        batch_path.write_text("{}", encoding="utf-8")

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--input",
            str(batch_path),
            "--files",
            "src/example.py",
            "--validation",
            "python3 -m unittest tests.test_example=passed",
            "--severity",
            "P2",
            "--homogeneous-reason",
            "Common repeated concern.",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "CONFLICTING_FIX_ALL_INPUT")
        self.assertIn("--files", payload["next_action"])
        self.assertIn("--validation", payload["next_action"])
        self.assertIn("--severity", payload["next_action"])
        self.assertIn("--homogeneous-reason", payload["next_action"])

    def test_agent_fix_all_input_preserves_per_item_summary_why_severity_and_validation(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    body="Why does this branch skip nil validation?",
                    classification_evidence={"classification": "fix", "record_id": "ev_abc"},
                ),
                github_thread(
                    "github-thread:def",
                    body="Can this log expose private data?",
                    classification_evidence={"classification": "fix", "record_id": "ev_def"},
                ),
            ]
        )
        first = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        second = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_request = json.loads(Path(json.loads(first.stdout)["request_path"]).read_text(encoding="utf-8"))
        second_request = json.loads(Path(json.loads(second.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "fix-all-input.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/shared.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_shared", "result": "passed"}
                        ],
                        "fix_reply": {"commit_hash": "abc123"},
                    },
                    "items": [
                        {
                            "request_id": first_request["request_id"],
                            "lease_id": first_request["lease_id"],
                            "item_id": "github-thread:abc",
                            "note": "Audit note for the accepted evidence ledger.",
                            "why": "The nil-validation branch now rejects missing values before use.",
                            "fix_reply": {
                                "summary": "Restored nil validation.",
                                "severity": "P1",
                                "severity_note": "Reviewer called out a crash path.",
                            },
                        },
                        {
                            "request_id": second_request["request_id"],
                            "lease_id": second_request["lease_id"],
                            "item_id": "github-thread:def",
                            "summary": "Redacted private log data.",
                            "why": "The logging path now omits the sensitive token mentioned in this thread.",
                            "fix_reply": {"severity": "P2", "severity_note": "Reviewer called out a data exposure risk."},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module(
            "agent", "fix-all", self.repo, self.pr, "--input", str(batch_path)
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_ACCEPTED")
        self.assertEqual(payload["submit"]["status"], "BATCH_ACTION_ACCEPTED")
        session = self.load_session()
        first_fix = session["items"]["github-thread:abc"]["accepted_response"]["fix_reply"]
        second_fix = session["items"]["github-thread:def"]["accepted_response"]["fix_reply"]
        self.assertEqual(first_fix["summary"], "Restored nil validation.")
        self.assertEqual(first_fix["why"], "The nil-validation branch now rejects missing values before use.")
        self.assertEqual(first_fix["severity"], "P1")
        self.assertEqual(first_fix["severity_note"], "Reviewer called out a crash path.")
        self.assertEqual(second_fix["summary"], "Redacted private log data.")
        self.assertEqual(second_fix["why"], "The logging path now omits the sensitive token mentioned in this thread.")
        self.assertEqual(
            session["items"]["github-thread:def"]["accepted_response"]["validation_commands"],
            [{"command": "python3 -m unittest tests.test_shared", "result": "passed"}],
        )

    def test_agent_fix_all_rejects_missing_body_without_explicit_evidence(self):
        self.write_session(items=[github_thread("github-thread:abc", body="")])

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "PER_THREAD_EVIDENCE_REQUIRED")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "open")

    def test_agent_fix_all_include_stale_routes_to_resolve_stale(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:stale",
                    path="src/stale.py",
                    state="stale",
                    status="STALE",
                    is_outdated=True,
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--include-stale",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "STALE_THREADS_REQUIRE_RESOLVE_STALE")
        self.assertIn("agent resolve-stale", payload["next_action"])

    def test_agent_fix_all_excludes_stale_without_opt_in(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:stale",
                    item_kind="github_thread",
                    source="github",
                    path="src/stale.py",
                    state="stale",
                    status="STALE",
                    is_outdated=True,
                    thread_id="PRRT_stale",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_NO_MATCH")
        self.assertEqual(payload["reason_code"], "NO_MATCHING_GITHUB_THREADS")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:stale"]["state"], "stale")

    def test_agent_fix_all_excludes_outdated_without_opt_in(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:outdated",
                    item_kind="github_thread",
                    source="github",
                    path="src/stale.py",
                    state="open",
                    status="OPEN",
                    is_outdated=True,
                    thread_id="PRRT_outdated",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_NO_MATCH")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:outdated"]["state"], "open")

    def test_agent_resolve_stale_matches_only_stale_thread_files(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:stale",
                    item_kind="github_thread",
                    source="github",
                    path="src/stale.py",
                    state="stale",
                    status="STALE",
                    is_outdated=True,
                    thread_id="PRRT_stale",
                ),
                open_item(
                    "github-thread:open",
                    item_kind="github_thread",
                    source="github",
                    path="src/stale.py",
                    thread_id="PRRT_open",
                ),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "resolve-stale",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--match-files",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_ACCEPTED")
        self.assertEqual(payload["matched_count"], 1)
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:stale"]["state"], "publish_ready")
        self.assertEqual(session["items"]["github-thread:open"]["state"], "open")

    def test_agent_resolve_stale_matches_legacy_outdated_thread_files(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:outdated",
                    item_kind="github_thread",
                    source="github",
                    path="src/stale.py",
                    state="open",
                    status="OPEN",
                    is_outdated=True,
                    thread_id="PRRT_outdated",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "resolve-stale",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--match-files",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_ACCEPTED")
        self.assertEqual(payload["matched_count"], 1)
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:outdated"]["state"], "publish_ready")

    def test_agent_resolve_stale_skips_publish_ready_outdated_items(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:stale",
                    item_kind="github_thread",
                    source="github",
                    path="src/stale.py",
                    state="publish_ready",
                    status="OPEN",
                    is_outdated=True,
                    thread_id="PRRT_stale",
                    accepted_response={
                        "resolution": "fix",
                        "fix_reply": {"commit_hash": "old123", "files": ["src/stale.py"]},
                    },
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "resolve-stale",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--match-files",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_NO_MATCH")
        self.assertEqual(payload["reason_code"], "NO_MATCHING_GITHUB_THREADS")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:stale"]["state"], "publish_ready")
        self.assertEqual(session["items"]["github-thread:stale"]["accepted_response"]["fix_reply"]["commit_hash"], "old123")

    def test_agent_resolve_stale_missing_validation_uses_stale_status(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:stale",
                    item_kind="github_thread",
                    source="github",
                    path="src/stale.py",
                    state="stale",
                    status="STALE",
                    is_outdated=True,
                    thread_id="PRRT_stale",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "resolve-stale",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--match-files",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_REJECTED")
        self.assertEqual(payload["reason_code"], "MISSING_VALIDATION_COMMANDS")
        self.assertEqual(payload["waiting_on"], "stale_resolution_input")

    def test_agent_resolve_stale_missing_commit_files_uses_stale_status(self):
        result = self.run_runtime_module(
            "agent",
            "resolve-stale",
            self.repo,
            self.pr,
            "--commit",
            "missingcommit123",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--match-files",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_REJECTED")
        self.assertEqual(payload["reason_code"], "COMMIT_FILES_UNAVAILABLE")

    def test_agent_fix_all_reports_partial_when_one_matched_thread_is_leased(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/first.py",
                    thread_id="PRRT_abc",
                ),
                open_item(
                    "github-thread:def",
                    item_kind="github_thread",
                    source="github",
                    path="src/second.py",
                    thread_id="PRRT_def",
                ),
            ],
            leases={
                "lease-existing": {
                    "lease_id": "lease-existing",
                    "item_id": "github-thread:def",
                    "agent_id": "other-agent",
                    "role": "fixer",
                    "status": "active",
                    "created_at": NOW.isoformat(),
                    "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                    "resume_token": "resume:req_existing",
                    "request_hash": "existing-request-hash",
                    "request_id": "req_existing",
                    "conflict_keys": [],
                }
            },
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/first.py,src/second.py",
            "--homogeneous-reason",
            "Both matched comments describe the same repeated formatting issue.",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
            "--now",
            NOW.isoformat(),
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_PARTIAL")
        self.assertEqual(payload["accepted_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["item_ids"], ["github-thread:abc"])
        self.assertEqual(payload["failed"][0]["item_id"], "github-thread:def")
        self.assertEqual(payload["failed"][0]["reason_code"], "NO_ELIGIBLE_ITEM")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "publish_ready")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "open")

    def test_agent_fix_all_requires_validation(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:abc",
                    item_kind="github_thread",
                    source="github",
                    path="src/shared.py",
                    thread_id="PRRT_abc",
                )
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "fix-all",
            self.repo,
            self.pr,
            "--commit",
            "abc123",
            "--files",
            "src/shared.py",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "MISSING_VALIDATION_COMMANDS")

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

    def test_agent_submit_batch_requires_item_specific_why(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified",
                    },
                )
            ]
        )
        issued = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1"
        )
        self.assertEqual(issued.returncode, 0, issued.stderr)
        request = json.loads(Path(json.loads(issued.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "batch-without-item-why.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/shared.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_shared", "result": "passed"}
                        ],
                        "fix_reply": {
                            "commit_hash": "abc123",
                            "why": "A common rationale must not satisfy item-specific review evidence.",
                        },
                    },
                    "items": [
                        {
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "item_id": "github-thread:abc",
                            "summary": "Fixed shared validation.",
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
        self.assertEqual(payload["reason_code"], "MISSING_BATCH_ITEM_WHY")
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "claimed")
        self.assertEqual(session["leases"][request["lease_id"]]["status"], "active")

    def test_agent_submit_batch_keeps_note_separate_from_reply_summary(self):
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified",
                    },
                )
            ]
        )
        issued = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1"
        )
        self.assertEqual(issued.returncode, 0, issued.stderr)
        request = json.loads(Path(json.loads(issued.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "batch-note-summary-separation.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/shared.py"],
                        "validation_commands": [
                            {"command": "python3 -m unittest tests.test_shared", "result": "passed"}
                        ],
                        "fix_reply": {
                            "commit_hash": "abc123",
                            "summary": "Fixed shared validation.",
                        },
                    },
                    "items": [
                        {
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "item_id": "github-thread:abc",
                            "note": "Audit note for the accepted batch item.",
                            "why": "The thread now validates the input before use.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_runtime_module("agent", "submit-batch", self.repo, self.pr, "--input", str(batch_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        session = self.load_session()
        response = session["items"]["github-thread:abc"]["accepted_response"]
        self.assertEqual(response["note"], "Audit note for the accepted batch item.")
        self.assertEqual(response["fix_reply"]["summary"], "Fixed shared validation.")

    def test_agent_submit_batch_rejects_mixed_invalid_item_without_partial_acceptance(self):
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
                    classification_evidence={
                        "event_type": "classification_recorded",
                        "classification": "fix",
                        "record_id": "ev_classified_2",
                    }
                ),
            ]
        )
        first = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        second = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--agent-id", "codex-1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_request = json.loads(Path(json.loads(first.stdout)["request_path"]).read_text(encoding="utf-8"))
        second_request = json.loads(Path(json.loads(second.stdout)["request_path"]).read_text(encoding="utf-8"))
        batch_path = self.workspace_dir() / "mixed-invalid-batch-action-response.json"
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_id": "codex-1",
                    "resolution": "fix",
                    "common": {
                        "files": ["src/example_one.py", "src/example.py"],
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
                            "item_id": "local-finding:1",
                            "summary": "Fixed local finding.",
                            "why": "The local finding should not be accepted in a batch.",
                        },
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
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "claimed")
        self.assertEqual(session["items"]["local-finding:1"]["state"], "claimed")
        self.assertEqual(session["leases"][first_request["lease_id"]]["status"], "active")
        self.assertEqual(session["leases"][second_request["lease_id"]]["status"], "active")
        self.assertNotIn("response_accepted", [row["event_type"] for row in self.ledger_rows()])

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

    def test_agent_publish_does_not_configure_telemetry_in_cli_handler(self):
        expected = {
            "status": "NO_PUBLISH_READY_ITEMS",
            "repo": self.repo,
            "pr_number": self.pr,
            "published_count": 0,
        }
        stdout = StringIO()

        with (
            patch("gh_address_cr.core.telemetry.SessionTelemetry.get_instance", side_effect=AssertionError("blocked")),
            patch("gh_address_cr.cli.workflow.publish_github_thread_responses", return_value=expected) as publish,
            redirect_stdout(stdout),
        ):
            result = cli.handle_agent_publish(None, [self.repo, self.pr])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue()), expected)
        publish.assert_called_once_with(
            self.repo,
            self.pr,
            agent_id="gh-address-cr-publisher",
            now=None,
        )

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
