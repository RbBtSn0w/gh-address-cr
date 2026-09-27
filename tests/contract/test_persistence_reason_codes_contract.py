"""Spec 035 F5: persistence failures reach agents with their own reason code.

Before 035c a session or persistence error either escaped agent commands as an
unstructured traceback or was flattened into ``SESSION_ERROR`` /
``PUBLISH_ERROR``, and ``status-action-map.md`` had no entry for the codes the
skill told agents to follow.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import multiprocessing
import os
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.cli import main
from gh_address_cr.core import agent_protocol, leases, protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.remediation import remediation_for

REPO = "owner/repo"
PR_NUMBER = "123"
PERSISTENCE_CASES = (
    ("STALE_REVISION", True),
    ("PERSISTENCE_BUSY", True),
    ("PERSISTENCE_INVALID", False),
)
AGENT_COMMANDS = (
    ("gh_address_cr.core.agent_protocol.issue_action_request", ["agent", "next", REPO, PR_NUMBER, "--role", "fixer"]),
    ("gh_address_cr.core.agent_protocol.submit_action_response", ["agent", "submit", REPO, PR_NUMBER, "--input", "r.json"]),
    ("gh_address_cr.core.publisher.publish_github_thread_responses", ["agent", "publish", REPO, PR_NUMBER]),
    ("gh_address_cr.core.leases.list_leases", ["agent", "leases", REPO, PR_NUMBER]),
    ("gh_address_cr.core.leases.reclaim_leases", ["agent", "reclaim", REPO, PR_NUMBER]),
)
ROOT = Path(__file__).resolve().parents[2]


def _run_cli(argv: list[str]) -> tuple[int, dict]:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
        exit_code = main(argv)
    return exit_code, json.loads(stdout.getvalue())


def _seed_session(tmp: str, *, items: int = 1, expired_leases: int = 0) -> None:
    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
        manager = session_store.SessionManager(REPO, PR_NUMBER)
        session = manager.create(status="WAITING_FOR_CLASSIFICATION")
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        session["items"] = {
            f"local:{index}": {
                "item_id": f"local:{index}",
                "item_kind": "local_finding",
                "source": "json",
                "title": "Finding",
                "body": "Body",
                "path": f"src/module_{index}.py",
                "line": 1,
                "state": "open",
                "status": "OPEN",
                "blocking": True,
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
            }
            for index in range(items)
        }
        session["leases"] = {
            f"lease-{index}": {
                "lease_id": f"lease-{index}",
                "item_id": f"local:{index}",
                "agent_id": f"agent-{index}",
                "role": "fixer",
                "status": "active",
                "created_at": past - timedelta(hours=1),
                "expires_at": past,
            }
            for index in range(expired_leases)
        }
        manager.save(session)


def _classify_in_process(tmp: str, barrier, queue, index: int) -> None:
    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
        barrier.wait()
        try:
            agent_protocol.record_classification(
                REPO, PR_NUMBER, item_id=f"local:{index}", classification="fix",
                agent_id=f"triage-{index}", note="Concurrent classification.",
            )
        except Exception as exc:
            queue.put(f"{type(exc).__name__}: {getattr(exc, 'reason_code', exc)}")
        else:
            queue.put("ok")


def _reclaim_in_process(tmp: str, barrier, queue) -> None:
    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
        barrier.wait()
        try:
            payload = leases.reclaim_leases(REPO, PR_NUMBER)
        except Exception as exc:
            queue.put(f"{type(exc).__name__}: {getattr(exc, 'reason_code', exc)}")
        else:
            queue.put(("ok", payload["expired_count"]))


class PersistenceReasonCodeContractTest(unittest.TestCase):
    def test_persistence_reason_codes_reach_agent_output(self):
        for target, argv in AGENT_COMMANDS:
            for reason_code, retryable in PERSISTENCE_CASES:
                with self.subTest(command=argv[1], reason_code=reason_code):
                    error = session_store.SessionError(reason_code, f"{reason_code}: injected")
                    with patch(target, side_effect=error):
                        exit_code, payload = _run_cli(argv)

                    self.assertEqual(exit_code, 5)
                    self.assertEqual(payload["reason_code"], reason_code)
                    self.assertEqual(payload["retryable"], retryable)
                    self.assertEqual(payload["waiting_on"], "runtime_store")
                    self.assertEqual(payload["exit_code"], 5)
                    self.assertTrue(payload["remediation"]["summary"])

    def test_high_level_commands_keep_persistence_reason_codes(self):
        from gh_address_cr.commands.high_level import HighLevelReviewRuntime

        error = session_store.SessionError("PERSISTENCE_BUSY", "PERSISTENCE_BUSY: injected")
        with patch("gh_address_cr.cli.preflight_high_level", return_value=None), patch.object(
            HighLevelReviewRuntime, "_handle_parsed", side_effect=error
        ):
            exit_code, payload = _run_cli(["review", REPO, PR_NUMBER])

        self.assertEqual(exit_code, 5)
        self.assertEqual(payload["reason_code"], "PERSISTENCE_BUSY")
        self.assertEqual(payload["waiting_on"], "runtime_store")
        self.assertTrue(payload["retryable"])

    def test_non_persistence_session_errors_are_not_marked_retryable(self):
        error = session_store.SessionError("SESSION_NOT_FOUND", "No session exists.")
        with patch("gh_address_cr.core.leases.list_leases", side_effect=error):
            exit_code, payload = _run_cli(["agent", "leases", REPO, PR_NUMBER])

        self.assertEqual(exit_code, 5)
        self.assertEqual(payload["reason_code"], "SESSION_NOT_FOUND")
        self.assertEqual(payload["waiting_on"], "session")
        self.assertFalse(payload["retryable"])

    def test_every_persistence_code_is_documented_and_remediated(self):
        status_action_map = (ROOT / "skill" / "references" / "status-action-map.md").read_text(encoding="utf-8")
        for code in (
            protocol_codes.STALE_REVISION,
            protocol_codes.PERSISTENCE_BUSY,
            protocol_codes.PERSISTENCE_INVALID,
            protocol_codes.SIDE_EFFECT_IN_PROGRESS,
        ):
            with self.subTest(code=code):
                self.assertIn(f"`{code}`", status_action_map)
                fallback = remediation_for("UNREGISTERED_CODE", repo=REPO, pr_number=PR_NUMBER)
                self.assertNotEqual(remediation_for(code, repo=REPO, pr_number=PR_NUMBER), fallback)


class StaleRevisionRetryContractTest(unittest.TestCase):
    def test_retry_reruns_only_stale_revision_and_is_bounded(self):
        stale = session_store.SessionError("STALE_REVISION", "stale")
        calls: list[int] = []

        def succeeds_on_third() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise stale
            return "done"

        self.assertEqual(session_store.retry_on_stale_revision(succeeds_on_third), "done")
        self.assertEqual(len(calls), 3)

        calls.clear()

        def always_stale() -> None:
            calls.append(1)
            raise stale

        with self.assertRaises(session_store.SessionError) as raised:
            session_store.retry_on_stale_revision(always_stale)
        self.assertEqual(raised.exception.reason_code, "STALE_REVISION")
        self.assertEqual(len(calls), session_store.STALE_REVISION_ATTEMPTS)

        calls.clear()

        def busy() -> None:
            calls.append(1)
            raise session_store.SessionError("PERSISTENCE_BUSY", "busy")

        with self.assertRaises(session_store.SessionError):
            session_store.retry_on_stale_revision(busy)
        self.assertEqual(len(calls), 1)

    def test_submit_reruns_from_fresh_state_after_a_concurrent_commit(self):
        from tests.test_native_workflow import UnstackedGitHubClient

        with tempfile.TemporaryDirectory() as tmp:
            _seed_session(tmp, items=2)
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                agent_protocol.record_classification(
                    REPO, PR_NUMBER, item_id="local:0", classification="fix", agent_id="triage", note="Real."
                )
                requested = agent_protocol.issue_action_request(
                    REPO, PR_NUMBER, role="fixer", agent_id="fixer-0", item_id="local:0",
                    github_client=UnstackedGitHubClient(),
                )
                request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
                response_path = Path(tmp) / "response.json"
                response_path.write_text(
                    json.dumps({
                        "schema_version": "1.0",
                        "request_id": request["request_id"],
                        "lease_id": request["lease_id"],
                        "agent_id": "fixer-0",
                        "resolution": "fix",
                        "note": "Fixed.",
                        "files": ["src/module_0.py"],
                        "validation_commands": [{"command": "unit", "result": "passed"}],
                    }),
                    encoding="utf-8",
                )
                real_load = session_store.load_session
                interleaved: list[bool] = []

                def load_then_commit_elsewhere(repo: str, pr_number: str) -> dict:
                    session = real_load(repo, pr_number)
                    if not interleaved:
                        interleaved.append(True)
                        agent_protocol.record_classification(
                            REPO, PR_NUMBER, item_id="local:1", classification="fix",
                            agent_id="triage-2", note="Concurrent.",
                        )
                    return session

                with patch.object(session_store, "load_session", side_effect=load_then_commit_elsewhere):
                    accepted = agent_protocol.submit_action_response(
                        REPO, PR_NUMBER, response_path=response_path, github_client=UnstackedGitHubClient()
                    )
                final = real_load(REPO, PR_NUMBER)

        self.assertEqual(accepted["status"], "ACTION_ACCEPTED")
        self.assertEqual(final["items"]["local:1"]["decision"], "fix")
        self.assertEqual(final["leases"][request["lease_id"]]["status"], "accepted")


class TransactionTelemetryBindingContractTest(unittest.TestCase):
    def test_transaction_only_commands_bind_pr_telemetry(self):
        from gh_address_cr.core.telemetry_runtime import SessionTelemetry

        with tempfile.TemporaryDirectory() as tmp:
            _seed_session(tmp, items=1)
            SessionTelemetry.reset()
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                agent_protocol.record_classification(
                    REPO, PR_NUMBER, item_id="local:0", classification="fix", agent_id="triage", note="Real."
                )
                telemetry_file = SessionTelemetry.get_instance().telemetry_file
                workspace = session_store.workspace_dir(REPO, PR_NUMBER)
            SessionTelemetry.reset()

        self.assertIsNotNone(telemetry_file)
        self.assertEqual(Path(telemetry_file).parent, workspace)


@unittest.skipIf(os.name == "nt", "concurrency contracts use fork")
class TransactionalHotPathContractTest(unittest.TestCase):
    def test_concurrent_classification_never_surfaces_stale_revision(self):
        context = multiprocessing.get_context("fork")
        worker_count = 8
        with tempfile.TemporaryDirectory() as tmp:
            _seed_session(tmp, items=worker_count)
            barrier, queue = context.Barrier(worker_count), context.Queue()
            workers = [
                context.Process(target=_classify_in_process, args=(tmp, barrier, queue, index))
                for index in range(worker_count)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=60)
            outcomes = [queue.get(timeout=5) for _ in workers]
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                final = session_store.load_session(REPO, PR_NUMBER)

        self.assertEqual(outcomes, ["ok"] * worker_count)
        self.assertEqual({item["decision"] for item in final["items"].values()}, {"fix"})

    def test_concurrent_reclaim_expires_each_lease_exactly_once(self):
        context = multiprocessing.get_context("fork")
        worker_count = 6
        with tempfile.TemporaryDirectory() as tmp:
            _seed_session(tmp, items=4, expired_leases=4)
            barrier, queue = context.Barrier(worker_count), context.Queue()
            workers = [context.Process(target=_reclaim_in_process, args=(tmp, barrier, queue)) for _ in range(worker_count)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=60)
            outcomes = [queue.get(timeout=5) for _ in workers]
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                final = session_store.load_session(REPO, PR_NUMBER)

        self.assertTrue(all(isinstance(outcome, tuple) and outcome[0] == "ok" for outcome in outcomes), outcomes)
        self.assertEqual(sum(outcome[1] for outcome in outcomes), 4)
        self.assertEqual({lease["status"] for lease in final["leases"].values()}, {"expired"})

    def test_mutation_closures_perform_no_file_or_network_io(self):
        real_transact = session_store.transact_session
        guarded: list[str] = []

        def forbid(*args, **kwargs):
            raise AssertionError("mutation closures must not perform file or network IO")

        def transact_with_io_guard(repo, pr_number, mutation, **kwargs):
            def guarded_mutation(payload):
                guarded.append(kwargs.get("operation", ""))
                with patch.object(builtins, "open", side_effect=forbid), patch.object(
                    socket, "socket", side_effect=forbid
                ):
                    return mutation(payload)

            return real_transact(repo, pr_number, guarded_mutation, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            _seed_session(tmp, items=2, expired_leases=1)
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                # Warm the state-directory writability cache that ledger construction consults.
                session_store.workspace_dir(REPO, PR_NUMBER)
                with patch.object(session_store, "transact_session", side_effect=transact_with_io_guard):
                    agent_protocol.record_classification(
                        REPO, PR_NUMBER, item_id="local:1", classification="fix", agent_id="triage", note="Real."
                    )
                    leases.reclaim_leases(REPO, PR_NUMBER)
                    leases.release_claimed_lease(REPO, PR_NUMBER, lease_id="missing-lease")

        self.assertEqual(len(guarded), 3)


if __name__ == "__main__":
    unittest.main()
