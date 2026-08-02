# Research: Stacked Pull Request Support

**Date**: 2026-08-01  
**Feature**: [spec.md](./spec.md)

## Decision 1: Support review resolution, not stack management

**Decision**: Discover stack context, resolve feedback one PR at a time, and
prove layer or stack-segment readiness. Stack creation, navigation,
restructuring, rebase, push, queue, and merge remain outside this feature.

**Rationale**: GitHub's official tooling owns local branch management. Updating
a lower layer cascades through upper layers with `gh stack rebase` and
`gh stack push`, potentially rewriting several remote branches. Those effects
are wider than gh-address-cr's reply/resolve outbox and must not be hidden.

**Alternatives considered**:

- Wrap every `gh stack` command: rejected as a second stack manager.
- Automatically rebase/push after a fix: rejected as an unauthorized side-effect expansion.
- Ignore stack structure: rejected because layer completion is not merge readiness.

**Source**: [Reviewing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-stacked-pull-requests)

## Decision 2: Read stack facts through a separate GraphQL adapter call

**Decision**: Add a dedicated paginated stack-context read to `GitHubClient`.
Do not merge preview fields into the existing review-thread query.

**Rationale**: GitHub GraphQL exposes read-only `PullRequest.stack` and
`PullRequest.stackEntry`; `PullRequestStack.entries` is paginated. A separate
call isolates public-preview schema failures so older hosts keep the existing
PR flow with explicit `stack_context=unavailable`.

Live schema introspection on 2026-08-01 confirmed:

- `PullRequest.stack: PullRequestStack`
- `PullRequest.stackEntry: PullRequestStackEntry`
- `PullRequestStack`: `id`, `number`, `baseRefName`, `size`, paginated `entries`
- `PullRequestStackEntry`: `id`, `position`, `pullRequest`, `stack`

**Alternatives considered**:

- REST only: viable, but the runtime already uses GraphQL for PR review facts
  and GraphQL exposes the selected member position.
- Require `gh stack`: rejected because review resolution does not need it and
  it is not installed on the current machine.
- Infer membership from base/head chains: rejected because GitHub membership is explicit.

**Source**: [About stacked pull requests](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs)

## Decision 3: Keep PR sessions authoritative and derive stack state

**Decision**: Preserve `session.json` per PR. Store only a labelled
last-observed context in member metadata. Recompute aggregate state from GitHub
facts and member sessions.

**Rationale**: Work items, leases, replies, and validations belong to one PR. A
mutable stack session would duplicate ownership and drift after reorder or merge.

**Alternatives considered**:

- Add `stack-session.json`: rejected as a second state engine.
- Copy all member items into the selected session: rejected as dual ownership.
- Trust the last stack-gate report: rejected as artifact-backed truth.

## Decision 4: Bind stacked-member evidence to head revision and topology

**Decision**: A valid stacked-member request carries `stack_context.v1`;
accepted validation records carry `revision_binding.v1` with member head OID
and topology fingerprint. Submit, publish, and gate refresh before use.

**Rationale**: A lower-layer update rebases branches above it. PR and thread IDs
can remain stable while commit OIDs, base refs, and tested code change. Current
success-like validation does not encode that revision.

**Alternatives considered**:

- Bind only to the fix commit: rejected because it may not be the current head.
- Bind only to thread identity: rejected because threads survive code revision.
- Preserve all pre-feature evidence: rejected as a hidden compatibility shim;
  stacked members require one fresh revision-bound proof.

## Decision 5: Keep default final-gate layer-scoped; add explicit --stack

**Decision**: Existing `final-gate` remains one-PR proof and emits
`completion_scope=pull_request`. `final-gate --stack` evaluates the contiguous
active segment from the lowest unmerged member through the selected PR and emits
`completion_scope=stack_segment`.

**Rationale**: Existing callers depend on PR scope. Automatic aggregation would
silently increase latency and make one PR fail because another was never
initialized. GitHub cannot merge a selected layer while leaving unmerged lower
layers behind, so aggregate readiness must still be explicit.

**Alternatives considered**:

- Aggregate by default: rejected as a breaking truth/performance change.
- Let a layer pass imply stack readiness: rejected as false completion.
- Add a top-level `stack` command family: deferred; `--stack` is the smaller boundary.

**Source**: [Merging stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests)

## Decision 6: Recompute member gates bottom-up

**Decision**: For each included unmerged member, load its existing session,
read current remote threads, current-login pending reviews, and requested
checks, then invoke the existing layer final-gate kernel. Identify the first
blocked member bottom-up while retaining all observed outcomes.

**Rationale**: This matches GitHub merge order and reuses the protected
fact → projection → policy gate. Missing sessions block rather than being
silently created because every layer must enter the review-resolution workflow.

**Alternatives considered**:

- Read prior completion summaries: rejected as artifact-backed truth.
- Evaluate only GitHub checks: rejected because review evidence disappears.
- Evaluate members in parallel: deferred until live latency proves a need;
  bottom-up order makes recovery deterministic.

## Decision 7: Reobserve topology before emitting aggregate proof

**Decision**: Capture one canonical fingerprint, evaluate members, then read the
anchor context again. Any change returns `STACK_CONTEXT_STALE` without a
completion line.

**Rationale**: GitHub may retarget/rebase after partial merge, and concurrent
pushes can change revisions during evaluation. A closing observation prevents
facts from different stack revisions being combined.

**Alternatives considered**:

- Lock branches: rejected; the CLI has no safe ownership boundary.
- Use observation age: rejected because mutations can occur in any time window.
- Retry until stable: rejected for v1 loop safety; one explicit refresh is deterministic.

## Decision 8: Add bounded span events, not new workflow spans

**Decision**: Add discovery and aggregate-decision events to the existing root
invocation span. Attributes are bounded availability, member-count bucket,
position class, requested scope, outcome, and reason code.

**Rationale**: These operations have observable value but do not yet justify
independent span ownership. Branch names, stack IDs, member lists, titles,
bodies, paths, and topology fingerprints are excluded.

**Alternatives considered**:

- A span per member: rejected as unproven high-cardinality expansion.
- No telemetry: rejected by repository policy.
- Export the fingerprint: rejected as unnecessary repository correlation.

## Upstream Capability and Verification Baseline

- GitHub documents stacked PRs as **public preview** and subject to change.
- All branches must be in one repository; cross-fork stacks are unsupported.
- Rules and CI derive from the bottom PR's trunk; merge order is bottom-up.
- Website, mobile, CLI, webhooks, REST, and GraphQL expose stack support.
- The asynchronous merge endpoint is required for API stack merge, but this
  project does not add merge behavior.
- Local `gh` is `2.95.0`; it advertises `gh stack`, but the extension is absent.
- `RbBtSn0w/gh-address-cr` had no open PRs during the probe. Live schema
  capability is proven; real stack behavior remains a separate acceptance step.

**Sources**:

- [About stacked pull requests](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs)
- [Creating stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-stacked-pull-requests)
- [Reviewing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-stacked-pull-requests)
- [Merging stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests)
- [REST pull request endpoints](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2026-03-10)
