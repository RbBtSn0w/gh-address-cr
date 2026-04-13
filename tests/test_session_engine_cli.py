import json

from tests.helpers import SessionEngineTestCase


class SessionEngineCLITest(SessionEngineTestCase):
    def test_init_creates_pr_session(self):
        result = self.run_engine("init", self.repo, self.pr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Initialized session", result.stdout)

        session = self.load_session()
        self.assertEqual(session["repo"], self.repo)
        self.assertEqual(session["pr_number"], self.pr)
        self.assertEqual(session["items"], {})

    def test_sync_github_upserts_threads(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "id": "THREAD_1",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/app.py",
                    "line": 12,
                    "body": "Please add a null check.",
                    "url": "https://example.test/thread/1",
                }
            ]
        )

        result = self.run_engine("sync-github", self.repo, self.pr, stdin=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Upserted 1 GitHub item", result.stdout)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_1"]
        self.assertEqual(item["item_kind"], "github_thread")
        self.assertEqual(item["status"], "OPEN")
        self.assertTrue(item["blocking"])

    def test_sync_github_marks_resolved_threads_handled(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        unresolved = json.dumps(
            [
                {
                    "id": "THREAD_RESOLVED",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/app.py",
                    "line": 12,
                    "body": "Please add a null check.",
                    "url": "https://example.test/thread/resolved",
                }
            ]
        )
        resolved = json.dumps(
            [
                {
                    "id": "THREAD_RESOLVED",
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "src/app.py",
                    "line": 12,
                    "body": "Please add a null check.",
                    "url": "https://example.test/thread/resolved",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=unresolved, check=True)
        self.run_engine("sync-github", self.repo, self.pr, stdin=resolved, check=True)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_RESOLVED"]
        self.assertEqual(item["status"], "CLOSED")
        self.assertTrue(item["handled"])
        self.assertIsNotNone(item["handled_at"])

    def test_gate_treats_stale_github_thread_as_non_unresolved(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "id": "THREAD_STALE",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/app.py",
                    "line": 12,
                    "body": "Please add a null check.",
                    "url": "https://example.test/thread/stale",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=payload, check=True)
        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_STALE",
            "STALE",
            "--note",
            "Thread became stale after a follow-up change.",
            check=True,
        )

        session = self.load_session()
        self.assertEqual(session["metrics"]["unresolved_github_threads_count"], 0)

        gate = self.run_engine("gate", self.repo, self.pr)
        self.assertEqual(gate.returncode, 0, gate.stderr)
        self.assertIn("REMOTE GATE PASS", gate.stdout)
    def test_run_local_review_deduplicates_findings(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        findings = json.dumps(
            [
                {
                    "title": "Missing nil guard",
                    "body": "A nil dereference is possible here.",
                    "path": "src/service.py",
                    "line": 33,
                    "severity": "P1",
                    "category": "correctness",
                },
                {
                    "title": "Missing nil guard",
                    "body": "A nil dereference is possible here.",
                    "path": "src/service.py",
                    "line": 33,
                    "severity": "P1",
                    "category": "correctness",
                },
            ]
        )

        first = self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=findings)
        second = self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=findings)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Created 1 local item", first.stdout)
        self.assertIn("Created 0 local item", second.stdout)

        session = self.load_session()
        local_items = [item for item in session["items"].values() if item["item_kind"] == "local_finding"]
        self.assertEqual(len(local_items), 1)
        self.assertEqual(local_items[0]["status"], "OPEN")

    def test_claim_and_update_status(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "id": "THREAD_2",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/core.py",
                    "line": 8,
                    "body": "Possible crash.",
                    "url": "https://example.test/thread/2",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=payload, check=True)

        claim = self.run_engine("claim", self.repo, self.pr, "github-thread:THREAD_2", "--agent", "fixer-1")
        self.assertEqual(claim.returncode, 0, claim.stderr)
        self.assertIn("Claimed item", claim.stdout)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_2"]
        self.assertEqual(item["status"], "CLAIMED")
        self.assertEqual(item["claimed_by"], "fixer-1")

        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_2",
            "ACCEPTED",
            "--note",
            "Confirmed and taking the fix.",
            check=True,
        )
        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_2",
            "FIXED",
            "--note",
            "Implemented the fix.",
            check=True,
        )
        update = self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_2",
            "VERIFIED",
            "--note",
            "Fixed and tested.",
        )
        self.assertEqual(update.returncode, 0, update.stderr)
        session = self.load_session()
        item = session["items"]["github-thread:THREAD_2"]
        self.assertEqual(item["status"], "VERIFIED")
        self.assertFalse(item["blocking"])

    def test_gate_fails_until_all_blocking_items_are_cleared(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        gh_payload = json.dumps(
            [
                {
                    "id": "THREAD_3",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/a.py",
                    "line": 1,
                    "body": "Fix me.",
                    "url": "https://example.test/thread/3",
                }
            ]
        )
        local_payload = json.dumps(
            [
                {
                    "title": "Unsafe cast",
                    "body": "The cast can fail at runtime.",
                    "path": "src/b.py",
                    "line": 7,
                    "severity": "P2",
                    "category": "runtime",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=gh_payload, check=True)
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)

        fail = self.run_engine("gate", self.repo, self.pr)
        self.assertEqual(fail.returncode, 1)
        self.assertIn("SESSION GATE FAIL", fail.stdout)

        self.run_engine("update-item", self.repo, self.pr, "github-thread:THREAD_3", "CLOSED", "--note", "Resolved on GitHub.", check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine("update-item", self.repo, self.pr, local_id, "ACCEPTED", "--note", "Confirmed the issue.", check=True)
        self.run_engine("update-item", self.repo, self.pr, local_id, "FIXED", "--note", "Implemented the local fix.", check=True)
        self.run_engine("update-item", self.repo, self.pr, local_id, "VERIFIED", "--note", "Fixed locally.", check=True)

        passed = self.run_engine("gate", self.repo, self.pr)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("SESSION GATE PASS", passed.stdout)

    def test_close_item_marks_local_finding_closed_and_handled(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Unsafe cast",
                    "body": "The cast can fail at runtime.",
                    "path": "src/b.py",
                    "line": 7,
                    "severity": "P2",
                    "category": "runtime",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")

        closed = self.run_engine("close-item", self.repo, self.pr, local_id, "--note", "Resolved locally.")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertIn("Closed item", closed.stdout)

        session = self.load_session()
        item = session["items"][local_id]
        self.assertEqual(item["status"], "CLOSED")
        self.assertFalse(item["blocking"])
        self.assertTrue(item["handled"])

    def test_resolve_local_item_fix_closes_atomically_and_clears_claim(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Unsafe cast",
                    "body": "The cast can fail at runtime.",
                    "path": "src/b.py",
                    "line": 7,
                    "severity": "P2",
                    "category": "runtime",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine("claim", self.repo, self.pr, local_id, "--agent", "fixer-1", check=True)

        resolved = self.run_engine(
            "resolve-local-item",
            self.repo,
            self.pr,
            local_id,
            "fix",
            "--note",
            "Fixed locally and verified.",
        )
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertIn("Resolved local item", resolved.stdout)

        session = self.load_session()
        item = session["items"][local_id]
        self.assertEqual(item["status"], "CLOSED")
        self.assertEqual(item["decision"], "accept")
        self.assertTrue(item["handled"])
        self.assertIsNone(item["claimed_by"])
        self.assertIsNone(item["lease_expires_at"])

    def test_update_item_terminal_local_status_clears_claim_and_marks_handled(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Clarify behavior",
                    "body": "This is expected behavior.",
                    "path": "src/c.py",
                    "line": 9,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine("claim", self.repo, self.pr, local_id, "--agent", "fixer-1", check=True)
        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            local_id,
            "CLARIFIED",
            "--note",
            "Expected behavior; no code change needed.",
            check=True,
        )

        session = self.load_session()
        item = session["items"][local_id]
        self.assertEqual(item["status"], "CLARIFIED")
        self.assertTrue(item["handled"])
        self.assertIsNone(item["claimed_by"])
        self.assertIsNone(item["lease_expires_at"])

    def test_update_item_rejects_illegal_transition(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "id": "THREAD_4",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/core.py",
                    "line": 8,
                    "body": "Possible crash.",
                    "url": "https://example.test/thread/4",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=payload, check=True)

        bad = self.run_engine("update-item", self.repo, self.pr, "github-thread:THREAD_4", "VERIFIED")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("Illegal status transition", bad.stderr)

    def test_update_item_requires_note_for_deferred(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "id": "THREAD_5",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/core.py",
                    "line": 10,
                    "body": "Style issue.",
                    "url": "https://example.test/thread/5",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=payload, check=True)

        bad = self.run_engine("update-item", self.repo, self.pr, "github-thread:THREAD_5", "DEFERRED")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("requires --note", bad.stderr)

    def test_mark_published_updates_local_finding(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Unsafe cast",
                    "body": "The cast can fail at runtime.",
                    "path": "src/b.py",
                    "line": 7,
                    "severity": "P2",
                    "category": "runtime",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")

        published = self.run_engine(
            "mark-published",
            self.repo,
            self.pr,
            local_id,
            "--published-ref",
            "comment-123",
            "--url",
            "https://example.test/comment/123",
            "--note",
            "Published to GitHub review comments.",
        )
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertIn("Marked published", published.stdout)

        session = self.load_session()
        item = session["items"][local_id]
        self.assertEqual(item["status"], "PUBLISHED")
        self.assertTrue(item["published"])
        self.assertEqual(item["published_ref"], "comment-123")
        self.assertEqual(item["url"], "https://example.test/comment/123")

    def test_repeated_local_finding_increments_repeat_count(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Repeated issue",
                    "body": "This keeps showing up.",
                    "path": "src/repeat.py",
                    "line": 5,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)

        session = self.load_session()
        item = next(item for item in session["items"].values() if item["item_kind"] == "local_finding")
        self.assertEqual(item["repeat_count"], 1)

    def test_reopen_item_increments_reopen_count(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Deferred issue",
                    "body": "Can be revisited.",
                    "path": "src/reopen.py",
                    "line": 3,
                    "severity": "P3",
                    "category": "style",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        session = self.load_session()
        item_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine("update-item", self.repo, self.pr, item_id, "DEFERRED", "--note", "Deferring for later.", check=True)
        self.run_engine("update-item", self.repo, self.pr, item_id, "OPEN", "--note", "Reopened after follow-up review.", check=True)

        session = self.load_session()
        item = session["items"][item_id]
        self.assertEqual(item["status"], "OPEN")
        self.assertEqual(item["reopen_count"], 1)

    def test_reclaim_stale_claims_releases_expired_lease(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "id": "THREAD_6",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/claim.py",
                    "line": 22,
                    "body": "Need ownership handling.",
                    "url": "https://example.test/thread/6",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=payload, check=True)
        self.run_engine("claim", self.repo, self.pr, "github-thread:THREAD_6", "--agent", "fixer-1", "--minutes", "-1", check=True)

        reclaimed = self.run_engine("reclaim-stale-claims", self.repo, self.pr)
        self.assertEqual(reclaimed.returncode, 0, reclaimed.stderr)
        self.assertIn("Reclaimed 1 stale claim", reclaimed.stdout)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_6"]
        self.assertIsNone(item["claimed_by"])
        self.assertEqual(item["status"], "OPEN")

    def test_claim_rejects_closed_item(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "id": "THREAD_CLOSED",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/closed.py",
                    "line": 14,
                    "body": "Already handled.",
                    "url": "https://example.test/thread/closed",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=payload, check=True)
        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_CLOSED",
            "CLOSED",
            "--note",
            "Resolved on GitHub.",
            check=True,
        )

        claimed = self.run_engine("claim", self.repo, self.pr, "github-thread:THREAD_CLOSED", "--agent", "fixer-1")
        self.assertNotEqual(claimed.returncode, 0)
        self.assertIn("Illegal status transition", claimed.stderr)

    def test_resolve_local_item_defer_reports_deferred_note_requirement(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Deferred issue",
                    "body": "Can be revisited.",
                    "path": "src/defer.py",
                    "line": 4,
                    "severity": "P3",
                    "category": "style",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")

        deferred = self.run_engine(
            "resolve-local-item",
            self.repo,
            self.pr,
            local_id,
            "defer",
            "--note",
            "",
        )
        self.assertNotEqual(deferred.returncode, 0)
        self.assertIn("Status DEFERRED requires --note", deferred.stderr)

    def test_sync_github_closes_published_local_finding_when_thread_appears(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Published issue",
                    "body": "This was posted to GitHub.",
                    "path": "src/map.py",
                    "line": 11,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine(
            "mark-published",
            self.repo,
            self.pr,
            local_id,
            "--published-ref",
            "comment-456",
            "--url",
            "https://example.test/comment/456",
            "--note",
            "Published upstream.",
            check=True,
        )

        gh_payload = json.dumps(
            [
                {
                    "id": "THREAD_7",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 11,
                    "body": "This was posted to GitHub.",
                    "url": "https://example.test/comment/456",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=gh_payload, check=True)

        session = self.load_session()
        local_item = session["items"][local_id]
        self.assertEqual(local_item["status"], "CLOSED")
        self.assertTrue(local_item["handled"])
        self.assertEqual(local_item["linked_github_item_id"], "github-thread:THREAD_7")

    def test_gate_fails_when_loop_threshold_is_exceeded(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Threshold issue",
                    "body": "This keeps resurfacing.",
                    "path": "src/loop.py",
                    "line": 9,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)

        gated = self.run_engine("gate", self.repo, self.pr)
        self.assertNotEqual(gated.returncode, 0)
        self.assertIn("loop_warning_items_count=1", gated.stdout)
