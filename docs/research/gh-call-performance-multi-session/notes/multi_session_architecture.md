# Multi-session gh contention: GitHub limits vs gh-address-cr architecture

Scope: several PR sessions / agents running gh-address-cr on one machine with one GitHub token. Code facts are cited as file:line (paths under `src/gh_address_cr/`, worktree cranky-napier-bd6bdb, HEAD cd17a66). Anything marked INFERENCE is my reasoning, not verified.

## 1. How is session state scoped, and is anything shared across sessions?

### Takeaway
State is scoped per PR workspace directory with a per-workspace `runtime.sqlite3`. The only cross-PR common ground is the state-dir root and the single `gh` credential. There is no shared rate-limit budget, throttle, header reader, token/login cache, or cross-workspace lock. Two sessions on different PRs are fully independent for local state but fully coupled on GitHub's side.

### Cited Findings (code, verified)
- State root is `GH_ADDRESS_CR_STATE_DIR` or `~/Library/Caches/gh-address-cr` (macOS) / `~/.cache/gh-address-cr`; workspace is `<state>/<owner>__<repo>/pr-<N>` — `core/paths.py:46-66`.
- Per-workspace SQLite store with `busy_timeout` default 5000 ms, `BEGIN IMMEDIATE` write transactions — `core/runtime_store.py:262-265`, `:500`, `:1367-1373`. No `journal_mode`/WAL pragma found by grep (INFERENCE: default rollback journal; readers/writers on the same PR serialize via busy_timeout only).
- Leases are scoped by `(session_id, item_id)`: unique partial index `leases_one_active_per_item` — `core/runtime_store.py:164-165`; table at `:82-99`. So leases arbitrate agents on one PR's items; they do nothing across PRs and nothing about GitHub budget.
- The only OS-level lock is a per-outbox-command `flock` under `<workspace>/outbox-exec/<command_id>.lock`, used as a liveness proof — `core/process_lock.py:1-90`. It is workspace-local, not a shared gh throttle.
- RFC 033 explicitly deferred a file lock / CAS protocol, and RFC 041 rejected a detached helper/spool as a "new subsystem beyond the protected baseline (principle X)" — `docs/rfcs/033-lease-state-machine/plan.md:159-170`, `docs/rfcs/041-telemetry-shutdown-wait/preflight.md` (Alternatives rejected).
- Viewer login is cached only on the `GitHubClient` instance (`self._viewer_login`) — `github/client.py:453-461`. `GitHubClient()` is constructed freshly in many entrypoints (`core/gate.py:133`, `core/publisher.py:435`, `core/workflow.py:809`, `commands/high_level.py:929`, `commands/final_gate.py:155`, `core/agent_batch.py:78/88`, `commands/agent.py:766`, `core/agent_protocol_submission.py:67/151/672`). `list_threads` calls `viewer_login()` first (`github/client.py:166-171`). Result: each CLI process (and each new client) pays `gh api user`; N sessions pay N times, nothing persisted.
- No reading of rate-limit state: grep for `x-ratelimit`, `Retry-After`, `retry_after`, `rate_limit` queries in `src/` finds only text-marker classification (`github/diagnostics.py:41`, `:93`, `:120`; `core/command_runner.py:258-259`; `github/client.py:787-788`; `cli.py:642-645`). No `gh api rate_limit`, no `gh api -i`, no GraphQL `rateLimit{}` field.
- `doctor` runs `gh auth status`, `gh api user`, `gh repo view` — `commands/doctor.py:61-67` (extra calls per diagnostic run, not shared).

### Inferences
- Same-PR collision: two processes on one PR share one workspace; local writes are safe-ish via SQLite (`BEGIN IMMEDIATE`, 5 s busy timeout) and item leases, but both will independently poll threads and may both issue reply/resolve mutations. Outbox in_flight locks protect duplicate execution of one command, not duplicate polling.
- Different-PR collision: no local collision; only shared GitHub budget (primary + secondary).

### Gaps
- Whether `list_threads` is invoked once or several times per `review`/`final-gate` cycle (call-count per cycle) was not measured; needs a trace count from existing `gh_address_cr.subprocess` spans.
- Did not verify WAL status beyond grep (no match).

## 2. GitHub side: shared budget and failure signatures

### Takeaway
All sessions on one token share the same primary bucket (5,000 REST req/h; 5,000 GraphQL points/h per user) and the same secondary limits (100 concurrent REST+GraphQL, 900 REST / 2,000 GraphQL points per minute, ~80 content-creating requests/min and 500/h, CPU time). This tool's workload is mutation-heavy (reply + resolve per thread), so content-creation and the 5-point mutation weight are the likeliest first walls, not the hourly primary limit.

