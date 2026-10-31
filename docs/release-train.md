# Release Train Status and Safe Operation

## Inspection checkpoint (2026-10-30)

This Python repository uses semantic-release as a Node-based release helper,
not as an npm package publisher. Stable promotion targets `main`; integration
and ordinary fixes target `develop`. The existing `release.config.cjs` analyzes
Conventional Commits and also releases `refactor` as patch changes. Keep that
contract; do not scaffold an npm package, npm registry publication, or a second
release configuration.

| Surface | Observed state |
| --- | --- |
| Default branch | `main` |
| Latest integration | `3cdbb0f9b07b43b30801ed6fabb23cbbf36da09a` (PRs #373, #374, #375) |
| Integration CI | Passed on that exact head |
| Stable GitHub Release / PyPI / Homebrew | `3.21.1`; PyPI wheel and sdist exist; tap points at the same version |
| Unpromoted history | develop ahead 15, behind 1 relative to main |
| Effective rules | Active deletion restriction and PR/thread rules on both trunks; required-check list is empty; administrator/App bypasses exist |
| Legacy branch protection API | 404 on each trunk; effective rulesets were inspected separately |
| Repository cleanup | `delete_branch_on_merge=false`; observed setting retained, not changed as a retention workaround |
| Scheduled proposal registration | Registered on main; Friday 15:00 Beijing time (UTC+8), 07:00 UTC |
| Latest completed scheduled run | 2026-10-30: success, before the three integration PRs landed |
| Latest stable publication workflow | 2026-10-19: success |

A merged feature PR or successful proposal job does not establish publication.
The three integration PRs are not included in stable 3.21.1. No stable promotion,
publishing dispatch, registry write, ruleset change or cleanup-setting change
was performed by this audit.

## Narrow safety repairs

The scheduled workflow now proposes only: it never auto-merges and never treats
missing checks as permission to merge. Successful exact-ref probes distinguish
missing trunks from command failures. Ahead count, equal-tree and Conventional
Commit guards avoid empty trains; proposal lookup avoids duplicates. The fallback
scan matches the current Python release rules; the actual semantic-release
analyzer remains the publication authority. Merged PR closing references are
carried from the commit range into the proposal body, preserving maintainer
notes before and after a bounded generated section on update. Ambiguous markers
stop without overwriting the body. Closing keywords accept an optional colon;
breaking-note detection follows configured whitespace/list-prefix formatting.
API errors stop proposal creation.

Sync checks out main and probes develop before use. After a successful main
release, or explicit dispatch, it creates a reviewed snapshot PR to develop.
It does not run on the initial main push, before the version writer has settled.

Each source main SHA selects `sync/main-to-develop/<full-main-sha>`. A single
empty validation commit has exactly main's tree, main as its sole parent, and a
fixed message without skip instructions. This prevents release-version
`[skip ci]` messages from suppressing the PR's Python CI, as observed in #379
and manually recovered through #380. Repeated runs verify and reuse the existing
snapshot/PR. Commit/ref creation requires an App or SYNC_TOKEN; GITHUB_TOKEN-only
creation stops because it can suppress downstream CI even with a clean message.
The App/token needs Contents and Pull requests write permissions, used only for
the snapshot and proposal; no new repository permissions are configured here.

Refs are created with the create-only API, never pushed or force-updated.
Existing snapshots with a different tree, parent or message are rejected; moving
main and API failures stop without a new proposal. A failed run may leave an
unreferenced commit or a valid snapshot; rerunning verifies live state and reuses
it. After an operator-approved merge, ordinary branch cleanup may remove the
snapshot head. The workflow neither writes trunk refs nor recreates develop.
Missing develop still requires a separately approved provenance-based recovery.
Proposal existence is not proof that CI passed or integration was synchronized.

These repairs reduce automation authority. They do not install the latest
release-train controller or qualify a lifecycle as Remote Verified. Workflow
changes must reach main before scheduled/default-branch automation uses them.
Until then the old default-branch workflows remain active.

## Promotion and publication gates

1. Review and land the safety repair on develop; preserve current trunk history.
2. Before promoting to main, approve the lifecycle policy. Except for the scoped
   manual retained-trunk release below, require trusted controller deployment.
   Use the supplied `repo-release-train` controller on one persistent
   POSIX host with an approved durable store outside PR-controlled content.
   Hosted ephemeral checkouts/caches are not that store. Do not invent freeze
   acknowledgements or install an unattended auto-merge substitute.
3. Explicitly choose retained/recreatable/snapshot topology and cleanup policy.
   The observed deletion restriction is useful evidence but bypass scope must be
   accounted for. Enabling cleanup or changing protections needs owner approval;
   do not toggle cleanup as a lifecycle workaround.
4. Coordinate integration/main writers and PR edits, record exact head/base and
   checkpoints, and inventory affected PRs. Use the approved manual procedure
   below for PR #383; otherwise prepare/promote/merge/reconcile with the supplied
   controller. Explicit human approval is required; drift invalidates prior
   approval. Require real green checks, even when proposal creation used
   GITHUB_TOKEN and did not trigger CI.
5. Merge the approved promotion with a merge commit so the existing analyzer can
   see feature/fix history. Main triggers `release.yml`: semantic version/changelog,
   package build and validation, plugin artifact, PyPI OIDC publication, then
   Homebrew resource snapshot, four bottle builds, immutable upload, independent
   installation verification and gated stable tap update. GitHub Release creation
   alone is not evidence that downstream jobs completed.
6. Verify the exact version/tag, PyPI wheel/sdist, plugin artifact and Homebrew
   formula against the successful release run. Review and validate sync-back,
   lifecycle retention/recovery and affected PR bases before resuming integration.

The local repair may be described as inspected and locally verified only.
Controller deployment, production lifecycle rehearsal, promotion and publication
remain separate gates; never claim them from fixture tests or dispatch alone.

## One-time manual release with retained trunks: PR #383

Policy approved for documentation on 2026-10-31. This exception applies only to
the next normal stable release proposed by PR #383 (`develop -> main`) and its
reviewed sync-back. Approval to document this procedure is not approval to merge,
pause writers, dispatch workflows, publish, or delete anything. The exception
ends when that release and sync-back are verified, or the operator aborts it;
future trains require their own policy decision. A changed release head/base
requires fresh checks and explicit approval, even while the proposal stays #383.

### Eligibility and unchanged controls

- Both `main` and `develop` must exist. Keep `main` as default/stable and use
  protected-retained `develop`; retain `delete_branch_on_merge=true` for ordinary
  PR heads. Do not disable cleanup, weaken rules, force-push or use a bypass.
- Re-read the effective deletion rules before promotion and before sync merge.
  At this checkpoint, active `trunk-retention` ruleset `26205878` covers exactly
  `refs/heads/main` and `refs/heads/develop`, has no bypass actors and reports
  `current_user_can_bypass=never`. Stop if equivalent protection is no longer
  effective. The older inspection table above is historical, not live policy.
- Keep the existing PR/thread rules. The current server-side required-check list
  is empty, so require successful named checks manually: `Validate base branch`,
  `lint-and-test (3.12)`, `(3.13)`, `(3.14)`, `otel-minimum-versions`, and every
  other non-skipped check applicable to the current candidate. Missing checks
  are not green. An intentionally skipped develop-head preview is not a failure.
- The controller deployment/rehearsal gate is replaced only for this bounded,
  human-driven, retained-trunk path. It is not satisfied or marked Remote
  Verified. Automated promotion, recreatable/snapshot topology and missing-ref
  recovery remain outside this exception and retain the controller requirement.

### Release record and writer pause

Keep the operator record in PR #383 with links to live GitHub facts and CI/release
artifacts. The record documents human decisions; it does not replace GitHub
refs, installed artifact evidence or runtime-owned review completion truth.

1. Name the release operator, recovery owner, integration/main writers and bots,
   and all open PRs targeting either trunk. Record full live head/base SHAs, the
   intended merge method, relevant check run URLs, current retention/cleanup
   evidence and the expected release side effects. The preparation checkpoint
   is not an approved release checkpoint.
2. Obtain explicit acknowledgments from the affected humans and automation
   owners that integration/main writes and affected PR admission/head/base edits
   are paused. Record an absolute start/expiry in UTC and Beijing time (UTC+8),
   plus who may resume them. Do not infer a pause from an empty PR queue, Actions
   concurrency, a green check or this policy approval. The pause is cooperative,
   not a server-side lock; inability to coordinate any writer blocks promotion.
3. Account explicitly for the main release/version writer. Other main and
   integration writers stay paused. After the authorized merge, the designated
   release workflow may write its accepted version/changelog descendant on main;
   wait for that writer and all downstream publishing jobs to settle before
   approving sync-back. An unexpected write, expired pause or uncertain outcome
   puts the process on HOLD; refresh the record and approval rather than claiming
   a previous pause still applies.

### Exact approval and authorized promotion

1. After the governance PR lands on develop, re-read both refs and PR #383's
   current candidate. Run its fresh CI and
   `gh-address-cr final-gate <owner/repo> 383 --require-checks`; require zero
   unresolved threads, pending reviews and blocking items. Current checks must
   correspond to the candidate being approved, not a prior integration run.
2. Obtain a separate owner approval naming PR #383, both full SHAs, the pause
   window, `merge` method and production consequences: main push triggers
   semantic-release, GitHub Release, PyPI and Homebrew publication. Approval of
   this document or a generic draft proposal is insufficient.
3. Immediately before the authorized merge, recheck refs, protection, writer
   acknowledgments, checks and reviews. Use a merge commit with an expected-head
   guard; never squash/rebase this promotion. The expected-head API does not
   atomically guard main's base: the acknowledged main-writer pause remains
   necessary. Drift or inability to establish the pause stops the operation.

### Publication settlement and reviewed sync-back

1. Record the merge SHA and verify that both trunks still exist. Wait for the
   complete release run, including the main version writer, PyPI, all four
   Homebrew builds/install verifications and the gated tap update. Follow the
   first-bottle acceptance checklist in PR #383 and `docs/homebrew-distribution.md`.
   A tag or a successful package build alone does not complete publication.
2. Once the main writer settles, capture the accepted published main SHA. Review
   the sync snapshot PR created by `Branches` (`.github/workflows/branches.yml`, `propose-sync`):
   its snapshot must have the published main tree, main as its sole parent and
   the validation message without CI-skip instructions. A stale or conflicting
   snapshot is a HOLD, not permission to reset develop or force-push.
3. Keep integration and affected PR edits paused. Require the sync PR's fresh CI,
   review completion, exact snapshot/develop SHAs and separate operator approval
   before merging it. Do not squash or rebase the sync: retain main as an
   ancestor via a normal merge commit, then verify the accepted published main
   SHA is an ancestor of develop and that both refs still exist.
4. Re-inventory affected PRs, verify their intended bases/heads and fresh checks
   against the synchronized integration state, and record any changes. Only
   then may the named operator close the release record and explicitly resume
   integration/queue writers. A later main hotfix is a new sync decision.

### Failure boundary

Missing either trunk, protection drift, an unknown write outcome or unpromoted
concurrent work stops this procedure. Preserve observed SHAs and run evidence;
do not reconstruct refs, delete journals/checkpoints, overwrite artifacts or
invent controller state. If PyPI succeeds while Homebrew fails, keep the prior
stable tap and follow the documented same-version recovery only after separate
approval. Credential/protection changes, additional dispatches and retries that
can publish are not authorized by this document. No unattended recovery or
automatic merge is introduced.

### Squash-promotion recovery preparation: PR #383

PR #383 was squash-merged as `d9bf402ced72b5e4fda53e23eb903a84ef54d9ee`.
Release run `41157884982` stopped at the squash-promotion guard: the analyzer
saw only the promotion's `chore(release)` subject and selected no release.
PyPI and Homebrew publishing were skipped. The subsequent Scheduled Release PR
run `41183001479` found equal trunk trees and correctly proposed nothing.

Prepare recovery without rewriting either trunk:

1. Branch from the retained develop candidate
   `2020026fdf2f3b7715c7fa0262d5a9ff6bb6bbf9` and merge the observed main
   `d9bf402ced72b5e4fda53e23eb903a84ef54d9ee` with a normal merge commit.
   Confirm the merge alone changes no files and both original tips are ancestors.
2. Open the recovery PR against develop, following the existing target-branch
   rule. Review its exact head/base and require a normal merge commit when
   separately authorized; never squash/rebase away the recorded main ancestry.
3. After that approved merge, open a fresh develop -> main promotion. Analyze
   every commit reachable from the candidate but not from `v3.21.2` using the
   configured official commit analyzer. The preserved Homebrew `fix(release)`
   commit must yield `patch` (expected next stable version `3.21.3` while the
   latest stable tag remains `v3.21.2`). Do not run semantic-release lifecycle
   hooks merely to validate the analyzer.
4. Refresh all checks, reviews, refs and first-bottle acceptance evidence for
   the replacement promotion. The prior #383 preparation/approval record does
   not authorize the new PR or new SHAs. Obtain a new bounded manual-policy
   decision, genuine writer-pause acknowledgments and exact production approval
   before merging the replacement promotion with a normal merge commit.

This recovery preparation authorizes no main merge, workflow dispatch, package
publication, protection change or history rewrite. Preserve the failed-run
evidence; do not retry production while main still exposes only the squash
promotion to the analyzer.

Local preparation evidence (2026-10-31): recovery merge `2f3d5db` has both
observed trunk tips as ancestors and the same tree as each tip. With the
repository parser options and release rules, official
`@semantic-release/commit-analyzer` 13.0.1 on Node 25.8.2 selected no release for
`v3.21.2..d9bf402` (one commit), and `patch` for `v3.21.2..2f3d5db` (seven
commits). No lifecycle hooks ran. All 16 release-train workflow tests passed.
These are preparation checks, not production or four-platform bottle evidence.

## Local verification

`python3 -m unittest tests.test_release_train_workflows` executes the actual
workflow shell steps with isolated git/GitHub fixtures. It covers no-op content,
release rules, duplicate proposals, closure continuity, maintainer notes,
missing-ref/transport/API failures, and reviewed sync without trunk writes.
These are deterministic workflow tests, not agent/model evaluations or remote
lifecycle rehearsals. Run the normal repository lint/type/unit/package gates
before publishing the repair.

## Local repair verification result

On the isolated `codex/release-train-audit` branch from integration head
`3cdbb0f9b07b43b30801ed6fabb23cbbf36da09a`:

- Development setup completed in its own virtual environment.
- Actionlint, including ShellCheck: all three changed workflows pass.
- Eight workflow tests pass, including subcases for transport/comparison/API
  failures, equal content, Conventional Commit rules and proposal deduplication.
- Full discovery: 1688 tests, OK (1 skipped), 189.086 seconds.
- Ruff and mypy ratchet pass (94 source files, zero type errors).
- CLI help, agent manifest, plugin payload build/check and diff checks pass.
- Verification did not dispatch production workflows or run model evaluations.
  Publication of this repair is a separate, owner-authorized step.

Suggested commit: `fix(ci): require reviewed release promotion and sync`.
The primary workspace's pre-existing edits were not changed.

## PR review correction

Three confirmed review concerns have focused regression coverage: breaking notes
accepted by the existing analyzer (indentation, list prefixes and case), optional
colons in closing references, and preservation of human notes on both sides of
an explicitly bounded generated block. Malformed or ambiguous block markers
stop the update without writing the PR body. Twelve workflow tests pass after
seven initially failing regression subcases reproduced these gaps. These fixes
change neither publication authority nor the retained/recovery policy.
