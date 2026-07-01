# Contracts: Core-Path-Anchored Complexity Reduction

A reduction feature's contracts are (1) the **reduced public CLI surface**,
(2) the **governance deltas** that make the reduction legal, and (3) the
**protected-baseline invariants** every stage must uphold. Executable enforcement
lives in the existing test suite + per-stage grep proofs.

## 1. Reduced CLI surface (versioned change)

| Command | Before | After | Note |
|---------|--------|-------|------|
| `review`, `address`, `threads`, `findings`, `agent`, `final-gate`, `adapter`, `version` | present | **unchanged** | core surface; machine summaries byte-for-byte identical (SC-004) |
| `consolidation` | present (024) | **removed** | versioned; help/metavar/skill updated |
| `evaluation` | present (023) | **removed** | versioned; `final-gate` manifest call removed (verdict unchanged) |
| `telemetry` | present | **shrunk (versioned)** | OTLP tracing kept; any removed public subcommand is a versioned change with help/metavar + unknown-command handling (FR-008/SC-008) |
| `command-session`, `doctor`, `active-pr`, `review-to-findings`, `submit-*` | present | unchanged (unless separately justified) | not in reduction scope |

**Guarantees**: after removal, invoking a removed command fails as an unknown
command listing the reduced supported set (non-zero exit); no core-command reason
code, wait state, exit code, or machine-summary field changes (SC-004). Every
public-surface removal also updates affected repo-root docs and `skill/`
guidance in the same change (FR-011/FR-017).

## 2. Governance deltas (US5 — `.specify/memory/constitution.md` + `AGENTS.md`)

Constitution MAJOR bump with a Sync Impact Report. Principle deltas:

```text
VI  Multi-Agent Coordination      MUST (always)  ->  MUST when blast radius = multi-agent work
VIII Telemetry Attributed Evidence MUST (full contract) -> MUST keep OpenTelemetry tracing;
                                                            attribution/fingerprint/coverage
                                                            required only for external telemetry ingestion
IX  First-Principles Runtime Kernel MUST (model all review resolution)
                                    -> final-gate keeps fact->projection->policy;
                                       broader kernel modeling is blast-radius-triggered
+X  Minimal Viable / Complexity Budget (NEW):
      the protected baseline (core journey + OpenTelemetry) is the floor;
      any new subsystem beyond it requires a recorded blast-radius justification.
```

`AGENTS.md`: the **Architecture Preflight Gate** fires only on a blast-radius
trigger (not on every runtime/telemetry/lease touch); references to removed layers
pruned.

**Invariant (SC-009)**: no unconditional MUST that US1–US4 violate remains;
version bumped; AGENTS.md consistent.

## 3. Protected-baseline invariants (cross-cutting, every stage)

- Core journey (findings → classify → reply + resolve → `final-gate`) works
  identically before/after each stage; reply/resolve remain `github/client.py`
  GraphQL mutations via `publisher.py` (unchanged).
- `final-gate` verdicts are byte-for-byte identical on representative fixtures
  before/after removing the evaluation manifest call (SC-002).
- OpenTelemetry still traces the surviving core CLI invocation after every stage
  (SC-005) — kept as live observability, not an empty shell; OTel plumbing that only
  served a removed subsystem is deleted with it (FR-006).
- Core review/resolve/final-gate complete with internal telemetry absent/disabled
  (fail-open — SC-006).
- `(src/ grep hits for deprecated/legacy/compat/shim) − (entries in
  `.deprecated-allowlist.txt`)` equals zero post-reduction (SC-011); the allowlist
  enumerates each intentionally-retained match with a justification.
- `skill/` contains zero references to a removed command or removed architecture
  still presented as live (SC-012 / FR-017).
- Repo-root docs do not retain stale references to removed commands, removed
  telemetry/orchestration behavior, or the deleted dual-engine model after the
  corresponding story lands (FR-011).
- The protected load-bearing layers (`agent_protocol`, `leases`, `agent_batch`,
  `github/client.py`, `publisher.py`, `session`, `gate`, `runtime_kernel/final_gate`)
  import cleanly after every stage (FR-010 positive survival assertion).
- Each stage independently green (`unittest` + `ruff`) with no dangling import
  (FR-009); git is the reversal mechanism (no runtime fact rewritten).
