import unittest
from datetime import datetime, timedelta, timezone

from gh_address_cr.core.leases import (
    LeaseConflictError,
    LeaseSubmissionError,
    accept_lease,
    calculate_conflict_keys,
    claim_lease,
    expire_leases,
    reclaim_lease,
    reject_lease,
    release_lease,
    submit_lease,
)


NOW = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)


def make_session():
    return {"leases": {}, "lease_events": []}


def make_item(item_id, path=None, conflict_keys=(), item_kind="local_finding", thread_id=None):
    item = {
        "item_id": item_id,
        "item_kind": item_kind,
        "title": f"Item {item_id}",
        "conflict_keys": list(conflict_keys),
    }
    if path is not None:
        item["path"] = path
    if thread_id is not None:
        item["thread_id"] = thread_id
    return item


class ClaimLeaseLifecycleTest(unittest.TestCase):
    def test_lifecycle_transitions_cover_active_submitted_and_terminal_states(self):
        session = make_session()

        released = claim_lease(
            session,
            make_item("item-release", path="src/release.py"),
            agent_id="agent-a",
            role="fixer",
            request_hash="req-release",
            lease_id="lease-release",
            now=NOW,
        )
        self.assertEqual(released.status, "active")

        release_lease(session, "lease-release", now=NOW + timedelta(seconds=1), reason="agent stopped")
        self.assertEqual(released.status, "released")

        accepted = claim_lease(
            session,
            make_item("item-accept", path="src/accept.py"),
            agent_id="agent-b",
            role="fixer",
            request_hash="req-accept",
            lease_id="lease-accept",
            now=NOW,
        )
        submit_lease(
            session,
            "lease-accept",
            agent_id="agent-b",
            role="fixer",
            item_id="item-accept",
            request_hash="req-accept",
            now=NOW + timedelta(seconds=2),
        )
        self.assertEqual(accepted.status, "submitted")

        accept_lease(session, "lease-accept", now=NOW + timedelta(seconds=3))
        self.assertEqual(accepted.status, "accepted")

        expired = claim_lease(
            session,
            make_item("item-expire", path="src/expire.py"),
            agent_id="agent-c",
            role="fixer",
            request_hash="req-expire",
            lease_id="lease-expire",
            ttl_seconds=1,
            now=NOW,
        )
        expire_leases(session, now=NOW + timedelta(seconds=2))
        self.assertEqual(expired.status, "expired")

        rejected = claim_lease(
            session,
            make_item("item-reject", path="src/reject.py"),
            agent_id="agent-d",
            role="fixer",
            request_hash="req-reject",
            lease_id="lease-reject",
            now=NOW,
        )
        reject_lease(session, "lease-reject", now=NOW + timedelta(seconds=4), reason="invalid evidence")
        self.assertEqual(rejected.status, "rejected")

        event_types = [event["event_type"] for event in session["lease_events"]]
        self.assertIn("lease_released", event_types)
        self.assertIn("lease_submitted", event_types)
        self.assertIn("lease_accepted", event_types)
        self.assertIn("lease_expired", event_types)
        self.assertIn("lease_rejected", event_types)

    def test_reclaim_expired_lease_preserves_accepted_evidence(self):
        session = make_session()
        accepted = claim_lease(
            session,
            make_item("accepted-item", path="src/accepted.py"),
            agent_id="agent-a",
            role="fixer",
            request_hash="req-accepted",
            lease_id="lease-accepted",
            now=NOW,
        )
        submit_lease(
            session,
            "lease-accepted",
            agent_id="agent-a",
            role="fixer",
            item_id="accepted-item",
            request_hash="req-accepted",
            now=NOW + timedelta(seconds=1),
        )
        accept_lease(session, "lease-accepted", now=NOW + timedelta(seconds=2))

        stale = claim_lease(
            session,
            make_item("stale-item", path="src/stale.py"),
            agent_id="agent-b",
            role="fixer",
            request_hash="req-stale-old",
            lease_id="lease-stale-old",
            ttl_seconds=1,
            now=NOW,
        )

        replacement = reclaim_lease(
            session,
            make_item("stale-item", path="src/stale.py"),
            agent_id="agent-c",
            role="fixer",
            request_hash="req-stale-new",
            lease_id="lease-stale-new",
            now=NOW + timedelta(seconds=5),
        )

        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(stale.status, "expired")
        self.assertEqual(replacement.status, "active")
        self.assertEqual(replacement.agent_id, "agent-c")


