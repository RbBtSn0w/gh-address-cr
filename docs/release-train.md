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
notes on update. API errors stop proposal creation.

Sync checks out main and probes develop before use. It creates a reviewed
`main -> develop` sync PR when necessary; it neither writes trunk refs nor
recreates a missing branch. Missing develop requires a provenance-based recovery
plan. A successful release workflow also triggers a fresh proposal check, after its
version writer has settled; explicit dispatch covers suppressed/lost push events. Proposal success
means only that a proposal exists, not that integration is synchronized.

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
