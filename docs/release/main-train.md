# Main release train

`main` is the only integration branch. Squash task PRs directly to main with a
Conventional Commit title and any breaking-change footer in the body. Friday
07:00 UTC and manual dispatch use the same read-only verification and dependent
publishers. `RELEASE_ENABLED` must explicitly equal `true`; keep it unset until
strict history lint, release permissions and trusted-publisher configuration are
accepted. No develop beta, promotion, sync-back or PR preview is produced.

## Architecture preflight

semantic-release owns baseline discovery, version selection, tags and release
notes. Git history/tags and the exact event candidate are the inputs. A thin
local-mirror API dry-run records a completed engine analysis; failure or early
return is not a no-op. The plan records the candidate, engine-selected baseline,
version and configuration digest. It is a consistency projection, not an
independent version controller. No version/changelog commits are made.

Read-only verification injects the planned version into package metadata, builds
wheel/sdist and plugin payload once, tests the installed wheel, and records every
archive checksum. The dependent publisher restores this run's immutable artifact
ID directly into the checked directory (`merge-multiple: true`), validates
candidate/config/checksums and reanalyzes with the same engine.
The stateless hook rejects baseline/version/candidate/config drift before tags.
No build or package installation hooks execute under publisher authority.

PyPI retains OIDC. Every failed-job retry first verifies the complete handoff,
then reads the version JSON and compares each expected filename and SHA-256.
Only HTTP 404 means absent. Matching existing files are retained; conflicting
bytes, malformed metadata and failed reads stop publication. Only missing files
are staged for upload, then a fresh read-back records each file's result. An
already complete matching version is a proven no-op. Attempt-specific receipts
preserve partial outcomes without overwriting earlier evidence.

Homebrew remains an explicit four-platform reusable workflow,
with the verified source SHA passed to every checkout. Marketplace publication
retains verified immutable assets, receipt validation, read-back and version-only
partial recovery. Source metadata may retain the previous release version; plugin
verification derives only the expected release version when regenerating metadata.
Skill bytes, inventory and source commit remain exact. Generator comparison runs
only during read-only preparation. Publisher and recovery validate sealed bytes,
receipt checksums, source skill/asset bytes and tag identity without executing a
tagged builder or regenerating payloads.

## Recovery and activation

A successful GitHub release is not proof of PyPI, bottle or marketplace delivery.
Inspect each target separately after failure. Recover only the missing side effect
from its existing immutable evidence; never replace published bytes or rewrite a
tag. The marketplace recovery workflow uses existing release assets and the same
publication lock. Homebrew recovery requires version and exact source SHA.

Before merge, retire external legacy branch-controller timers separately. The PR
must not produce the old `gh-address-cr-dist` artifact: the old default-branch
`workflow_run` preview downloader therefore fails closed on this PR's CI run.
Local checks do not prove schedules, production credentials or remote delivery.
The current develop candidate history contains messages rejected by strict
commitlint, with no SHA exemptions. A final squash PR to main does not import
that ancestry: verify the actual merged main range, preserving business and
breaking semantics in its squash metadata. A local net-tree squash fixture can
prove the planned analysis, but never establishes the future merge message.
