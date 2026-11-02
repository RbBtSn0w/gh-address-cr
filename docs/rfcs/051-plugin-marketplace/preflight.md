# Plugin marketplace distribution preflight

Status: implementation approved; production activation awaits the next stable release.

## Ownership and inputs

The immutable stable source tag owns source identity and version. The existing
`skill/` directory owns skill content. A deterministic build produces one ZIP,
its checksum, and `publication.json` (schema `plugin-publication.v1`). GitHub
Release assets are immutable recovery inputs. The `marketplace` Git branch is
an installable projection of those assets, never a second editable source.
Inputs are the exact source commit/tag, stable version, build-run URL, release
metadata, asset bytes and observed remote branch commit/tree.

## Projection, policy and side effects

The projection contains the catalog, plugin payload, README, LICENSE and source
receipt. Policy is explicit: missing branch -> create; higher candidate version
-> advance; identical same-version snapshot -> no-op; same-version divergence
or malformed remote truth -> fail; older candidate -> superseded. Serialize
writers and retry non-fast-forward races at most three times, re-reading facts.
Plan immutable asset uploads first, then one normal Git ref update. Confirm
completion only by fetching the remote commit and comparing the entire tree.
No force push, trunk mutation, PR-session transition or new state engine exists.

## Recovery and boundaries

Recovery reads existing stable Release assets and validates their source tag;
it never rebuilds missing historical assets or repeats PyPI/semantic-release.
Asset upload uncertainty is reconciled by reading actual remote bytes. Identical
assets are reusable; divergent same-name bytes fail. Telemetry/report artifacts
cannot authorize publication or turn an unverified write into success. Reporting
excludes its own output from payload hashes. Telemetry failure is visible and
fail-open; distribution validation and Git failures are fail-loud.

## Complexity and contracts

One release helper and one generated branch extend the existing release lane.
Keeping only Actions artifacts was rejected because Git consumers cannot read
untracked generated files. A separate repository and credentials are unnecessary.
Reuse existing release telemetry and subprocess sanitization; phases are events.
Tests cover portable/legacy manifests, reproducible archives, safety validation,
source identity, the entire policy table, asset recovery, Git races and readback,
workflow permissions/conditions and a pinned Codex two-version installation.
Live first-release and macOS acceptance remain explicit rollout gates, not
claims inferred from unit tests. No production branch or asset is created by
implementation verification.

## Review refinements

Source verification also executes the exact tagged builder in a temporary source
projection using isolated Python, without release tokens or checkout credentials.
Its output is compared byte-for-byte with the already downloaded ZIP; it is
never substituted for absent or damaged assets. The v1 distribution README is a
fixed receipt-schema contract. Historical metadata is validated structurally
rather than matched against the current builder template.

The compatibility smoke reads Codex's installed/enabled selection and verifies
that version's actual cached manifest and skill files. A newer cached version
alone cannot satisfy installation acceptance. The smoke refuses an existing
profile and runs only on a disposable GitHub Actions runner.
