# Main release train

`main` is the only integration branch. Squash task PRs directly to main with a
Conventional Commit title and any breaking-change footer in the body. Friday
07:00 UTC and manual dispatch use the same read-only verification and dependent
publishers. Only publication requires `RELEASE_ENABLED=true`; leave it unset
until release permissions and trusted-publisher configuration are accepted. No develop beta, promotion, sync-back or PR preview is produced.

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

PyPI retains OIDC. Normal publication requires fresh main; original-run recovery
requires the original existing tag. Both first verify the complete handoff,
then reads the version JSON and compares each expected filename and SHA-256.
Only HTTP 404 means absent. Matching existing files are retained; conflicting
bytes, malformed metadata and failed reads stop publication. Only missing files
are staged for upload, then a fresh read-back records each file's result. An
already complete matching version is a proven no-op. Attempt-specific receipts
preserve partial outcomes without overwriting earlier evidence.

Homebrew remains an explicit four-platform reusable workflow,
with helpers checked out at immutable `github.workflow_sha`, the trusted workflow
snapshot. The verified product source SHA remains an explicit input and must
match the stable tag and be an ancestor of that snapshot. The package version
comes from verified PyPI metadata, not source metadata commits. Helper runtime uses current trusted source through `PYTHONPATH=src` and installs
only third-party binary dependencies. Original wheels are payload bytes and are
never installed or imported under publication authority. Installed-product bottle
verification runs separately without publication credentials. Marketplace publication
retains verified immutable assets, receipt validation, read-back and version-only
partial recovery. Source metadata may retain the previous release version; plugin
verification derives only the expected release version when regenerating metadata.
Skill bytes, inventory and source commit remain exact. Generator comparison runs
only during read-only preparation. Publisher and recovery validate sealed bytes,
receipt checksums, source skill/asset bytes and tag identity without executing a
tagged builder or regenerating payloads.

## Original-run recovery after main advances

Dispatch **Release** on main with `operation=recover`, `source_run_id` and
`artifact_id` from the original normal release. The same `release.yml` preserves
PyPI's workflow identity. Trusted current-main recovery tools validate the actual
same-repository, same-workflow completed main schedule/manual run and its immutable
artifact, sealed plan/inventory and existing tag's peeled candidate SHA.
The original run may have failed; a recovery run is never the next recovery source.
No tag is created or replaced, no version is selected, and no product is rebuilt.
A missing original tag or expired/missing artifact stops recovery.

Matching GitHub assets and PyPI filename hashes are retained; only missing assets
and files are uploaded and read back. Draft GitHub releases are found through authenticated paginated release lists
and finish only after all sealed assets match. Missing-release creation and
draft completion explicitly use `--latest=false`, preserving a newer GitHub
latest selection; existing notes are never rewritten. A missing release uses
only sealed original generated notes. Conflicts or unverifiable reads stop. PyPI recovery relies on
the original tag and sealed archives, not live-main equality. Four-platform
Homebrew recovery restores original atomic bottle bundles and fails closed when
one is missing; recovery does not build replacement bottles. Marketplace uses the
existing sealed bundle and source tag.

If the original run proves Homebrew never started, complete its first delivery
through the existing independent **Homebrew** workflow with `operation=release`,
the original version/source SHA and `rebuild=0`. First verify the original artifact,
tag, PyPI sdist hash and absence of a newer tap or competing publication; missing
assets alone do not prove first delivery. This creates the first resource snapshot
and bottles without rebuilding the original wheel/sdist. Preserve the earlier
partial/failed runs and record this separate operation as first delivery. Once
Homebrew artifacts exist, recovery must reuse their sealed snapshot/bundles; it
must never fall back to a new build because evidence is missing.

`release-result.json` and the Actions summary separate verification from publication
and record GitHub, PyPI, Homebrew and marketplace independently. Disabled publication
still runs credential-free analysis and needed exact-candidate verification. A
proven no-change plan skips package builds and product verification. Reports are
observations, not permission to publish, and local tests prove no remote delivery.

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
PR metadata keeps strict Conventional Commit lint. Historical engine-selected
ranges validate release semantics only: parseable ordinary commits and breaking
footers; genuine multi-parent merge metadata is recorded without style rejection.
A malformed ordinary commit, including one hidden behind a skip marker, still
fails closed. Existing product baseline remains mandatory.

External readiness is separate: verify PyPI OIDC, Marketplace snapshot identity and
the existing release App's tap installation/access using actual channel receipts.
The configured App metadata names ID `2758804` and `RELEASE_BOT_PRIVATE_KEY`;
credential names alone never prove delivery or authorization. Retain dated staging
observations as history rather than treating them as the current service state.

## Historical squash compatibility (2026-11-07)

Historical standard GitHub PR squash envelopes are ordinary commits: their full
Conventional Commit body must validate. Thin `release-commit-analyzer.mjs` and
`release-notes-generator.mjs` adapters use the same message projection and forward
all existing options to the official plugins. True multi-parent merges retain
original messages and complete breaking notes. Empty/malformed/nested bodies and
invalid skip-marker messages still fail. No SHA exemption, baseline fabrication
or Git history rewrite is used.

Recovery requires the sealed original release notes to be a string and exactly
match any existing Release before asset writes. After asset reconciliation, recheck
the identity and notes before publishing a draft, then verify them on final
readback. Missing or conflicting notes stop recovery; an existing body is never
replaced. Only an entirely absent Release is created using the original notes.
