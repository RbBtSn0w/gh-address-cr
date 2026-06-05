# Quickstart: Runtime Complexity Plateau

## Prerequisites

- Python 3.10+
- Development install available from the repository root
- GitHub CLI available for live PR workflows when running end-to-end checks

```bash
pip install -e .
```

## Focused Validation Scenarios

### 1. Work Item Handling Boundary

Validate that the first migrated work item type is handled through an explicit boundary and preserves user-visible parity.

Expected proof:

- Boundary applicability is deterministic.
- Conflict or unsupported matching fails loudly.
- Required evidence is unchanged or explicitly strengthened.
- Unmigrated work item types preserve existing public behavior.

Suggested checks:

```bash
python3 -m unittest tests.test_agent_protocol tests.test_control_plane_workflow
```

### 2. Lease Recovery

Validate that expired and stale lease cases return actionable recovery outcomes.

Expected proof:

- Recoverable expiration returns `renew` or `reclaim`.
- Stale request context returns `refresh_state`.
- Completed or transferred work returns `stop` or `already_completed`.
- Stale submissions never overwrite newer runtime truth.

Suggested checks:

```bash
python3 -m unittest tests.test_claim_leases tests.test_lease_scheduling tests.test_issue78_agent_experience
```

### 3. Telemetry Runtime Boundary

Validate telemetry fail-open behavior and the 250ms normal-path budget.

Expected proof:

- Core review/final-gate flows continue when telemetry is unavailable.
- Telemetry-specific commands fail loudly on malformed or unsafe input.
- Coverage labels remain truthful.
- Sensitive telemetry does not enter shareable reports.

Suggested checks:

```bash
python3 -m unittest tests.test_telemetry_acceptance_matrix tests.core.test_telemetry tests.test_final_gate
```

### 4. Logic Validation Signals

Validate that evidence gaps and state contradictions produce explainable signals without blocking low-confidence advisory cases.

Expected proof:

- Missing required evidence produces a blocking signal.
- State contradiction produces a blocking signal.
- Low-confidence advisory signal does not block normal completion.
- Signals do not mutate review item state by themselves.

Suggested checks:

```bash
python3 -m unittest tests.test_agent_protocol tests.test_final_gate
```

### 5. Skill Guidance And CLI Smoke

Validate that agent-facing guidance remains thin and the CLI still loads.

```bash
python3 -m unittest tests.test_skill_docs
python3 -m gh_address_cr --help
```

## Standard Completion Checks

Run the repository completion checks before claiming implementation complete:

```bash
ruff check src tests
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
```

## Expected End State

- The active PR workflow keeps existing public command behavior.
- Each delivery slice has independent tests and user-visible evidence.
- Lease recovery gives agents a safe next action instead of a retry loop.
- Telemetry degradation is visible but does not block core review completion.
- Logic validation improves gate quality without becoming completion authority.
