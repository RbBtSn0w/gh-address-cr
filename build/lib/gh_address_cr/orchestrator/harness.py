import argparse
import sys
import json
import time
from pathlib import Path
from uuid import uuid4
import os
from typing import List, Optional
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


def _output_signal(status: str, reason_code: str, next_action: str, message: str, warnings: Optional[List[str]] = None) -> None:
    payload = {
        "status": status,
        "reason_code": reason_code,
        "next_action": next_action,
        "message": message
    }
    if warnings:
        payload["warnings"] = warnings
    sys.stdout.write(json.dumps(payload) + "\n")


def check_runtime_version() -> bool:
    try:
        current = Version(__version__)
        required = Version(MIN_REQUIRED_VERSION)
        if current < required:
            return False
    except Exception:
        pass
    return True


def _parse_common_args(args: List[str]):
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--max-concurrency", type=int, default=int(os.environ.get("GH_ADDRESS_CR_ORCH_MAX_CONCURRENCY", 3)))
    parser.add_argument("--circuit-breaker-threshold", type=int, default=int(os.environ.get("GH_ADDRESS_CR_ORCH_CIRCUIT_BREAKER_THRESHOLD", 3)))
    try:
        return parser.parse_known_args(args)
    except (argparse.ArgumentError, SystemExit) as e:
        _output_signal("FAILED", "INVALID_ARGUMENTS", "HALT", str(e))
        sys.exit(2)


def handle_agent_orchestrate(subcommand: str | None, passthrough: List[str]) -> int:
    try:
        if not check_runtime_version():
            _output_signal("FAILED", "INCOMPATIBLE_RUNTIME", "HALT", f"Incompatible Runtime CLI version: {__version__}")
            return 2

        valid_subcommands = ["start", "status", "step", "resume", "stop", "submit"]
        if subcommand not in valid_subcommands:
            _output_signal("FAILED", "INVALID_SUBCOMMAND", "HALT", f"Invalid subcommand: {subcommand}. Use one of {valid_subcommands}")
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
    except SystemExit as e:
        # If it reached here, it was likely from a sub-call that we didn't catch
        # We don't want to double-signal if _output_signal was already called
        # But if it's a raw SystemExit from core, we should signal it.
        # We'll assume if e.code is a string, it's a message we should signal.
        if isinstance(e.code, str):
            _output_signal("FAILED", "SYSTEM_EXIT", "HALT", e.code)
        return e.code if isinstance(e.code, int) else 2
    except Exception as e:
        _output_signal("FAILED", "SYSTEM_ERROR", "HALT", str(e))
        return 5


