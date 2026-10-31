# Python and Homebrew distribution

## Distribution contract

The Python package retains wheel/sdist publication and CPython 3.12–3.14 support.
Homebrew uses `python@3.14`, `Language::Python::Virtualenv` and
`virtualenv_install_with_resources`. It does not depend on uv.

| macOS | Architecture | Runner | Expected bottle tag |
| --- | --- | --- | --- |
| 15 | Apple Silicon | `macos-15` | `arm64_sequoia` |
| 15 | Intel | `macos-15-intel` | `sequoia` |
| 26 | Apple Silicon | `macos-26` | `arm64_tahoe` |
| 26 | Intel | `macos-26-intel` | `tahoe` |

All four targets consume the same formula prepared on `macos-15`. Homebrew
selects relocation and platform compatibility. No job forces bottle selection
or claims an architecture-independent bottle. A missing compatible bottle can
cause a normal user installation to build from source. Runner availability is
an external requirement; unavailable targets block publication.

`pyproject.toml` continues to express compatibility ranges. The formula's
checksummed resources are the runtime dependency snapshot for that Homebrew
release. They are not a new cross-platform Python lockfile. Source installations
use normal build isolation and can download build dependencies. Neither source
builds nor bottles promise byte-for-byte reproducibility.

Stable formulas infer their version from the sdist filename to satisfy Homebrew
audit. Identity-based preview URLs retain an explicit version before the checksum.
Snapshot validation checks the inferred or explicit version against the requested
package version; stable downgrade protection handles both forms.

## Publication and ownership

`.github/workflows/release.yml` builds and publishes Python distributions before invoking
`.github/workflows/homebrew.yml`. The latter prepares/preserves a source formula, builds four
bottles, merges official bottle JSON, uploads immutable assets, verifies ordinary
installation in four fresh jobs, then updates only the stable tap formula.
`dry-run` and `testpypi` render scaffolds but never invoke production Homebrew
publication. No-version runs skip publication.

The renderer produces a **scaffold**, not a publishable dependency manifest.
Only the shared preparation path calls `brew update-python-resources`. Missing
resources, invalid hashes, malformed output, constraint conflicts and
`RESOURCE-ERROR` fail publication. No ignore-errors switch is allowed. The
main-package cooldown bypass does not bypass dependency cooldowns or errors.

Release assets on `v<version>` include:

- `gh-address-cr-<version>.homebrew-source.rb` and `.json`: immutable input.
- Standard platform bottle files and per-target build records.
- Per-target `.bottle-r<rebuild>.zip` recovery bundles, containing the exact
  record and bottle bytes, uploaded atomically before individual assets.
- `gh-address-cr-<version>.r<rebuild>.gh-address-cr.rb` and `.publication.json`:
  final formula and its identity.

An upload is read back and hashed. Existing identical assets are reused;
different bytes fail without overwriting. A single recovery bundle makes partial
individual uploads resumable without rebuilding different bytes under the same
name. Final tap publication performs read-only asset verification. It fetches
the latest tap head and retries a non-force push on concurrent updates; other
formula changes survive. Repeated successful publication makes no extra commit.
Stable version/rebuild downgrades are rejected.

Release snapshots and evidence do not own application session state or alter
`final-gate`. See [architecture preflight](rfcs/049-homebrew-distribution/preflight.md).

## Recovery

When PyPI succeeds but Homebrew fails, keep the existing stable formula. Inspect
the failed job and its artifacts, fix the infrastructure/helper failure, and
dispatch the Homebrew workflow for the same version:

```bash
gh workflow run homebrew.yml --ref main -f version=3.21.3 -f rebuild=0
```

This is an example for a future published version, not an instruction to
overwrite 3.21.2. The workflow verifies tag metadata and the published PyPI
sdist URL/hash against the preserved snapshot. It never re-resolves a saved
snapshot. A tag/source mismatch, corrupt asset or changed bytes under the same
name stops recovery.

If bottle bytes must change, use an explicitly larger rebuild:

```bash
gh workflow run homebrew.yml --ref main -f version=3.21.3 -f rebuild=1
```

A rebuild retains the original source/resource snapshot and creates new bottle
filenames. It does not republish the Python package. Changed dependency resources
require a subsequent normal package release. Do not delete assets to bypass
identity checks.

## Development previews and credentials

CI builds PR packages without publication credentials. Source asset names contain
the PR number, full head SHA, run ID and run attempt. A trusted `workflow_run`
consumer checks workflow/repository/run provenance and the current open PR head.
It uploads source bytes without executing them. A separate read-only macOS job
prepares resources and verifies source installation. Only the final trusted job
receives a tap-only GitHub App token and updates `gh-address-cr-dev`.

External build processes do not inherit publication-token environment variables.
Preview and stable formulae conflict because both install `gh-address-cr`.
Previews remain source builds; fixed resources remove open-ended runtime
dependency selection but do not remove compilation or build-isolation costs.

Preview asset retention is a deferred operational requirement: immutable names
accumulate on the shared release and can eventually reach GitHub's asset limit.
Automatic deletion needs an explicit retention/recovery policy, coordination with
in-flight builds and protection for sources referenced by retained formulas.
This workflow does not delete historical preview sources. Until that policy is
implemented, capacity exhaustion can block new previews without affecting stable
publication.

```bash
brew unlink gh-address-cr
brew install rbbtsn0w/tap/gh-address-cr-dev
gh-address-cr --version
gh-address-cr agent manifest
```

To return to an already installed stable formula:

```bash
brew unlink gh-address-cr-dev
brew link gh-address-cr
```

## Acceptance and diagnostics

Build jobs run source installation, formula tests and linkage checks.
Independent jobs install/upgrade through the final public bottle URLs and
require `poured_from_bottle` in the installation receipt. They check version,
help, manifest, package origin, exact resource closure and metadata constraints,
package data, SQLite, TLS, local OTLP export and the isolated agent journey.
The journey is explicitly run in process using the installed interpreter;
repository sources are not inserted into its import search path.
Python is then reinstalled and the installed interpreter, entrypoint, dependency
closure and linkage are verified again.

Evidence includes Homebrew/Python/build configuration, installed dependency
versions, previous application version, whether Python actually changed,
startup smoke duration and six installation samples per target. A runner on
which Python did not change does not prove a Python-version upgrade.

Empty/warm application download-cache trials each run three times. System
dependency installation is timed separately. Downloads are timed before ordinary
installation. Installation time includes unpacking; Homebrew does not expose
a separate stable unpack measurement. These are six observations, not P95.
Receipt checks and rejection of source-build/index activity enforce the bottle
installation boundary. No total-upgrade latency promise is made.

Release helpers use one INTERNAL root span and CLIENT spans for actual
subprocesses. Phase markers are events; duration and exit information contain
no argv, output, credentials or raw paths. Synthetic verification uses the
development endpoint or a local receiver. Exporter diagnostics are visible but
cannot change the build outcome; missing local acceptance spans do fail the
explicit installed-exporter check.

Before the first production release, run the repository's full local gates and
review all four real workflow results. Also perform a normal installation on the
owner's current system and record actual compatibility selection if it falls
outside the matrix. Do not use forced bottle installation as evidence. Local
fixture tests and workflow lint establish orchestration contracts; they do not
establish real bottles, performance, interpreter-upgrade or machine acceptance.