### Cited Findings
- 5,000 req/h for PAT / app-on-behalf-of-user, shared across all of the user's tokens and apps; GitHub App installation tokens start at 5,000/h and scale (cap 12,500); Actions `GITHUB_TOKEN` 1,000/h per repo — [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
- Secondary: max 100 concurrent requests shared REST+GraphQL; 900 pts/min REST, 2,000 pts/min GraphQL; GET=1 pt, writes=5 pts; GraphQL mutation request=5; 90 s CPU per 60 s (60 s for GraphQL); ~80 content-generating req/min and 500/h — same page.
- Exceeding returns 403 or 429. Primary: `x-ratelimit-remaining: 0` -> wait until `x-ratelimit-reset`. Secondary: honor `retry-after`; else if remaining 0 wait for reset; else wait at least one minute, then exponential backoff; continuing while limited may get the integration banned — same page.
- Best practice: make requests serially, not concurrently; wait at least one second between POST/PATCH/PUT/DELETE; use conditional requests (ETag; 304 on authenticated requests does not count against primary limit); respect `x-poll-interval` — [Best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).
- GraphQL: 5,000 points/h for users; cost = connection request count / 100, min 1; `rateLimit{limit cost remaining resetAt}` available and headers `x-ratelimit-*` with resource `graphql` — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api).
- `GET /rate_limit` does not count against the REST limit; returns `core`, `graphql`, `search`, etc.; headers are authoritative if they disagree — [Rate limit endpoint](https://docs.github.com/en/rest/rate-limit/rate-limit). Note: secondary limit state is not observable (REST limits page: "no way to check secondary limit status").
- Prior art: Octokit throttling plugin uses Bottleneck, retries per `retry-after`, `fallbackSecondaryRateRetryAfter` default 60 s, and can share throttle state across processes via a Redis-backed Bottleneck with a shared id — [plugin-throttling.js](https://github.com/octokit/plugin-throttling.js).

### Inferences
- Failure signatures with many sessions: `gh` stderr containing "secondary rate limit" / "rate limit exceeded" (HTTP 403, sometimes 429), plus 502/503 and timeouts under load. Current code classification: "rate limit" / "secondary rate" markers -> `GitHubRateLimitError`, not transient, not retried (`github/diagnostics.py:41,120`; `github/client.py:787-788`); `command_runner.py:258` also maps "http 429". A secondary-limit 403 whose text lacks those exact markers would be classed "permission_denied" (`core/command_runner.py` ~261, "forbidden"/"http 403") — a mislabel risk (INFERENCE; not reproduced).
- Existing retry is blind to `Retry-After`: `_run_gh` sleeps `2**attempt` (`github/client.py:520-540`) and `run_cmd` does the same (`core/command_runner.py` retry loop, `_should_retry_gh` at ~:120-127); default runner uses `retries=1` (`github/client.py:542-546`) so effectively no retry on the client path. Transient markers are the substrings "502"/"503"/timeout/"graphql error" (`github/transient_failures.py:12-18`) — substring "502" can false-match unrelated text (INFERENCE).
- Retrying without jitter in N independent processes synchronizes retry storms (thundering herd).
- A GitHub App/installation token gives a separate bucket, but the tool's attribution rules require replies from the "current authenticated GitHub login" (AGENTS.md principle III; `core/gate.py:171`, `core/publisher.py:558`) — switching identity changes evidence semantics. INFERENCE: not a drop-in.

### Gaps
- Not confirmed from cli/cli sources whether `gh` itself retries on secondary limits (search returned no authoritative cli/cli issue). Treat as: gh surfaces the error; verify before relying.
- Exact GraphQL point cost of `list_threads` (first:100 threads, nested comments) not computed.
- Whether 403 secondary-limit messages from `gh` always contain the string "secondary rate" was not verified.

## 3. Coordinator design options (single machine)

### Takeaway
Recommended: a staged, daemon-free path — (A) cheap per-call hygiene and `Retry-After`-aware backoff with jitter, (B) a machine-wide flock-slot concurrency semaphore + minimum write spacing in the gh runner, (C) a small shared TTL cache for viewer login (and optionally rate-limit snapshot), with (D) a circuit breaker keyed on observed rate-limit state. A long-lived daemon is not justified under principle X.

### Options evaluated (fit against AGENTS.md; effort/impact are INFERENCE)
1. A. Header/stderr-aware backoff in the existing runner (parse `retry-after`, `x-ratelimit-reset` via `gh api -i` or stderr; jitter; cap attempts; classify 403-secondary correctly). Effort low; impact medium (fixes storms and mislabels). Fits: deterministic runtime, no new state, extends existing `run_cmd` retry; contract/test update needed since error classification is public machine-readable (reason codes `GH_RATE_LIMITED`, `cli.py:642`).
2. B. Machine-wide concurrency semaphore: N slot files `<state_dir>/gh-slots/slot-K.lock` with `fcntl.flock` (reuse `core/process_lock.py` primitive, already vetted incl. win32 path); wrap each `gh` subprocess; plus a global "last write at" timestamp guarded by a flock'd file to enforce >=1 s between mutations per GitHub guidance. OS releases locks on crash (same property the repo already relies on, `process_lock.py` docstring). Effort low-medium; impact high for secondary limits (bounds concurrency regardless of session count). Caveat: state dir must be shared across sessions (default is; `GH_ADDRESS_CR_STATE_DIR` per-session overrides defeat it — document). Fail-open on lock errors vs fail-fast: AGENTS.md says core flows stay fail-open for telemetry, but fail-fast for unsafe handling; a throttle is neither — recommend bounded wait then proceed with a diagnostic event (needs recorded decision). Architecture preflight: arguably new "runtime state" but ephemeral and non-authoritative; write a short preflight like RFC 041's (state owner none; flocks are liveness not truth).
3. C. SQLite token bucket in a shared `ratelimit.sqlite3` under the state root. More expressive (budget accounting across sessions) but a second store beside "exactly one authoritative store" (principle I); must be explicitly non-authoritative. Higher effort, marginal benefit over B given GitHub gives no secondary-limit visibility. Defer.
4. D. Shared on-disk TTL cache: viewer login (`gh api user`) keyed by host+token-fingerprint-free key (e.g. hash of `gh auth status` active account is itself a call; use gh config hosts file mtime — INFERENCE), TTL ~minutes. Low effort, removes 1 call per process. Thread-snapshot caching keyed by PR+updatedAt/ETag: higher risk — final-gate truth depends on fresh thread state (principle III, IX: artifacts must not become truth). Recommend caching only identity, and ETag-conditional GETs only for read-only REST lists (commits, files) where 304 is free; GraphQL does not support ETag 304 in the same way (INFERENCE; not verified).
5. E. Request coalescing across processes (single-flight via flock on a key + short-lived result file). Useful only when sessions hit identical reads (same PR). Medium effort, limited impact; defer.
6. F. Circuit breaker: on rate-limit classification, write `<state>/gh-backoff-until` (epoch from retry-after/reset) so all sessions pause together; others read it before calling. Low effort, high impact once A exists; breaker file is advisory, not truth.
7. G. Long-lived local daemon (single gh funnel). Best control, but new process lifecycle, IPC, versioning, crash recovery; RFC 041 already rejected a detached helper for the same reasons (principle X). Not recommended unless B+F prove insufficient with measured evidence.
8. H. Reduce call count first (dedupe `viewer_login`, batch resolve via GraphQL aliases, avoid repeated `list_threads`). Impact potentially largest per effort; INFERENCE since call counts per cycle were not measured.

### Recommended staging (impact/effort)
1. Measure (Section 4 attributes) — prerequisite, low effort.
2. H + D(identity only): cut redundant calls.
3. A + F: Retry-After-aware jittered backoff and shared backoff-until file.
4. B: flock slot semaphore + write spacing.
5. Revisit C/E/G only with evidence.

### Gaps
- No empirical measurement of how many concurrent sessions trigger secondary limits with this workload.
- Windows flock semantics (msvcrt) exist in `process_lock.py` but cross-process slot semantics untested.

## 4. Observability (OTel)

### Takeaway
The subprocess span already carries attempts_used, duration, exit code, error.type/category; what is missing is rate-limit state, wait time, and per-session call counts.

### Cited Findings
- Existing: child span `GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME` (SpanKind.CLIENT) with `gh_address_cr.subprocess.attempts_configured/attempts_used/duration_ms`, `process.exit.code`, `process.pid`, `error.type`, error category (`rate_limit` classification at `core/command_runner.py:258-259`), start/end span events — `core/command_runner.py` run_cmd (~:150-215).
- Privacy: argv reduced by `command_label`/`subprocess_operation` to bounded categories; never log paths/PII/tokens — AGENTS.md Telemetry section.
- Semconv CLI spans require executable name, exit code, pid, error.type — [CLI spans](https://opentelemetry.io/docs/specs/semconv/cli/cli-spans/) (cited via AGENTS.md; not re-fetched).

### Inferences (proposed attributes, all low-cardinality and public-safe)
- Per gh span: `gh_address_cr.github.rate_limit.resource` (core|graphql), `.remaining`, `.limit`, `.reset_in_s` (seconds, not epoch if desired), `.retry_after_s`, `gh_address_cr.github.failure_class` (primary|secondary|network|transient|auth), `gh_address_cr.github.throttle_wait_ms`, `gh_address_cr.github.slot_wait_ms`, `gh_address_cr.github.operation_kind` (read|mutation).
- Span events: `gh_address_cr.github.backoff` (reason, wait_s, attempt), `gh_address_cr.github.circuit_open/closed`.
- Per-invocation root attributes: `gh_address_cr.github.calls_total`, `.calls_mutation`, `.retries_total`, `.rate_limited_total`; plus concurrent-session count approximated by number of held slot locks at acquire time (`gh_address_cr.github.slots_in_use`).
- Remaining-count source: parse `x-ratelimit-*` from `gh api -i` output or one free `gh api rate_limit` per invocation (does not count against REST limit per docs above). Per GitHub, treat values as approximate across regions.
- Respect principle VIII: keep span promotion rules (no new child spans for slot waits; use attributes/events) and fail-open if telemetry read fails.

### Gaps
- Dataset/dashboard queries for Honeycomb not built; no existing baseline numbers collected.
