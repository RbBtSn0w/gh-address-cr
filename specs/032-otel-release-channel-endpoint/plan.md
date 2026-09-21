# Implementation Plan: OTel Release-Channel Default Endpoint

## Architecture Preflight

| Boundary | Decision |
|---|---|
| Authoritative state owner | Package `__version__` is the only input; telemetry never becomes workflow truth |
| External inputs | `__version__`, `OTEL_EXPORTER_OTLP_*` env, `DISABLE_TELEMETRY`/`DO_NOT_TRACK` |
| Projection | One pure function `release_channel(version) -> production | development` and one default-endpoint table |
| Policy | Only dev releases (`.devN`) leave production; unparseable version -> production; explicit endpoint and opt-out always win |
| Side-effect boundary | Only which approved gateway origin the existing traces-only exporter targets |
| Artifact truth | Honeycomb data per environment is operational evidence, never final-gate evidence |
| Recovery/replay | Export stays fail-open; rollback is reverting the default table to production, or the existing opt-out |
| Self-reference risk | A build cannot infer gateway health from absent spans; misrouting is caught by per-channel canaries, not by the client |
| Executable contracts | Table-driven channel tests, precedence tests, repo-version contract test, per-channel canaries |

## Design Notes

- Channel derivation uses `packaging.version.Version` (already a runtime
  dependency). `is_devrelease` -> development; everything else, including `-beta.N`
  builds published from `develop` and any version whose only non-final marker is a
  `local` segment, -> production. A local segment is not consulted: preview builds
  are `<base>.devN+<sha>` and `.devN` already identifies them.
  Pre-releases are deliberately not routed away: they are user-facing builds and
  their failures are real signal.
- Failure direction is deliberate. Routing a stable build to a non-production
  origin silently loses production telemetry; routing a dev build to production
  is the current behavior. When unsure, choose production.
- Keep the channel logic next to `_traces_endpoint` in `otel_tracing.py` and keep
  `GATEWAY_ORIGINS` as the single allowlist so the admission header rule is
  unchanged.
- Local dev installs (`pip install -e .`) report the checked-in stable version and
  therefore stay on production; developers who need isolation use the explicit
  endpoint or the opt-out. This is the accepted residual gap, recorded rather
  than hidden. The CI fix (#280) covers CI in the meantime.

## Delivery

1. Add `release_channel()` and the channel default table with tests written first
   (red), then implement (green).
2. Update `_traces_endpoint` to fall back to the channel default; keep the two
   explicit-variable branches first.
3. Update `README.md` and `PRIVACY.md` to describe channel routing and keep the
   opt-out text.
4. Run repository verification, then canary each channel and record the evidence
   (endpoint, environment slug, one trace ID) in this spec.
5. Only after canaries pass, revisit alert semantics (separate change).

## Risks

| Risk | Mitigation |
|---|---|
| Stable release misclassified and routed off production | Table test over real published formats; repo-version contract test; unparseable -> production |
| Privacy expectation shifts for dev-build users | Same anonymous profile and fields, documented in `PRIVACY.md`; opt-out unchanged |
| Pre-release noise in production alerts | Alert semantics are handled separately (per-version, deduplicated); beta versions remain distinguishable by `service.version` |
