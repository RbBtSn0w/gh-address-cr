import json
from pathlib import Path
from tests.helpers import PythonScriptTestCase


class BatchNextTestCase(PythonScriptTestCase):
    def init_session(self, items, leases=None):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": f"{self.repo}#{self.pr}",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "ACTIVE",
            "items": {item["item_id"]: item for item in items},
            "leases": leases or {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def test_batch_next_generates_leases_and_skeleton(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "title": "Concern 1",
                "body": "First issue",
                "path": "src/a.py",
                "line": 10,
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-2",
                "item_kind": "github_thread",
                "source": "github",
                "title": "Concern 2",
                "body": "Second issue",
                "path": "src/b.py",
                "line": 20,
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
        ]
        self.init_session(items)

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        response = json.loads(result.stdout)
        self.assertEqual(response["status"], "BATCH_ACTION_REQUESTED")
        self.assertEqual(response["lease_count"], 2)
        self.assertEqual(len(response["leased_items"]), 2)
        self.assertIn("agent submit-batch octo/example 77 --input", response["next_action"])
        self.assertIn("submit_batch", response["commands"])

        session = self.load_session()
        self.assertEqual(session["items"]["thread-1"]["state"], "claimed")
        self.assertEqual(session["items"]["thread-2"]["state"], "claimed")

        lease_ids = [item_info["lease_id"] for item_info in response["leased_items"]]
        for lid in lease_ids:
            self.assertIn(lid, session["leases"])
            self.assertEqual(session["leases"][lid]["status"], "active")
            self.assertEqual(session["leases"][lid]["role"], "fixer")
            self.assertEqual(session["leases"][lid]["agent_id"], "test-agent")

        skeleton_path = Path(response["response_skeleton_path"])
        self.assertTrue(skeleton_path.exists())
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))

        self.assertEqual(skeleton["agent_id"], "test-agent")
        self.assertEqual(skeleton["resolution"], "fix")
        self.assertIn("common", skeleton)
        self.assertIn("items", skeleton)
        self.assertEqual(len(skeleton["items"]), 2)

        item1_ids = {itm["item_id"] for itm in skeleton["items"]}
        self.assertEqual(item1_ids, {"thread-1", "thread-2"})

        skeleton["common"]["files"] = ["src/a.py", "src/b.py"]
        skeleton["common"]["validation_commands"][0]["command"] = "python3 -m unittest tests.test_issue112_batch_next"
        skeleton["common"]["fix_reply"]["test_command"] = "python3 -m unittest tests.test_issue112_batch_next"
        skeleton["common"]["fix_reply"]["test_result"] = "passed"
        for item in skeleton["items"]:
            item["fix_reply"]["summary"] = f"Fixed {item['item_id']}"
            item["fix_reply"]["why"] = f"The validation covers {item['item_id']}."
        skeleton_path.write_text(json.dumps(skeleton, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        submitted = self.run_runtime_module("agent", "submit-batch", self.repo, self.pr, "--input", str(skeleton_path))
        self.assertEqual(submitted.returncode, 0, submitted.stderr)
        submitted_payload = json.loads(submitted.stdout)
        self.assertEqual(submitted_payload["status"], "BATCH_ACTION_ACCEPTED")
        self.assertEqual(submitted_payload["accepted_count"], 2)

    def test_batch_next_reuses_existing_active_leases(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "state": "claimed",
                "active_lease_id": "lease-existing",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-2",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
        ]
        leases = {
            "lease-existing": {
                "lease_id": "lease-existing",
                "item_id": "thread-1",
                "agent_id": "test-agent",
                "role": "fixer",
                "status": "active",
                "request_id": "req-existing",
                "expires_at": "2026-06-12T23:59:59Z",
                "created_at": "2026-06-12T21:59:59Z",
            }
        }
        self.init_session(items, leases)

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        session = self.load_session()
        self.assertEqual(session["items"]["thread-1"]["active_lease_id"], "lease-existing")
        self.assertEqual(session["items"]["thread-2"]["state"], "claimed")

        response = json.loads(result.stdout)
        skeleton_path = Path(response["response_skeleton_path"])
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))

        items_in_skeleton = {itm["item_id"]: itm for itm in skeleton["items"]}
        self.assertIn("thread-1", items_in_skeleton)
        self.assertIn("thread-2", items_in_skeleton)
        self.assertEqual(items_in_skeleton["thread-1"]["lease_id"], "lease-existing")
        self.assertEqual(items_in_skeleton["thread-1"]["request_id"], "req-existing")

    def test_batch_next_skips_stale_and_other_agent_leases(self):
        items = [
            {
                "item_id": "thread-open",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-stale",
                "item_kind": "github_thread",
                "source": "github",
                "state": "stale",
                "status": "STALE",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-other-agent",
                "item_kind": "github_thread",
                "source": "github",
                "state": "claimed",
                "active_lease_id": "lease-other",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
        ]
        leases = {
            "lease-other": {
                "lease_id": "lease-other",
                "item_id": "thread-other-agent",
                "agent_id": "other-agent",
                "role": "fixer",
                "status": "active",
                "request_id": "req-other",
                "request_hash": "req-other",
                "expires_at": "2026-06-12T23:59:59Z",
                "created_at": "2026-06-12T21:59:59Z",
            }
        }
        self.init_session(items, leases)

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        skeleton = json.loads(Path(response["response_skeleton_path"]).read_text(encoding="utf-8"))
        self.assertEqual([item["item_id"] for item in skeleton["items"]], ["thread-open"])

    def test_batch_next_fails_when_no_unresolved_threads(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "state": "closed",
            }
        ]
        self.init_session(items)

        result = self.run_runtime_module("agent", "next", self.repo, self.pr, "--batch")
        self.assertEqual(result.returncode, 4, result.stderr)
        err = json.loads(result.stdout)
        self.assertEqual(err["status"], "NO_ELIGIBLE_ITEM")

    def test_cli_requires_role_or_batch(self):
        self.init_session([])
        result = self.run_runtime_module("agent", "next", self.repo, self.pr)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one of the following arguments is required: --role or --batch", result.stderr)