class ClaimLeaseConflictTest(unittest.TestCase):
    def test_rejects_duplicate_active_lease_for_same_item(self):
        session = make_session()
        item = make_item("same-item", path="src/same.py")

        claim_lease(
            session,
            item,
            agent_id="agent-a",
            role="fixer",
            request_hash="req-a",
            lease_id="lease-a",
            now=NOW,
        )

        with self.assertRaisesRegex(LeaseConflictError, "ITEM_ALREADY_LEASED"):
            claim_lease(
                session,
                item,
                agent_id="agent-b",
                role="fixer",
                request_hash="req-b",
                lease_id="lease-b",
                now=NOW,
            )

    def test_rejects_overlapping_write_conflict_keys_and_allows_read_only_overlap(self):
        write_session = make_session()
        claim_lease(
            write_session,
            make_item("write-a", path="src/shared.py"),
            agent_id="fixer-a",
            role="fixer",
            request_hash="req-write-a",
            lease_id="lease-write-a",
            now=NOW,
        )

        with self.assertRaisesRegex(LeaseConflictError, "CONFLICT_KEYS_OVERLAP"):
            claim_lease(
                write_session,
                make_item("write-b", path="src/shared.py"),
                agent_id="fixer-b",
                role="fixer",
                request_hash="req-write-b",
                lease_id="lease-write-b",
                now=NOW,
            )

        read_only_session = make_session()
        claim_lease(
            read_only_session,
            make_item("read-a", path="src/shared.py"),
            agent_id="triage-a",
            role="triage",
            request_hash="req-read-a",
            lease_id="lease-read-a",
            now=NOW,
        )

        read_only = claim_lease(
            read_only_session,
            make_item("read-b", path="src/shared.py"),
            agent_id="verifier-b",
            role="verifier",
            request_hash="req-read-b",
            lease_id="lease-read-b",
            now=NOW,
        )

        self.assertEqual(read_only.status, "active")

    def test_allows_concurrent_independent_write_leases(self):
        session = make_session()
        leases = [
            claim_lease(
                session,
                make_item(f"item-{index}", path=f"src/file_{index}.py"),
                agent_id=f"agent-{index}",
                role="fixer",
                request_hash=f"req-{index}",
                lease_id=f"lease-{index}",
                now=NOW,
            )
            for index in range(3)
        ]

        self.assertEqual([lease.status for lease in leases], ["active", "active", "active"])
        self.assertEqual(len(session["leases"]), 3)

    def test_calculates_conflict_keys_for_item_file_thread_and_github_side_effects(self):
        keys = calculate_conflict_keys(
            make_item(
                "thread-item",
                path="./src/../src/thread.py",
                item_kind="github_thread",
                thread_id="PRRT_123",
                conflict_keys=["custom:docs"],
            )
        )

        self.assertIn("item:thread-item", keys)
        self.assertIn("file:src/thread.py", keys)
        self.assertIn("thread:PRRT_123", keys)
        self.assertIn("github_reply:PRRT_123", keys)
        self.assertIn("github_resolve:PRRT_123", keys)
        self.assertIn("custom:docs", keys)


class ClaimLeaseSubmissionTest(unittest.TestCase):
    def test_rejects_duplicate_stale_expired_and_cross_role_submissions(self):
        duplicate_session = make_session()
        duplicate = claim_lease(
            duplicate_session,
            make_item("duplicate-item", path="src/duplicate.py"),
            agent_id="agent-a",
            role="fixer",
            request_hash="req-duplicate",
            lease_id="lease-duplicate",
            now=NOW,
        )
        submit_lease(
            duplicate_session,
            "lease-duplicate",
            agent_id="agent-a",
            role="fixer",
            item_id="duplicate-item",
            request_hash="req-duplicate",
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(duplicate.status, "submitted")

        with self.assertRaisesRegex(LeaseSubmissionError, "DUPLICATE_SUBMISSION"):
            submit_lease(
                duplicate_session,
                "lease-duplicate",
                agent_id="agent-a",
                role="fixer",
                item_id="duplicate-item",
                request_hash="req-duplicate",
                now=NOW + timedelta(seconds=2),
            )

        stale_session = make_session()
        stale = claim_lease(
            stale_session,
            make_item("stale-item", path="src/stale.py"),
            agent_id="agent-b",
            role="fixer",
            request_hash="req-stale",
            lease_id="lease-stale",
            now=NOW,
        )
        release_lease(stale_session, "lease-stale", now=NOW + timedelta(seconds=1), reason="agent cancelled")
        self.assertEqual(stale.status, "released")

        with self.assertRaisesRegex(LeaseSubmissionError, "STALE_LEASE"):
            submit_lease(
                stale_session,
                "lease-stale",
                agent_id="agent-b",
                role="fixer",
                item_id="stale-item",
                request_hash="req-stale",
                now=NOW + timedelta(seconds=2),
            )

        expired_session = make_session()
        expired = claim_lease(
            expired_session,
            make_item("expired-item", path="src/expired.py"),
            agent_id="agent-c",
            role="fixer",
            request_hash="req-expired",
            lease_id="lease-expired",
            ttl_seconds=1,
            now=NOW,
        )

        with self.assertRaisesRegex(LeaseSubmissionError, "EXPIRED_LEASE"):
            submit_lease(
                expired_session,
                "lease-expired",
                agent_id="agent-c",
                role="fixer",
                item_id="expired-item",
                request_hash="req-expired",
                now=NOW + timedelta(seconds=2),
            )
        self.assertEqual(expired.status, "expired")

        cross_role_session = make_session()
        cross_role = claim_lease(
            cross_role_session,
            make_item("cross-role-item", path="src/cross_role.py"),
            agent_id="agent-d",
            role="fixer",
            request_hash="req-cross-role",
            lease_id="lease-cross-role",
            now=NOW,
        )

        with self.assertRaisesRegex(LeaseSubmissionError, "CROSS_ROLE_SUBMISSION"):
            submit_lease(
                cross_role_session,
                "lease-cross-role",
                agent_id="agent-d",
                role="verifier",
                item_id="cross-role-item",
                request_hash="req-cross-role",
                now=NOW + timedelta(seconds=1),
            )
        self.assertEqual(cross_role.status, "active")


if __name__ == "__main__":
    unittest.main()
