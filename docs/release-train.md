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
