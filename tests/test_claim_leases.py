import unittest
from datetime import datetime, timedelta, timezone

from gh_address_cr.core.leases import (
    LeaseConflictError,
    LeaseSubmissionError,
    accept_lease,
    calculate_conflict_keys,
    calculate_lease_recovery_state,
    claim_lease,
    expire_leases,
    reclaim_lease,
    reject_lease,
    release_lease,
    submit_lease,
)

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)


def make_session():
    return {"items": {}, "leases": {}, "lease_events": []}


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


class LeaseRecoveryOutcomeTest(unittest.TestCase):
    def test_active_valid_lease_reports_no_stale_recovery(self):
        session = make_session()
        item = make_item("active-item", path="src/active.py")
        item["state"] = "claimed"
        session["items"][item["item_id"]] = item
        lease = claim_lease(
            session,
            item,
            agent_id="agent-a",
            role="fixer",
            request_hash="hash-current",
            lease_id="lease-active",
            ttl_seconds=3600,
            now=NOW,
        )

        recovery = calculate_lease_recovery_state(
            session,
            lease.lease_id,
            agent_id="agent-a",
            role="fixer",
            item_id=item["item_id"],
            request_hash="hash-current",
            now=NOW + timedelta(seconds=1),
        )

        self.assertEqual(recovery.recovery_outcome, "stop")
        self.assertEqual(recovery.reason_code, "LEASE_ACTIVE")
        self.assertIsNone(recovery.resume_command)

    def test_falsy_lease_fields_fail_closed_without_collapsing_numeric_values(self):
        session = make_session()
        item = make_item("fallback-item", path="src/fallback.py")
        item["state"] = "claimed"
        session["items"][item["item_id"]] = item
        session["leases"]["lease-falsy"] = {
            "lease_id": "lease-falsy",
            "item_id": 0,
            "agent_id": 0,
            "role": "fixer",
            "status": False,
            "request_id": 0,
            "request_hash": 0,
            "expires_at": NOW + timedelta(hours=1),
        }
        session["items"]["0"] = make_item("0", path="src/zero.py")

        recovery = calculate_lease_recovery_state(
            session,
            "lease-falsy",
            agent_id="agent-a",
            role="fixer",
            item_id="fallback-item",
            request_hash="hash-current",
            now=NOW,
        )

        self.assertEqual(recovery.lease_status, "unknown")
        self.assertEqual(recovery.item_id, "0")
        self.assertEqual(recovery.agent_id, "0")
        self.assertEqual(recovery.request_id, "0")
        self.assertEqual(recovery.request_hash, "0")
        self.assertEqual(recovery.reason_code, "LEASE_RECOVERY_STOP")

    def test_expired_active_submission_returns_renew_recovery(self):
        session = make_session()
        item = make_item("renew-item", path="src/renew.py")
        item["state"] = "claimed"
        session["items"][item["item_id"]] = item
        lease = claim_lease(
            session,
            item,
            agent_id="agent-a",
            role="fixer",
            request_hash="hash-current",
            lease_id="lease-renew",
            ttl_seconds=1,
            now=NOW,
        )

        with self.assertRaises(LeaseSubmissionError) as caught:
            submit_lease(
                session,
                lease.lease_id,
                agent_id="agent-a",
                role="fixer",
                item_id=item["item_id"],
                request_hash="hash-current",
                now=NOW + timedelta(seconds=2),
            )

        recovery = caught.exception.recovery_state
        self.assertEqual(caught.exception.reason_code, "EXPIRED_LEASE")
        self.assertEqual(recovery["recovery_outcome"], "renew")
        self.assertEqual(recovery["reason_code"], "EXPIRED_LEASE_RENEWABLE")
        self.assertEqual(session["items"][item["item_id"]]["state"], "open")

    def test_expired_active_submission_with_stale_request_hash_refreshes_state(self):
        session = make_session()
        item = make_item("expired-stale-item", path="src/expired_stale.py")
        item["state"] = "claimed"
        session["items"][item["item_id"]] = item
        lease = claim_lease(
            session,
            item,
            agent_id="agent-a",
            role="fixer",
            request_hash="hash-current",
            lease_id="lease-expired-stale",
            ttl_seconds=1,
            now=NOW,
        )

        with self.assertRaises(LeaseSubmissionError) as caught:
            submit_lease(
                session,
                lease.lease_id,
                agent_id="agent-a",
                role="fixer",
                item_id=item["item_id"],
                request_hash="hash-stale",
                now=NOW + timedelta(seconds=2),
            )

        recovery = caught.exception.recovery_state
        self.assertEqual(caught.exception.reason_code, "EXPIRED_LEASE")
        self.assertEqual(recovery["recovery_outcome"], "refresh_state")
        self.assertEqual(recovery["reason_code"], "STALE_REQUEST_CONTEXT")

    def test_wrong_agent_expired_submission_stops_instead_of_renewing(self):
        session = make_session()
        item = make_item("wrong-agent-item", path="src/wrong.py")
        item["state"] = "claimed"
        session["items"][item["item_id"]] = item
        lease = claim_lease(
            session,
            item,
            agent_id="agent-a",
            role="fixer",
            request_hash="hash-current",
            lease_id="lease-wrong-agent",
            ttl_seconds=1,
            now=NOW,
        )

        with self.assertRaises(LeaseSubmissionError) as caught:
            submit_lease(
                session,
                lease.lease_id,
                agent_id="agent-b",
                role="fixer",
                item_id=item["item_id"],
                request_hash="hash-current",
                now=NOW + timedelta(seconds=2),
            )

        self.assertEqual(caught.exception.reason_code, "WRONG_AGENT")
        self.assertEqual(caught.exception.recovery_state["recovery_outcome"], "stop")
        self.assertEqual(caught.exception.recovery_state["reason_code"], "LEASE_RECOVERY_STOP")
        self.assertNotIn("resume_command", caught.exception.recovery_state)

    def test_stale_request_context_returns_refresh_state_recovery(self):
        session = make_session()
        item = make_item("stale-item", path="src/stale.py")
        item["state"] = "claimed"
        session["items"][item["item_id"]] = item
        lease = claim_lease(
            session,
            item,
            agent_id="agent-a",
            role="fixer",
            request_hash="hash-old",
            lease_id="lease-stale",
            now=NOW,
        )

        with self.assertRaises(LeaseSubmissionError) as caught:
            submit_lease(
                session,
                lease.lease_id,
                agent_id="agent-a",
                role="fixer",
                item_id=item["item_id"],
                request_hash="hash-current",
                now=NOW + timedelta(seconds=1),
            )

        recovery = caught.exception.recovery_state
        self.assertEqual(caught.exception.reason_code, "STALE_REQUEST_CONTEXT")
        self.assertEqual(recovery["recovery_outcome"], "refresh_state")
        self.assertEqual(recovery["reason_code"], "STALE_REQUEST_CONTEXT")

    def test_terminal_and_transferred_leases_return_stop_or_completed_recovery(self):
        completed_session = make_session()
        completed_item = make_item("completed-item", path="src/completed.py")
        completed_item.update({"state": "handled", "handled": True})
        completed_session["items"][completed_item["item_id"]] = completed_item
        completed = claim_lease(
            completed_session,
            completed_item,
            agent_id="agent-a",
            role="fixer",
            request_hash="hash-current",
            lease_id="lease-completed",
            now=NOW,
        )
        submit_lease(
            completed_session,
            completed.lease_id,
            agent_id="agent-a",
            role="fixer",
            item_id=completed_item["item_id"],
            request_hash="hash-current",
            now=NOW + timedelta(seconds=1),
        )
        accept_lease(completed_session, completed.lease_id, now=NOW + timedelta(seconds=2))

        completed_recovery = calculate_lease_recovery_state(
            completed_session,
            completed.lease_id,
            agent_id="agent-a",
            role="fixer",
            item_id=completed_item["item_id"],
            request_hash="hash-current",
            now=NOW + timedelta(seconds=3),
        )
        self.assertEqual(completed_recovery.recovery_outcome, "already_completed")
        self.assertEqual(completed_recovery.reason_code, "LEASE_ALREADY_COMPLETED")

        transferred_session = make_session()
        transferred_item = make_item("transferred-item", path="src/transferred.py")
        transferred_item.update({"state": "claimed", "claimed_by": "agent-b"})
        transferred_session["items"][transferred_item["item_id"]] = transferred_item
        expired = claim_lease(
            transferred_session,
            transferred_item,
            agent_id="agent-a",
            role="fixer",
            request_hash="hash-current",
            lease_id="lease-transferred",
            ttl_seconds=1,
            now=NOW,
        )
        expire_leases(transferred_session, now=NOW + timedelta(seconds=2))

        transferred_recovery = calculate_lease_recovery_state(
            transferred_session,
            expired.lease_id,
            agent_id="agent-a",
            role="fixer",
            item_id=transferred_item["item_id"],
            request_hash="hash-current",
            now=NOW + timedelta(seconds=3),
        )
        self.assertEqual(transferred_recovery.recovery_outcome, "stop")
        self.assertEqual(transferred_recovery.reason_code, "LEASE_RECOVERY_STOP")
        self.assertIsNone(transferred_recovery.resume_command)

    def test_expired_lease_stops_when_item_has_new_active_lease_owner(self):
        session = make_session()
        item = make_item("transferred-active-item", path="src/transferred-active.py")
        item.update({"state": "claimed", "active_lease_id": "lease-new"})
        session["items"][item["item_id"]] = item
        old = claim_lease(
            session,
            item,
            agent_id="agent-old",
            role="fixer",
            request_hash="hash-old",
            lease_id="lease-old",
            ttl_seconds=1,
            now=NOW,
        )
        expire_leases(session, now=NOW + timedelta(seconds=2))
        claim_lease(
            session,
            item,
            agent_id="agent-new",
            role="fixer",
            request_hash="hash-new",
            lease_id="lease-new",
            now=NOW + timedelta(seconds=3),
        )

        recovery = calculate_lease_recovery_state(
            session,
            old.lease_id,
            agent_id="agent-old",
            role="fixer",
            item_id=item["item_id"],
            request_hash="hash-old",
            now=NOW + timedelta(seconds=4),
        )

        self.assertEqual(recovery.recovery_outcome, "stop")
        self.assertEqual(recovery.reason_code, "LEASE_RECOVERY_STOP")
        self.assertIsNone(recovery.resume_command)


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

        wrong_item_expired_session = make_session()
        wrong_item = make_item("wrong-expired-item", path="src/wrong_expired.py")
        wrong_item_expired_session["items"][wrong_item["item_id"]] = wrong_item
        wrong_expired = claim_lease(
            wrong_item_expired_session,
            wrong_item,
            agent_id="agent-w",
            role="fixer",
            request_hash="req-wrong-expired",
            lease_id="lease-wrong-expired",
            ttl_seconds=1,
            now=NOW,
        )

        with self.assertRaisesRegex(LeaseSubmissionError, "WRONG_ITEM"):
            submit_lease(
                wrong_item_expired_session,
                wrong_expired.lease_id,
                agent_id="agent-w",
                role="fixer",
                item_id="different-item",
                request_hash="req-wrong-expired",
                now=NOW + timedelta(seconds=2),
            )
        self.assertEqual(wrong_expired.status, "active")

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
