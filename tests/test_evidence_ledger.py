import hashlib
import tempfile
import unittest
from pathlib import Path


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

if __name__ == "__main__":
    unittest.main()
