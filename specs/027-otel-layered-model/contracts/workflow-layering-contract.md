# Contract: Layered Workflow Telemetry

This contract defines the observable runtime behavior expected if the layered
OTel model is adopted.

## C-1 Root span remains the single invocation anchor

- Every CLI invocation emits exactly one root `gh-address-cr.cli` span.
- The root span remains the authoritative top-level timeline for one invocation.
- Adoption of child spans does not create a synthetic cross-invocation parent.

## C-2 Child spans are reserved for independently measurable operations

- A workflow step may become a child span only if it has at least one of:
  - independent duration worth querying
  - independent count worth aggregating
  - independent error ownership
  - externally visible product/operational value
- Child spans must have stable names and deterministic parentage.
- The first approved child span names are:
  - `gh_address_cr.adapter`
  - `gh_address_cr.command_session.operation`
- These spans must be direct children of the active `gh-address-cr.cli` root
  span for the current invocation.

## C-3 Checkpoints remain events by default

- Phase markers, state transitions, and singular timeline annotations remain
  events unless explicitly promoted by the rule in C-2.
- Event retention must not be used as a workaround for missing child-span
  timing on a truly independent operation.
- For the first implementation slice, `preflight`, `session`, `ingest`, `gate`,
  and summary-style high-level workflow markers remain event-first.

## C-4 First implementation slice targets bounded candidates

- The first implementation slice must cover:
  - adapter execution boundaries
  - command-session operation boundaries
  - at least one high-level workflow boundary only if it satisfies C-2
- The first slice must not promote every high-level phase marker.

## C-5 Session grouping stays correlation-first

- Multi-invocation sessions may be grouped by correlation attributes.
- Missing or partial trace context across processes must not block execution or
  cause synthetic parent-child links to be invented.

## C-6 Telemetry remains observed evidence

- No span/event attribute may become workflow truth, gate truth, or review
  resolution truth.
- Fail-open behavior for the core review workflow remains unchanged.

## C-7 Public contract protection

- The first implementation slice must not require new public CLI flags,
  machine-summary fields, or packaged-skill behavior changes.
- If a later slice needs that surface area, it requires explicit contract
  versioning or a follow-up architecture/spec decision.

## Verification Targets

- Runtime tests prove the retained root-span contract.
- New tests prove child-span presence only for promoted operations.
- Existing event-based checkpoints remain visible where intended.
- Smoke checks confirm no CLI behavior regressions when telemetry is enabled.
