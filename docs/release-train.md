# Release train

The active policy is the [Main release train](release/main-train.md). `main` is
the only integration trunk; task PRs use Conventional Commit squash metadata.
Friday 07:00 UTC and manual main dispatch use the same verification and dependent
publication path. Analysis/verification run without activation; publication
requires `RELEASE_ENABLED=true`. Original-run recovery uses the same workflow.

The previous develop promotion, sync-back, guarded branch-controller and preview
workflows are retired by this migration. Historical reports and approvals do not
authorize their reactivation. Do not delete remote branches, rewrite history or
change external timers, protection or credentials as part of this source change.

## Actions receipts and shared runtime (2026-11-08)

The `Release` workflow distinguishes scheduled, manual and recovery runs. Its final
read-only `Release outcome` restores analysis, the verified payload and every
channel receipt by immutable producer artifact ID. Successful earlier producers
remain usable during failed-only reruns. A full rerun stops before new analysis or
product builds: an earlier attempt may already have created the original tag.
Recover its original sealed identity, or dispatch a new release for current main.

Stable tag, GitHub Release, PyPI, Homebrew and Marketplace are independent intended
targets, anchored in `.github/release-train.json`. Workflow environment mappings
cannot remove a target. Job success never substitutes for its remote receipt:

- GitHub readback peels the original tag to the exact source SHA, matches sealed
  notes and the stable release ID, then downloads and checks the original wheel
  and sdist digests.
- PyPI requires both original filenames and verified per-file digests. A wheel-only
  receipt, missing file or conflicting bytes cannot complete publication.
- Homebrew reads the remote tap commit and formula bytes after four-target
  verification and bottle readback, and records the exact formula digest.
- Marketplace re-reads the published remote snapshot against the original bundle.
  Preserving a newer marketplace version remains unconfirmed for the older train.

Unavailable, failed or conflicting receipts remain unknown. The original verified
artifact ID is available on the first failure. Recovery instructions require a
verified original tag and unexpired artifact provenance/digest; a result job may
report its own finishing run's producer metadata, while actual recovery still
requires the source run to be complete. Original notes and bytes are preserved;
publishers do not rebuild wheel/sdist or move tags.

The configured consistency plugin checks the complete analyzed notes in the
official `prepare` phase, after generation and before tag creation or service
prepare hooks. Missing notes or UTC-date drift stop publication before side
effects; semantic-release remains the version engine.

Recovery availability also requires the shared publication preflight: existing
notes, release identity and all original asset bytes must be readable and match.
A tag alone is insufficient. Matching drafts and missing assets remain repairable;
conflicts or unreadable evidence suppress the command. Recovery validates every
existing asset before uploading any missing file.

`.github/release-train/` is generated common runtime with a source revision and
per-file hashes. Do not hand-edit it. `.github/release-train.json`, the fixed-command
`scripts/release/train-adapter.mjs`, product handoffs/channel adapters and native
workflows remain consumer-owned. Upgrade from the authorized source skill's
`scripts/release-train/sync.mjs sync --consumer <checkout> --revision <revision>`;
`node .github/release-train/sync.mjs check --consumer .` verifies consumer integrity
without upstream access. Local tests use synthetic receipts and never publish a
package, tap commit, Marketplace snapshot or GitHub Release.

## Versioned custom implementation

The existing release adapter exposes protocol 1 and its engine-selected identity to shared coordination. Analysis retains the real semantic-release tag; the original immutable pipeline envelope is captured in the existing plan. Present invalid envelopes fail before Node-owned publication/handoff/recovery boundaries. Reporting uses original goals and returns its parsed result to the shared exit policy, so successful report generation does not hide incomplete channel evidence. See [the release-only architecture preflight](rfcs/release-pipeline-integration-20261110.md) for authority, artifact and recovery boundaries. The Python review/session runtime, final-gate semantics, telemetry and existing PyPI file-level restore contract are unchanged.

## Pipeline capability configuration

`.github/release-train.json` owns configuration schema v2 / pipeline protocol v1,
required goals, existing execution bindings and cadence. The current explicit
schedule preserves Friday 15:00 Asia/Singapore (07:00 UTC). A new explicit empty
cadence uses Friday 15:00 Asia/Shanghai; changing cadence is a normal configuration
change, not a release approval. Runtime dispatch inputs do not change the schedule.

With isolated `yaml@2.9.1` provisioned in `RELEASE_TOOLS`, run the read-only checks:

```bash
node .github/release-train/pipeline-contract.mjs check
node .github/release-train/cadence.mjs check
```

An explicit maintenance `cadence.mjs update` changes only the native schedule
projection; review that diff. Original plans retain exact identity, notes and goals.
Reports/recovery use those original goals after configuration or main advances; old
plans remain compatible and never acquire invented receipts. Public capability
coordination stays separate from product/platform implementations and existing CI
job permissions. Activation, credentials and existing delivery destinations are
unchanged by configuration migration.

## Ordinary CI release contracts

PR/main CI checks generated integrity, actual pipeline job bindings and configured
cadence in the existing Python 3.14 matrix entry. CI and release candidate verification share `npm run test:release`, which automatically includes new release test files.
These checks do not depend on publication enablement or version changes. Product
test matrices remain independent; the contract environment selects npm 12 explicitly.
No publishing credentials, OIDC grant or private upstream checkout is needed.
A green check is evidence only when its log shows the applicable commands and
release tests ran; source/CI success does not prove channel delivery.
