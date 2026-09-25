# Contract: Lease Entry Points

Every call site under `src/` that creates a lease, directly or through
`issue_action_request`, is listed here with its class and the rule that protects it.
`tests/contract/test_lease_state_machine_contract.py` discovers call sites by scanning the
source and fails when one is missing from this table, or listed but no longer present.

Adding a call site is therefore a two-line change: the code, and a row here. That is the
point. The defects fixed under #273 were each found at an entry point nobody had listed.

## Classes

| Class | What the caller holds after the claim | On failure after the claim |
|---|---|---|
| `one-shot` | Nothing: the command claims, builds the response and submits in one go | MUST release every lease it created (FR-001) |
| `two-step` | The request path and skeleton, to correct and resubmit | Keeps the lease |
| `batch-claim` | The batch skeleton | Rolls the whole batch back if a later claim in it fails; keeps the leases once the skeleton is handed over |
| `orchestrated` | A worker packet, plus the orchestrator's shadow lease | MUST release the core lease if granting the shadow lease fails (FR-001) |
| `creator` | Not a call site: the function that mints leases | n/a |
| `unreferenced` | Nothing calls it from `src/`; tests only | Unprotected, and must stay unreachable from production. If a caller is added it needs a class |

## Entry points

`Protection` names how FR-001 is satisfied for that row.

| Location | Function | Class | Protection |
|---|---|---|---|
| `core/agent_protocol.py` | `commit_claim` | `creator` | Runs the existing claim policy inside the SQLite writer reservation; re-entry returns the holder's own lease instead of a second one (FR-003) |
| `core/agent_protocol.py` | `claimed_fixer_lease` | `creator` | The rollback wrapper; releases only a lease it created (FR-002) |
| `core/agent_batch.py` | `commit_batch` | `creator` | Runs batch selection and claim policy inside one SQLite writer reservation |
| `core/agent_batch.py` | `_lease_new_github_thread` | `creator` | Pure in-transaction claim helper; post-commit failure compensates only `created` leases |
| `commands/agent.py` | `handle_agent_next` | `two-step` | Exempt by design |
| `core/leases.py` | `reclaim_lease` | `unreferenced` | None needed while unreferenced. A thin `expire_leases` + `claim_lease` wrapper, redundant since `claim_lease` already expires first |
| `core/workflow.py` | `fast_fix_item` | `one-shot` | `claimed_fixer_lease` |
| `core/workflow.py` | `decline_item` | `one-shot` | `claimed_fixer_lease` |
| `core/workflow_matching.py` | `_submit_decline_thread` | `one-shot` | `claimed_fixer_lease` |
| `core/workflow_matching.py` | `_build_fast_fix_batch_response` | `one-shot` | `_process_fast_fix_matches` releases the chunk's leases when writing or submitting the batch raises a `WorkflowError`, skipping any lease id that existed before the chunk's claims |
| `orchestrator/harness.py` | `handle_step` | `orchestrated` | Releases the core lease when the shadow grant raises `LeaseConflictError`. The step names no item, so the lease is always its own |

## Violations found and fixed under this spec

Both were found by listing every entry point against FR-001, not by a report, and each was
reproduced by a failing test before its fix (`tests/contract/test_claim_rollback_contract.py`).

1. **`_build_fast_fix_batch_response`**, reached from `agent resolve --commit --files`. It
   claims one lease per matched thread, then submits them as one batch. A rejected submit left
   every claimed lease `active`, and the command is one-shot, so the caller held no skeleton
   to retry with: two matched threads were both locked. Covered by
   `BatchFastFixRollbackTest`.
2. **`handle_step`**, reached from `agent orchestrate step`. It issues the core lease, then
   grants the orchestrator's shadow lease. With two items on one file the shadow grant raised
   `LeaseConflictError`; the step answered `LEASE_CONFLICT` / `RETRY` and left the second
   item's core lease `active` with no shadow, so retrying could not succeed. Covered by
   `OrchestratorStepRollbackTest`.

## Boundary: what this table does not cover

- The shadow lease's own lifecycle (`grant_lease`, `release_lease`,
  `validate_lease_for_submission`) is described in `lease-transitions.md`; it creates no
  core lease.
- Tests construct leases directly through `claim_lease`. The scan covers `src/` only.
