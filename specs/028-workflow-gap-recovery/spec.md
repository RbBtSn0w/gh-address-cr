# Feature Specification: Workflow Gap Recovery

**Feature Branch**: `028-workflow-gap-recovery`  
**Created**: 2026-07-07  
**Status**: Draft  
**Input**: User description: "Use `speckit-specify` to plan a complete resolution of the current issues 195-200."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Recover blocked final-gate sessions (Priority: P1)

As an agent closing a PR session, I need `final-gate` to either provide a valid recovery path for historical closed-thread evidence gaps or classify them in a way that does not deadlock completion, so that I can finish PR handling without inventing unsupported manual work.

**Why this priority**: Issues `#195`, `#196`, and `#197` all show the current highest-severity workflow failure: the system reports missing reply evidence, while the runtime simultaneously makes the affected items impossible to claim or repair.

**Independent Test**: Can be fully tested by reproducing a session with closed GitHub threads that lack reply evidence and confirming that `final-gate` returns a supported next action or a non-blocking classification instead of an unrecoverable loop.

**Acceptance Scenarios**:

1. **Given** a PR session with closed GitHub threads that still lack durable reply evidence, **When** the agent runs `final-gate`, **Then** the result identifies a supported recovery action or explicitly excludes the unrecoverable historical items from blocking completion.
2. **Given** a duplicate or homogeneous stale-thread situation where one thread was closed upstream, **When** the agent tries to repair the affected item, **Then** the runtime can target the specific blocked item or explain why the item no longer needs repair.
3. **Given** a `final-gate` blocker caused by reply evidence mismatch, **When** the agent follows the prescribed runtime action, **Then** the blocker can be cleared without relying on hidden state or manual artifact edits.

---

### User Story 2 - Unblock item handling after lease or claim conflicts (Priority: P2)

As an agent moving between batch and item-by-item handling, I need the system to explain lease ownership and provide a safe recovery path, so that work claimed by one workflow does not silently block another workflow.

**Why this priority**: Issue `#198` blocks normal operator recovery and creates misleading `NO_ELIGIBLE_ITEM` failures even when work exists but is locked under an active batch lease.

**Independent Test**: Can be fully tested by claiming items through a batch flow and then attempting an individual resolve flow, confirming the runtime exposes the active lock owner and a deterministic reclaim or release action.

**Acceptance Scenarios**:

1. **Given** a work item already locked by an active batch lease, **When** an agent attempts an individual resolve action, **Then** the runtime reports that the item is lease-locked and points to the supported recovery path.
2. **Given** an item was batch-claimed but the agent now needs to handle it individually, **When** the agent runs the recommended recovery step, **Then** the lease can be released, reclaimed, or converted without corrupting session state.

---

### User Story 3 - Treat environment-specific diagnostics honestly (Priority: P3)

As an agent running local development loops, I need environment-sensitive diagnostics for telemetry and GitHub permissions, so that expected local limitations are surfaced as actionable advice instead of misleading abnormal blockers.

**Why this priority**: Issues `#199` and `#200` show lower-severity but high-friction failures where expected local-runtime constraints are surfaced with the wrong severity or with no clear synchronization guidance.

**Independent Test**: Can be fully tested by running a local PR loop without hosted CI telemetry and by invoking a GitHub action through the wrapped CLI with granted runner permissions, confirming the output distinguishes advisory conditions from true blockers and provides a next step.

**Acceptance Scenarios**:

1. **Given** a local run with no active CI-host telemetry, **When** the agent runs `final-gate`, **Then** runtime-only telemetry is reported as advisory information rather than an abnormal condition that demands narrative justification.
2. **Given** a runtime where the agent runner has GitHub permissions but the wrapped CLI does not, **When** a GitHub side-effect command is attempted, **Then** the failure explains the permission-source mismatch and the supported synchronization or configuration action.

### Edge Cases

