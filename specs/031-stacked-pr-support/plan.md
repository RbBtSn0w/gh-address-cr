# Implementation Plan: Stacked Pull Request Support

**Branch**: `031-stacked-pr-support` | **Date**: 2026-08-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/031-stacked-pr-support/spec.md`

## Summary

Make every existing PR-scoped workflow stack-aware while preserving one
authoritative session per pull request. A GitHub fact adapter reads and
validates the selected PR's stack; a pure runtime kernel projects an immutable
`StackContext` and topology fingerprint. Existing review resolution continues
one layer at a time. Action requests and validation evidence bind to the
observed member revision so a cascading rebase cannot reuse stale proof.
`final-gate` remains layer-scoped by default and gains explicit `--stack`
aggregation that recomputes every unmerged member from the bottom through the
selected PR against one coherent topology snapshot.

This feature does not create, navigate, restructure, rebase, force-push, queue,
or merge stacks. GitHub and the official `gh stack` extension own those effects.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Python stdlib; GitHub CLI `gh`; existing
`GitHubClient`, session store, structured agent protocol, final-gate runtime
kernel, and OpenTelemetry integration  
**Storage**: Existing JSON `session.json` and evidence ledger per PR; additive
observed context and revision-binding fields only; no stack session or database  
**Testing**: `unittest`, contract fixtures, CLI subprocess smoke tests, mocked
GitHub runner tests, and isolated live GitHub acceptance  
**Target Platform**: Local-first CLI on macOS/Linux and GitHub.com; older GitHub
Enterprise versions degrade to explicit stack-context unavailability  
**Project Type**: Single Python CLI runtime plus packaged skill payload  
**Performance Goals**: One initial stack discovery plus one final freshness read
per stack-aware command; no duplicate topology query per member; deterministic
projection for at least 100 members without material local latency  
**Constraints**: GitHub's feature is public preview; GraphQL stack fields are
read-only; pagination must complete; existing unstacked calls remain compatible;
telemetry excludes branch/member identity; no new stack-management side effects  
**Scale/Scope**: One repository and selected PR at a time; a stack may span
multiple pages; aggregate gating covers the lowest unmerged member through the
selected member and loads each member's existing PR-scoped session

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1 design.*

- **Control plane ownership — PASS**: PR sessions remain authoritative for work
  items, leases, evidence, and layer gates. Stack context is an immutable GitHub
  observation cached only as non-authoritative metadata and refreshed before
  major actions. No Markdown state or `stack-session.json` is introduced.
- **First-principles runtime kernel — PASS**: `StackObservationFact` is the
  external input. `StackContext` and `StackGateProjection` are pure projections.
  Availability/freshness/aggregate decisions use policy tables. The command
  plan reuses existing per-PR reads and reply/resolve outbox; no stack mutation
  command exists. Reports are outputs, never fact sources.
- **Public CLI contract — PASS with additive versioning**: Existing commands and
  exits remain valid. Summaries add versioned `stack_context`,
  `completion_scope`, and optional `stack_gate`. `final-gate --stack` is new.
  Existing `gate_scope: final|inline` is preserved. New reason codes and wait
  states are additive and documented in the Status-to-Action Map.
- **Evidence-first handling — PASS**: Findings and GitHub threads remain
  independently classified and published per PR. Stack membership adds revision
  binding and freshness checks but cannot satisfy classification, reply,
  resolve, validation, or layer final-gate obligations.
- **Packaged skill boundary — PASS**: GitHub adapters and policy live under
  `src/`. `skill/` contains routing, behavior policy, completion guidance, and
  machine-contract docs only. Live fixtures stay at repository root.
- **External intake replaceability — PASS**: Normalized findings stay PR-scoped;
  no producer or agent vendor becomes part of stack discovery or gating.
- **Telemetry evidence boundary — PASS**: Existing root invocation spans remain.
  Stack discovery and aggregate evaluation are span events, not new child spans.
  Attributes use bounded availability, size bucket, position class, outcome,
  and reason code; branch names and member lists are excluded. Telemetry remains
  fail-open and cannot affect gate decisions.
- **Architecture plateau discipline — PASS**: One adapter, pure kernel, and
  aggregate coordinator replace handler-local stack checks. The design adds no
  second session/state engine.
- **Fail-fast verification — PASS**: Fixtures cover pagination, malformed and
  unavailable schemas, topology mutation, stale requests, revision-bound
  evidence, aggregate order, machine output, docs, privacy, and live capability.

## Architecture Preflight

### Authoritative State Owner

- `session.json` for each `owner/repo#pr_number` remains authoritative for that
  PR's items, leases, evidence, and workflow status.
