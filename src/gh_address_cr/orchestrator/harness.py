import argparse
import sys
import json
import time
from pathlib import Path
from uuid import uuid4
from typing import List
from gh_address_cr import __version__
from packaging.version import Version
from gh_address_cr.orchestrator.session import (
    OrchestrationSession,
    load_orchestration_session,
    save_orchestration_session,
    OrchestrationSessionError,
    LeaseConflictError,
    ExpiredLeaseError,
)
from gh_address_cr.orchestrator.worker import (
    build_worker_packet,
    parse_and_validate_response,
    WorkerPacketValidationError,
    HumanHandoffRequired,
    MAX_RETRIES,
)
from gh_address_cr.core import workflow, session_engine
from gh_address_cr.core import session as core_session

MIN_REQUIRED_VERSION = "0.0.1"
MAX_QUEUE_RECONCILIATION_SECONDS = 1.0


def check_runtime_version() -> bool:
    try:
        current = Version(__version__)
        required = Version(MIN_REQUIRED_VERSION)
        if current < required:
            sys.stderr.write(
                f"Incompatible Runtime CLI version: {__version__}. Orchestrator requires >={MIN_REQUIRED_VERSION}.\n"
            )
            return False
    except Exception:
        pass
    return True


def _parse_common_args(args: List[str]):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    return parser.parse_known_args(args)


def handle_agent_orchestrate(subcommand: str | None, passthrough: List[str]) -> int:
    if not check_runtime_version():
        return 2

    if subcommand not in ["start", "status", "step", "resume", "stop", "submit"]:
        sys.stderr.write(
            "usage: gh-address-cr agent orchestrate {start,status,step,resume,stop,submit} <repo> <pr_number> ...\n"
        )
        return 2

    if subcommand == "start":
        return handle_start(passthrough)
    elif subcommand == "status":
        return handle_status(passthrough)
    elif subcommand == "step":
        return handle_step(passthrough)
    elif subcommand == "resume":
        return handle_resume(passthrough)
    elif subcommand == "stop":
        return handle_stop(passthrough)
    elif subcommand == "submit":
        return handle_submit(passthrough)

    return 2


