"""Advisory execution locks that prove an outbox executor is still alive.

An outbox command is ``in_flight`` from the moment its executor commits the
attempt until it records the external result. SQLite cannot hold a lock across
that external call without blocking every other writer, so the executor holds
an OS advisory lock on ``<workspace>/outbox-exec/<command_id>.lock`` instead.
The operating system releases the lock when the process exits for any reason,
so "lock acquirable" is proof that the executor is gone, with no pid-reuse
ambiguity. Network filesystems are unsupported (Spec 034 FR-013).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import IO

if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle: IO[bytes]) -> bool:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


LOCK_DIRECTORY = "outbox-exec"


class ExecutionLock:
    """A held execution lock; release it exactly once."""

    def __init__(self, handle: IO[bytes]):
        self._handle: IO[bytes] | None = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()


def _lock_path(workspace: Path, command_id: str) -> Path:
    if not command_id or "/" in command_id or "\\" in command_id or command_id in {".", ".."}:
        raise ValueError("Outbox command identifiers must be plain file names.")
    directory = Path(workspace) / LOCK_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{command_id}.lock"


def try_acquire_execution_lock(workspace: Path, command_id: str) -> ExecutionLock | None:
    """Acquire the command's execution lock, or return None if a live executor holds it."""
    handle = open(_lock_path(workspace, command_id), "a+b")
    if not _try_lock(handle):
        handle.close()
        return None
    return ExecutionLock(handle)


def is_execution_lock_held(workspace: Path, command_id: str) -> bool:
    """True while any process, including this one, holds the command's execution lock."""
    probe = try_acquire_execution_lock(workspace, command_id)
    if probe is None:
        return True
    probe.release()
    return False
