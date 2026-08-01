# Validation: Stacked Pull Request Support

## Local verification (2026-08-01)

- Editable install: passed with pyenv Python 3.14.4.
- Ruff: `ruff check src tests scripts/build_plugin_payload.py` passed.
- Unit suite: `python3 -m unittest discover -s tests` passed, 963 tests after
  review-regression coverage was added.
- CLI smoke: root help passed; `final-gate --help` exposes `--stack`.
- Agent manifest: passed with `status=MANIFEST_READY`.
- Plugin payload: build and `--check` passed.

## Live GitHub capability and sandbox fixture

- GitHub CLI: 2.95.0 (2026-06-17).
- Authorized private demo repository:
  `RbBtSn0w/f2g-demo-portal-b-20260528`.
- The official `gh stack` extension download was attempted, but the downloaded
  release asset was truncated and failed its published digest. The E2E harness
  therefore used GitHub's documented stacked-PR REST endpoint directly; it did
  not install or trust the damaged binary.
- GraphQL introspection confirmed `PullRequest.stack` and
  `PullRequest.stackEntry`.
- `PullRequestStack` exposes `baseRefName`, `entries`, `id`, `number`, and
  `size`.
- `PullRequestStackEntry` exposes `id`, `position`, `pullRequest`, and `stack`.
- `scripts/e2e_stacked_pr_sandbox.py provision` created three isolated branches,
  PRs, review threads, and GitHub stack `#5`. The manifest is
  `/var/tmp/gh-address-cr-stack-e2e-20260801-01.json`.
- Bottom PR `#2`, middle PR `#3`, and top PR `#4` were observed at positions
  `1`, `2`, and `3` by both REST and GraphQL. All three reported stack size `3`
  and topology fingerprint
  `sha256:5c1e524d83b1ad2fa90251258cb08267255f0f4c2041e6a8a40f41368de04a6d`.

## Live regression sequence

1. `address --lean` discovered one real unresolved GitHub review thread on each
   member and returned `WAITING_FOR_SIMPLE_ADDRESS` (exit `5`) with the expected
   selected position.
2. The initial top `final-gate --stack --machine` returned
   `STACK_MEMBER_BLOCKED` (exit `5`), covered PRs `[2, 3, 4]`, selected bottom
   PR `#2` as the first blocker, and aggregated three unresolved/blocking
   threads.
3. Each fixture thread was declined through `agent resolve` and then published
   through `agent publish`. GitHub showed the runtime-owned reply and resolved
   thread on all three PRs.
4. Each layer `final-gate --machine --no-auto-clean` passed with
   `completion_scope=pull_request`, zero unresolved/blocking threads, and 100%
   runtime telemetry coverage.
5. The aggregate top gate passed with exit `0`, covered PRs `[2, 3, 4]`, and
   emitted:

   ```text
   [gh-address-cr stack: PASSED | scope: stack segment through PR #4 | members: 3 | telemetry: runtime-only (37 events, 100.0%)]
   ```

6. The new `exercise` action was then run against the already-resolved fixture.
   It idempotently skipped duplicate resolution, re-passed all three layer
   gates, and re-passed the aggregate gate with 53 events and 100% coverage.

The PRs remain open and unmerged for inspection and repeatable E2E runs. The
manifest-scoped `cleanup` action can unstack them, close only PRs `#2`-`#4`, and
delete only the three fixture branches.

## Review-regression closure

The post-implementation review identified seven contract regressions. Focused
RED/GREEN tests now prove:

- preview-only stack lookup failures remain fail-open for layer workflows;
- single and batch action requests refresh GitHub context before binding;
- publish refreshes even legacy/unbound responses and blocks unbound evidence
  on a current stack member before GitHub side effects;
- only session-loading failures become `STACK_MEMBER_SESSION_INVALID`, while
  missing snapshot input keeps exit `2` and runtime failures keep evaluation
  error semantics;
- a valid aggregate run performs exactly one opening and one closing stack
  observation, with the opening context projected coherently to each member;
- `check_requirement` is present in direct output, persisted result, and audit
  metadata; and
- successful stack gates honor default `auto-clean`, while `--no-auto-clean`
  preserves the workspace.

After these fixes, the retained live sandbox was exercised again without new
PR or thread mutation. PRs `#2`, `#3`, and `#4` each passed with
`completion_scope=pull_request`; stack `#5` passed with
`completion_scope=stack_segment`, covered `[2, 3, 4]`, and reported 68 runtime
events at 100% coverage.

A final direct `final-gate ... 4 --stack --machine --no-auto-clean` invocation
also passed with all aggregate counts at zero, 74 runtime events at 100%, and
artifact SHA-256
`df84d44330dd6cd249370a355132f8125315c77a04ee3c5d1592bd8fb4ca352a`.

## Acceptance boundary

Fixture-backed acceptance covers discovery, pagination, invalid topology,
revision invalidation before side effects, bottom-up aggregation, member-state
blockers, and closing-topology freshness. Live acceptance now proves real stack
discovery, real review-thread mutation, layer gates, aggregate blocking, and
aggregate completion. A destructive cascade/rebase was intentionally not added
to the reusable harness; stale revision behavior remains covered by executable
contract fixtures without force-updating remote branches.
