import argparse
import sys
import json
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
)
from gh_address_cr.core import session as core_session

MIN_REQUIRED_VERSION = "0.0.1"


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

        # Phase 3: Evidence Validation
        required_evidence = ["files", "validation_commands", "note", "fix_reply"]
        parse_and_validate_response(parsed.input, required_evidence)

        # Validate lease
        session.validate_lease_for_submission(parsed.item_id, parsed.token)

        # Release lease upon successful validation
        session.release_lease(parsed.item_id, parsed.token)

        save_orchestration_session(session)
        sys.stdout.write(
            json.dumps({"status": "SUCCESS", "message": f"Verified and submitted {parsed.item_id}"}) + "\n"
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
        # In a real impl, we'd load core session here to populate initial queue
        # For MVP, we just create a new OrchestrationSession
        session = OrchestrationSession(run_id=f"run-{uuid4().hex[:8]}", repo=repo, pr_number=pr)

        # Poll core items to build queue (Simulated for MVP)
        # core_data = core_session.SessionManager(repo, pr).load()
        # for item_id, item in core_data.get("items", {}).items():
        #     if item.get("blocking"):
        #         session.queued_items.append(item_id)

        save_orchestration_session(session)
        sys.stdout.write(f"agent orchestrate start: initialized session {session.run_id} for {repo}/pr-{pr}\n")
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
    except OrchestrationSessionError as e:
        sys.stderr.write(f"{e}\n")
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

    # Pick next item (MVP: just the first one)
    item_id = session.queued_items.pop(0)
    role = parsed.role or "fixer"  # Default to fixer for MVP

    try:
        lease = session.grant_lease(item_id, role)
        # Mock item data for packet construction
        item_data = {"item_id": item_id, "path": "unknown", "line": 0}

        workspace = core_session.workspace_dir(repo, pr)
        response_path = str(workspace / f"response-{item_id}.json")

        packet = build_worker_packet(
            run_id=session.run_id,
            lease_token=lease.lease_token,
            role=role,
            session_id=f"{repo.replace('/', '__')}/pr-{pr}",
            item=item_data,
            response_path=response_path,
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
        load_orchestration_session(repo, pr)
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
        sys.stdout.write(
            json.dumps(
                {
                    "status": "READY",
                    "run_id": session.run_id,
                    "active_leases": len(session.active_leases),
                    "queued_items": len(session.queued_items),
                }
            )
            + "\n"
        )
        return 0
    except OrchestrationSessionError as e:
        sys.stderr.write(f"{str(e)}\n")
        return 2


def handle_stop(args: List[str]) -> int:
    parsed, _ = _parse_common_args(args)
    repo, pr = parsed.repo, parsed.pr_number
    try:
        session = load_orchestration_session(repo, pr)
        if session.active_leases:
            sys.stderr.write(f"Cannot stop: {len(session.active_leases)} active leases exist.\n")
            return 2
        sys.stdout.write("agent orchestrate stop completed\n")
        return 0
    except OrchestrationSessionError:
        # If no session, stopping is trivial
        sys.stdout.write("agent orchestrate stop: no active session found\n")
        return 0