- A closed GitHub thread was resolved outside the current session, and no reply URL exists in local evidence.
- A stale recovery command matches files or reasons shared by multiple items, but only one specific blocked item needs intervention.
- A lease exists in orchestration state but no longer corresponds to valid runtime state after a resume or crash recovery.
- A local run has partial telemetry imported from one source and runtime-only telemetry from another, requiring mixed-severity reporting instead of a binary healthy/unhealthy label.
- A GitHub permission denial is caused by a true missing permission rather than a sync mismatch, and the diagnostic must not misclassify it as recoverable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST detect when `final-gate` is blocked by historical or closed-thread reply-evidence gaps and return a deterministic supported recovery path or a documented non-blocking classification.
- **FR-002**: The system MUST allow blocked closed-thread evidence cases to be targeted by a supported runtime action when evidence repair is still required.
- **FR-003**: The system MUST preserve the distinction between claimable active review items and historical closed items while still allowing `final-gate` to reason about both consistently.
- **FR-004**: The system MUST provide machine-readable reason codes and next actions that distinguish `missing_reply_evidence`, `closed_historical_item`, `lease_locked_item`, `permission_mismatch`, and `advisory_runtime_only_telemetry` cases.
- **FR-005**: The system MUST explain when an item-level action is blocked by an active lease, including which workflow currently owns the lease and what supported recovery action is available.
- **FR-006**: The system MUST provide a safe recovery path for agents that need to move from batch-claimed work to individual item handling without mutating authoritative session state outside the runtime.
- **FR-007**: The system MUST support item-scoped repair flows for stale or homogeneous matching cases where file-based or reason-based matching alone is insufficient to recover the exact blocked item.
- **FR-008**: The system MUST classify runtime-only telemetry in local development loops as advisory unless another verified telemetry defect makes the run materially incomplete or unsafe.
- **FR-009**: The system MUST differentiate a local-environment advisory from a true telemetry ingestion, attribution, or safety failure.
- **FR-010**: The system MUST detect when wrapped GitHub CLI permissions are out of sync with the agent runner's granted permissions and return a clear remediation path.
- **FR-011**: The system MUST continue to fail loudly for unsupported or unsafe GitHub actions, malformed recovery inputs, or ambiguous item-targeting requests.
- **FR-012**: Public CLI, machine-summary, and packaged-skill guidance MUST be updated together whenever the supported recovery path, severity model, or permission guidance changes.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Yes. This feature changes deterministic runtime ownership for `final-gate` truth evaluation, lease conflict reporting, telemetry severity projection, and GitHub permission diagnostics. Authoritative state remains in runtime code and session artifacts, not in Markdown notes.
- **Runtime Kernel Model**: External facts include GitHub thread status, stored reply evidence, active leases, session history, telemetry coverage inputs, runtime environment metadata, and wrapped GitHub permission responses. Projections include final-gate blocker classes, lease ownership state, permission mismatch state, and advisory-vs-blocking telemetry severity. Policy decisions are expressed through explicit blocker classification and Status-to-Action mapping. Side effects stay within supported runtime commands that claim, release, publish, resolve, or inspect state. Artifacts remain evidence only. Contract tests must cover replay of blocked sessions, closed historical items, lease conflicts, advisory telemetry runs, and permission mismatch diagnostics.
- **CLI / Agent Contract Impact**: Yes. The feature may add or refine machine-readable reason codes, next actions, and runtime action guidance, but it MUST preserve the stable high-level CLI contract and keep the Status-to-Action Map deterministic.
- **Evidence Requirements**: Completion evidence must still prove reply, resolve, and final-gate truth for claimable review items. Historical closed-thread handling must record why the item is recoverable, excluded, or already satisfied. Lease recovery and permission diagnostics must emit machine-readable evidence of the blocking condition and the chosen repair action.
- **Packaged Skill Boundary**: Runtime classification, lease logic, final-gate truth, and machine summaries belong in repo-root code and tests. Packaged-skill changes are limited to guidance that explains the supported recovery actions and diagnostic severity without embedding runtime logic.
- **External Intake Replaceability**: Preserved. The feature does not couple intake to a specific review producer; it only hardens downstream resolution and recovery behavior after findings or threads already exist.
- **Telemetry Evidence Boundary**: Telemetry remains observed workflow evidence only. The feature changes severity interpretation for local runtime-only coverage but must retain source attribution, coverage labels, safe metadata handling, deterministic imports, duplicate handling, and fail-open review completion for telemetry absence.
- **Architecture Plateau Risk**: This feature reduces ambiguity by collapsing several dead-end blocker paths into explicit blocker classes and recovery actions. It must not add hidden fallback branches, artifact-authored truth, or ad hoc exceptions for individual issue reproductions.
- **Fail-Fast Behavior**: Unsupported combinations of targeting modes, malformed item identifiers, inconsistent lease ownership, unsafe GitHub side effects, and ambiguous permission or telemetry states must fail loudly with a reason code rather than silently degrade.

### Key Entities *(include if feature involves data)*

- **FinalGateBlocker**: A projected blocker state that represents why a PR session cannot complete, including blocker class, evidence status, recoverability, and supported next action.
- **ReplyEvidenceRecord**: Durable evidence associated with a review item, including whether a reply URL exists, whether the related GitHub thread is open or closed, and whether the evidence came from the current authenticated actor.
- **LeaseRecoveryState**: Authoritative runtime projection of work-item claim ownership and recovery status, including current owner workflow, expiry or releasability, recovery outcome, and whether an item can transition to a different handling mode.
- **EnvironmentDiagnostic**: Runtime classification of non-review blockers such as telemetry coverage context and GitHub permission alignment, including severity, cause, and recommended operator action.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In reproduced sessions matching issues `#195`-`#197`, 100% of `final-gate` blockers caused by closed-thread evidence gaps end in either a successful supported recovery path or an explicit non-blocking classification, with no dead-end loop between gate output and available commands.
- **SC-002**: In reproduced lease-conflict sessions matching issue `#198`, agents can identify the blocking lease owner and supported recovery action within one command response, without requiring source-code inspection or manual artifact edits.
- **SC-003**: In local development runs matching issue `#199`, runtime-only telemetry is reported as advisory in 100% of cases where no other verified telemetry defect exists.
- **SC-004**: In reproduced permission-mismatch runs matching issue `#200`, the first failing command response identifies whether the problem is a permission-sync mismatch or a true missing permission and provides a concrete next step.
- **SC-005**: Regression coverage includes automated acceptance or contract tests for all six issue classes before the feature is considered ready for implementation.

## Assumptions

- The six issues represent one coherent workflow-hardening feature rather than six unrelated products, because they all sit on the runtime closure and operator recovery boundary.
- The first implementation slice will prioritize deterministic recovery and diagnostics over broad UX polish or new command families.
- Existing public commands remain the preferred surface; if new sub-actions are needed, they will fit within the current runtime/agent protocol rather than bypass it.
- Local development loops without hosted CI telemetry are a first-class supported environment and should not be treated as abnormal by default.
