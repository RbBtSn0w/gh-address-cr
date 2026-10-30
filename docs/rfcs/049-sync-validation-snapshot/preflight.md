# Architecture Preflight: CI-safe release sync snapshots

## Trigger and smallest boundary

PR #379 used the published main version commit as its head. Its `[skip ci]`
message suppressed Python CI; #380 proved that an identical-tree empty-commit
snapshot can run real CI. Automating that repair adds bounded GitHub commit/ref
writes, so this preflight precedes implementation. No review-runtime, session,
lease, final-gate or telemetry contract changes.

## Authority, inputs and policy

GitHub commits, refs and PRs own state. Successful main release completion and
explicit dispatch are wakeups; remove the early main-push wakeup so version
writers settle first. Read live main/develop and stop on missing refs or errors.
When develop includes main, return without side effects or requiring credentials.
Otherwise require an App/PAT capable of triggering CI; GITHUB_TOKEN is not a
silent fallback for creating a supposedly CI-ready proposal.

The derived snapshot name is `sync/main-to-develop/<full-main-sha>`. Its commit
must have exactly main's tree, one parent equal to main, and the fixed non-skip
validation message. Reuse only a verified snapshot and matching open PR. Never
retarget or overwrite an existing ref. Recheck live main before proposing.

## Side effects, recovery and truth boundaries

Only create an empty commit, create its reserved snapshot ref, and open a PR to
develop. Use create-only ref POST; no trunk writes, deletes, force updates,
auto-merge or missing-develop recovery. A failed/uncertain write stops; the next
run reads GitHub state and safely reuses an already-created valid snapshot.
Concurrency serializes this workflow but is not a trunk-writer lock.

A snapshot/PR existing does not prove CI ran or passed. Logs and request JSON
are derived operational evidence, never persistence authority. Existing review
runtime telemetry remains unchanged; no new telemetry ingestion plane is added.

## Executable acceptance

Execute the workflow shell against isolated git/GitHub fixtures. Prove a skip-CI
source yields a same-tree/single-parent, non-skip snapshot; repeat runs reuse it;
invalid snapshots, ref/API errors, moving main and default-token-only writes stop
without PR creation or overwrite; zero-change and missing-develop guards remain.
Verify Actionlint/ShellCheck and repository lint/type/test/package gates. These
are deterministic tests, not new model evaluations or a production rehearsal.
