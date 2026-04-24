# Contract: CLI Control Plane

## Existing Public Commands

These commands remain stable:

```text
gh-address-cr review <owner/repo> <pr_number>
gh-address-cr threads <owner/repo> <pr_number>
gh-address-cr findings <owner/repo> <pr_number> --input <path>|-
gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>
gh-address-cr review-to-findings <owner/repo> <pr_number> --input -
gh-address-cr final-gate <owner/repo> <pr_number>
```

`review` remains the public main entrypoint.

Compatibility during migration:

```text
python3 -m gh_address_cr review <owner/repo> <pr_number>
python3 gh-address-cr/scripts/cli.py review <owner/repo> <pr_number>
```

The skill-local `scripts/cli.py` path is a shim only. It must delegate to the
installed runtime or fail loudly before mutating session state.

## Runtime Compatibility Preflight

Before a skill adapter or compatibility shim delegates to the runtime, it must
compare:

- skill-owned runtime requirements file
- required runtime version
- installed runtime version
- required protocol version
- runtime supported protocol versions
- required public entrypoints

Failure output must be machine-readable and must occur before session mutation.

## Runtime Tool Preflight

Before any command performs PR inspection, GitHub review-state lookup, reply
posting, or thread resolution, the runtime must verify that `gh` is available
and authenticated. Missing or unusable `gh` must produce a machine-readable
failure before session mutation or GitHub side effects.

Required machine reason codes:

- `GH_NOT_FOUND`: `gh` is absent from `PATH`
- `GH_AUTH_FAILED`: `gh` is installed but not authenticated

Both failures exit non-zero before creating or modifying the PR session.

## Proposed Advanced/Internal Protocol Commands

These commands are implementation-planning contracts. They remain
advanced/internal until implemented, tested, and documented as public surface.

```text
gh-address-cr agent manifest
gh-address-cr agent next <owner/repo> <pr_number> --role <role>
gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>
gh-address-cr agent leases <owner/repo> <pr_number>
gh-address-cr agent reclaim <owner/repo> <pr_number>
```

## `agent manifest`

Purpose: emit the runtime-supported capability manifest used to decide role,
action, format, protocol-version, and maximum parallel-claim eligibility before
leases are issued.

Output:

```json
{
  "status": "MANIFEST_READY",
  "schema_version": "1.0",
  "runtime_version": "1.0.0",
  "supported_protocol_versions": ["1.0"],
  "roles": [
    "coordinator",
    "review_producer",
    "triage",
    "fixer",
    "verifier",
    "publisher",
    "gatekeeper"
  ],
  "actions": [
    "review",
    "produce_findings",
    "triage",
    "fix",
    "clarify",
    "defer",
    "reject",
    "verify",
    "publish",
    "gate"
  ],
  "input_formats": ["action_request.v1"],
  "output_formats": ["action_response.v1"],
  "constraints": {
    "max_parallel_claims": 2
  }
}
```

Exit codes:

- `0`: manifest emitted
- `2`: manifest generation failed
- `5`: runtime or protocol compatibility failure

## `agent next`

Purpose: issue an `ActionRequest` and claim lease for the next eligible item.

Output:

```json
{
  "status": "ACTION_REQUESTED",
  "repo": "owner/repo",
  "pr_number": "123",
  "request_path": ".../action-request-req_123.json",
  "lease_id": "lease_123",
  "item_id": "github-thread:abc",
  "next_action": "Pass request_path to an agent with the fixer role."
}
```

Exit codes:

- `0`: request issued
- `4`: no eligible item for the requested role
- `5`: blocked by invalid session state, manifest mismatch, or conflict keys

## `agent submit`

Purpose: validate an `ActionResponse`, append evidence, and either accept or
reject the response.

Output:

```json
{
  "status": "ACTION_ACCEPTED",
  "repo": "owner/repo",
  "pr_number": "123",
  "lease_id": "lease_123",
  "item_id": "github-thread:abc",
  "evidence_record_id": "ev_123",
  "next_action": "Run review again to publish accepted evidence."
}
```

Exit codes:

- `0`: response accepted
- `2`: malformed response
- `5`: stale lease, missing evidence, verifier rejection, or unsafe side effect
  claim

When a verifier rejects submitted fixer evidence, the runtime emits
`VERIFICATION_REJECTED`, appends `verification_rejected` evidence, returns the
item to open/blocked state, and performs no GitHub side-effect attempts.

## `agent leases`

Purpose: inspect active and recently closed leases for diagnostics.

Output includes:

- lease id
- item id
- agent id
- role
- status
- created and expiry timestamps
- conflict keys

## `agent reclaim`

Purpose: expire stale leases and return affected items to an eligible state.

Rules:

- Must not delete accepted evidence
- Must append a lease expiration evidence record
- Must not post GitHub side effects

## Compatibility Rules

- Existing machine summary fields remain stable unless versioned:
  `status`, `repo`, `pr_number`, `item_id`, `item_kind`, `counts`,
  `artifact_path`, `reason_code`, `waiting_on`, `next_action`, `exit_code`.
- New protocol commands must emit JSON by default.
- `--human` may be added for diagnostics, but agents must consume JSON.
- `scripts/cli.py` remains usable from the repo root only as a compatibility
  shim.
- Skill-owned docs must use skill-root-relative paths and describe the runtime
  as an external prerequisite.
- A missing or incompatible runtime must fail before session mutation.

## Final Gate Compatibility

The separated runtime must preserve final-gate semantics from the current skill:

- zero unresolved GitHub review threads
- zero current-login pending reviews
- zero session blocking items
- no terminal GitHub thread missing durable reply evidence
- machine-readable failure reason and next action when any check fails
