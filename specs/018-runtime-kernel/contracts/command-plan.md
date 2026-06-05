# Contract: Runtime Kernel Command Plan

## Scope

This contract defines the side-effect planning boundary for the runtime-kernel slice. Command planning is deterministic and non-executing.

## Planned Command Kinds

- `reply_thread`: plan a GitHub review-thread reply.
- `resolve_thread`: plan a GitHub review-thread resolve.
- `retry_command`: plan a retry for a failed side-effect command.
- `run_final_gate`: plan final-gate evaluation when the policy decision is final-gate eligible.

## Idempotency

Each planned command must include:

- `command_id`
- `command_kind`
- `item_id` when item-scoped
- `idempotency_key`
- `reason_code`
- `payload`

Item-scoped command payloads must include:

- `item_id`
- `thread_id`
- `source_fact_id`
- `source_observed_at`

`command_id` and `idempotency_key` must be stable for the same projection, decision, and source generation. Regenerating a plan must not create duplicate logical commands.

## Completion Evidence

Planned commands are not completion evidence. Completion evidence requires a recorded `command_executed` fact with:

- matching `command_id`
- matching source generation
- `status` equal to `succeeded`
- durable evidence such as a non-empty, non-blank `result_url` when the command requires external proof

Unknown, stale-generation, failed, or missing execution results keep the related work unresolved.
Failed execution results may produce `retry_command` plans that reference the
failed command identity and original command kind without counting as
completion evidence.
Successful `retry_command` execution results may satisfy the original required
command kind only when the retry references the failed current-generation
command identity, the original command kind, the same source generation, and
the required durable evidence.

## Side-Effect Boundary

Command planning must not:

- post GitHub replies
- resolve GitHub threads
- write artifacts
- mutate `session.json`
- archive or delete workspaces

Those operations belong to an executor or existing runtime command path outside this kernel slice.
