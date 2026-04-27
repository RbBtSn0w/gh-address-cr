import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import uuid
from gh_address_cr.core import session as core_session

STATE_INITIALIZED = "INITIALIZED"
STATE_RUNNING = "RUNNING"
STATE_PAUSED = "PAUSED"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"

LEASE_TTL_MINUTES = 15


class LeaseConflictError(Exception):
    pass


class ExpiredLeaseError(Exception):
    pass


class OrchestrationSessionError(Exception):
    pass


@dataclass
class LeaseRecord:
    item_id: str
    assigned_role: str
    agent_id: str
    lease_token: str
    expires_at: datetime
    context_key: str = ""

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if now is None:
            now = datetime.now(timezone.utc)
        return now >= self.expires_at

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "assigned_role": self.assigned_role,
            "agent_id": self.agent_id,
            "lease_token": self.lease_token,
            "expires_at": self.expires_at.isoformat(),
            "context_key": self.context_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LeaseRecord":
        return cls(
            item_id=data["item_id"],
            assigned_role=data["assigned_role"],
            agent_id=data["agent_id"],
            lease_token=data["lease_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            context_key=data.get("context_key", ""),
        )


@dataclass
class OrchestrationSession:
    run_id: str
    repo: str
    pr_number: str
    state: str = STATE_INITIALIZED
    active_leases: Dict[str, LeaseRecord] = field(default_factory=dict)
    queued_items: List[str] = field(default_factory=list)
    retry_counts: Dict[str, int] = field(default_factory=dict)
    audit_warnings: List[str] = field(default_factory=list)

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _append_audit_warning(self, event_type: str, error: Exception) -> None:
        message = f"{event_type}: {type(error).__name__}: {error}"
        if message not in self.audit_warnings:
            self.audit_warnings.append(message)
        if len(self.audit_warnings) > 8:
            self.audit_warnings = self.audit_warnings[-8:]

    def pop_audit_warnings(self) -> List[str]:
        warnings = list(self.audit_warnings)
        self.audit_warnings.clear()
        return warnings

    def log_audit_event(self, event_type: str, details: dict) -> bool:
        workspace = core_session.workspace_dir(self.repo, self.pr_number)
        audit_file = workspace / "orchestration_audit.log"
        event = {
            "timestamp": self._utc_now().isoformat(),
            "run_id": self.run_id,
            "event_type": event_type,
            "details": details,
        }
        try:
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
            return True
        except OSError as exc:
            self._append_audit_warning(event_type, exc)
            return False

    def grant_lease(self, item_id: str, role: str, agent_id: str = "agent", context_key: str = "") -> LeaseRecord:
        now = self._utc_now()

        # Check for context_key overlap across all active leases
        if context_key:
            for existing in self.active_leases.values():
                if existing.context_key == context_key and not existing.is_expired(now):
                    raise LeaseConflictError(
                        f"Cannot grant lease for {item_id}: overlapping context key '{context_key}' locked by {existing.item_id}."
                    )

        if item_id in self.active_leases:
            existing = self.active_leases[item_id]
            if not existing.is_expired(now):
                raise LeaseConflictError(f"Item {item_id} already has an active lease.")
            self.release_lease(item_id, existing.lease_token, force=True)

        token = f"lease-{uuid.uuid4().hex}"
        expires = now + timedelta(minutes=LEASE_TTL_MINUTES)

        lease = LeaseRecord(
            item_id=item_id,
            assigned_role=role,
            agent_id=agent_id,
            lease_token=token,
            expires_at=expires,
            context_key=context_key,
        )
        self.active_leases[item_id] = lease
        self.log_audit_event("LEASE_GRANTED", {"item_id": item_id, "role": role, "agent_id": agent_id, "token": token})
        return lease

    def release_lease(self, item_id: str, token: str, force: bool = False) -> None:
        if item_id not in self.active_leases:
            return

        existing = self.active_leases[item_id]
        if existing.lease_token != token and not force:
            raise LeaseConflictError("Invalid lease token for release.")

        del self.active_leases[item_id]
        self.log_audit_event("LEASE_RELEASED", {"item_id": item_id, "token": token, "forced": force})

    def validate_lease_for_submission(self, item_id: str, token: str) -> None:
        if item_id not in self.active_leases:
            raise ExpiredLeaseError(f"No active lease found for {item_id}.")

        lease = self.active_leases[item_id]
        if lease.lease_token != token:
            raise LeaseConflictError("Token mismatch during submission.")

        if lease.is_expired(self._utc_now()):
            self.release_lease(item_id, lease.lease_token, force=True)
            raise ExpiredLeaseError("Lease expired before submission.")

    def handle_verifier_reject(self, item_id: str, token: str) -> None:
        self.release_lease(item_id, token, force=True)
        self.log_audit_event("VERIFIER_REJECT", {"item_id": item_id})

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "repo": self.repo,
            "pr_number": self.pr_number,
            "state": self.state,
            "active_leases": {k: v.to_dict() for k, v in self.active_leases.items()},
            "queued_items": self.queued_items,
            "retry_counts": self.retry_counts,
            "audit_warnings": self.audit_warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OrchestrationSession":
        session = cls(
            run_id=data.get("run_id", f"run-{uuid.uuid4().hex}"),
            repo=data["repo"],
            pr_number=data["pr_number"],
            state=data.get("state", STATE_INITIALIZED),
            queued_items=data.get("queued_items", []),
            retry_counts=data.get("retry_counts", {}),
            audit_warnings=data.get("audit_warnings", []),
        )
        session.active_leases = {k: LeaseRecord.from_dict(v) for k, v in data.get("active_leases", {}).items()}
        return session


def save_orchestration_session(session: OrchestrationSession) -> None:
    workspace = core_session.workspace_dir(session.repo, session.pr_number)
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "orchestration.json"
    path.write_text(json.dumps(session.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_orchestration_session(repo: str, pr_number: str) -> OrchestrationSession:
    workspace = core_session.workspace_dir(repo, pr_number)
    path = workspace / "orchestration.json"

    if not path.exists():
        raise OrchestrationSessionError("orchestration.json is missing. Session cannot be resumed.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return OrchestrationSession.from_dict(data)
    except json.JSONDecodeError:
        raise OrchestrationSessionError("orchestration.json is corrupted. Session cannot be resumed.")
