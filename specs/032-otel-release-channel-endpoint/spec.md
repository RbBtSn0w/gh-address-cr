# Feature Specification: OTel Release-Channel Default Endpoint

## Objective

Make the default OTLP endpoint a function of the build's release channel so that
development, preview, and pre-release builds cannot export to the production
gateway by default. Stable releases keep exporting to the production gateway.
CLI, workflow-state, final-gate, and Status-to-Action behavior do not change.

## Problem

`otel-tracing.v2` (spec 030) fixed the default to the production gateway and
removed `deployment.environment.name` from the client because distributable
software must not self-declare a hosted environment. The gateway therefore
selects the Honeycomb environment purely by which origin the client posts to,
and every caller that does not override the endpoint lands in `production`.

Evidence (Honeycomb, 2026-09-21):

- Since 2026-07-25 the `development`, `staging`, and `test` environments received
  zero events; all traffic reached `production`.
- Production contains non-release builds: `3.15.1.dev271+83f6be4`,
  `3.13.1.dev266+*`, `3.15.2.dev279+*`, and `3.15.3`.
- CI smoke runs of the installed wheel against the placeholder `owner/repo`
  exported exit-4 failures to production and fired the production auth and error
  alerts about every CI run.

Per-caller opt-in (`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) fixes one source at a
time and leaves local development, PR preview installs (Homebrew dev formula),
and agent environments leaking.

## Requirements

- Derive a release channel from the installed `__version__` using PEP 440:
  - `development`: dev release (`.devN`) only. PR preview builds are versioned
    `<base>.devN+<sha>`, so the `.devN` alone identifies them; the `+<sha>` is
    not needed and is deliberately not a signal;
  - `production`: everything else, including final releases and published
    pre-releases (`a`, `b`, `rc`, `-beta.N`). Pre-releases are real user-facing
    builds distributed through normal channels, so they report to production.
  - A local version segment (`+...`) never changes the channel on its own. A
    version that is both a pre-release and carries a local segment, for example
    `3.16.0-beta.1+abc`, is `production`: there is no rule under which it could
    also be `development`, so the mapping is a function of the dev-release flag
    alone. This follows the plan's stated failure direction: routing a real
    build away from production silently loses its telemetry, and a local
    segment is not evidence that a build is synthetic (a repackaged release may
    carry one).
- When no endpoint is configured, use the approved gateway origin for the
  channel: `production` -> `https://telemetry-gateway.hamiltonsnow.workers.dev`,
  `development` -> `https://telemetry-gateway-development.hamiltonsnow.workers.dev`,
  each with `/v1/traces`. The staging origin stays allowlisted but is never a
  default; it remains available through the explicit endpoint variables.
- Precedence, highest first: telemetry opt-out (`DISABLE_TELEMETRY`,
  `DO_NOT_TRACK`) disables export; `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`;
  `OTEL_EXPORTER_OTLP_ENDPOINT`; the channel default.
- A version that cannot be parsed falls back to the production default so a
  parsing defect never silently discards stable-release telemetry.
- Do not export the channel as a Resource attribute and do not restore
  `deployment.environment.name`; `service.version` already carries the signal.
- The `anonymous-client-v1` admission header keeps its exact-origin allowlist;
  no new origin is added.

## Success Criteria

- A table-driven test maps representative versions to channels, including the
  formats this repository actually publishes: `3.15.2` and `3.16.0-beta.1`
  (production), `3.15.2.dev279+5dc8a44` and `3.13.1.dev266+b3bddc8` (development),
  and the boundaries that follow from the rule above: `3.16.0-beta.1+abc` and
  `3.15.2+internal` (production: a local segment alone is not a dev release).
- Explicit endpoint variables and the opt-out keep their existing precedence.
- The repository's own `__version__` classifies as `production` on `main`, and a
  contract test fails if a stable-looking version would route off production.
- Canary evidence per channel: one span from a dev build reaches only the
  `development` Honeycomb environment, and one from a stable or pre-release build
  only `production`.
- `PRIVACY.md` and `README.md` describe channel routing and still contain
  `DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1`.

## Non-Goals

- Changes to the gateway Worker, its secrets, or Honeycomb environment routing.
- Alert or trigger redesign and anonymous-ingest trust boundaries (tracked
  separately); dataset cleanup.
- Client-declared environments, new attributes, or any identifier.
- The `adg` client, which needs the same rule in its own spec and repository.