def handle_submit(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent orchestrate submit", exit_on_error=False)
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--input", required=True)
    try:
        parsed, _ = parser.parse_known_args(args)
    except (argparse.ArgumentError, SystemExit) as e:
        _output_signal("FAILED", "INVALID_ARGUMENTS", "HALT", str(e))
        return 2
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
            cb_threshold = session.config.get("circuit_breaker_threshold", MAX_RETRIES)
            if retry_count >= cb_threshold:
                if parsed.item_id in session.active_leases:
                    session.active_leases[parsed.item_id].waiting_for_human = True
                    session.active_leases[parsed.item_id].handoff_reason = str(e)
                    session.active_leases[parsed.item_id].artifact_path = parsed.input
                save_orchestration_session(session)
                _output_signal("FAILED", "HUMAN_INTERVENTION_REQUIRED", "HANDOFF", f"CRITICAL: Human Handoff Required: Max retries ({cb_threshold}) reached for {parsed.item_id}.")
                return 2
            save_orchestration_session(session)
            _output_signal("FAILED", "PAYLOAD_CORRUPT", "RETRY", f"Submission failed: {e}")
            return 2
        except HumanHandoffRequired as e:
            cb_threshold = session.config.get("circuit_breaker_threshold", MAX_RETRIES)
            session.retry_counts[parsed.item_id] = max(retry_count, cb_threshold)
            if parsed.item_id in session.active_leases:
                session.active_leases[parsed.item_id].waiting_for_human = True
                session.active_leases[parsed.item_id].handoff_reason = str(e)
                session.active_leases[parsed.item_id].artifact_path = parsed.input
            save_orchestration_session(session)
            _output_signal("FAILED", "HUMAN_INTERVENTION_REQUIRED", "HANDOFF", f"CRITICAL: Human Handoff Required: {e}")
            return 2

        try:
            _ = workflow.submit_action_response(repo, pr, response_path=str(parsed.input))
        except workflow.WorkflowError as e:
            save_orchestration_session(session)
            _output_signal("FAILED", e.reason_code, "RETRY", f"Submission failed: {e.reason_code}: {e}")
            return 2

        session.release_lease(parsed.item_id, parsed.token)
        session.retry_counts.pop(parsed.item_id, None)
        warnings = session.pop_audit_warnings()

        save_orchestration_session(session)
        _output_signal(
            "SUCCESS",
            "SUBMITTED",
            "PROCEED",
            f"Verified and submitted {parsed.item_id}",
            warnings
        )
        return 0
    except (WorkerPacketValidationError, ExpiredLeaseError, LeaseConflictError) as e:
        _output_signal("FAILED", "STALE_REQUEST_CONTEXT", "RETRY", f"Submission failed: {e}")
        return 2
    except OrchestrationSessionError as e:
        _output_signal("FAILED", "SESSION_ERROR", "HALT", f"Submission failed: {e}")
        return 2
    except HumanHandoffRequired as e:
        _output_signal("FAILED", "HUMAN_INTERVENTION_REQUIRED", "HANDOFF", f"CRITICAL: Human Handoff Required: {e}")
        return 2
    except Exception as e:
        _output_signal("FAILED", "SYSTEM_ERROR", "HALT", f"Unexpected error: {e}")
        return 5


def handle_start(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number

    try:
        try:
            session = load_orchestration_session(repo, pr)
            if session.completed:
                runtime_state = _load_runtime_state(repo, pr)
                if not _eligible_runtime_items(runtime_state):
                    _output_signal("LOCKED", "SESSION_LOCKED", "HALT", "Session is locked and fully handled.")
                    return 0
                else:
                    session.completed = False
        except OrchestrationSessionError:
            session = OrchestrationSession(run_id=f"run-{uuid4().hex[:8]}", repo=repo, pr_number=pr)

        session.config["max_concurrency"] = parsed.max_concurrency
        session.config["circuit_breaker_threshold"] = parsed.circuit_breaker_threshold

        _sync_queue_from_runtime(session, enforce_budget=False)
        warnings = session.pop_audit_warnings()

        save_orchestration_session(session)
        
        _output_signal(
            "SUCCESS", 
            "INITIALIZED", 
            "PROCEED", 
            f"Initialized session {session.run_id} for {repo}/pr-{pr} (queued={len(session.queued_items)})",
            warnings
        )
        return 0
    except (Exception, SystemExit) as e:
        msg = str(e) if not isinstance(e, SystemExit) else str(e.code)
        _output_signal("FAILED", "SYSTEM_ERROR", "HALT", f"Failed to start orchestration: {msg}")
        return 5


def handle_step(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent orchestrate step", exit_on_error=False)
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--role", help="Role-based filtering (e.g., triage)")
    parser.add_argument("--max-concurrency", type=int, default=int(os.environ.get("GH_ADDRESS_CR_ORCH_MAX_CONCURRENCY", 3)))
    parser.add_argument("--circuit-breaker-threshold", type=int, default=int(os.environ.get("GH_ADDRESS_CR_ORCH_CIRCUIT_BREAKER_THRESHOLD", 3)))
    try:
        parsed, _ = parser.parse_known_args(args)
    except (argparse.ArgumentError, SystemExit) as e:
        _output_signal("FAILED", "INVALID_ARGUMENTS", "HALT", str(e))
        return 2
    repo, pr = parsed.repo, parsed.pr_number

    try:
        session = load_orchestration_session(repo, pr)
        if "--max-concurrency" in args:
            session.config["max_concurrency"] = parsed.max_concurrency
        if "--circuit-breaker-threshold" in args:
            session.config["circuit_breaker_threshold"] = parsed.circuit_breaker_threshold

        _sync_queue_from_runtime(session, enforce_budget=False)

        if session.completed:
            if not session.queued_items and not session.active_leases:
                _output_signal("LOCKED", "SESSION_LOCKED", "HALT", "Session is locked and fully handled.")
                return 0
            else:
                session.completed = False

        if len(session.active_leases) >= session.config.get("max_concurrency", 3):
            warnings = session.pop_audit_warnings()
            _output_signal("WAITING", "MAX_CONCURRENCY_REACHED", "RETRY", f"Max concurrency ({session.config.get('max_concurrency', 3)}) reached.", warnings)
            return 0

    except (OrchestrationSessionError, SystemExit) as e:
        msg = str(e) if not isinstance(e, SystemExit) else str(e.code)
        _output_signal("FAILED", "SESSION_ERROR", "HALT", msg)
        return 2
    except Exception as e:
        _output_signal("FAILED", "SYSTEM_ERROR", "HALT", f"Failed to synchronize runtime queue: {e}")
        return 2

    # Simple dequeue logic
    if not session.queued_items:
        if not session.active_leases:
            warnings = session.pop_audit_warnings()
            _output_signal("SUCCESS", "QUEUE_EMPTY", "HALT", "Zero pending items.", warnings)
            return 0
        else:
            warnings = session.pop_audit_warnings()
            _output_signal("WAITING", "WAITING_FOR_LEASES", "RETRY", f"Waiting for {len(session.active_leases)} active leases.", warnings)
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
            warnings = session.pop_audit_warnings()
            if not session.active_leases:
                _output_signal("SUCCESS", "QUEUE_EMPTY", "HALT", "Zero pending items.", warnings)
            else:
                _output_signal("WAITING", "WAITING_FOR_LEASES", "RETRY", f"Waiting for {len(session.active_leases)} active leases.", warnings)
            return 0

        if e.reason_code in {"MISSING_CLASSIFICATION", "REQUEST_REJECTED"}:
            save_orchestration_session(session)
            warnings = session.pop_audit_warnings()
            _output_signal("WAITING", e.reason_code, "RETRY", str(e), warnings)
            return 0

        _output_signal("FAILED", "WORKFLOW_DISPATCH_FAILED", "RETRY", f"Workflow dispatch failed: {e.reason_code}: {e}")
        return 2

    try:
        item_id = str(action_result.get("item_id"))
        request_path = str(action_result.get("request_path"))
        action_request = json.loads(Path(request_path).read_text(encoding="utf-8"))

        item_data = action_request.get("item", {})
        
        context_key = str(item_data.get("path") or item_id)
        lease = session.grant_lease(item_id, role, agent_id=f"orchestrator:{session.run_id}", context_key=context_key)
        warnings = session.pop_audit_warnings()

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
        
        payload = {
            "status": "DISPATCHED",
            "reason_code": "NEW_TASK",
            "next_action": "PROCEED",
            "packet": packet
        }
        if warnings:
            payload["warnings"] = warnings
        sys.stdout.write(json.dumps(payload) + "\n")
        return 0
    except LeaseConflictError as e:
        _output_signal("FAILED", "LEASE_CONFLICT", "RETRY", f"Lease conflict: {e}")
        return 2


def handle_resume(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number
    try:
        session = load_orchestration_session(repo, pr)
        _sync_queue_from_runtime(session, enforce_budget=False)
        warnings = session.pop_audit_warnings()
        save_orchestration_session(session)
        
        _output_signal("SUCCESS", "RESUMED", "PROCEED", f"Resumed session {session.run_id} for {repo}/pr-{pr}", warnings)
        return 0
    except (OrchestrationSessionError, SystemExit) as e:
        msg = str(e) if not isinstance(e, SystemExit) else str(e.code)
        _output_signal("FAILED", "SESSION_ERROR", "HALT", msg)
        return 2
    except Exception as e:
        _output_signal("FAILED", "SYSTEM_ERROR", "HALT", f"Failed to resume orchestration: {e}")
        return 5


def handle_status(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number
    try:
        session = load_orchestration_session(repo, pr)
        elapsed = _sync_queue_from_runtime(session, enforce_budget=True)
        warnings = session.pop_audit_warnings()
        save_orchestration_session(session)
        
        payload = {
            "status": "READY",
            "reason_code": "STATUS_OK",
            "next_action": "PROCEED",
            "run_id": session.run_id,
            "active_leases": len(session.active_leases),
            "queued_items": len(session.queued_items),
            "reconciliation_seconds": round(elapsed, 6),
        }
        if warnings:
            payload["warnings"] = warnings
        sys.stdout.write(json.dumps(payload) + "\n")
        return 0
    except (OrchestrationSessionError, SystemExit) as e:
        msg = str(e) if not isinstance(e, SystemExit) else str(e.code)
        _output_signal("FAILED", "SESSION_ERROR", "HALT", msg)
        return 2
    except RuntimeError as e:
        _output_signal("FAILED", "RECONCILIATION_TIMEOUT", "RETRY", str(e))
        return 2
    except Exception as e:
        _output_signal("FAILED", "SYSTEM_ERROR", "HALT", f"Unexpected error during status: {e}")
        return 5


def handle_stop(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number
    try:
        session = load_orchestration_session(repo, pr)
        if session.active_leases:
            _output_signal("FAILED", "ACTIVE_LEASES_EXIST", "HALT", f"Cannot stop: {len(session.active_leases)} active leases exist.")
            return 2
        gate_rc = _run_authoritative_gate(repo, pr)
        if gate_rc != 0:
            _output_signal("FAILED", "GATE_FAILED", "HALT", "Cannot stop: final-gate failed.")
            return 2
        
        session.completed = True
        from datetime import datetime, timezone
        session.completed_at = datetime.now(timezone.utc).isoformat()
        session.completed_reason = "Manual stop via agent orchestrate stop"
        save_orchestration_session(session)

        _output_signal("SUCCESS", "COMPLETED", "HALT", "agent orchestrate stop completed")
        return 0
    except OrchestrationSessionError:
        _output_signal("SUCCESS", "COMPLETED", "HALT", "agent orchestrate stop: no active session found")
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
