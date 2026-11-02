# Community Marketplace distribution

The first stable Marketplace publication is **pending**. Workflow and local
compatibility checks do not prove that a production branch or release asset
exists. The OpenAI curated Plugin Directory is not a self-service publish target
for this repository.

## Sources and installation

`skill/` owns the adapter content. The repository-root
`.agents/plugins/marketplace.json` is a developer catalog whose local source is
`dist/plugin/gh-address-cr`. Build that payload before registering the catalog:

```bash
python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr
codex plugin marketplace add .agents/plugins/marketplace.json
codex plugin add gh-address-cr@gh-address-cr-community
```

After the first stable publication is verified, remote consumers use the
`marketplace` branch, which includes the catalog and complete plugin payload:

```bash
codex plugin marketplace add RbBtSn0w/gh-address-cr --ref marketplace
codex plugin add gh-address-cr@gh-address-cr-community
```

Do not register the source branch `main` as a remote Marketplace: its ignored
build output is absent from Git. Choose either local or remote registration for
the catalog name `gh-address-cr-community`. Command syntax above was checked
against local Codex help; CI pins the official `@openai/codex@0.166.0` package
for an isolated, two-version Git installation test. This is CLI compatibility
evidence, not acceptance of a live production listing or the macOS desktop UI.

To fetch a newer catalog snapshot:

```bash
codex plugin marketplace upgrade gh-address-cr-community
```

Verify the active installation after refreshing:

```bash
codex plugin list --marketplace gh-address-cr-community --json
```

In the pinned Codex 0.166.0 CI test, explicit Marketplace upgrade advanced the
active installed version from 1.0.0 to 1.0.1. Repeating `codex plugin add gh-address-cr@gh-address-cr-community` also succeeded and preserved the new
version. Check the `installed` record and its enabled/version fields; available
catalog entries or a newer cached directory alone do not prove replacement.
This observation does not establish background updates, existing-session hot
reload, or the behavior of other client versions. Start a new session after
updating. There is no `codex plugin update` command in the tested CLI.

The plugin contains only the skill adapter; it neither bundles nor upgrades the
Python runtime. Install it with `pipx install gh-address-cr`, or update an
existing installation with `pipx upgrade gh-address-cr`.

## Release boundary

A stable source tag `vX.Y.Z` is the immutable source identity. The build fails
unless HEAD equals that tag's commit. The release helper prepares:

- `gh-address-cr-X.Y.Z.zip`, including hidden plugin metadata
- `gh-address-cr-X.Y.Z.zip.sha256`
- `publication.json`, schema `plugin-publication.v1`, recording source identity
  and build provenance

Actions transports the ZIP and receipts, rather than an unpacked payload that
could lose hidden files. After PyPI succeeds, the plugin publisher and Homebrew
publisher run as independent jobs. Dry-run, TestPyPI, and no-release runs do not
publish the Marketplace. Plugin failure never repeats PyPI publication.

The writer uses the same repository's `GITHUB_TOKEN` with only `contents: write`;
no new PAT or cross-repository credential is needed. Normal publication checks
out the exact source SHA from the build. Recovery runs only when dispatched on the default branch and checks out that
trusted branch's implementation. Both writers share the fixed
`plugin-marketplace-publication` concurrency group with cancellation disabled.

GitHub Release assets are immutable recovery inputs. Identical existing asset
bytes are reusable; conflicting bytes fail rather than overwrite. Only after
assets are present does the helper project them onto the `marketplace` branch.
The branch is generated distribution output; do not edit it as another source
of truth. Publication uses a normal Git ref update, never a force push, and
reports success only after fetching and comparing the complete remote tree.

| Observed remote snapshot | Candidate action |
| --- | --- |
| Branch absent | Create the first snapshot |
| Candidate version newer | Advance the branch |
| Same version and identical snapshot | No-op |
| Same version with divergent content | Fail; investigate source/assets |
| Candidate version older | Report superseded; preserve newer snapshot |
| Malformed remote truth | Fail; investigate before repair |

Non-fast-forward races trigger a bounded reread/retry, not forced replacement.
Publication receipts and telemetry describe distribution; they never determine
PR-session state or `final-gate` truth. Telemetry errors remain visible and
fail-open; unsafe assets, source divergence, and unverified Git writes fail loud.

## Recovery

Use **Recover Plugin Marketplace** (`.github/workflows/plugin-marketplace.yml`)
with a stable version that already contains the plugin assets. The existing
3.22.0 release predates this lane and cannot be recovered through it. It accepts only a version
and reuses validated assets from that GitHub Release. It does not run
semantic-release, build a Python package, rebuild historical plugin assets, or
repeat PyPI upload. Missing assets are a hard stop; inspect the original release
run rather than rebuilding historical bytes in recovery.

The equivalent helper invocation from a trusted checkout is:

```bash
python -m scripts.release.plugin_release recover \
  --directory dist/plugin-release --version X.Y.Z
```

Source validation temporarily reproduces the tagged builder output and compares
it byte-for-byte with the existing ZIP, including generated manifests and images.
Those verification files are never uploaded or used to replace missing assets.

Normal and recovery publication obey the same version policy and remote
readback. An older recovery may legitimately finish as superseded.

## Rollout evidence still required

Before describing the remote listing as available, verify the first stable
release's ZIP/checksum/receipt assets, successful PyPI prerequisite, and exact
remote `marketplace` tree readback. Then install from the real GitHub branch
and verify the expected plugin version and skill content. Retain that release
run and source receipt as evidence. macOS desktop installation and replacement
remain an explicit acceptance gate; Linux CLI smoke alone does not close it.

## Bundle contract

`publication.json` has exactly these v1 fields: `schema_version`, `version`,
`source_tag`, `source_commit`, `archive`, `files`, `snapshot`, and `build_run_url`.
`archive` records the versioned ZIP name and SHA-256. `files` maps plugin-root
relative file paths to SHA-256 values. `snapshot` carries the catalog, fixed v1
README, and tagged LICENSE needed to restore the distribution tree. The build
URL is a public workflow-run link; local paths, credentials and telemetry are
not part of the receipt. The receipt excludes its own hash to avoid a
self-referential artifact boundary. A future receipt shape or README contract
change requires an explicit schema version and corresponding recovery tests.

The builder preserves `--output` and `--check`; `--archive PATH` creates the
same ZIP used by publication and optional manual account upload. `--check`
rejects an archive output request rather than creating files during validation.
Building requires the development tooling dependency PyYAML; it is not added
to the installed review runtime's dependencies.
