import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from gh_address_cr.core import session as core_session
from gh_address_cr.core.io import write_json_atomic

STATE_INITIALIZED = "INITIALIZED"
STATE_RUNNING = "RUNNING"
STATE_PAUSED = "PAUSED"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"

ORCHESTRATION_SCHEMA_VERSION = 2
DISPATCH_RECEIPT_SCHEMA_VERSION = "dispatch-receipt.v1"


class DispatchValidationError(Exception):
    pass


class OrchestrationSessionError(Exception):
    pass


@dataclass
class DispatchReceipt:
    item_id: str
    assigned_role: str
    agent_id: str
    lease_id: str
    request_id: str
    runtime_revision: int
    delivery_token: str
    retry_count: int = 0
    waiting_for_human: bool = False
    handoff_reason: Optional[str] = None
    artifact_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "schema_version": DISPATCH_RECEIPT_SCHEMA_VERSION,
            "item_id": self.item_id,
            "assigned_role": self.assigned_role,
            "agent_id": self.agent_id,
            "lease_id": self.lease_id,
            "request_id": self.request_id,
            "runtime_revision": self.runtime_revision,
            "delivery_token": self.delivery_token,
            "retry_count": self.retry_count,
            "waiting_for_human": self.waiting_for_human,
            "handoff_reason": self.handoff_reason,
            "artifact_path": self.artifact_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DispatchReceipt":
        if data.get("schema_version") != DISPATCH_RECEIPT_SCHEMA_VERSION:
            raise OrchestrationSessionError("Unsupported dispatch receipt schema version.")
        return cls(
            item_id=data["item_id"],
            assigned_role=data["assigned_role"],
            agent_id=data["agent_id"],
            lease_id=data["lease_id"],
            request_id=data["request_id"],
            runtime_revision=int(data["runtime_revision"]),
            delivery_token=data["delivery_token"],
            retry_count=data.get("retry_count", 0),
            waiting_for_human=data.get("waiting_for_human", False),
            handoff_reason=data.get("handoff_reason"),
            artifact_path=data.get("artifact_path"),
        )


@dataclass
class OrchestrationSession:
    run_id: str
    repo: str
    pr_number: str
    state: str = STATE_INITIALIZED
    config: Dict[str, int] = field(default_factory=lambda: {"max_concurrency": 3, "circuit_breaker_threshold": 3})
    completed: bool = False
    completed_at: Optional[str] = None
    completed_reason: Optional[str] = None
    active_dispatches: Dict[str, DispatchReceipt] = field(default_factory=dict)
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

    def project_dispatch(
        self,
        *,
        item_id: str,
        role: str,
        agent_id: str,
        lease_id: str,
        request_id: str,
        runtime_revision: int,
    ) -> DispatchReceipt:
        receipt = DispatchReceipt(
            item_id=item_id,
            assigned_role=role,
            agent_id=agent_id,
            lease_id=lease_id,
            request_id=request_id,
            runtime_revision=runtime_revision,
            delivery_token=f"dispatch-{uuid.uuid4().hex}",
        )
        self.active_dispatches[item_id] = receipt
        self.log_audit_event("DISPATCH_PROJECTED", {"item_id": item_id, "role": role})
        return receipt

    def validate_dispatch(self, item_id: str, delivery_token: str, runtime_state: dict) -> DispatchReceipt:
        receipt = self.active_dispatches.get(item_id)
        if receipt is None or receipt.delivery_token != delivery_token:
            raise DispatchValidationError("Dispatch token does not match the active projection.")
        lease = runtime_state.get("leases", {}).get(receipt.lease_id)
        if not isinstance(lease, dict):
            raise DispatchValidationError("Canonical lease no longer exists.")
        if str(lease.get("status") or "").lower() not in {"active", "submitted"}:
            raise DispatchValidationError("Canonical lease is no longer active.")
        if str(lease.get("item_id") or "") != item_id:
            raise DispatchValidationError("Canonical lease item binding changed.")
        if str(lease.get("request_id") or "") != receipt.request_id:
            raise DispatchValidationError("Canonical request binding changed.")
        return receipt

    def remove_dispatch(self, item_id: str, delivery_token: str) -> None:
        receipt = self.active_dispatches.get(item_id)
        if receipt is None:
            return
        if receipt.delivery_token != delivery_token:
            raise DispatchValidationError("Dispatch token does not match the active projection.")
        del self.active_dispatches[item_id]
        self.log_audit_event("DISPATCH_REMOVED", {"item_id": item_id})

    def reconcile_dispatches(self, runtime_state: dict, *, runtime_revision: int) -> dict[str, int]:
        removed = 0
        for item_id, receipt in list(self.active_dispatches.items()):
            try:
                self.validate_dispatch(item_id, receipt.delivery_token, runtime_state)
            except DispatchValidationError:
                del self.active_dispatches[item_id]
                removed += 1
        return {"retained": len(self.active_dispatches), "removed": removed, "runtime_revision": runtime_revision}

    def to_dict(self) -> dict:
        return {
            "schema_version": ORCHESTRATION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "repo": self.repo,
            "pr_number": self.pr_number,
            "state": self.state,
            "config": self.config,
            "completed": self.completed,
            "completed_at": self.completed_at,
            "completed_reason": self.completed_reason,
            "active_dispatches": {k: v.to_dict() for k, v in self.active_dispatches.items()},
            "queued_items": self.queued_items,
            "retry_counts": self.retry_counts,
            "audit_warnings": self.audit_warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OrchestrationSession":
        schema_version = int(data.get("schema_version") or 1)
        if schema_version not in {1, ORCHESTRATION_SCHEMA_VERSION}:
            raise OrchestrationSessionError("Unsupported orchestration schema version.")
        session = cls(
            run_id=data.get("run_id", f"run-{uuid.uuid4().hex}"),
            repo=data["repo"],
            pr_number=data["pr_number"],
            state=data.get("state", STATE_INITIALIZED),
            config=data.get("config", {"max_concurrency": 3, "circuit_breaker_threshold": 3}),
            completed=data.get("completed", False),
            completed_at=data.get("completed_at"),
            completed_reason=data.get("completed_reason"),
            queued_items=data.get("queued_items", []),
            retry_counts=data.get("retry_counts", {}),
            audit_warnings=data.get("audit_warnings", []),
        )
        if schema_version == ORCHESTRATION_SCHEMA_VERSION:
            session.active_dispatches = {
                k: DispatchReceipt.from_dict(v) for k, v in data.get("active_dispatches", {}).items()
            }
        elif data.get("active_leases"):
            session.audit_warnings.append(
                "ORCHESTRATION_V1_RECONCILE_REQUIRED: legacy shadow leases were discarded; runtime reconciliation is required"
            )
        return session


def save_orchestration_session(session: OrchestrationSession) -> None:
    workspace = core_session.workspace_dir(session.repo, session.pr_number)
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "orchestration.json"
    write_json_atomic(path, session.to_dict())


def load_orchestration_session(repo: str, pr_number: str) -> OrchestrationSession:
    workspace = core_session.workspace_dir(repo, pr_number)
    path = workspace / "orchestration.json"

    if not path.exists():
        raise OrchestrationSessionError("orchestration.json is missing. Session cannot be resumed.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return OrchestrationSession.from_dict(data)
    except json.JSONDecodeError as exc:
        raise OrchestrationSessionError("orchestration.json is corrupted. Session cannot be resumed.") from exc
