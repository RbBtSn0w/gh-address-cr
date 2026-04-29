import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SRC_ROOT


sys.path.insert(0, str(SRC_ROOT))


class EvidenceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self.temp_dir.name) / "evidence.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_evidence_record_serializes_payload_hash_and_round_trips(self):
        from gh_address_cr.evidence.ledger import EvidenceRecord

        record = EvidenceRecord.new(
            session_id="session-1",
            item_id="github-thread:THREAD_1",
            lease_id="lease-1",
            agent_id="codex-fixer",
            role="fixer",
            event_type="response_accepted",
            payload={"b": 2, "a": 1},
            timestamp="2026-04-24T01:02:03Z",
        )

        serialized = record.to_json()
        expected_hash = hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
        self.assertEqual(serialized["payload_hash"], expected_hash)
        self.assertEqual(EvidenceRecord.from_json(serialized), record)
        self.assertTrue(record.record_id.startswith("ev_"))

    def test_ledger_appends_records_in_order_without_rewriting_existing_rows(self):
        from gh_address_cr.evidence.ledger import EvidenceLedger

        ledger = EvidenceLedger(self.ledger_path)
        first = ledger.append_event(
            session_id="session-1",
            item_id="item-1",
            lease_id="lease-1",
            agent_id="agent-1",
            role="coordinator",
            event_type="request_issued",
            payload={"step": 1},
            timestamp="2026-04-24T01:00:00Z",
        )
        first_line = self.ledger_path.read_text(encoding="utf-8")

        second = ledger.append_event(
            session_id="session-1",
            item_id="item-1",
            lease_id="lease-1",
            agent_id="agent-1",
            role="coordinator",
            event_type="response_submitted",
            payload={"step": 2},
            timestamp="2026-04-24T01:01:00Z",
        )

        rows = ledger.load()
        self.assertEqual([row.record_id for row in rows], [first.record_id, second.record_id])
        self.assertTrue(self.ledger_path.read_text(encoding="utf-8").startswith(first_line))

    def test_lease_events_append_evidence_records(self):
        from gh_address_cr.evidence.ledger import EvidenceLedger

        ledger = EvidenceLedger(self.ledger_path)
        ledger.record_lease_event(
            event_type="lease_expired",
            session_id="session-1",
            item_id="local-finding:abc",
            lease_id="lease-abc",
            agent_id="codex-fixer",
            role="fixer",
            reason="ttl elapsed",
            timestamp="2026-04-24T01:02:00Z",
        )

        [record] = ledger.load()
        self.assertEqual(record.event_type, "lease_expired")
        self.assertEqual(record.payload["reason"], "ttl elapsed")

    def test_side_effect_attempt_serializes_idempotency_retry_and_backoff_state(self):
        from gh_address_cr.evidence.ledger import SideEffectAttempt

        attempt = SideEffectAttempt(
            attempt_id="attempt-1",
            session_id="session-1",
            item_id="github-thread:THREAD_1",
            side_effect_type="github_reply",
            idempotency_key="reply:THREAD_1:abc",
            status="retrying",
            retry_count=2,
            backoff_until="2026-04-24T01:05:00Z",
            last_error="rate limited",
            external_url=None,
        )

        self.assertEqual(SideEffectAttempt.from_json(attempt.to_json()), attempt)
        self.assertEqual(attempt.to_json()["idempotency_key"], "reply:THREAD_1:abc")

    def test_reply_publisher_records_success_and_reuses_idempotency_key(self):
        from gh_address_cr.evidence.ledger import EvidenceLedger
        from gh_address_cr.github.replies import ReplyPublisher, RetryPolicy

        calls = []

        def post_reply(thread_id, body):
            calls.append((thread_id, body))
            return "https://example.test/reply/1"

        ledger = EvidenceLedger(self.ledger_path)
        publisher = ReplyPublisher(ledger, post_reply=post_reply, retry_policy=RetryPolicy(max_attempts=1))

        first = publisher.post_reply(
            session_id="session-1",
            item_id="github-thread:THREAD_1",
            lease_id="lease-1",
            agent_id="publisher",
            thread_id="THREAD_1",
            body="Fixed.",
            idempotency_key="reply:THREAD_1:fixed",
            timestamp="2026-04-24T01:00:00Z",
        )
        second = publisher.post_reply(
            session_id="session-1",
            item_id="github-thread:THREAD_1",
            lease_id="lease-1",
            agent_id="publisher",
            thread_id="THREAD_1",
            body="Fixed.",
            idempotency_key="reply:THREAD_1:fixed",
            timestamp="2026-04-24T01:01:00Z",
        )

        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(second["status"], "succeeded")
        self.assertTrue(second["deduplicated"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(ledger.successful_side_effect_url("reply:THREAD_1:fixed"), "https://example.test/reply/1")
        self.assertIn("reply_posted", [record.event_type for record in ledger.load()])

    def test_reply_publisher_records_immediate_retry_then_success(self):
        from gh_address_cr.evidence.ledger import EvidenceLedger
        from gh_address_cr.github.replies import GitHubTransientError, ReplyPublisher, RetryPolicy

        calls = []

        def post_reply(thread_id, body):
            calls.append((thread_id, body))
            if len(calls) == 1:
                raise GitHubTransientError("504 gateway timeout")
            return "https://example.test/reply/retried"

        ledger = EvidenceLedger(self.ledger_path)
        publisher = ReplyPublisher(
            ledger,
            post_reply=post_reply,
            retry_policy=RetryPolicy(max_attempts=2, immediate_retries=1),
        )

        result = publisher.post_reply(
            session_id="session-1",
            item_id="github-thread:THREAD_2",
            lease_id="lease-2",
            agent_id="publisher",
            thread_id="THREAD_2",
            body="Retried.",
            idempotency_key="reply:THREAD_2:retry",
            timestamp="2026-04-24T01:00:00Z",
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(calls), 2)
        attempts = [record.payload for record in ledger.load() if record.event_type == "side_effect_attempt"]
        self.assertEqual([attempt["status"] for attempt in attempts], ["retrying", "succeeded"])
        self.assertEqual(attempts[0]["last_error"], "504 gateway timeout")

    def test_reply_publisher_schedules_backoff_with_resume_token(self):
        from gh_address_cr.evidence.ledger import EvidenceLedger
        from gh_address_cr.github.replies import GitHubTransientError, ReplyPublisher, RetryPolicy

        def post_reply(thread_id, body):
            raise GitHubTransientError("secondary rate limit")

        ledger = EvidenceLedger(self.ledger_path)
        publisher = ReplyPublisher(
            ledger,
            post_reply=post_reply,
            retry_policy=RetryPolicy(max_attempts=3, immediate_retries=1, backoff_seconds=90),
        )

        result = publisher.post_reply(
            session_id="session-1",
            item_id="github-thread:THREAD_3",
            lease_id="lease-3",
            agent_id="publisher",
            thread_id="THREAD_3",
            body="Back off.",
            idempotency_key="reply:THREAD_3:backoff",
            timestamp="2026-04-24T01:00:00Z",
        )

        self.assertEqual(result["status"], "retrying")
        self.assertEqual(result["resume_token"], "resume:session-1:github-thread:THREAD_3:github_reply")
        self.assertEqual(result["backoff_until"], "2026-04-24T01:01:30Z")

    def test_reply_publisher_blocks_after_retry_exhaustion(self):
        from gh_address_cr.evidence.ledger import EvidenceLedger
        from gh_address_cr.github.replies import GitHubTransientError, ReplyPublisher, RetryPolicy

        def post_reply(thread_id, body):
            raise GitHubTransientError("service unavailable")

        ledger = EvidenceLedger(self.ledger_path)
        publisher = ReplyPublisher(
            ledger,
            post_reply=post_reply,
            retry_policy=RetryPolicy(max_attempts=2, immediate_retries=1),
        )

        result = publisher.post_reply(
            session_id="session-1",
            item_id="github-thread:THREAD_4",
            lease_id="lease-4",
            agent_id="publisher",
            thread_id="THREAD_4",
            body="Exhaust.",
            idempotency_key="reply:THREAD_4:exhaust",
            timestamp="2026-04-24T01:00:00Z",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["resume_token"], "resume:session-1:github-thread:THREAD_4:github_reply")
        self.assertEqual(ledger.load()[-1].payload["status"], "blocked")

    def test_reply_evidence_audit_reports_terminal_threads_missing_durable_reply(self):
        from gh_address_cr.evidence.audit import terminal_threads_missing_reply_evidence

        items = [
            {
                "item_id": "github-thread:THREAD_OK",
                "item_kind": "github_thread",
                "state": "closed",
                "reply_evidence": {"reply_url": "https://example.test/reply", "author_login": "agent"},
            },
            {
                "item_id": "github-thread:THREAD_MISSING",
                "item_kind": "github_thread",
                "state": "deferred",
                "reply_evidence": {"reply_url": "", "author_login": "agent"},
            },
        ]

        self.assertEqual(terminal_threads_missing_reply_evidence(items), ["github-thread:THREAD_MISSING"])

    def test_resolve_publisher_rejects_resolve_only_without_reply_evidence_before_mutation(self):
        from gh_address_cr.evidence.ledger import EvidenceLedger
        from gh_address_cr.github.threads import ResolvePublisher

        calls = []

        def resolve_thread(thread_id):
            calls.append(thread_id)
            return True

        ledger = EvidenceLedger(self.ledger_path)
        publisher = ResolvePublisher(ledger, resolve_thread=resolve_thread)

        result = publisher.resolve_thread(
            session_id="session-1",
            item_id="github-thread:THREAD_5",
            lease_id="lease-5",
            agent_id="publisher",
            thread_id="THREAD_5",
            idempotency_key="resolve:THREAD_5",
            reply_evidence=None,
            timestamp="2026-04-24T01:00:00Z",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("reply evidence", result["error"])
        self.assertEqual(calls, [])
        [record] = ledger.load()
        self.assertEqual(record.event_type, "side_effect_attempt")
        self.assertEqual(record.payload["side_effect_type"], "github_resolve")


if __name__ == "__main__":
    unittest.main()
