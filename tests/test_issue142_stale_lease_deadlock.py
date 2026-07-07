"""Regression tests for issue #142.

Two coupled failures observed on PR #141:

1. A thread claimed via ``agent next --batch`` keeps a non-expired lease plus
   ``state="claimed"``. Once GitHub marks the thread STALE, neither
   ``agent resolve --batch`` (rejects stale) nor ``agent resolve --stale``
   (excluded because the active lease still gates ``_next_item``) can resolve
   it, and ``agent reclaim`` only releases *expired* leases. The thread
   deadlocks.

2. After an out-of-band ``gh`` reply resolves a thread, ``final-gate`` keeps
   failing with ``FINAL_GATE_MISSING_REPLY_EVIDENCE`` because the runtime never
   recorded login-matched reply evidence. ``agent evidence add --reply-url``
   must let that evidence be ingested.
"""

import json
from datetime import datetime, timedelta, timezone

from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import open_item

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def _batch_lease(lease_id: str, item_id: str, agent_id: str) -> dict:
    """An active, non-expired fixer lease, as ``agent next --batch`` leaves it."""
    return {
        "lease_id": lease_id,
        "item_id": item_id,
        "agent_id": agent_id,
        "role": "fixer",
        "status": "active",
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "resume_token": f"resume:req_{lease_id}",
        "request_hash": f"hash-{lease_id}",
        "request_id": f"req_{lease_id}",
        "conflict_keys": [],
    }


