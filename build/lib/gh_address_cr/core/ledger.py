from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(
        self,
        action: str,
        status: str,
        repo: str,
        pr_number: str,
        *,
        message: str,
        details: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if not action:
            raise ValueError("Audit event action is required.")
        if not status:
            raise ValueError("Audit event status is required.")
        if not message:
            raise ValueError("Audit event message is required.")
        record = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "action": action,
            "status": status,
            "repo": repo,
            "pr_number": str(pr_number),
            "message": message,
            "details": details or {},
        }
        if run_id:
            record["run_id"] = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record
