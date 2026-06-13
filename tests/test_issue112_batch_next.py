import json
from pathlib import Path

from tests.helpers import PythonScriptTestCase

TEST_NOW = "2026-06-12T22:30:00+00:00"


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
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent", "--now", TEST_NOW
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        response = json.loads(result.stdout)
        self.assertEqual(response["status"], "BATCH_ACTION_REQUESTED")
        self.assertEqual(response["lease_count"], 2)
        self.assertEqual(len(response["leased_items"]), 2)
        self.assertIn("agent resolve octo/example 77 --batch --input", response["next_action"])
        self.assertIn("resolve_batch", response["commands"])

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

        submitted = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr, "--batch", "--input", str(skeleton_path), "--now", TEST_NOW
        )
        self.assertEqual(submitted.returncode, 0, submitted.stderr)
        submitted_payload = json.loads(submitted.stdout)
        self.assertEqual(submitted_payload["status"], "FAST_FIX_ALL_ACCEPTED")
        self.assertEqual(submitted_payload["accepted_count"], 2)

    def test_submit_batch_rejection_returns_skeleton_recovery_guidance(self):
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
        requested = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent", "--now", TEST_NOW
        )
        self.assertEqual(requested.returncode, 0, requested.stderr)
        request_payload = json.loads(requested.stdout)
        skeleton_path = Path(request_payload["response_skeleton_path"])
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
        skeleton["common"]["files"] = []
        skeleton["common"]["validation_commands"][0]["command"] = "python3 -m unittest tests.test_issue112_batch_next"
        skeleton["common"]["fix_reply"]["test_command"] = "python3 -m unittest tests.test_issue112_batch_next"
        skeleton["common"]["fix_reply"]["test_result"] = "passed"
        for item in skeleton["items"]:
            item["fix_reply"]["summary"] = f"Fixed {item['item_id']}"
            item["fix_reply"]["why"] = f"The validation covers {item['item_id']}."
        skeleton_path.write_text(json.dumps(skeleton, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        rejected = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr, "--batch", "--input", str(skeleton_path), "--now", TEST_NOW
        )

        self.assertEqual(rejected.returncode, 5)
        payload = json.loads(rejected.stdout)
        self.assertEqual(payload["status"], "BATCH_ACTION_REJECTED")
        self.assertEqual(payload["reason_code"], "MISSING_FILES")
        self.assertEqual(payload["batch_response_skeleton_path"], str(skeleton_path))
        self.assertEqual(payload["recovery_action"], "edit_batch_response_skeleton")
        self.assertIn(str(skeleton_path), payload["commands"]["resolve_batch"])
        self.assertIn("--batch", payload["commands"]["batch_next"])
        self.assertIn("Edit", payload["next_action"])

        session = self.load_session()
        lease_ids = [item_info["lease_id"] for item_info in request_payload["leased_items"]]
        for lease_id in lease_ids:
            self.assertEqual(session["leases"][lease_id]["status"], "active")
        event_types = [json.loads(line)["event_type"] for line in Path(session["ledger_path"]).read_text().splitlines()]
        self.assertNotIn("response_accepted", event_types)

    def test_batch_next_with_files_filter(self):
        items = [
            {
                "item_id": "thread-a",
                "item_kind": "github_thread",
                "source": "github",
                "path": "src/a.py",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-b",
                "item_kind": "github_thread",
                "source": "github",
                "path": "src/b.py",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
        ]
        self.init_session(items)

        # 仅选择过滤 "src/a.py"
        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--files", "src/a.py", "--agent-id", "test-agent"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["lease_count"], 1)
        self.assertEqual(response["leased_items"][0]["item_id"], "thread-a")

        session = self.load_session()
        self.assertEqual(session["items"]["thread-a"]["state"], "claimed")
        self.assertEqual(session["items"]["thread-b"]["state"], "open")

    def test_batch_next_excludes_non_fix_classifications(self):
        items = [
            {
                "item_id": "thread-fix",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-reject",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
                "classification_evidence": {
                    "event_type": "classification_recorded",
                    "classification": "reject",
                    "record_id": "ev-reject",
                },
            },
        ]
        self.init_session(items)

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent", "--now", TEST_NOW
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        
        # 应当仅租赁了 "thread-fix"
        self.assertEqual(response["lease_count"], 1)
        self.assertEqual(response["leased_items"][0]["item_id"], "thread-fix")

        session = self.load_session()
        self.assertEqual(session["items"]["thread-fix"]["state"], "claimed")
        self.assertEqual(session["items"]["thread-reject"]["state"], "open")

    def test_batch_next_respects_max_parallel_claims(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-2",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-3",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
        ]
        self.init_session(items)

        # 由于 MAX_PARALLEL_CLAIMS 被配置为 2 (可以从 CapabilityManifest.constraints 查看)
        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent", "--now", TEST_NOW
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        
        # 仅应有最多 2 个新租赁
        self.assertEqual(response["lease_count"], 2)
        
        session = self.load_session()
        claimed_count = sum(1 for itm in session["items"].values() if itm["state"] == "claimed")
        self.assertEqual(claimed_count, 2)

    def test_batch_next_reconstructs_lease_context(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "state": "claimed",
                "active_lease_id": "lease-existing",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            }
        ]
        # lease-existing 缺失 request_hash/request_path
        leases = {
            "lease-existing": {
                "lease_id": "lease-existing",
                "item_id": "thread-1",
                "agent_id": "test-agent",
                "role": "fixer",
                "status": "active",
                "request_id": "",
                "expires_at": "2026-06-12T23:59:59Z",
                "created_at": "2026-06-12T21:59:59Z",
            }
        }
        self.init_session(items, leases)

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent", "--now", TEST_NOW
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        
        # 验证 lease-existing 已经在 session 中补充了 request_id/request_hash/request_path
        session = self.load_session()
        updated_lease = session["leases"]["lease-existing"]
        self.assertTrue(updated_lease.get("request_id"))
        self.assertTrue(updated_lease.get("request_hash"))
        self.assertTrue(updated_lease.get("request_path"))
        self.assertTrue(Path(updated_lease["request_path"]).is_file())

        # 验证生成的 skeleton 能正常被 submit-batch
        skeleton_path = Path(response["response_skeleton_path"])
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
        skeleton["common"]["files"] = ["src/a.py"]
        skeleton["common"]["validation_commands"][0]["command"] = "echo pass"
        skeleton["common"]["fix_reply"]["test_command"] = "echo pass"
        skeleton["common"]["fix_reply"]["test_result"] = "passed"
        skeleton["items"][0]["fix_reply"]["summary"] = "fixed missing request context"
        skeleton["items"][0]["fix_reply"]["why"] = "reconstructed successfully"
        skeleton_path.write_text(json.dumps(skeleton, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        submitted = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr, "--batch", "--input", str(skeleton_path), "--now", TEST_NOW
        )
        self.assertEqual(submitted.returncode, 0, submitted.stderr)

    def test_batch_next_rolls_back_on_conflict(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "path": "src/b.py",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
            {
                "item_id": "thread-2",
                "item_kind": "github_thread",
                "source": "github",
                "path": "src/a.py",
                "line": 2,
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            },
        ]
        # 外部已经有人占用了 "src/a.py" 上的锁，这会导致 thread-2 的 claim_lease 爆发 LeaseConflictError
        leases = {
            "lease-other": {
                "lease_id": "lease-other",
                "item_id": "thread-other",
                "agent_id": "other-agent",
                "role": "fixer",
                "status": "active",
                "conflict_keys": ["file:src/a.py"],
                "expires_at": "2026-06-12T23:59:59Z",
                "created_at": "2026-06-12T21:59:59Z",
            }
        }
        self.init_session(items, leases)

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent", "--now", TEST_NOW
        )
        # 应该发生 LEASE_REJECTED
        self.assertEqual(result.returncode, 5, result.stderr)

        # 验证 session 一致性：此前成功获取的 thread-1 应当被回滚释放，不留痕迹
        session = self.load_session()
        self.assertEqual(session["items"]["thread-1"]["state"], "open")
        self.assertNotIn("thread-1", [lease.get("item_id") for lease in session["leases"].values() if lease.get("agent_id") == "test-agent"])

    def test_batch_next_merges_existing_skeleton_replies(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            }
        ]
        self.init_session(items)

        # 1. 运行第一次，写入 skeleton
        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        
        # 模拟用户手工编辑 skeleton 文件
        skeleton_path = Path(response["response_skeleton_path"])
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
        skeleton["items"][0]["fix_reply"]["summary"] = "User edited summary"
        skeleton["items"][0]["fix_reply"]["why"] = "User edited why"
        skeleton["common"]["commit_hash"] = "edited-commit"
        skeleton_path.write_text(json.dumps(skeleton, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # 2. 运行第二次，应当做增量合并
        result2 = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent"
        )
        self.assertEqual(result2.returncode, 0, result2.stderr)

        # 验证编辑好的字段在二次获取后没有丢失
        updated_skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
        self.assertEqual(updated_skeleton["items"][0]["fix_reply"]["summary"], "User edited summary")
        self.assertEqual(updated_skeleton["items"][0]["fix_reply"]["why"], "User edited why")
        self.assertEqual(updated_skeleton["common"]["commit_hash"], "edited-commit")

    def test_cli_requires_role_or_batch(self):
        self.init_session([])
        result = self.run_runtime_module("agent", "next", self.repo, self.pr)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one of the following arguments is required: --role or --batch", result.stderr)

    def test_cli_role_and_batch_are_mutually_exclusive(self):
        self.init_session([])
        # 同时传入 --role 与 --batch
        result = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--batch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("arguments --role and --batch are mutually exclusive", result.stderr)

    def test_cli_files_only_allowed_with_batch(self):
        self.init_session([])
        # 仅传入 --role 与 --files，但没有 --batch
        result = self.run_runtime_module("agent", "next", self.repo, self.pr, "--role", "fixer", "--files", "src/a.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("argument --files can only be used with --batch", result.stderr)

    def test_batch_next_fails_fast_on_invalid_skeleton_json(self):
        items = [
            {
                "item_id": "thread-1",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            }
        ]
        self.init_session(items)
        skeleton_path = self.workspace_dir() / "batch-response-skeleton.json"
        skeleton_path.write_text("invalid json content", encoding="utf-8")

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent"
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertIn("Failed to parse existing batch skeleton JSON", result.stderr)

    def test_batch_next_leases_already_classified_threads(self):
        items = [
            {
                "item_id": "thread-classified",
                "item_kind": "github_thread",
                "source": "github",
                "state": "open",
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
                "classification_evidence": {
                    "event_type": "classification_recorded",
                    "classification": "fix",
                    "note": "already classified",
                    "record_id": "rec-exist",
                },
                "decision": "fix",
            }
        ]
        self.init_session(items)

        result = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        session = self.load_session()
        self.assertEqual(session["items"]["thread-classified"]["state"], "claimed")

    def test_submit_batch_rejection_prioritizes_lease_recovery(self):
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
            }
        ]
        self.init_session(items)
        requested = self.run_runtime_module(
            "agent", "next", self.repo, self.pr, "--batch", "--agent-id", "test-agent", "--now", TEST_NOW
        )
        self.assertEqual(requested.returncode, 0)
        request_payload = json.loads(requested.stdout)
        skeleton_path = Path(request_payload["response_skeleton_path"])
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
        skeleton["common"]["files"] = ["src/a.py"]
        skeleton["common"]["validation_commands"][0]["command"] = "python3 -m unittest"
        skeleton["common"]["fix_reply"]["test_command"] = "python3 -m unittest"
        skeleton["common"]["fix_reply"]["test_result"] = "passed"
        for item in skeleton["items"]:
            item["fix_reply"]["summary"] = "Fixed"
            item["fix_reply"]["why"] = "Why fixed"
        skeleton_path.write_text(json.dumps(skeleton, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Artificially expire the lease in the session so it triggers EXPIRED_LEASE
        session = self.load_session()
        lease_id = list(session["leases"].keys())[0]
        session["leases"][lease_id]["expires_at"] = "2020-01-01T00:00:00Z"
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")

        # Submit should fail with BATCH_ACTION_REJECTED due to expired lease and return lease recovery guidance
        rejected = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr, "--batch", "--input", str(skeleton_path), "--now", TEST_NOW
        )
        self.assertEqual(rejected.returncode, 5)
        payload = json.loads(rejected.stdout)
        self.assertEqual(payload["status"], "BATCH_ACTION_REJECTED")
        self.assertIn("lease_recovery", payload)
        self.assertEqual(payload["lease_recovery"]["recovery_outcome"], "renew")
        self.assertIn("Please renew the expired lease", payload["next_action"])