class Issue142StaleLeaseDeadlockTest(PythonScriptTestCase):
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
        return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _stale_claimed_thread(self, *, lease_id="lease-batch"):
        return open_item(
            "github-thread:stale",
            item_kind="github_thread",
            source="github",
            path="src/stale.py",
            body="Please fix this stale concern.",
            state="claimed",
            status="STALE",
            is_outdated=True,
            active_lease_id=lease_id,
            thread_id="PRRT_stale",
        )

    def test_stale_resolve_self_heals_batch_claimed_thread(self):
        """The deadlock case: a batch-claimed thread that became STALE must be
        resolvable in one ``agent resolve --stale --match-files`` shot."""
        self.write_session(
            items=[self._stale_claimed_thread()],
            leases={"lease-batch": _batch_lease("lease-batch", "github-thread:stale", "codex-1")},
        )

        result = self.run_runtime_module(
            "agent",
            "resolve",
            "--stale",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--match-files",
            "--now",
            NOW.isoformat(),
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_ACCEPTED")
        self.assertEqual(payload["matched_count"], 1)
        self.assertEqual(payload["accepted_count"], 1)

        session = self.load_session()
        item = session["items"]["github-thread:stale"]
        self.assertEqual(item["state"], "publish_ready")
        # The dangling batch lease must have been released so it no longer
        # blocks re-claim through ``_next_item``.
        self.assertEqual(session["leases"]["lease-batch"]["status"], "released")

    def test_stale_resolve_does_not_release_other_agents_lease(self):
        """Self-healing must be scoped to the resolving agent: a stale thread
        leased by a *different* agent stays excluded and untouched."""
        self.write_session(
            items=[self._stale_claimed_thread(lease_id="lease-other")],
            leases={"lease-other": _batch_lease("lease-other", "github-thread:stale", "other-agent")},
        )

        result = self.run_runtime_module(
            "agent",
            "resolve",
            "--stale",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--match-files",
            "--now",
            NOW.isoformat(),
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_NO_MATCH")
        self.assertEqual(payload["reason_code"], "NO_MATCHING_GITHUB_THREADS")

        session = self.load_session()
        self.assertEqual(session["leases"]["lease-other"]["status"], "active")
        self.assertEqual(session["items"]["github-thread:stale"]["state"], "claimed")

    def test_stale_resolve_does_not_release_non_fixer_self_lease(self):
        """Self-healing is scoped to the agent's own *fixer* lease (#143): a
        non-fixer lease (triage/verifier) the same agent holds on the stale
        thread must not be auto-released."""
        verifier_lease = _batch_lease("lease-verify", "github-thread:stale", "codex-1")
        verifier_lease["role"] = "verifier"
        self.write_session(
            items=[self._stale_claimed_thread(lease_id="lease-verify")],
            leases={"lease-verify": verifier_lease},
        )

        result = self.run_runtime_module(
            "agent",
            "resolve",
            "--stale",
            self.repo,
            self.pr,
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/stale.py",
            "--validation",
            "python3 -m unittest tests.test_stale=passed",
            "--match-files",
            "--now",
            NOW.isoformat(),
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "STALE_RESOLUTION_NO_MATCH")

        session = self.load_session()
        self.assertEqual(session["leases"]["lease-verify"]["status"], "active")
        self.assertEqual(session["leases"]["lease-verify"]["role"], "verifier")
        self.assertEqual(session["items"]["github-thread:stale"]["state"], "claimed")

    def test_direct_item_resolve_reports_lease_owner_instead_of_no_eligible_item(self):
        """An item blocked by another active lease must report lease ownership
        and recovery details instead of a generic no-work response."""
        locked = open_item(
            "github-thread:locked",
            item_kind="github_thread",
            source="github",
            path="src/locked.py",
            body="Please fix this locked concern.",
            state="open",
            status="OPEN",
            active_lease_id="lease-other",
            thread_id="PRRT_locked",
        )
        self.write_session(
            items=[locked],
            leases={"lease-other": _batch_lease("lease-other", "github-thread:locked", "other-agent")},
        )

        result = self.run_runtime_module(
            "agent",
            "resolve",
            self.repo,
            self.pr,
            "github-thread:locked",
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/locked.py",
            "--summary",
            "Fix locked issue.",
            "--why",
            "Apply requested change.",
            "--validation",
            "python3 -m unittest tests.test_locked=passed",
            "--now",
            NOW.isoformat(),
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "LEASE_LOCKED_ITEM")
        self.assertEqual(payload["reason_code"], "LEASE_LOCKED_ITEM")
        self.assertEqual(payload["waiting_on"], "lease")
        self.assertEqual(payload["lease_recovery"]["agent_id"], "other-agent")
        self.assertIn("agent leases", payload["next_action"])


class Issue142ReplyEvidenceIngestTest(PythonScriptTestCase):
    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_77",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_GATE",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))

    def ledger_rows(self):
        ledger = self.workspace_dir() / "evidence.jsonl"
        if not ledger.exists():
            return []
        return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_evidence_add_reply_url_records_login_matched_evidence(self):
        """``agent evidence add --reply-url`` records reply evidence for a thread
        that was resolved out-of-band, so final-gate can reconcile it."""
        self.write_session(
            items=[
                open_item(
                    "github-thread:PRRT_done",
                    item_kind="github_thread",
                    source="github",
                    path="src/done.py",
                    body="Please fix this resolved concern.",
                    state="closed",
                    status="CLOSED",
                    thread_id="PRRT_done",
                )
            ]
        )

        reply_url = "https://github.com/octo/example/pull/77#discussion_r999"
        result = self.run_runtime_module(
            "agent",
            "evidence",
            "add",
            self.repo,
            self.pr,
            "--reply-url",
            reply_url,
            "--thread-id",
            "PRRT_done",
            "--author-login",
            "agent-login",
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

        session = self.load_session()
        item = session["items"]["github-thread:PRRT_done"]
        self.assertTrue(item.get("reply_posted"))
        self.assertEqual(item["reply_url"], reply_url)
        self.assertEqual(
            item["reply_evidence"],
            {"reply_url": reply_url, "author_login": "agent-login"},
        )

        event_types = [row.get("event_type") for row in self.ledger_rows()]
        self.assertIn("reply_posted", event_types)

    def test_final_gate_reconciles_ingested_reply_when_remote_detection_misses(self):
        """End-to-end: a thread resolved on GitHub but with ``viewer_replied``
        false (manual ``gh`` reply the runtime never saw) must pass final-gate
        once its reply evidence has been ingested."""
        from gh_address_cr.core import gate

        reply_url = "https://github.com/octo/example/pull/77#discussion_r321"
        session = {
            "repo": self.repo,
            "pr_number": self.pr,
            "items": {
                "github-thread:PRRT_x": {
                    "item_id": "github-thread:PRRT_x",
                    "item_kind": "github_thread",
                    "thread_id": "PRRT_x",
                    "state": "closed",
                    # Ingested by ``record_reply_evidence``:
                    "reply_evidence": {"reply_url": reply_url, "author_login": "agent-login"},
                }
            },
        }
        # Remote reports the thread resolved but never saw a viewer reply.
        remote_threads = [{"id": "PRRT_x", "isResolved": True, "viewer_replied": False}]

        merged = gate._session_with_remote_threads(session, remote_threads, current_login="agent-login")
        result = gate.evaluate_final_gate(
            merged,
            remote_threads=remote_threads,
            pending_reviews=[],
            current_login="agent-login",
            check_runs=[],
        )

        self.assertEqual(result.counts["github_threads_missing_reply_count"], 0)
        self.assertTrue(result.passed, result.to_machine_summary())
