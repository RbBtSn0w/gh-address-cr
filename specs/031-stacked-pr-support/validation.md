# Validation: Stacked Pull Request Support

## Local verification (2026-08-01)

- Editable install: passed with pyenv Python 3.14.4.
- Ruff: `ruff check src tests scripts/build_plugin_payload.py` passed.
- Unit suite: `python3 -m unittest discover -s tests` passed, 1007 tests after
  the iterative Mode A review closures and responsibility-boundary hardening
  were added.
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

## Second review-regression closure

The follow-up review identified four additional recovery and compatibility
regressions. Nine focused RED/GREEN tests plus the full 981-test suite now
prove:

- ordinary unstacked, unbound submissions preserve the local path and do not
  construct a GitHub client or perform a submit-time stack read;
- an unbound request issued during unavailable context is rejected when submit
  discovers current stack membership, its unusable lease is released, its item
  becomes claimable, and a fresh request can be issued immediately;
- a legacy request that records present stack context without a revision
  binding remains unverifiable and is rejected even after the PR is unstacked;
- generated logic-validation signals carry `item_kind`, while terminal local
  and GitHub items both recover stale, unbound, or missing validation through
  item-scoped `agent evidence add` against the current member revision;
- aggregate stack recovery preserves item-scoped evidence commands and routes
  still-blocking local items through normal `review`, not `--auto-simple`; and
- `FINAL_GATE_MISSING_REPLY_EVIDENCE` maps to `evidence add --reply-url`
  instead of a no-op publish attempt.

The editable install initially encountered HTTP 403 from the configured PyPI
mirror while resolving `setuptools>=77`. After installing that build dependency
from the official PyPI index, `pip install --no-build-isolation -e .` passed;
ruff, CLI help, agent manifest, plugin payload build/check, and
`git diff --check` also passed.

The retained sandbox was exercised once more after this closure. The first
attempt reached the layer gate but hit a transient GitHub `/user` TLS handshake
timeout. A direct API probe reproduced the timeout, a bounded connectivity
probe then passed, and the single retry completed without fixture mutation:
all three `address` calls were already `PASSED`, PRs `#2`, `#3`, and `#4`
passed their layer gates, and stack `#5` passed with exact coverage `[2, 3, 4]`,
119 runtime events, and 100% aggregate runtime coverage:

```text
[gh-address-cr stack: PASSED | scope: stack segment through PR #4 | members: 3 | telemetry: runtime-only (119 events, 100.0%)]
```

A final direct `final-gate ... 4 --stack --machine --no-auto-clean` invocation
then passed with every aggregate count at zero, 125 runtime events at 100%, and
stack-audit artifact SHA-256
`227df6692f9f184cc345c2f36f1d881786e1749abb273cced6f93ccb04d553ad`.

## Responsibility-boundary audit

A full CLI/runtime/skill audit after the lower-layer feedback scenario added
executable coverage for the remaining ownership and handoff boundaries:

- layer `final-gate` replaces stale cached topology with explicit unavailable
  context and reports `stack_merge_readiness=unknown` when discovery fails;
- manual validation evidence discovers a current stacked member even when a
  legacy session has no cached context, then binds the owning revision;
- a known stacked member cannot publish unbound evidence while context refresh
  is unavailable;
- later unavailable observations retain a non-authoritative safety hint so
  known stack membership cannot silently degrade into ordinary-PR handling;
- submit refreshes even an initially unbound request and rejects it if current
  stack membership is then discovered;
- stacked `ActionRequest` validation requires every stack-management operation
  to remain forbidden, while emitted single and batch requests expose the
  owning PR head branch;
- member-blocked stack gates return the nested layer's executable recovery
  action instead of merely repeating the failing gate;
- stale or unbound layer gates return a targeted revision-validation command;
- explicit stack discovery failures retain `completion_scope=stack_segment`,
  report `waiting_on=stack_context`, and expose deterministic retry commands;
- pagination rejects stack or selected-member identity changes between pages;
  and
- the packaged skill now defines the lower-layer owning-branch handoff, separate
  authorization for checkout/rebase/push, and post-propagation request refresh.

The retained sandbox was verified and exercised again after this audit. PRs
`#2`, `#3`, and `#4` passed their layer gates with 94, 91, and 98 runtime events;
stack `#5` passed with exact coverage `[2, 3, 4]`, 104 runtime events, and 100%
runtime coverage:

```text
[gh-address-cr stack: PASSED | scope: stack segment through PR #4 | members: 3 | telemetry: runtime-only (104 events, 100.0%)]
```

## Iterative Mode A closure

The final post-fix review loop completed with no remaining finding after
focused RED/GREEN coverage closed the following additional gaps:

- malformed or duplicate topology cannot silently change the selected member
  or covered segment;
- single and batch stale requests release all unusable leases, while ordinary
  unbound submissions retain the offline-compatible path;
- terminal local findings and GitHub threads share item-scoped validation
  recovery without routing local items through a thread-only producer;
- aggregate member failures preserve the nested `layer_waiting_on` state and
  human failure output retains counts, telemetry, recovery, artifact paths, and
  hashes while stale topology still suppresses completion guidance;
- stack telemetry and audit metadata remain bounded and include the requested
  check policy; and
- the reusable sandbox exercises `--require-required-checks` and rejects a
  passing payload unless the selected member and exact covered range match the
  fixture manifest.

Local completion evidence for this closure is 307 stacked-PR focused tests and
the full 1007-test suite, plus ruff, CLI help/manifest, plugin payload, and diff
hygiene checks. The retained live sandbox results above predate the final
required-check harness enforcement; no new remote mutation or live acceptance
claim was made during this final local Mode A pass.

## Acceptance boundary

Fixture-backed acceptance covers discovery, pagination, invalid topology,
revision invalidation before side effects, bottom-up aggregation, member-state
blockers, and closing-topology freshness. Live acceptance now proves real stack
discovery, real review-thread mutation, layer gates, aggregate blocking, and
aggregate completion. A destructive cascade/rebase was intentionally not added
to the reusable harness; stale revision behavior remains covered by executable
contract fixtures without force-updating remote branches.
