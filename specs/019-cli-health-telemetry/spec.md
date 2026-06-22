# Feature Specification: CLI Health Telemetry

## Problem Statement

The existing telemetry surface is useful for efficiency summaries, but it is not
yet reliable enough to discover `gh-address-cr` CLI product issues and feed
them back into future fixes. A `runtime-only` final-gate result currently tells
the operator that host telemetry was not imported, but not whether the CLI
missed a profile, lacked an agent session id, failed to find a transcript, could
not attribute the transcript to the PR window, or hit storage problems.

Telemetry MUST therefore shift from "agent profile data collection" to a CLI
health model:

1. Runtime CLI observations are authoritative for CLI health.
2. Host telemetry is contextual evidence only.
3. Missing host telemetry is fail-open for review completion but diagnose-loud.
4. Diagnostics must be vendor-neutral and profile-driven.
5. Every health issue must map to a stable `reason_code`, `next_action`, and
   public-safe detail.

## Architecture Preflight

- **Authoritative state owner**: deterministic runtime under
  `src/gh_address_cr/core/`. CLI health diagnostics are stored with PR-scoped
  telemetry ledgers and projected into reports.
- **External facts / event inputs**: runtime command telemetry, telemetry import
  summaries, host profile package data, environment variables, discovered
  transcript paths, PR session window timestamps, and telemetry store health.
- **Projection shape**: `CliHealthIssue`, `HostAutodiscoveryCheck`, and
  `TelemetryDoctorReport`.
- **Policy / decision function**: stable issue taxonomy maps diagnostics to
  `reason_code`, `severity`, `retryable`, and `next_action`.
- **Side-effect boundary**: `final-gate` may append fail-open telemetry import
  diagnostics; `telemetry doctor` only reads/project diagnostics and writes no
  review-resolution state.
- **Artifact truth boundary**: health reports and efficiency reports are
  diagnostic artifacts only. They do not resolve review items or prove
  completion.
- **Recovery / replay**: doctor reports are derived from PR-scoped ledgers and
  current host/profile facts; appended autodiscovery misses are replayable as
  import-summary diagnostics.
- **Executable tests**: command tests must cover fail-open autodiscovery misses,
  doctor output, coverage labels, reason codes, and public-safe diagnostics.

## Requirements

- **FR-001** Runtime CLI telemetry MUST remain the authoritative source for CLI
  health evidence. Host telemetry MUST NOT be required for final-gate success.
- **FR-002** Host telemetry autodiscovery misses MUST be recorded as structured,
  public-safe diagnostics with stable `reason_code` values.
- **FR-003** Autodiscovery diagnostics MUST be profile-driven. Adding a profile
  such as Codex or Claude Code must not require hard-coded final-gate branches.
- **FR-004** `gh-address-cr telemetry doctor <owner/repo> <pr_number>` MUST emit
  a machine-readable report that checks packaged profiles, relevant environment
  variables, transcript discovery, PR attribution window availability, telemetry
  storage health, and existing import diagnostics.
- **FR-005** CLI health issues MUST include `reason_code`, `severity`,
  `retryable`, `next_action`, and public-safe `detail`.
- **FR-006** Efficiency reports MUST surface CLI health issues separately from
  inefficiency flags so product problems are not hidden as generic slow/failing
  operations.
- **FR-007** The latest PR-scoped CLI machine summary MUST feed CLI health
  telemetry when it reports a non-passing `reason_code`, preserving the
  observed reason code as metadata and using the runtime-provided `next_action`
  as the repair feedback path.
- **FR-008** Malformed or unsafe telemetry input remains fail-loud for telemetry
  commands. Missing host telemetry remains fail-open for core review flows.
- **FR-009** Public docs and executable acceptance tests MUST evolve with the
  CLI health contract.

## Non-Goals

- Telemetry does not resolve GitHub review threads or local findings.
- Telemetry does not store prompts, file contents, tokens, usernames, or private
  machine identifiers.
- This feature does not require every public command to be fully instrumented in
  one step; it establishes the durable health taxonomy and projection boundary.
