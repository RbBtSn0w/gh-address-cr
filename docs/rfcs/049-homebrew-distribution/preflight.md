# Homebrew distribution boundary

Status: Accepted for implementation
Date: 2026-10-30

## Decision and complexity budget

Publish a standard Python virtualenv formula with a complete, checksummed
runtime-resource snapshot. Resolve that snapshot once with Homebrew's
`update-python-resources`; never restore the retired hand-written resolver.
Stable releases require bottles for macOS 15 and 26 on arm64 and x86_64.
Development previews retain source installation with the same preparation and
validation path.

The simpler online `uv pip install .` formula leaves dependency selection,
build preparation and network latency on every user's machine. Bottles move
that repeated work to publication without introducing a bundled interpreter,
another package repository or a runtime state engine. Source installation still
uses normal build isolation and may download build dependencies.

## Authority, inputs and projections

The release workflow owns publication ordering. Its inputs are the published
PyPI sdist metadata, release tag, immutable source bytes, a prepared formula
snapshot, standard `brew bottle --json` metadata and actual installation
results. A release snapshot is a versioned build input, not PR-session truth.
It is stored as a checksummed immutable Release asset before bottle builds.
The final bottle formula and human-readable timing/verification summaries are
derived outputs. Neither reports nor OTel can make a failed build pass.

All four builds consume the same source formula. Homebrew determines bottle
tags and relocation; the workflow never forces a bottle or declares an `all`
bottle. A target's installed dependency closure must satisfy package metadata.
Python package compatibility ranges remain in `pyproject.toml`.

## Policy and side effects

1. Verify stable version/tag and PyPI source identity.
2. Restore a valid existing snapshot, or prepare and preserve one.
3. Build all four bottles without tap-write credentials.
4. Merge standard bottle metadata and upload immutable bottle assets.
5. In fresh jobs, install the final formula normally and verify bottle use.
6. Only after all four targets pass, update the stable tap formula.

Missing assets may be uploaded; matching assets are reused; different bytes
under an existing name fail. A changed build uses an explicit rebuild number.
Each target first uploads one immutable recovery bundle containing its record
and exact bottle bytes. Interrupted individual uploads restore that bundle,
avoiding nondeterministic rebuilding under an already published asset name.
The final tap gate verifies remote assets without uploading or repairing them.
PyPI publication is not rolled back when Homebrew fails. A Homebrew-only
dispatch resumes the same version and snapshot without semantic-release.
The tap stays on its previous version until every required target succeeds.
Tap updates replay only the selected formula onto the latest remote head and
never reset or overwrite unrelated formula changes.

Preview artifacts use PR, full head SHA and run identity in their names.
Privileged publication runs trusted default-branch code; PR code and formula
execution run only in read-only, credential-free build jobs. The privileged
publisher validates the current PR head and provenance before updating the
rolling development formula.

## Telemetry and recovery

Release helpers reuse the runtime tracing and sanitization modules. Each
invocation has one INTERNAL root; subprocesses have CLIENT spans with actual
process identity, exit status and failure type. Checkpoints are events. Only
bounded operation names, channel, architecture and outcomes enter telemetry;
paths, argv values, raw output and credentials do not. Export failures remain
visible and fail open. Verification exports use a local receiver or the
development environment, never production.

Standard bottle JSON, immutable formula snapshots, asset hashes and installed
dependency inventories provide replay/diagnostic inputs. They do not change
`runtime.sqlite3`, session persistence, agent protocols or `final-gate`.
Exact reporting duration excludes writing the report itself.

## Executable acceptance

Contract tests cover source selection, standard formulas, complete resources,
malformed resolver output, immutable asset collisions, snapshot recovery,
four-target gating, idempotent publication, concurrent tap writers, preview
provenance and telemetry safety/failure boundaries. Real macOS jobs cover
source builds, ordinary bottle installs, dependency checks, installed package
data, SQLite, local OTLP export, the isolated agent journey, prior-version
upgrades and interpreter/linkage checks. Timing reports separate system
dependencies from package download/assembly/startup and label cache state.
Python reinstallation is explicitly exercised; an actual patch-version upgrade
is reported only when the runner provided different before/after versions.
Local fixture tests do not establish remote bottle or performance acceptance.
