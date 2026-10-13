# gh Call Performance and Multi-Session Research

Research snapshot from 2026-10-12, taken at `cd17a66` (release 3.20.1, after
PR #352). It investigates why `gh` commands fail intermittently and whether
multiple concurrent PR sessions sharing one GitHub token are supported.

This is a static research reference, like `docs/rfcs/`: it does not select
active work and does not decide delivery status. Code citations
(`file:line`) are pinned to the snapshot and may have drifted; PR #363
(retry of transient `gh` reads and cross-session coordination of `gh` calls)
landed after it. Verify any claim against current code and tests before acting
on it. `AGENTS.md` and executable contracts govern.

| File | Contents |
| --- | --- |
| `report.md` | Synthesis (Chinese): retry/backoff diagnosis, call-volume analysis, phased recommendations (stages 0-4), unverified claims. |
| `notes/codebase_gh_audit.md` | Audit of every `gh` call path, its cost, caching, and failure handling. |
| `notes/github_api_efficiency.md` | GitHub REST/GraphQL limits, batching, ETag and secondary-limit findings (from WebFetch summaries, not page-by-page review). |
| `notes/multi_session_architecture.md` | Session state scoping and what is shared across sessions on one machine and token. |

Known caveat carried from the report: no real failure telemetry was available,
so attribution of the failures is inferred from code and documentation, not
measured.
