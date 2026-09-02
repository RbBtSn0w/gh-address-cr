from __future__ import annotations

from typing import Any

from gh_address_cr.core.command_templates import common_summary_commands


class WorkflowError(RuntimeError):
    def __init__(
        self,
        *,
        status: str,
        reason_code: str,
        exit_code: int,
        message: str,
        waiting_on: str | None = None,
        payload: dict[str, Any] | None = None,
    ):
        self.status = status
        self.reason_code = reason_code
        self.exit_code = exit_code
        self.waiting_on = waiting_on
        self.payload = payload or {}
        super().__init__(message)

    def to_summary(self, *, repo: str, pr_number: str) -> dict[str, Any]:
        return {
            **self.payload,
            "status": self.status,
            "repo": repo,
            "pr_number": pr_number,
            "reason_code": self.reason_code,
            "waiting_on": self.waiting_on,
            "next_action": str(self),
            # Error paths otherwise ship a diagnosis with no runnable command, forcing a
            # reference-doc lookup. Curated per-raise-site menus win over the default.
            "commands": self.payload.get("commands") or common_summary_commands(repo, str(pr_number)),
            "exit_code": self.exit_code,
        }
