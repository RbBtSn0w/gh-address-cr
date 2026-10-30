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
2. Before promoting to main, approve the lifecycle policy and trusted controller
   deployment. Use the supplied `repo-release-train` controller on one persistent
   POSIX host with an approved durable store outside PR-controlled content.
   Hosted ephemeral checkouts/caches are not that store. Do not invent freeze
   acknowledgements or install an unattended auto-merge substitute.
3. Explicitly choose retained/recreatable/snapshot topology and cleanup policy.
   The observed deletion restriction is useful evidence but bypass scope must be
   accounted for. Enabling cleanup or changing protections needs owner approval;
   do not toggle cleanup as a lifecycle workaround.
4. Coordinate integration/main writers and PR edits, record exact head/base and
   checkpoints, and inventory affected PRs. Prepare/promote/merge/reconcile with
   the supplied controller and explicit human approval; drift invalidates prior
   approval. Require real green checks, even when proposal creation used
   GITHUB_TOKEN and did not trigger CI.
5. Merge the approved promotion with a merge commit so the existing analyzer can
   see feature/fix history. Main triggers `release.yml`: semantic version/changelog,
   package build and validation, plugin artifact, PyPI OIDC publication, then
   Homebrew rendering/audit/install/test and tap update. GitHub Release creation
   alone is not evidence that downstream jobs completed.
6. Verify the exact version/tag, PyPI wheel/sdist, plugin artifact and Homebrew
   formula against the successful release run. Review and validate sync-back,
   lifecycle retention/recovery and affected PR bases before resuming integration.

The local repair may be described as inspected and locally verified only.
Controller deployment, production lifecycle rehearsal, promotion and publication
remain separate gates; never claim them from fixture tests or dispatch alone.

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
