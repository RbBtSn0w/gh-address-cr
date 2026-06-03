# Implementation Plan: External Agent Telemetry Ingestion

**Branch**: `016-external-agent-telemetry` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/015-external-agent-telemetry/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Extend the existing agent-efficiency metrics feature so runtime metrics are visible in final-gate output, audit summaries, and structured reports, then add PR-scoped external agent telemetry ingestion for generic and host-specific agent sources. The runtime will own canonical event normalization, deterministic event fingerprinting, safety checks, deduplication, coverage labeling, combined efficiency reporting, and final-gate evidence while keeping review state, GitHub side effects, and published reply handling unchanged. Telemetry commands fail loudly for telemetry-specific failures; core PR review, address, publish, reply, resolve, and final-gate flows remain fail-open for damaged or missing telemetry by reporting `runtime-only` or `unavailable` coverage.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: Python standard library and current package dependencies from `pyproject.toml`; no new required third-party dependency
**Storage**: Existing PR session workspace files under the runtime cache; new telemetry event, import ledger, fingerprint ledger, and report artifacts are PR-scoped files
**Testing**: `ruff check src tests`, `python3 -m unittest discover -s tests`, targeted telemetry/CLI/workflow tests, CLI smoke checks
**Target Platform**: Local-first cross-platform Python CLI runtime and installable skill guidance
**Project Type**: Single Python CLI package plus packaged skill adapter
**Performance Goals**: Preserve existing PR review handling latency; telemetry import/report generation should be linear in imported event count and avoid blocking final-gate when telemetry is unavailable or damaged
**Constraints**: Runtime state and final-gate evidence remain deterministic; telemetry failures fail open for review handling but fail loud for telemetry commands; unsafe external telemetry must not leak private prompts, tokens, usernames, machine identifiers, or unnecessary absolute local paths; duplicate or overlapping imports must be idempotent through deterministic event fingerprint hashes
**Scale/Scope**: PR-scoped workflow telemetry for one runtime session plus zero or more imported host-agent telemetry batches; cross-PR aggregation is out of scope

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. The runtime owns normalized telemetry state, event fingerprints, report artifacts, coverage labels, final-gate evidence, and all existing review side effects. The skill only routes agents to ingest/report telemetry.
- **Public CLI contract**: PASS. Existing `review`, `address`, `agent publish`, and `final-gate` behavior remains stable. New telemetry commands are additive, and final-gate output gains additional evidence without changing existing gate counts or review-resolution reason codes.
- **Evidence-first handling**: PASS. Imported telemetry is evidence about workflow efficiency, not evidence that resolves review items. Review classification, reply, resolve, and final-gate proof remain unchanged and authoritative.
- **Packaged skill boundary**: PASS. Runtime parsing, safety checks, deduplication, fingerprinting, storage, and report generation live under `src/gh_address_cr/`; skill updates only describe when to ingest external telemetry and how to report coverage.
- **External intake replaceability**: PASS. Telemetry intake is separate from normalized findings intake and does not couple review resolution to any review producer or agent vendor.
- **Fail-fast verification**: PASS. The plan includes tests for malformed telemetry, unsafe content, duplicate and overlapping imports, runtime-only summary repair, generic agent imports, host-specific imports, report artifacts, final-gate evidence, and fail-open core workflow behavior.

## Project Structure

### Documentation (this feature)

```text
specs/015-external-agent-telemetry/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── telemetry-ingestion.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py                         # telemetry command routing and final-gate output additions
├── core/
│   ├── telemetry.py               # canonical events, fingerprinting, import validation, reports, coverage labels
│   ├── workflow.py                # validation command telemetry capture for workflow execution
│   ├── gate.py                    # final-gate session metrics and report status integration
│   └── paths.py                   # PR-scoped telemetry artifact path helpers
└── commands/
    └── submit_feedback.py         # feedback context may include efficiency report metadata

skill/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    └── agent-protocol.md

tests/
├── core/
│   └── test_telemetry.py          # canonical event import, fingerprinting, sanitization, reports, coverage labels
├── fixtures/
│   └── telemetry/                 # valid, malformed, duplicate, and unsafe telemetry feeds
├── test_python_wrappers.py        # CLI command surface and final-gate output contracts
├── test_native_workflow.py        # publish/final-gate integration behavior
└── test_skill_docs.py             # packaged guidance for telemetry ingestion and coverage reporting
```

**Structure Decision**: Keep this as a single Python CLI/runtime feature. The new behavior is an extension of the existing telemetry and final-gate surfaces, so it should stay close to `src/gh_address_cr/core/telemetry.py`, `src/gh_address_cr/cli.py`, and existing workflow/gate tests. No new service, database, or standalone app is needed.

## Complexity Tracking

No constitution violations.

## Phase 0: Research

See [research.md](./research.md).

## Phase 1: Design And Contracts

- [data-model.md](./data-model.md): external telemetry event, deterministic event fingerprint hash, telemetry import, telemetry source, coverage report, efficiency report, and safety diagnostics.
- [contracts/telemetry-ingestion.md](./contracts/telemetry-ingestion.md): public CLI command contract, accepted generic event feed shape, report output shape, diagnostics, idempotent duplicate handling, fail-open/fail-loud behavior, and coverage labels.
- [quickstart.md](./quickstart.md): runtime-only repair scenario, generic external agent import, host-specific import, malformed/unsafe feed rejection, duplicate import idempotence, corrupted telemetry fail-open behavior, and final-gate proof.

## Post-Design Constitution Check

- **Control plane ownership**: PASS. Design artifacts keep telemetry normalization, fingerprinting, persistence, report generation, and final-gate evidence in deterministic runtime code.
- **Public CLI contract**: PASS. New telemetry commands are additive; existing command outputs remain compatible except for additional report/evidence fields.
- **Evidence-first handling**: PASS. Telemetry evidence is scoped to workflow efficiency and cannot resolve or mutate review items.
- **Packaged skill boundary**: PASS. Skill changes are guidance-only and use skill-root-relative paths.
- **External intake replaceability**: PASS. Telemetry intake uses source attribution and canonical events without coupling to review producers.
- **Fail-fast verification**: PASS. Quickstart and contracts define targeted tests for each changed public behavior and failure mode, including fingerprint idempotence and core workflow fail-open behavior.
