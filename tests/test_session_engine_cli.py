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
        self.assertEqual(session["loop_state"]["status"], "IDLE")

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

    def test_sync_github_reopened_thread_becomes_unhandled_again(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        resolved = json.dumps(
            [
                {
                    "id": "THREAD_REOPENED",
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "src/app.py",
                    "line": 12,
                    "body": "Please add a null check.",
                    "url": "https://example.test/thread/reopened",
                }
            ]
        )
        reopened = json.dumps(
            [
                {
                    "id": "THREAD_REOPENED",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/app.py",
                    "line": 12,
                    "body": "Please add a null check.",
                    "url": "https://example.test/thread/reopened",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=resolved, check=True)
        self.run_engine("sync-github", self.repo, self.pr, stdin=reopened, check=True)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_REOPENED"]
        self.assertEqual(item["status"], "OPEN")
        self.assertFalse(item["handled"])
        self.assertIsNone(item["handled_at"])
        self.assertEqual(item["reopen_count"], 1)

    def test_gate_treats_stale_github_thread_as_unresolved(self):
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
        self.assertEqual(session["metrics"]["unresolved_github_threads_count"], 1)

        gate = self.run_engine("gate", self.repo, self.pr)
        self.assertNotEqual(gate.returncode, 0, gate.stderr)
        self.assertIn("REMOTE GATE FAIL", gate.stdout)

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

    def test_run_local_review_ignores_whitespace_only_finding_differences(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        first_payload = json.dumps(
            [
                {
                    "title": "Missing nil guard",
                    "body": "A nil dereference is possible here.",
                    "path": "src/service.py",
                    "line": 33,
                    "severity": "P1",
                    "category": "correctness",
                }
            ]
        )
        second_payload = json.dumps(
            [
                {
                    "title": "Missing  nil   guard",
                    "body": "A nil dereference is possible here.\n\n",
                    "path": "src/service.py",
                    "line": 33,
                    "severity": "P1",
                    "category": "correctness",
                }
            ]
        )

        first = self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=first_payload)
        second = self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=second_payload)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Created 1 local item", first.stdout)
        self.assertIn("Created 0 local item", second.stdout)

    def test_sync_local_finding_reopens_closed_item_when_it_reappears(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Recurring issue",
                    "body": "This keeps showing up.",
                    "path": "src/recurring.py",
                    "line": 17,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )

        first = self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", "--sync", stdin=payload)
        self.assertEqual(first.returncode, 0, first.stderr)
        session = self.load_session()
        item_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine("update-item", self.repo, self.pr, item_id, "CLOSED", "--note", "Resolved after review.", check=True)

        second = self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", "--sync", stdin=payload)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Synced 0 missing local item(s) to CLOSED.", second.stdout)

        session = self.load_session()
        item = session["items"][item_id]
        self.assertEqual(item["status"], "OPEN")
        self.assertTrue(item["blocking"])
        self.assertEqual(item["reopen_count"], 1)
        self.assertFalse(item["handled"])
        self.assertIsNone(item["handled_at"])

        session = self.load_session()
        local_items = [item for item in session["items"].values() if item["item_kind"] == "local_finding"]
        self.assertEqual(len(local_items), 1)
        self.assertEqual(local_items[0]["repeat_count"], 1)

    def test_ingest_local_sync_closes_missing_same_source_items(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        initial = json.dumps(
            [
                {
                    "title": "Keep me",
                    "body": "Still present.",
                    "path": "src/keep.py",
                    "line": 3,
                    "severity": "P2",
                    "category": "correctness",
                },
                {
                    "title": "Close me",
                    "body": "Will disappear from the next snapshot.",
                    "path": "src/close.py",
                    "line": 7,
                    "severity": "P2",
                    "category": "correctness",
                },
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=initial, check=True)

        refreshed = json.dumps(
            [
                {
                    "title": "Keep me",
                    "body": "Still present.",
                    "path": "src/keep.py",
                    "line": 3,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        result = self.run_engine(
            "ingest-local",
            self.repo,
            self.pr,
            "--source",
            "local-agent:test",
            "--sync",
            stdin=refreshed,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Existing active local item(s): 1", result.stdout)
        self.assertIn("Synced 1 missing local item(s) to CLOSED.", result.stdout)

        session = self.load_session()
        keep_item = next(item for item in session["items"].values() if item["path"] == "src/keep.py")
        close_item = next(item for item in session["items"].values() if item["path"] == "src/close.py")
        self.assertEqual(keep_item["status"], "OPEN")
        self.assertEqual(close_item["status"], "CLOSED")
        self.assertTrue(close_item["handled"])

    def test_ingest_local_sync_keeps_identical_findings_scoped_per_source(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Shared finding",
                    "body": "Two producers reported the same issue.",
                    "path": "src/shared.py",
                    "line": 11,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:a", stdin=payload, check=True)
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:b", stdin=payload, check=True)

        synced = self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:a", "--sync", stdin="[]")
        self.assertEqual(synced.returncode, 0, synced.stderr)
        self.assertIn("Synced 1 missing local item(s) to CLOSED.", synced.stdout)

        session = self.load_session()
        local_items = [item for item in session["items"].values() if item["item_kind"] == "local_finding"]
        self.assertEqual(len(local_items), 2)
        closed_item = next(item for item in local_items if item["source"] == "local-agent:a")
        open_item = next(item for item in local_items if item["source"] == "local-agent:b")
        self.assertEqual(closed_item["status"], "CLOSED")
        self.assertEqual(open_item["status"], "OPEN")

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

    def test_update_item_reopen_clears_claim_and_reenables_selection(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Reopen me",
                    "body": "This finding should come back after reopening.",
                    "path": "src/reopen.py",
                    "line": 11,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=local_payload, check=True)
        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine("claim", self.repo, self.pr, local_id, "--agent", "fixer-1", check=True)
        self.run_engine("update-item", self.repo, self.pr, local_id, "CLOSED", "--note", "Temporarily closed.", check=True)

        reopen = self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            local_id,
            "OPEN",
            "--note",
            "Reopened after resurfacing.",
        )
        self.assertEqual(reopen.returncode, 0, reopen.stderr)

        session = self.load_session()
        item = session["items"][local_id]
        self.assertEqual(item["status"], "OPEN")
        self.assertTrue(item["blocking"])
        self.assertFalse(item["handled"])
        self.assertIsNone(item["claimed_by"])
        self.assertIsNone(item["lease_expires_at"])
        self.assertFalse(item["needs_human"])

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

    def test_gate_summary_reports_current_run_counts_not_lifetime_totals(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        gh_payload = json.dumps(
            [
                {
                    "id": "THREAD_3A",
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "src/a.py",
                    "line": 1,
                    "body": "Fix me first.",
                    "url": "https://example.test/thread/3a",
                },
                {
                    "id": "THREAD_3B",
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "src/b.py",
                    "line": 2,
                    "body": "Fix me second.",
                    "url": "https://example.test/thread/3b",
                },
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, "--scan-id", "seed-run", stdin=gh_payload, check=True)
        self.run_engine("sync-github", self.repo, self.pr, "--scan-id", "current-run", stdin=gh_payload, check=True)

        gated = self.run_engine("gate", self.repo, self.pr)
        self.assertEqual(gated.returncode, 0, gated.stderr)
        self.assertIn("tracked_items_count=2", gated.stdout)
        self.assertIn("handled_items_count=2", gated.stdout)
        self.assertIn("github_threads_total_count=2", gated.stdout)
        self.assertIn("github_threads_new_count=0", gated.stdout)
        self.assertIn("github_threads_handled_this_run_count=0", gated.stdout)
        self.assertIn("github_threads_unresolved_count=0", gated.stdout)
        self.assertIn("local_findings_total_count=0", gated.stdout)
        self.assertIn("local_findings_new_count=0", gated.stdout)
        self.assertIn("local_findings_handled_this_run_count=0", gated.stdout)
        self.assertIn("local_findings_unresolved_count=0", gated.stdout)

        summary = (self.workspace_dir() / "audit_summary.md").read_text(encoding="utf-8")
        self.assertNotIn("## Current Run Snapshot", summary)
        self.assertNotIn("- GitHub threads: total 2;", summary)
        self.assertNotIn("- Local findings: total 0;", summary)

    def test_gate_summary_omits_current_run_progress_block(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        gh_seed_payload = json.dumps(
            [
                {
                    "id": "THREAD_EXISTING",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/existing.py",
                    "line": 1,
                    "body": "Existing thread.",
                    "url": "https://example.test/thread/existing",
                }
            ]
        )
        local_seed_payload = json.dumps(
            [
                {
                    "title": "Existing local finding",
                    "body": "Needs a fix.",
                    "path": "src/local.py",
                    "line": 3,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, "--scan-id", "seed-run", stdin=gh_seed_payload, check=True)
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", "--scan-id", "seed-run", stdin=local_seed_payload, check=True)

        gh_current_payload = json.dumps(
            [
                {
                    "id": "THREAD_EXISTING",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/existing.py",
                    "line": 1,
                    "body": "Existing thread.",
                    "url": "https://example.test/thread/existing",
                },
                {
                    "id": "THREAD_NEW",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/new.py",
                    "line": 7,
                    "body": "New thread.",
                    "url": "https://example.test/thread/new",
                },
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, "--scan-id", "current-run", stdin=gh_current_payload, check=True)
        self.run_engine("update-item", self.repo, self.pr, "github-thread:THREAD_EXISTING", "CLOSED", "--note", "Resolved on GitHub.", check=True)
        self.run_engine("update-item", self.repo, self.pr, "github-thread:THREAD_NEW", "CLOSED", "--note", "Resolved on GitHub.", check=True)

        session = self.load_session()
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        self.run_engine(
            "resolve-local-item",
            self.repo,
            self.pr,
            local_id,
            "fix",
            "--note",
            "Resolved in current run.",
            check=True,
        )

        gated = self.run_engine("gate", self.repo, self.pr)
        self.assertEqual(gated.returncode, 0, gated.stderr)
        self.assertIn("github_threads_total_count=2", gated.stdout)
        self.assertIn("github_threads_new_count=1", gated.stdout)
        self.assertIn("github_threads_handled_this_run_count=2", gated.stdout)
        self.assertIn("github_threads_unresolved_count=0", gated.stdout)
        self.assertIn("local_findings_total_count=1", gated.stdout)
        self.assertIn("local_findings_new_count=0", gated.stdout)
        self.assertIn("local_findings_handled_this_run_count=1", gated.stdout)
        self.assertIn("local_findings_unresolved_count=0", gated.stdout)

        summary = (self.workspace_dir() / "audit_summary.md").read_text(encoding="utf-8")
        self.assertNotIn("- GitHub threads: total 2;", summary)
        self.assertNotIn("- Local findings: total 1;", summary)

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

    def test_update_item_reopening_clears_stale_handled_and_needs_human_flags(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Reopen me",
                    "body": "This item was previously handled.",
                    "path": "src/reopen_flags.py",
                    "line": 11,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        session = self.load_session()
        item_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        item = session["items"][item_id]
        item["status"] = "CLOSED"
        item["blocking"] = False
        item["handled"] = True
        item["handled_at"] = "2026-04-14T00:00:00+00:00"
        item["needs_human"] = True
        item["updated_at"] = "2026-04-14T00:00:00+00:00"
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")

        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            item_id,
            "OPEN",
            "--note",
            "Reopened after follow-up review.",
            check=True,
        )

        session = self.load_session()
        item = session["items"][item_id]
        self.assertEqual(item["status"], "OPEN")
        self.assertEqual(item["reopen_count"], 1)
        self.assertFalse(item["handled"])
        self.assertIsNone(item["handled_at"])
        self.assertFalse(item["needs_human"])

    def test_update_item_closing_clears_stale_needs_human_flag(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Close me",
                    "body": "This item was escalated earlier.",
                    "path": "src/close_flags.py",
                    "line": 13,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        session = self.load_session()
        item_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        session["items"][item_id]["needs_human"] = True
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")

        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            item_id,
            "CLOSED",
            "--note",
            "Resolved after escalation.",
            check=True,
        )

        session = self.load_session()
        item = session["items"][item_id]
        self.assertEqual(item["status"], "CLOSED")
        self.assertTrue(item["handled"])
        self.assertFalse(item["needs_human"])

    def test_update_items_batch_updates_core_fields_and_clears_claim(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Batch update me",
                    "body": "Batch write-back should update the session once.",
                    "path": "src/batch_update.py",
                    "line": 21,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        session = self.load_session()
        item_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        session["items"][item_id]["claimed_by"] = "agent-a"
        session["items"][item_id]["claimed_at"] = "2026-04-14T00:00:00+00:00"
        session["items"][item_id]["lease_expires_at"] = "2026-04-16T00:00:00+00:00"
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")

        batch_update = json.dumps(
            [
                {
                    "item_id": item_id,
                    "status": "CLOSED",
                    "handled": True,
                    "decision": "fix",
                    "note": "Closed in batch.",
                    "reply_posted": True,
                    "reply_url": "https://example.test/reply",
                    "last_auto_action": "fix",
                    "last_auto_failure": None,
                    "needs_human": False,
                    "clear_claim": True,
                }
            ]
        )
        result = self.run_engine("update-items-batch", self.repo, self.pr, stdin=batch_update, check=True)
        self.assertEqual(result.returncode, 0, result.stderr)

        session = self.load_session()
        item = session["items"][item_id]
        self.assertEqual(item["status"], "CLOSED")
        self.assertTrue(item["handled"])
        self.assertIsNotNone(item["handled_at"])
        self.assertEqual(item["decision"], "fix")
        self.assertEqual(item["resolution_note"], "Closed in batch.")
        self.assertTrue(item["reply_posted"])
        self.assertEqual(item["reply_url"], "https://example.test/reply")
        self.assertEqual(item["last_auto_action"], "fix")
        self.assertIsNone(item["last_auto_failure"])
        self.assertFalse(item["needs_human"])
        self.assertFalse(item["blocking"])
        self.assertIsNone(item["claimed_by"])
        self.assertIsNone(item["claimed_at"])
        self.assertIsNone(item["lease_expires_at"])

    def test_update_items_batch_clears_stale_last_auto_failure_when_null_is_explicit(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        payload = json.dumps(
            [
                {
                    "title": "Clear failure note",
                    "body": "Batch update should be able to clear old failures.",
                    "path": "src/batch_failure.py",
                    "line": 27,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.run_engine("ingest-local", self.repo, self.pr, "--source", "local-agent:test", stdin=payload, check=True)
        session = self.load_session()
        item_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        session["items"][item_id]["last_auto_failure"] = "temporary failure"
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")

        batch_update = json.dumps(
            [
                {
                    "item_id": item_id,
                    "status": "CLOSED",
                    "handled": True,
                    "note": "Cleared batch failure.",
                    "last_auto_action": "fix",
                    "last_auto_failure": None,
                }
            ]
        )
        self.run_engine("update-items-batch", self.repo, self.pr, stdin=batch_update, check=True)

        session = self.load_session()
        item = session["items"][item_id]
        self.assertEqual(item["status"], "CLOSED")
        self.assertTrue(item["handled"])
        self.assertIsNone(item["last_auto_failure"])

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

    def test_sync_github_closes_published_local_finding_clears_claim_and_updates_timestamp(self):
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
        self.run_engine("claim", self.repo, self.pr, local_id, "--agent", "fixer-1", check=True)
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
        published_session = self.load_session()
        published_item = published_session["items"][local_id]
        self.assertEqual(published_item["status"], "PUBLISHED")
        self.assertEqual(published_item["claimed_by"], "fixer-1")

        gh_payload = json.dumps(
            [
                {
                    "id": "THREAD_7B",
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
        self.assertIsNone(local_item["claimed_by"])
        self.assertIsNone(local_item["claimed_at"])
        self.assertIsNone(local_item["lease_expires_at"])
        self.assertEqual(local_item["updated_at"], local_item["handled_at"])

    def test_sync_github_closes_published_local_finding_when_reply_changes_latest_comment(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        local_payload = json.dumps(
            [
                {
                    "title": "Published upstream",
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
            "456",
            "--url",
            "https://example.test/comment/456",
            "--note",
            "Published upstream.",
            check=True,
        )

        gh_payload = json.dumps(
            [
                {
                    "id": "THREAD_8",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 11,
                    "body": "Follow-up reply changed the latest comment body.",
                    "url": "https://example.test/comment/789",
                    "first_url": "https://example.test/comment/456",
                    "latest_url": "https://example.test/comment/789",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=gh_payload, check=True)

        session = self.load_session()
        local_item = session["items"][local_id]
        self.assertEqual(local_item["status"], "CLOSED")
        self.assertTrue(local_item["handled"])
        self.assertEqual(local_item["linked_github_item_id"], "github-thread:THREAD_8")

    def test_sync_github_maps_outdated_thread_to_stale(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        gh_payload = json.dumps(
            [
                {
                    "id": "THREAD_STALE",
                    "isResolved": False,
                    "isOutdated": True,
                    "path": "src/map.py",
                    "line": 12,
                    "body": "Old context.",
                    "url": "https://example.test/comment/stale",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=gh_payload, check=True)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_STALE"]
        self.assertEqual(item["status"], "STALE")
        self.assertTrue(item["blocking"])
        self.assertEqual(session["metrics"]["unresolved_github_threads_count"], 1)

    def test_sync_github_preserves_dropped_thread_until_resolved(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        initial_payload = json.dumps(
            [
                {
                    "id": "THREAD_DROPPED",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 14,
                    "body": "Will be dropped locally.",
                    "url": "https://example.test/comment/dropped",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=initial_payload, check=True)
        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_DROPPED",
            "DROPPED",
            "--note",
            "Superseded elsewhere.",
            check=True,
        )

        reopened_payload = json.dumps(
            [
                {
                    "id": "THREAD_DROPPED",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 14,
                    "body": "Still unresolved upstream.",
                    "url": "https://example.test/comment/dropped",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=reopened_payload, check=True)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_DROPPED"]
        self.assertEqual(item["status"], "DROPPED")

    def test_sync_github_preserves_stale_thread_until_resolved(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        initial_payload = json.dumps(
            [
                {
                    "id": "THREAD_MANUAL_STALE",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 16,
                    "body": "Will be marked stale locally.",
                    "url": "https://example.test/comment/manual-stale",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=initial_payload, check=True)
        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_MANUAL_STALE",
            "STALE",
            "--note",
            "Manually parked pending later follow-up.",
            check=True,
        )

        refreshed_payload = json.dumps(
            [
                {
                    "id": "THREAD_MANUAL_STALE",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 16,
                    "body": "Still open on GitHub.",
                    "url": "https://example.test/comment/manual-stale",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=refreshed_payload, check=True)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_MANUAL_STALE"]
        self.assertEqual(item["status"], "STALE")
        self.assertTrue(item["blocking"])

    def test_sync_github_reopens_deferred_thread_when_github_is_still_unresolved(self):
        self.run_engine("init", self.repo, self.pr, check=True)
        initial_payload = json.dumps(
            [
                {
                    "id": "THREAD_DEFERRED",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 18,
                    "body": "Will be deferred locally.",
                    "url": "https://example.test/comment/deferred",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=initial_payload, check=True)
        self.run_engine(
            "update-item",
            self.repo,
            self.pr,
            "github-thread:THREAD_DEFERRED",
            "DEFERRED",
            "--note",
            "Valid issue, but not for this PR.",
            check=True,
        )

        refreshed_payload = json.dumps(
            [
                {
                    "id": "THREAD_DEFERRED",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/map.py",
                    "line": 18,
                    "body": "Still open on GitHub.",
                    "url": "https://example.test/comment/deferred",
                }
            ]
        )
        self.run_engine("sync-github", self.repo, self.pr, stdin=refreshed_payload, check=True)

        session = self.load_session()
        item = session["items"]["github-thread:THREAD_DEFERRED"]
        self.assertEqual(item["status"], "OPEN")
        self.assertTrue(item["blocking"])

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
