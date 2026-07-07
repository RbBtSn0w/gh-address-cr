import json
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import github_thread, open_item

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)


class ControlPlaneFixAllWorkflowCLITest(PythonScriptTestCase):
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
            "resolve",
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
            "resolve",
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
            "resolve",
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
        self.assertIn("agent next", payload["next_action"])
        self.assertIn("--batch", payload["next_action"])
        self.assertEqual(
            shlex.split(payload["commands"]["batch_next"]),
            [
                "gh-address-cr",
                "agent",
                "next",
                self.repo,
                self.pr,
                "--batch",
                "--agent-id",
                "<agent_id>",
                "--files",
                "src/shared.py",
            ],
        )
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "open")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "open")

    def test_agent_fix_all_quotes_batch_next_file_filter(self):
        risky_path = "src/shared path/unsafe;$(echo pwn).py"
        self.write_session(
            items=[
                github_thread(
                    "github-thread:abc",
                    path=risky_path,
                    body="Why does this branch skip nil validation?",
                    classification_evidence={"classification": "fix", "record_id": "ev_abc"},
                ),
                github_thread(
                    "github-thread:def",
                    path=risky_path,
                    body="Can this log expose private data?",
                    classification_evidence={"classification": "fix", "record_id": "ev_def"},
                ),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "resolve",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            risky_path,
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "PER_THREAD_EVIDENCE_REQUIRED")
        argv = shlex.split(payload["commands"]["batch_next"])
        self.assertEqual(argv[:7], ["gh-address-cr", "agent", "next", self.repo, self.pr, "--batch", "--agent-id"])
        self.assertEqual(argv[7], "<agent_id>")
        self.assertEqual(argv[8:10], ["--files", risky_path])

    def test_agent_fix_all_rejects_distinct_thread_bodies_with_homogeneous_reason(self):
        self.write_session(
            items=[
                github_thread("github-thread:abc", body="Why does this branch skip nil validation?"),
                github_thread("github-thread:def", body="Can this log expose private data?"),
            ]
        )

        result = self.run_runtime_module(
            "agent",
            "resolve",
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
        self.assertIn("--batch", payload["next_action"])
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
            "resolve",
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
            "resolve",
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

        result = self.run_runtime_module("agent", "resolve", self.repo, self.pr, "--batch", "--input", str(batch_path))

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

        result = self.run_runtime_module("agent", "resolve", self.repo, self.pr, "--batch", "--input", str(batch_path))

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAST_FIX_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "STALE_THREADS_REQUIRE_RESOLVE_STALE")
        self.assertIn("agent resolve", payload["next_action"])

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
            "agent", "resolve", self.repo, self.pr, "--batch", "--input", str(batch_path)
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
            "resolve",
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
            "resolve",
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
        self.assertIn("agent resolve", payload["next_action"])

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
            "resolve",
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
            "resolve",
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
            "resolve",
            "--stale",
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
            "resolve",
            "--stale",
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
            "resolve",
            "--stale",
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
            "resolve",
            "--stale",
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
            "resolve",
            "--stale",
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
            "resolve",
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
        self.assertEqual(payload["failed"][0]["reason_code"], "LEASE_LOCKED_ITEM")
        self.assertIn("agent leases", payload["failed"][0]["next_action"])
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "publish_ready")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "open")

    def test_agent_resolve_item_reports_active_batch_lease_owner(self):
        self.write_session(
            items=[
                open_item(
                    "github-thread:def",
                    item_kind="github_thread",
                    source="github",
                    path="src/second.py",
                    thread_id="PRRT_def",
                    active_lease_id="lease-existing",
                )
            ],
            leases={
                "lease-existing": {
                    "lease_id": "lease-existing",
                    "item_id": "github-thread:def",
                    "agent_id": "batch-agent",
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
            "resolve",
            self.repo,
            self.pr,
            "github-thread:def",
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/second.py",
            "--summary",
            "Fix the second thread.",
            "--why",
            "The patch addresses the requested change.",
            "--validation",
            "python3 -m unittest tests.test_shared=passed",
            "--now",
            NOW.isoformat(),
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "LEASE_LOCKED_ITEM")
        self.assertEqual(payload["reason_code"], "LEASE_LOCKED_ITEM")
        self.assertEqual(payload["waiting_on"], "lease")
        self.assertEqual(payload["item_id"], "github-thread:def")
        self.assertEqual(payload["lease_recovery"]["lease_id"], "lease-existing")
        self.assertEqual(payload["lease_recovery"]["agent_id"], "batch-agent")
        self.assertIn("agent leases", payload["next_action"])

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
            "resolve",
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
