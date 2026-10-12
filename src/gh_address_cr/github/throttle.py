"""Advisory, machine-local coordination of `gh` calls across concurrent sessions (Spec 045).

Every session on a machine shares one GitHub token and therefore one rate-limit
budget, yet sessions on different PRs share no local state. This module adds three
non-authoritative hints under ``<state_dir>/gh-throttle/``: a bounded number of
concurrent read slots, one serialized lane for mutations with spacing between them,
and a shared backoff that opens after a rate-limit signal. All of it is fail-open:
missing, malformed or unwritable files mean "no information" and the call proceeds.
Nothing here is read by ``final-gate`` or any state transition.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.paths import PathResolutionError, state_dir
from gh_address_cr.core.process_lock import ExecutionLock, try_acquire_execution_lock
from gh_address_cr.github.errors import GitHubRateLimitError

THROTTLE_DIRECTORY = "gh-throttle"
READ_SLOTS = 8
SLOT_WAIT_SECONDS = 10.0
MUTATION_WAIT_SECONDS = 30.0
MUTATION_SPACING_SECONDS = 1.0
# GitHub's documented minimum wait when a rate-limit response carries no reset time.
BACKOFF_SECONDS = 60.0
_POLL_SECONDS = 0.1
# Anchored on the unescaped JSON key so a comment body that merely mentions the word cannot match.
_GRAPHQL_RATE_LIMITED_RE = re.compile(r'"type"\s*:\s*"RATE_LIMITED"')

_BACKOFF_FILE = "backoff-until.json"
_LAST_MUTATION_FILE = "last-mutation.json"
_MUTATION_LOCK = "mutation"


def is_mutation_command(cmd: Sequence[str]) -> bool:
    return any(str(part).startswith("query=mutation") for part in cmd)


def is_rate_limit_result(category: str | None, returncode: int, stdout: str | None) -> bool:
    """A rate-limit signal: a classified failure, or a GraphQL RATE_LIMITED error returned with exit 0."""
    if returncode != 0:
        return category == "rate_limit"
    return _GRAPHQL_RATE_LIMITED_RE.search(stdout or "") is not None


def record_rate_limit() -> None:
    """Open (or extend) the shared backoff window after observing a rate-limit signal."""
    root = _root()
    if root is None:
        return
    until = time.time() + BACKOFF_SECONDS
    try:
        write_json_atomic(root / _BACKOFF_FILE, {"until": max(until, _read_epoch(root / _BACKOFF_FILE, "until"))})
    except OSError:
        return


@contextmanager
def gh_call_gate(cmd: Sequence[str]) -> Iterator[None]:
    """Serialize mutations, bound concurrent reads, and honor a shared rate-limit backoff."""
    root = _root()
    if root is None:
        yield
        return
    _raise_if_backoff_open(root)
    mutation = is_mutation_command(cmd)
    started = time.monotonic()
    if mutation:
        lock = _acquire_named(root, _MUTATION_LOCK, MUTATION_WAIT_SECONDS)
    else:
        lock = _acquire_slot(root, SLOT_WAIT_SECONDS)
    _emit_wait("mutation" if mutation else "read", started, timed_out=lock is None)
    try:
        if mutation:
            _space_mutation(root)
        yield
    finally:
        if mutation:
            _mark_mutation(root)
        if lock is not None:
            lock.release()


def _root() -> Path | None:
    try:
        root = state_dir() / THROTTLE_DIRECTORY
        root.mkdir(parents=True, exist_ok=True)
    except (OSError, PathResolutionError):
        return None
    return root


def _read_epoch(path: Path, key: str) -> float:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        return 0.0
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _raise_if_backoff_open(root: Path) -> None:
    remaining = _read_epoch(root / _BACKOFF_FILE, "until") - time.time()
    if remaining <= 0:
        return
    from gh_address_cr.otel_tracing import add_current_span_event

    add_current_span_event(
        "gh_address_cr.github.throttle.breaker_open",
        {"gh_address_cr.github.throttle.remaining_s": int(remaining)},
    )
    raise GitHubRateLimitError(
        f"GitHub rate limiting was observed recently; not contacting GitHub for another {int(remaining) + 1}s."
    )


def _acquire_named(root: Path, name: str, wait_seconds: float) -> ExecutionLock | None:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            lock = try_acquire_execution_lock(root, name)
        except OSError:
            return None
        if lock is not None:
            return lock
        if time.monotonic() >= deadline:
            return None
        time.sleep(_POLL_SECONDS * random.uniform(0.5, 1.5))


def _acquire_slot(root: Path, wait_seconds: float) -> ExecutionLock | None:
    deadline = time.monotonic() + wait_seconds
    while True:
        for index in range(READ_SLOTS):
            try:
                lock = try_acquire_execution_lock(root, f"slot-{index}")
            except OSError:
                return None
            if lock is not None:
                return lock
        if time.monotonic() >= deadline:
            return None
        time.sleep(_POLL_SECONDS * random.uniform(0.5, 1.5))


def _space_mutation(root: Path) -> None:
    gap = MUTATION_SPACING_SECONDS - (time.time() - _read_epoch(root / _LAST_MUTATION_FILE, "at"))
    if 0 < gap <= MUTATION_SPACING_SECONDS:
        time.sleep(gap)


def _mark_mutation(root: Path) -> None:
    try:
        write_json_atomic(root / _LAST_MUTATION_FILE, {"at": time.time()})
    except OSError:
        return


def _emit_wait(kind: str, started: float, *, timed_out: bool) -> None:
    from gh_address_cr.otel_tracing import add_current_span_event

    add_current_span_event(
        "gh_address_cr.github.throttle.wait",
        {
            "gh_address_cr.github.throttle.kind": kind,
            "gh_address_cr.github.throttle.wait_ms": int((time.monotonic() - started) * 1000),
            "gh_address_cr.github.throttle.timed_out": timed_out,
        },
    )
