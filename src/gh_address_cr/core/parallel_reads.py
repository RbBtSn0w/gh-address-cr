"""Run independent read-only GitHub lookups concurrently.

Each ``gh`` call costs a full network round trip, so independent reads are
issued together. Outcomes are returned in submission order, one per thunk, and
the caller decides which exception wins; this keeps the error precedence of the
former sequential code. Only read-only, mutually independent calls belong here.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class ReadOutcome:
    """Value or exception captured from one concurrent read."""

    __slots__ = ("error", "value")

    def __init__(self, value: Any = None, error: Exception | None = None):
        self.value = value
        self.error = error

    def unwrap(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.value


def _capture(thunk: Callable[[], Any]) -> ReadOutcome:
    try:
        return ReadOutcome(value=thunk())
    except Exception as exc:
        return ReadOutcome(error=exc)


def gather_reads(*thunks: Callable[[], Any]) -> list[ReadOutcome]:
    """Run ``thunks`` concurrently and return their outcomes in submission order.

    Every thunk runs in a copy of the caller's context so the active OTel span
    and session telemetry stay attached to subprocess spans started in workers.
    """
    if len(thunks) <= 1:
        return [_capture(thunk) for thunk in thunks]
    with ThreadPoolExecutor(max_workers=len(thunks), thread_name_prefix="gh-address-cr-read") as pool:
        futures = [pool.submit(contextvars.copy_context().run, _capture, thunk) for thunk in thunks]
        return [future.result() for future in futures]
