# Data Model: Action Request Friction Repair

## ActionRequest

Runtime-owned work assignment issued for one item under an active lease.

Fields relevant to this feature:

- `schema_version`
- `request_id`
- `session_id`
- `lease_id`
- `agent_role`
- `item`
- `allowed_actions`
- `required_evidence`
- `repository_context.repo`
- `repository_context.pr_number`
- `resume_command`
- `forbidden_actions`

Validation rules:

- `request_id`, `lease_id`, `agent_role`, `item`, and repository identity are required for runtime helper mode.
- Repository identity may be read from `repository_context` or from legacy top-level `repo` and `pr_number`.
- Requests that forbid direct GitHub side effects must not be converted into direct reply or resolve operations by the helper.

## LegacyLoopRequest

Older manual continuation artifact for loop-level workflows.

Fields relevant to this feature:

- `repo`
- `pr_number`
- `item`
- optional command-specific continuation fields

Validation rules:

- Top-level `repo`, `pr_number`, and `item` are required for legacy helper mode.
- Legacy output may remain a loop action payload when no structured request and lease identity are present.

## ActionResponse

Agent-produced evidence submitted back to the runtime for one request and lease.

Fields relevant to this feature:

- `schema_version`
- `request_id`
- `lease_id`
- `agent_id`
- `resolution`
- `note`
- `files`
- `validation_commands`
- `reply_markdown`
- `fix_reply`

Validation rules:

- Fix responses require `files` and validation evidence.
- GitHub-thread fix responses require `fix_reply`.
- Clarify, defer, and reject responses require `reply_markdown` when required by the runtime.
- Response identity must match the issued request and active lease.

## BatchActionResponse

Grouped response payload for multiple GitHub-thread fixes.

Fields relevant to this feature:

- `schema_version`
- `agent_id`
- `resolution`
- `common.files`
- `common.validation_commands`
- `common.fix_reply`
- `items[].request_id`
- `items[].lease_id`
- `items[].item_id`
- `items[].summary`
- `items[].why`

Validation rules:

- Only GitHub-thread fix responses are supported.
- Each item must carry its own request and lease identity.
- Duplicate leases, duplicate items, stale leases, local findings, and unsupported resolutions reject the batch without partial acceptance.

## ClassificationEvidence

Triage-phase evidence that records whether a work item should be fixed, clarified, deferred, or rejected.

Fields relevant to this feature:

- `classification`
- `note`
- `record_id`
- `event_type`

Validation rules:

- Mutating fixer requests require prior classification evidence.
- Missing classification is not the same as missing fixer resolution.