def handle_submit(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent orchestrate submit")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--input", required=True)
    parsed, _ = parser.parse_known_args(args)
    repo, pr = parsed.repo, parsed.pr_number

    try:
        session = load_orchestration_session(repo, pr)
        session.validate_lease_for_submission(parsed.item_id, parsed.token)

        retry_count = int(session.retry_counts.get(parsed.item_id, 0))

        required_evidence = ["files", "validation_commands", "note", "fix_reply"]
        try:
            parse_and_validate_response(parsed.input, required_evidence, retry_count=retry_count)
        except WorkerPacketValidationError as e:
            retry_count += 1
            session.retry_counts[parsed.item_id] = retry_count
            save_orchestration_session(session)
            if retry_count >= MAX_RETRIES:
                sys.stderr.write(
                    f"CRITICAL: Human Handoff Required: Max retries ({MAX_RETRIES}) reached for {parsed.item_id}.\n"
                )
                return 2
            sys.stderr.write(f"Submission failed: {e}\n")
            return 2
        except HumanHandoffRequired as e:
            session.retry_counts[parsed.item_id] = max(retry_count, MAX_RETRIES)
            save_orchestration_session(session)
            sys.stderr.write(f"CRITICAL: Human Handoff Required: {e}\n")
            return 2

        try:
            result = workflow.submit_action_response(repo, pr, response_path=str(parsed.input))
        except workflow.WorkflowError as e:
            save_orchestration_session(session)
            sys.stderr.write(f"Submission failed: {e.reason_code}: {e}\n")
            return 2

        session.release_lease(parsed.item_id, parsed.token)
        session.retry_counts.pop(parsed.item_id, None)

        save_orchestration_session(session)
        sys.stdout.write(
            json.dumps(
                {
                    "status": "SUCCESS",
                    "message": f"Verified and submitted {parsed.item_id}",
                    "runtime_status": result.get("status"),
                }
            )
            + "\n"
        )
        return 0
    except (OrchestrationSessionError, WorkerPacketValidationError, ExpiredLeaseError, LeaseConflictError) as e:
        sys.stderr.write(f"Submission failed: {e}\n")
        return 2
    except HumanHandoffRequired as e:
        sys.stderr.write(f"CRITICAL: Human Handoff Required: {e}\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"Unexpected error: {e}\n")
        return 5


def handle_start(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number

    # Initialize from core session
    try:
        session = OrchestrationSession(run_id=f"run-{uuid4().hex[:8]}", repo=repo, pr_number=pr)
        _sync_queue_from_runtime(session, enforce_budget=False)

        save_orchestration_session(session)
        sys.stdout.write(
            f"agent orchestrate start: initialized session {session.run_id} for {repo}/pr-{pr} (queued={len(session.queued_items)})\n"
        )
        return 0
    except Exception as e:
        sys.stderr.write(f"Failed to start orchestration: {e}\n")
        return 5


def handle_step(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent orchestrate step")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--role", help="Role-based filtering (e.g., triage)")
    parsed, _ = parser.parse_known_args(args)
    repo, pr = parsed.repo, parsed.pr_number

    try:
        session = load_orchestration_session(repo, pr)
        _sync_queue_from_runtime(session, enforce_budget=False)
    except OrchestrationSessionError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"Failed to synchronize runtime queue: {e}\n")
        return 2

    # Simple dequeue logic
    if not session.queued_items:
        if not session.active_leases:
            sys.stdout.write(json.dumps({"status": "READY_FOR_FINAL_GATE", "message": "Zero pending items."}) + "\n")
            return 0
        else:
            sys.stdout.write(
                json.dumps({"status": "WAITING", "message": f"Waiting for {len(session.active_leases)} active leases."})
                + "\n"
            )
            return 0

    role = parsed.role or "fixer"  # Default to fixer for MVP

    try:
        action_result = workflow.issue_action_request(
            repo,
            pr,
            role=role,
            agent_id=f"orchestrator:{session.run_id}",
        )
    except workflow.WorkflowError as e:
        if e.reason_code in {"NO_ELIGIBLE_ITEM"}:
            _sync_queue_from_runtime(session, enforce_budget=False)
            save_orchestration_session(session)
            if not session.active_leases:
                sys.stdout.write(
                    json.dumps({"status": "READY_FOR_FINAL_GATE", "message": "Zero pending items."}) + "\n"
                )
            else:
                sys.stdout.write(
                    json.dumps(
                        {
                            "status": "WAITING",
                            "message": f"Waiting for {len(session.active_leases)} active leases.",
                            "reason_code": e.reason_code,
                        }
                    )
                    + "\n"
                )
            return 0

        if e.reason_code in {"MISSING_CLASSIFICATION", "REQUEST_REJECTED"}:
            save_orchestration_session(session)
            sys.stdout.write(
                json.dumps(
                    {
                        "status": "WAITING",
                        "reason_code": e.reason_code,
                        "message": str(e),
                    }
                )
                + "\n"
            )
            return 0

        sys.stderr.write(f"Workflow dispatch failed: {e.reason_code}: {e}\n")
        return 2

    try:
        item_id = str(action_result.get("item_id"))
        request_path = str(action_result.get("request_path"))
        action_request = json.loads(Path(request_path).read_text(encoding="utf-8"))

        item_data = action_request.get("item", {})
        context_key = str(item_data.get("path") or item_id)
        lease = session.grant_lease(item_id, role, agent_id=f"orchestrator:{session.run_id}", context_key=context_key)

        session.queued_items = [queued_id for queued_id in session.queued_items if queued_id != item_id]

        workspace = core_session.workspace_dir(repo, pr)
        response_path = str(workspace / f"response-{item_id}.json")

        packet = build_worker_packet(
            run_id=session.run_id,
            lease_token=lease.lease_token,
            role=role,
            session_id=str(action_request.get("session_id") or f"{repo.replace('/', '__')}/pr-{pr}"),
            item=item_data,
            response_path=response_path,
            action_request=action_request,
        )

        save_orchestration_session(session)
        sys.stdout.write(json.dumps({"status": "DISPATCHED", "packet": packet}) + "\n")
        return 0
    except LeaseConflictError as e:
        sys.stderr.write(f"Lease conflict: {e}\n")
        return 2


def handle_resume(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number
    try:
        session = load_orchestration_session(repo, pr)
        _sync_queue_from_runtime(session, enforce_budget=False)
        save_orchestration_session(session)
        sys.stdout.write(f"agent orchestrate resume reloaded state for {repo}/pr-{pr}\n")
        return 0
    except OrchestrationSessionError as e:
        sys.stderr.write(f"{str(e)}\n")
        return 2


def handle_status(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number
    try:
        session = load_orchestration_session(repo, pr)
        elapsed = _sync_queue_from_runtime(session, enforce_budget=True)
        save_orchestration_session(session)
        sys.stdout.write(
            json.dumps(
                {
                    "status": "READY",
                    "run_id": session.run_id,
                    "active_leases": len(session.active_leases),
                    "queued_items": len(session.queued_items),
                    "reconciliation_seconds": round(elapsed, 6),
                }
            )
            + "\n"
        )
        return 0
    except OrchestrationSessionError as e:
        sys.stderr.write(f"{str(e)}\n")
        return 2
    except RuntimeError as e:
        sys.stderr.write(f"Queue reconciliation failed: {e}\n")
        return 2


def handle_stop(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number
    try:
        session = load_orchestration_session(repo, pr)
        if session.active_leases:
            sys.stderr.write(f"Cannot stop: {len(session.active_leases)} active leases exist.\n")
            return 2
        gate_rc = _run_authoritative_gate(repo, pr)
        if gate_rc != 0:
            sys.stderr.write("Cannot stop: final-gate failed.\n")
            return 2
        sys.stdout.write("agent orchestrate stop completed\n")
        return 0
    except OrchestrationSessionError:
        # If no session, stopping is trivial
        sys.stdout.write("agent orchestrate stop: no active session found\n")
        return 0


def _sync_queue_from_runtime(session: OrchestrationSession, *, enforce_budget: bool) -> float:
    started = time.perf_counter()
    runtime_state = _load_runtime_state(session.repo, session.pr_number)
    queued = _eligible_runtime_items(runtime_state)
    session.queued_items = [item_id for item_id in queued if item_id not in session.active_leases]
    elapsed = time.perf_counter() - started
    if enforce_budget and elapsed > MAX_QUEUE_RECONCILIATION_SECONDS:
        raise RuntimeError(
            f"reconciliation exceeded {MAX_QUEUE_RECONCILIATION_SECONDS:.3f}s budget ({elapsed:.3f}s)"
        )
    return elapsed


def _eligible_runtime_items(runtime_state: dict) -> List[str]:
    items = runtime_state.get("items") if isinstance(runtime_state, dict) else {}
    leases = runtime_state.get("leases") if isinstance(runtime_state, dict) else {}

    active_runtime_items = set()
    if isinstance(leases, dict):
        for lease in leases.values():
            if not isinstance(lease, dict):
                continue
            if str(lease.get("status") or "").lower() in {"active", "submitted"}:
                item_id = lease.get("item_id")
                if item_id:
                    active_runtime_items.add(str(item_id))

    eligible: List[str] = []
    if isinstance(items, dict):
        for item_id in sorted(items.keys()):
            item = items.get(item_id)
            if not isinstance(item, dict):
                continue
            if not bool(item.get("blocking")):
                continue
            if bool(item.get("handled")):
                continue
            if str(item_id) in active_runtime_items:
                continue
            eligible.append(str(item_id))

    return eligible


def _load_runtime_state(repo: str, pr_number: str) -> dict:
    try:
        return session_engine.load_session(repo, pr_number)
    except SystemExit as exc:
        if "Unsupported session schema version" in str(exc):
            return core_session.load_session(repo, pr_number)
        raise


def _run_authoritative_gate(repo: str, pr_number: str) -> int:
    try:
        return session_engine.cmd_gate(argparse.Namespace(repo=repo, pr_number=pr_number))
    except SystemExit as exc:
        if "Unsupported session schema version" not in str(exc):
            raise
        runtime_state = core_session.load_session(repo, pr_number)
        items = runtime_state.get("items", {}) if isinstance(runtime_state, dict) else {}
        if not isinstance(items, dict):
            return 1
        blocking = [item for item in items.values() if isinstance(item, dict) and bool(item.get("blocking"))]
        return 0 if not blocking else 1
