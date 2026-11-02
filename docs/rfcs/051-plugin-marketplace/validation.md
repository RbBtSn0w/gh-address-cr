# Marketplace implementation verification

Date: 2026-11-02. Production distribution is pending the next stable release.

## Local implementation checks

- Development virtual environment refreshed with `scripts/dev_setup.sh`.
- Full unittest discovery: 1826 tests, OK, one skipped (214.933 seconds).
- Ruff: `src tests scripts/build_plugin_payload.py scripts/release` passed.
- Mypy ratchet: zero errors in 94 source files.
- actionlint: CI, release and recovery workflows passed.
- CLI help, agent manifest, portable payload/archive build and `--check` passed.
- Bare Git tests prove complete first snapshot, repeat no-op, bounded failures,
  uncertain push reconciliation and divergence rejection. Asset tests prove
  uncertain upload reconciliation, immutable-byte conflict and missing recovery
  input rejection. Source-tag tampering and reconstructed-hash image tampering
  fail. Smoke profile tests prove existing profiles are protected and cache-only
  version advances cannot satisfy active installation checks.
- Independent review's two findings (cache versus active install; generated
  files' source binding) were fixed, regression tested and closed by the reviewer.

The local suite above ran before integrating the upstream 3.22.0 version-only
synchronization; post-integration targeted checks and PR CI are recorded below.

## Remaining rollout evidence

The pinned real Codex two-version test executes on a disposable Actions runner;
its result must be read before client compatibility is declared proven. There
is no production `marketplace` branch creation or historical release overwrite
in local tests. First real GitHub installation, macOS desktop/new-session skill
loading and same-version production recovery remain next-release acceptance
checks. A later real release is needed for live cross-version update evidence.

## Post-integration checks

Upstream `develop` synchronization changed only CHANGELOG and version metadata
to 3.22.0. After a normal merge and development-environment refresh, 81 focused
packaging/runtime/workflow/distribution tests passed (10.804 seconds), together
with Ruff, the zero-error mypy ratchet, actionlint, CLI/agent manifest smoke,
portable archive generation and the builder's non-mutating check.