- GitHub remains authoritative for stack membership/order, branches, member
  revisions, review threads, pending reviews, and checks.
- No persisted authoritative stack aggregate exists. Cached observation metadata
  is labelled non-authoritative and refreshed before claim, submit/resolve,
  publish, and gate decisions.
- The cache retains only a non-authoritative `stack_membership_observed` safety
  hint when a later refresh is unavailable. It cannot prove current topology;
  it only prevents unbound requests, evidence, or publication from silently
  degrading a previously observed stack member into an ordinary PR.

### External Facts and Event Inputs

- Selected PR: number, state, draft flag, base/head refs, head OID, and queue state.
- Stack availability: absent, present, unavailable, or invalid.
- Present stack: node ID, repository-local number, trunk, reported size,
  paginated entries, positions, and each member's PR facts.
- Existing per-member thread, pending-review, check, finding, evidence, and lease facts.
- A closing stack observation after aggregate evaluation supplies freshness.

### Projection Shape

1. Normalize and validate raw GitHub data into `StackContext`.
2. Hash canonical structure into `topology_fingerprint` for local correlation.
3. Select the active segment: non-merged members from the lowest unmerged
   position through the selected position. A merged prefix is informational;
   closed/draft/invalid members inside the segment block.
4. Load each active member's existing PR session and recompute its current layer
   final-gate projection from remote facts.
5. Compare evidence bindings and the closing observation, then produce a
   bottom-up `StackGateProjection`.

### Policy and Status-to-Action Map

| Condition | Layer operation | Explicit stack gate | Stable action |
|-----------|-----------------|---------------------|---------------|
| No stack | Existing behavior, PR scope | One-member segment | Continue |
| Valid unchanged stack | Per-PR flow with revision binding | Bottom-up segment | Act on first blocked member |
| Stack API unavailable | Continue with readiness unknown | `STACK_CONTEXT_UNAVAILABLE` | Restore capability |
| Malformed/incomplete stack | Preserve bounded diagnostics | `STACK_CONTEXT_INVALID` | Refresh and inspect |
| Request topology/revision changed | Reject before publish | `STACK_CONTEXT_STALE` | Refresh and revalidate |
| Member session missing | Current layer unaffected | `STACK_MEMBER_SESSION_MISSING` | Run member review/address |
| Member layer gate fails | Retain its layer result | `STACK_MEMBER_BLOCKED` | Run member recovery command |
| All pass and closing snapshot matches | Layer proof only | `PASSED` with exact range | Claim only reported scope |

### Side-Effect and Outbox Boundary

- Existing runtime-owned GitHub reply/resolve operations stay scoped to one PR.
- Stack discovery, projection, and aggregate gate are read-only.
- No `gh stack` command or asynchronous merge endpoint is invoked.
- A stale context blocks before existing publish side effects execute.

### Artifact Truth and Telemetry Self-Reference

- Machine summaries, audit Markdown, completion summaries, efficiency reports,
  and prior stack-gate results are reporting evidence only.
- Aggregate gating reads current sessions and GitHub facts; it never consumes a
  prior pass artifact as a member decision.
- The report write itself is outside gate truth and measured business counts.
- Direct machine output may show owning branches; telemetry and public-safe
  reports redact them and never attach member lists or topology fingerprints.

### Recovery, Replay, and Executable Contracts

