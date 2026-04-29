# Contract: Multi-Agent Protocol

## Scope

This contract defines how the deterministic control plane coordinates multiple
AI agents. Agents consume requests and return evidence. The CLI owns leases,
state transitions, GitHub side effects, and final-gate evaluation.

## Roles

| Role | Kind | Responsibility |
|------|------|----------------|
| `coordinator` | deterministic CLI | Select items, issue leases, merge accepted evidence |
| `review_producer` | AI agent or adapter | Produce normalized findings |
| `triage` | AI agent | Classify a claimed item |
| `fixer` | AI agent | Modify files and return fix evidence |
| `verifier` | AI agent or deterministic check | Validate evidence and test results |
| `publisher` | deterministic CLI | Post replies and resolve GitHub threads |
| `gatekeeper` | deterministic CLI | Run final-gate and block completion |

## CapabilityManifest

Agents and adapters are eligible for work only through a declared capability
manifest.

Minimum JSON-compatible shape:

```json
{
  "schema_version": "1.0",
  "agent_id": "codex-fixer-1",
  "roles": ["fixer", "verifier"],
  "actions": ["fix", "verify"],
  "input_formats": ["action_request.v1"],
  "output_formats": ["action_response.v1"],
  "protocol_versions": ["1.0"],
  "constraints": {
    "max_parallel_claims": 2
  }
}
```

Rules:

- The coordinator must not issue a role that is absent from the manifest.
- The coordinator must not include an action that is absent from the manifest.
- The coordinator must not issue more active leases than allowed by
  `constraints.max_parallel_claims`.
- Missing or malformed manifests are not eligible for mutating work.

## ActionRequest

Minimum JSON-compatible shape:

```json
{
  "schema_version": "1.0",
  "request_id": "req_123",
  "session_id": "session_123",
  "lease_id": "lease_123",
  "agent_role": "fixer",
  "item": {
    "item_id": "github-thread:abc",
    "item_kind": "github_thread",
    "title": "Missing validation",
    "body": "The input is not checked before use.",
    "path": "src/example.py",
    "line": 42
  },
  "allowed_actions": ["fix", "clarify", "defer", "reject"],
  "required_evidence": ["note", "files", "validation_commands"],
  "forbidden_actions": ["post_github_reply", "resolve_github_thread"],
  "resume_command": "gh-address-cr agent submit owner/repo 123 --input response.json"
}
```

Rules:

- `request_id`, `session_id`, `lease_id`, `agent_role`, `item`,
  `allowed_actions`, and `required_evidence` are required.
- Mutating requests must include an active lease.
- `forbidden_actions` must include direct GitHub reply and resolve operations
  for AI-agent roles.
- Skill-local shims must not appear as the authoritative runtime in
  `resume_command`; they may only be compatibility fallbacks.

## Pre-Fix Classification Gate

The coordinator must record classification evidence before issuing a mutating
fixer request or accepting code-modifying evidence.

Rules:

- Every item must be classified as `fix`, `clarify`, `defer`, or `reject`.
- Mutating fixer requests require a prior `classification_recorded` evidence
  record for the same item.
- Missing or stale classification evidence blocks fixer leases, appends
  `request_rejected` or `response_rejected` evidence, and does not mutate
  files, terminal item state, or GitHub state.
- Classifications that produce `clarify`, `defer`, or `reject` are terminal
  handling decisions unless a later verifier or maintainer record reopens the
  item with explicit rationale.

## ActionResponse

Minimum JSON-compatible shape for a fix:

```json
{
  "schema_version": "1.0",
  "request_id": "req_123",
  "lease_id": "lease_123",
  "agent_id": "codex-fixer-1",
  "resolution": "fix",
  "note": "Fixed input validation and verified with unit tests.",
  "files": ["src/example.py", "tests/test_example.py"],
  "validation_commands": [
    {
      "command": "python3 -m unittest discover -s tests",
      "result": "passed"
    }
  ],
  "fix_reply": {
    "summary": "Fixed input validation.",
    "commit_hash": "abc123",
    "files": ["src/example.py", "tests/test_example.py"]
  }
}
```

Minimum JSON-compatible shape for clarify/defer/reject:

```json
{
  "schema_version": "1.0",
  "request_id": "req_456",
  "lease_id": "lease_456",
  "agent_id": "codex-triage-1",
  "resolution": "clarify",
  "note": "Existing behavior is intentional and covered by tests.",
  "reply_markdown": "This is intentional because ...",
  "validation_commands": [
    {
      "command": "python3 -m unittest tests.test_example",
      "result": "passed"
    }
  ]
}
```

Rules:

- `resolution` must be one of `fix`, `clarify`, `defer`, or `reject`.
- `lease_id` must match an active lease.
- `fix` requires changed files and validation evidence.
- GitHub-thread `fix` requires `fix_reply`.
- `clarify`, `defer`, and `reject` require `reply_markdown`.
- Responses that claim direct GitHub side effects are invalid.

## Lease Validation

The control plane must reject an `ActionResponse` when:

- the lease is missing
- the lease is expired
- the lease belongs to another item
- the lease belongs to another agent and has not been transferred
- the response hash does not match the issued request context
- required evidence is missing
- a code-modifying response lacks prior classification evidence

## Item Independence

Parallel mutating claims are allowed only when all of these are true:

- work item IDs are distinct
- no active lease already owns the same remote thread id
- known file-path conflict keys do not overlap
- the requested roles are compatible with the side effects they may trigger

Read-only triage or verifier work may share conflict keys only when it cannot
mutate session state or publish GitHub side effects.

## Multi-Agent Coordination

Parallelism is item-scoped. Multiple agents may work at once only when their
leases target different items or non-conflicting read-only roles.

The coordinator may issue:

- multiple fixer requests for independent items
- one verifier request per submitted fixer response
- one publisher action after evidence is accepted
- one gatekeeper action after all blocking items are terminal

The publisher and gatekeeper roles are deterministic CLI roles, not AI-agent
roles.

When a verifier rejects fixer evidence, the coordinator must append a
`verification_rejected` evidence record, return the item to a blocked or open
state, and avoid GitHub reply or resolve side effects.

## Final Gate Scope

The gatekeeper must block completion unless the current PR session proves:

- zero unresolved GitHub review threads
- zero current-login pending reviews
- zero session blocking items
- no terminal GitHub thread missing durable reply evidence
- required validation evidence for terminal local findings and accepted fixes

## Transient GitHub Failure Handling

GitHub API rate limits and transient failures must be represented as retry,
scheduled-backoff, or blocking workflow evidence. After bounded retry/backoff
exhaustion, the item must block with a resume action. The publisher must
preserve idempotency keys so a retry cannot duplicate a previously successful
reply or resolve operation.
