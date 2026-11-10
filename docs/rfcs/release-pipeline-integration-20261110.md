# Release pipeline integration preflight

Date: 2026-11-10. Scope: existing repository release tooling only; not the installed skill, review/session kernel, final-gate, telemetry ingestion or a new delivery adapter.

## State and inputs

Semantic-release remains the sole version/tag/notes authority. Its existing plan is the engine record; a versioned `plan.pipeline` envelope binds the original candidate, engine identity, configuration digest and declared goals. External inputs remain the existing GitHub event, sealed plan/materials, file-level PyPI receipts and independent remote observations. Current configuration cannot remove an original goal.

## Projection and deterministic policy

The adapter exposes its existing analysis path and engine identity without selecting a version. Shared coordination captures the immutable envelope after analysis. Before existing effect entrypoints run, the common validator checks its digest and agreement with the engine record. Missing legacy envelopes preserve documented legacy behavior; a present invalid envelope fails closed. Reports pass the original plan and current configuration to the common writer, project original goals and use the common report exit policy. Job success alone never proves delivery.

## Effects, recovery and artifacts

The existing engine, sealed handoff, GitHub publication, per-file PyPI publication/recovery, Homebrew and Marketplace remain the effect owners in their existing jobs. No command/outbox service is added: the current workflow commands are the bounded effect plan, with existing receipts as execution evidence. Node adapter boundaries validate the original envelope before invoking existing Python handoff/recovery. Python payload verification and PyPI restore semantics remain unchanged. No artifact code is executed. Original immutable material bytes, not the current checkout, remain recovery input.

The envelope is a versioned release identity source protected by a digest and explicit contract tests; it does not make reporting output authoritative. `release-result.json` and summaries remain projections of independent evidence. Reporting does not observe its own write or manufacture telemetry coverage.

## Justification and acceptance

A small adapter contract is needed to connect existing release semantics to shared coordination; retaining unversioned custom output would hide goals and identity from the common boundary. This adds no second version algorithm, review-state kernel, persistence system, credentials, permissions or platform adapter. Tests must prove engine tag retention, adapter analysis-path/identity projection, original goals after configuration changes, invalid-envelope refusal before handoff/effects, and parsed result propagation. Existing release tests remain the regression boundary. No review/session/final-gate or telemetry surfaces are modified, so their broader runtime tests and telemetry schema work are outside this release-only change.

## Implemented release boundary

The existing custom adapter now declares protocol 1, exposes its existing `--output` analysis path, and projects engine identity. The engine retains semantic-release's `nextRelease.gitTag` in `plan.tag`; v2 capture requires that real engine tag. Only an explicitly legacy plan may infer the historical `v${version}` tag when the field is absent. No second version calculation is introduced.

Adapter seal/publish/recover, engine publication and the existing consistency hook validate a present immutable envelope before their existing effects. The observer validates the original engine/envelope relation, retains original goals after configuration changes and passes `{config, plan}` to the common writer. The adapter returns the parsed retained result to the common exit policy while preserving the direct observer's exit contract. A failed subprocess cannot reuse a stale `release-result.json`.

The Node checks do not replace Python sealed-file verification. Existing GitHub recovery, per-file PyPI staging/restore, Homebrew and Marketplace behavior remain independently scoped and unchanged. Tests cover analysis-path capture, real engine tag retention, refusal of v2 tag synthesis, notes/envelope mismatch, original goals and incomplete report propagation. Remote effects and actual trusted-publisher readiness are not established by these synthetic/local tests.