- Fixtures replay unsupported capability, unstacked, multi-page, merged-prefix,
  queued, malformed, and topology-changed observations.
- Pure kernel tests prove canonical fingerprints, active segments, revision
  freshness, failure order, and deterministic replay.
- CLI contracts prove additive fields/codes and unchanged unstacked calls.
- Agent tests prove context changes invalidate requests before submit/publish.
- Live proof is reported at three levels: schema capability, isolated stack
  discovery, and isolated mutation/freshness acceptance.

### Mode A Repair Preflight

- A batch submission is one immutable action transaction: all response rows are
  validated first, one lazily acquired GitHub stack observation is reused for
  every row, and a stale/cross-layer rejection releases every lease in that
  rejected batch back to the authoritative session queue.
- Terminal `github_thread` and `local_finding` items share the runtime-owned
  item validation-evidence boundary. The CLI validates item kind/state before
  network discovery, attaches the current revision binding, and never treats a
  producer artifact as current-revision proof.
- The E2E manifest remains non-authoritative. Local namespace validation plus
  live stack, pull-request, branch, revision, and synthetic-comment identity
  must all pass before cleanup or exercise may issue a GitHub mutation.
- Contract, workflow, and mocked GitHub tests replay stale batch transactions,
  local item reconciliation, malformed topology, forged manifests, and
  unrelated-thread selection without making external writes.

## Project Structure

### Documentation (this feature)

```text
specs/031-stacked-pr-support/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── stack-context-v1.md
│   ├── stack-final-gate.md
│   └── revision-bound-evidence.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── github/client.py                    # Paginated PR/stack fact reads
├── core/
│   ├── runtime_kernel/
│   │   ├── final_gate.py               # Reused member policy
│   │   └── stack.py                    # NEW facts/projection/policy
│   ├── stack_gate.py                   # NEW aggregate coordinator
│   ├── agent_protocol.py               # Context in requests + stale guard
│   ├── agent_batch.py                  # Same context for batch requests
│   ├── validation_evidence.py          # Revision-binding eligibility
│   ├── gate.py                         # Layer scope/context
│   ├── command_templates.py            # Member recovery templates
│   ├── protocol_codes.py               # Additive codes
│   └── telemetry_safety.py             # Bounded stack attributes
├── commands/
│   ├── high_level.py                   # Discover/emit context
│   ├── agent.py                        # Refresh major actions
│   └── final_gate.py                   # --stack aggregation
└── otel_tracing.py                     # Discovery/evaluation events

skill/
├── SKILL.md
└── references/
    ├── agent-protocol.md
    ├── completion-contract.md
    └── status-action-map.md

tests/
├── fixtures/stacked_pr/
├── contract/test_stacked_pr_contract.py
├── test_stack_kernel.py
├── test_stack_github_client.py
├── test_stack_final_gate.py
├── test_agent_protocol.py
├── test_final_gate.py
├── test_otel_telemetry.py
└── test_skill_docs.py
```

**Structure Decision**: Keep the existing single-project CLI. Add one pure stack
kernel and one small aggregate coordinator. Extend current adapters and protocol
at their ownership boundaries. Do not add a database, daemon, webhook consumer,
new package, or stack session engine.

## Phased Delivery

- **P1 / US1 — awareness**: Adapter, pure context validation/fingerprint,
  additive summary, and unstacked compatibility. Read-only and independently shippable.
- **P2 / US2 — revision-safe resolution**: Bind request/evidence, refresh major
  actions, and reject stale or cross-layer submissions before publish.
- **P3 / US3 — aggregate gate**: `final-gate --stack`, bottom-up member
  evaluation, closing snapshot, recovery commands, and scoped completion line.
- **P4 / US4 — adoption**: Bounded events, privacy checks, skill/docs, complete
  repository gates, live schema probe, and isolated real-stack acceptance.

## Complexity Tracking

No constitution violations. The new kernel/coordinator are required by the
Architecture Preflight and reduce state space relative to handler-local branches.
