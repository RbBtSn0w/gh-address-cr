# Spec 046: Post-push `headRef` lag is a transient stack observation

Architecture Preflight for issue #365. Current code, tests, and `AGENTS.md` govern
execution. This preflight supersedes one line of Spec 040 §6 V3 ("reject the
observation as invalid when its `oid` differs from `headRefOid`") for the lag case
only.

## Problem

The first `agent resolve` (or `agent next`) right after `git push` returns
`REQUEST_REJECTED`, and an identical retry succeeds.

Evidence:

- Honeycomb, production dataset `gh-address-cr`, root span `gh-address-cr.cli`,
  version 3.20.1, 2026-10-15T08:28:40Z: `reason_code = STACK_CONTEXT_INVALID`,
  0.9 s, exactly one `github.graphql` call. The PR (#368) is not stacked.
- A unit reproduction on the pre-fix code: one stack read of an unstacked PR whose
  `headRef.target.oid` differs from `headRefOid` projects
  `invalid / missing_head_tree_oid`, and `refresh_stack_context_for_request`
  raises `REQUEST_REJECTED / STACK_CONTEXT_INVALID` (exit 5).

Mechanism: right after a push, GitHub briefly serves a new `headRefOid` while
`headRef.target` still points at the previous commit. `_head_tree_oid` correctly
refuses a tree read from a different commit and returns `None`.
`PullRequestMemberFact.from_dict` then raises `missing_head_tree_oid` for every
non-merged member, including the `absent` (unstacked) path. So the bug is not
limited to stacked PRs.

## Preflight

| Item | Decision |
| --- | --- |
| Authoritative state owner | Unchanged. `runtime.sqlite3` owns review state. The stack context is a non-authoritative GitHub observation (`metadata.pull_request_context`, `authoritative: false`). |
| External facts / inputs | The `get_stack_context` GraphQL read: per PR `state`, `headRefOid`, `headRef.target.oid`, `headRef.target.tree.oid`. Consumers: request issue (`refresh_stack_context_for_request`), `agent submit` binding verify (`verify_request_revision_binding`), publish preflight (`publisher._verify_publish_revision_bindings`), `workflow` stack checks, and the `final-gate` stack gate. All read through `GitHubClient.get_stack_context`, so all get the fix. |
| Projection | Unchanged shape (`stack_context.v1`, availabilities `absent / present / unavailable / invalid`; no fifth value). New on exhaustion: an unstacked read (`stack: null`) projects `unavailable` with `diagnostic = {reason_code: STACK_CONTEXT_UNAVAILABLE, invariant: head_ref_oid_lag}` (stored in the neutral `diagnostic_cause` field via `unavailable_stack_context(cause=...)`); a stacked read stays `invalid` with `diagnostic = {reason_code: STACK_CONTEXT_INVALID, invariant: head_ref_oid_lag}`. |
| Policy | One deterministic rule in the reader. A read is **lagging** when it projects `invalid / missing_head_tree_oid` and **every** non-`MERGED` PR in it whose head tree is missing is an `OPEN` PR whose `headRef.target.oid` is present and differs from `headRefOid` (one lagging member must not mask a genuinely missing tree on another). A lagging read is repeated from page 1, at most `HEAD_REF_LAG_READS = 3` reads in total, sleeping `backoff_seconds(attempt)` (about 0.5-1 s, then 1-2 s) between reads. A converged read is returned as is. If every read lags, an unstacked read is `unavailable` and a stacked read stays `invalid`. Downstream policy for both is unchanged: `unavailable` is fail-open for a PR never observed as stacked and `REQUEST_REJECTED / STACK_CONTEXT_UNAVAILABLE` for a known stacked PR; `invalid` always fails closed. |
| Real invariant failures stay invalid | A missing `headRef` on an open PR, a non-commit target, or a missing tree on a matching OID still project `invalid / missing_head_tree_oid` after one read, with no re-read. A `MERGED` or `CLOSED` PR whose head branch moved afterwards is a permanent mismatch, not lag, so it never triggers a re-read (a merged member's tree is optional and never gates evidence; a closed one stays `invalid`). |
| Agent-facing output | Additive: every `STACK_CONTEXT_INVALID` / `STACK_CONTEXT_UNAVAILABLE` rejection built from a `StackContext` (request issue, response submit, publish preflight, validation evidence) carries `stack_diagnostic = {reason_code, invariant?}` from one helper, `stack_diagnostic_payload`. `invariant` is omitted when no bounded cause is known (capability loss, `gh` failure). `head_ref_oid_lag` tells the agent to wait and rerun; any other invariant is a real defect. Documented in `skill/references/agent-protocol.md` and `status-action-map.md`. |
| Side-effect plan | No GitHub writes. At most two extra GraphQL reads per lagging observation. These compose with the transport-level retry in `_read_json` (which retries failed calls); the lag rule retries successful-but-incoherent reads. Both go through the Spec 045 throttle. |
| Artifact truth boundary | The cached observation stays non-authoritative. An `unavailable` cache entry keeps `stack_membership_observed` from the previous entry, so a known stacked PR is not forgotten. No artifact becomes truth. |
| Telemetry | One span event `gh_address_cr.github.stack.head_ref_lag` on the current span, only when lag was seen: `...head_ref_lag.reads` (int, 2..3) and `...head_ref_lag.outcome` (`converged`: a re-read returned a coherent context; `invalid`: a re-read returned a different, real invariant failure; `exhausted`). No OIDs, refs, or repository names. |
| Recovery / replay | Nothing to replay. The observation is re-read on every request, submit, publish, and gate. A rejected request creates no lease. |
| Contract tests | `tests/test_stack_github_client.py`. `HeadRefLagTests`: unstacked and stacked convergence; unstacked exhaustion to `unavailable`; stacked exhaustion stays `invalid / head_ref_oid_lag`; real invariants stay `invalid` without a re-read; lag on one member does not mask a missing tree on another; merged and closed PRs are not lag; telemetry `converged` / `invalid` / `exhausted`. `HeadRefLagRequestBindingTests`: request issues after convergence; first-observed stacked PR and known stacked PR both fail closed on exhaustion; an unbound response is rejected at submit under persistent stacked lag; publish and validation-evidence rejections carry `stack_diagnostic`; `stack_diagnostic` omits `invariant` without a cause; `agent next` through `cli.main` emits `stack_diagnostic` in stdout JSON. |

## Why exhaustion splits by stack shape

A lag is "cannot observe a coherent head right now". For an **unstacked** read
that is `unavailable`: the head tree is never part of a revision binding
(`revision_binding_for_context` requires `present`), so failing open loses
nothing, and a PR known to have been stacked still rejects with
`STACK_CONTEXT_UNAVAILABLE`.

For a **stacked** read, `unavailable` would be unsafe. A PR first observed as
stacked is not yet marked `stack_membership_observed` (only a `present` read sets
it), so request issue, `agent submit` binding verification, and validation
evidence would all accept work without a revision binding. A stacked read
therefore stays `invalid`, which every consumer rejects, and only its invariant
changes from `missing_head_tree_oid` to `head_ref_oid_lag` so the agent knows
to wait and rerun rather than inspect the stack.

## Efficiency

The re-read also runs for unstacked reads, so an unstacked PR still projects
`absent` (with its real head tree) instead of `unavailable` once the lag clears.
In practice the lag clears after one re-read (about 0.5-1 s). The worst case is
3 reads plus about 1.5-3 s of sleep per stack observation; a command that
observes the stack twice (request issue and submit) can pay that twice.

## Deferred

- `pagination_stack_changed`: `_selected_pr_page_identity` includes `headRefOid`, so
  a push between stack pages also projects `invalid`. It needs a multi-page stack
  and a push mid-read, and no production evidence shows it. It belongs to the same
  transient-observation rule if it ever appears.
- Persisting a request-time rejection `reason_code` in workspace/audit artifacts
  (the other #365 ask). The request path loads the session and raises before any
  save, so persisting needs a new write on the rejection path. That is a separate
  change. The JSON summary of `agent resolve` already carries `reason_code`
  through `output_workflow_error` (now with `stack_diagnostic`), and the root span
  records it since 3.20.1.
  Follow-up: RFC 047 models and implements this observation through the
  existing canonical evidence store, with separate commit/projection outcomes;
  this paragraph records the original deferral, not current absence of support.

## Alternatives rejected

- **Accept `headRefOid` without a tree.** Breaks the Spec 040 binding key
  (`head_tree_oid`) for stacked evidence.
- **Read the tree via `headRefOid` in a second query.** Two queries are not one
  snapshot and add a read on every call, not only lagging ones.
- **Retry at the request layer.** Every consumer reads through the client; one
  rule there covers request, submit, publish, and gate.
