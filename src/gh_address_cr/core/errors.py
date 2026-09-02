from __future__ import annotations

from typing import Any

from gh_address_cr.core.command_templates import common_summary_commands
from gh_address_cr.core.remediation import remediation_for


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
            # reference-doc lookup. Curated per-raise-site menus win over the default --
            # checked by key presence, not truthiness, so an intentionally empty curated
            # dict is preserved instead of being replaced by the default menu.
            "commands": (
                self.payload["commands"] if "commands" in self.payload else common_summary_commands(repo, str(pr_number))
            ),
            "remediation": (
                self.payload["remediation"]
                if "remediation" in self.payload
                else remediation_for(self.reason_code, repo=repo, pr_number=str(pr_number))
            ),
            "exit_code": self.exit_code,
        }
