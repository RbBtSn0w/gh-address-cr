# Spec 045: Cross-session `gh` throttle (advisory, machine-local)

Architecture Preflight for coordinating `gh` calls across concurrent sessions that
share one GitHub token. Current code, tests, and `AGENTS.md` govern execution.

## Problem

GitHub's primary and secondary limits are per token, so every session on a machine
shares one budget. Sessions on different PRs are isolated locally (one
`runtime.sqlite3` per PR) and know nothing of each other: no shared throttle, no
shared backoff, no spacing between writes. GitHub asks clients to make mutating
requests serially with at least one second between them, and to stop sending
requests after a rate-limit signal (403/429). Secondary-limit state is not
observable, so the only usable signal is a failure this machine observed.

Evidence is code and documentation only; no production failure data exists in the
repository. Measure first with the `gh_address_cr.subprocess` spans and the
`gh_address_cr.github.retry` / `gh_address_cr.github.throttle.*` events.

## Preflight

| Item | Decision |
| --- | --- |
| Authoritative state owner | None new. Review state stays in `runtime.sqlite3`. Nothing under `gh-throttle/` is read by `final-gate` or any state transition. |
| External facts / inputs | A `gh` result classified as rate limited (stderr category `rate_limit`, or a GraphQL `RATE_LIMITED` error returned with exit 0); wall-clock time; whether a command is a GraphQL mutation. |
| Projection | `<state_dir>/gh-throttle/backoff-until.json` (`{"until": epoch}`) and `last-mutation.json` (`{"at": epoch}`). Both are derived observations, written last-writer-wins by `write_json_atomic`, and never authoritative. |
| Policy | Deterministic constants: 8 read slots, 1 mutation lane, 1.0 s spacing between mutations, 60 s backoff after a rate-limit signal (GitHub's documented minimum when no reset is known). A mutation serializes machine-wide on one lock. While the backoff is open, a call fails fast with `GITHUB_RATE_LIMITED` without contacting GitHub. |
| Side-effect plan | No new network IO. Advisory `flock` files and two tiny JSON files, all under the state dir, reusing `core/process_lock.py`. The OS releases a lock when its holder exits, so a crashed session never strands a slot. |
| Artifact truth boundary | The files are coordination hints, not evidence. A missing, malformed, or unwritable file means "no information" and the call proceeds (fail-open). A reply is still proven only by reply/resolve evidence and `final-gate`. |
| Self-reference risk | Telemetry events (`gh_address_cr.github.throttle.wait`, `.breaker_open`) carry bounded integers and a fixed `kind` enum only; no paths, logins, or argv. They are observations and change no completion semantics. |
| Recovery / replay | Nothing to replay. Locks vanish with their holder; the backoff file expires by itself; deleting `gh-throttle/` is always safe. |

## Scope

The gate wraps `GitHubClient`'s default runner, which carries every review-path
read and mutation. Auxiliary commands (`doctor`, `active-pr`, `submit-feedback`)
and the auth preflight call `gh` directly and are intentionally outside it.

## Alternatives rejected

- **Long-lived local daemon / HTTP client.** Already rejected for a similar helper in
  Spec 041 (principle X). It adds a process lifecycle and a second control surface.
- **Second SQLite store with a token bucket.** A second persistence boundary beside
  the authoritative one for a signal GitHub does not expose.
- **ETag conditional requests / thread-snapshot cache.** GraphQL has no documented
  equivalent, and a cache must never stand in for the fresh reads `final-gate` needs.

## Accepted trade-offs and limits

- A rate-limit signal stops every session on the machine for 60 s, even if the
  real reset is later. Each new signal extends the window.
- Machine-wide serialization only works when sessions share a state dir. A
  per-session `GH_ADDRESS_CR_STATE_DIR` override disables the coordination.
- Lock waits are bounded (10 s read slot, 30 s mutation lane); on timeout the call
  proceeds and a `throttle.wait` event records `timed_out`.
- `flock` does not work on network filesystems (same limit as Spec 034 FR-013).
- Mutations pay at least 1 s each, which keeps a publish loop under GitHub's
  80-content-requests-per-minute guidance.

## Executable contract tests

- `tests/test_gh_throttle.py`: backoff open/expired/corrupt, fail-open on an
  unwritable state dir, slot exhaustion times out and proceeds, mutation spacing,
  mutation detection, rate-limit results open the breaker through the default
  runner, and an open breaker avoids spawning `gh`.
