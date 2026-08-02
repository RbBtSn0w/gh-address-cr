# Data Model: Stacked Pull Request Support

All stack models are immutable inputs, projections, or decisions. None is a new
authoritative persistence aggregate. JSON examples show public machine shapes;
implementation should use frozen value types where practical.

## 1. PullRequestMemberFact

One GitHub-observed PR inside the selected stack.

| Field | Type | Rules |
|-------|------|-------|
| `position` | integer | 1-based, unique, contiguous |
| `pr_number` | string | Positive repository-local PR number |
| `state` | enum | `OPEN`, `CLOSED`, or `MERGED` |
| `is_draft` | boolean | Draft active members block readiness |
| `base_ref_name` | string | Direct base at observation time |
| `head_ref_name` | string | Owning branch at observation time |
| `head_oid` | string | Full commit OID for revision binding |
| `merge_queue_state` | string/null | Bounded normalized queue state |

Raw branch names may appear in direct local machine output and action context,
but never become telemetry attributes or public-safe report fields.

## 2. StackObservationFact

The complete result of one GitHub context read.

| Field | Type | Rules |
|-------|------|-------|
| `schema_version` | string | `stack_observation.v1` |
| `availability` | enum | `absent`, `present`, `unavailable`, `invalid` |
| `repo` | string | Normalized `owner/repo` |
| `selected_pr_number` | string | Exactly one selected member when present |
| `observed_at` | timestamp | UTC RFC 3339 |
| `stack_node_id` | string/null | Required when present; local only |
| `stack_number` | integer/null | Required when present |
| `trunk_ref_name` | string/null | Required when present |
| `reported_size` | integer/null | Equals complete entry count |
| `members` | member list | Complete pagination result |
| `diagnostic_code` | string/null | Required for unavailable/invalid |

### Validation invariants

1. `absent` carries selected PR facts but no stack identity or entries.
2. `present` has at least two entries and complete pagination.
3. Positions equal `1...reported_size`, with no duplicates.
4. The selected PR occurs exactly once.
5. A `MERGED` prefix is allowed; no merged member appears above an unmerged member.
6. Consecutive unmerged members form a base/head chain. After a merged prefix,
   the lowest unmerged member targets the stack trunk.
7. Presence is never inferred from branch relationships alone.

## 3. StackContext

The canonical projection emitted by commands and embedded in action requests.

```json
{
  "schema_version": "stack_context.v1",
  "availability": "present",
  "observed_at": "2026-08-01T12:00:00Z",
  "topology_fingerprint": "sha256:...",
  "stack": {
    "number": 7,
    "trunk_ref_name": "main",
    "size": 3,
    "selected_position": 2,
    "members": []
  }
}
```

The fingerprint hashes canonical repository, stack node, trunk, size, ordered
positions, member PR numbers, states, refs, head OIDs, draft flags, and queue
state. `observed_at` and diagnostics are excluded so identical facts replay to
the same fingerprint.

## 4. RevisionBinding

Eligibility key attached to stacked-member validation/completion evidence.

| Field | Type | Rules |
|-------|------|-------|
| `schema_version` | string | `revision_binding.v1` |
| `pr_number` | string | Matches session/request |
| `head_oid` | string | Matches current selected-member OID |
| `stack_number` | integer | Current stack identity |
| `stack_position` | integer | Current selected position |
| `topology_fingerprint` | string | Matches current context |
| `captured_at` | timestamp | Audit only, not age-based freshness |

```text
unbound -> bound_current -> stale
                     \-> consumed_by_current_gate
```

- Pre-feature stacked evidence without a binding becomes `unbound` and requires
  one fresh validation.
- Same PR, OID, position, stack identity, and fingerprint stays current.
- Any mismatch becomes stale. Reply/resolve facts are evaluated separately.

## 5. StackMemberGateOutcome

One recomputed layer result inside the aggregate projection.

| Field | Type | Rules |
|-------|------|-------|
| `position` | integer | Bottom-up order |
| `pr_number` | string | Member owner |
| `member_state` | enum | Current PR lifecycle |
| `session_status` | enum | `loaded`, `missing`, `invalid` |
| `revision_status` | enum | `current`, `unbound`, `stale`, `not_required` |
| `layer_passed` | boolean | Existing final-gate decision |
| `layer_reason_code` | string/null | Existing member blocker |
| `waiting_on` | string/null | Recovery category |
| `commands` | object | Member-scoped runtime commands |

Merged-prefix entries are reported as already landed and are not converted into
passing active outcomes.

## 6. StackGateProjection

| Field | Type | Rules |
|-------|------|-------|
| `schema_version` | string | `stack_gate_projection.v1` |
| `selected_pr_number` | string | Upper bound of requested segment |
| `topology_fingerprint` | string | Initial coherent observation |
| `check_requirement` | enum/null | `all`, `required`, or omitted |
| `merged_prefix` | member list | Informational, not gated |
| `included_members` | outcome list | Lowest unmerged through selected |
| `excluded_upper_members` | member list | Above selected, not claimed |
| `first_blocked_pr_number` | string/null | Bottom-up first blocker |
| `closing_fingerprint` | string/null | Must match before pass |

## 7. StackGateDecision

| Field | Type | Rules |
|-------|------|-------|
| `status` | enum | `PASSED`, `BLOCKED`, `FAILED` |
| `reason_code` | string/null | Stack code when blocked/failed |
| `waiting_on` | string/null | Status-to-Action category |
| `completion_scope` | string | `stack_segment` |
| `covered_pr_numbers` | string list | Exact active segment; direct machine output |
| `first_blocked_pr_number` | string/null | Recovery target |
| `member_outcomes` | outcome list | All observed outcomes |
| `next_action` | string | Deterministic recovery command |

### Failure precedence

1. Context unavailable or invalid
2. Context changed during evaluation
3. Missing/invalid member session
4. Stale/unbound revision evidence
5. First bottom-up member layer failure
6. Pass

Nested member failures retain the existing final-gate ordering.

## 8. Session Metadata (Non-Authoritative Observation)

```json
{
  "metadata": {
    "pull_request_context": {
      "authority": "github_observation",
      "authoritative": false,
      "stack_context": {},
      "refreshed_at": "2026-08-01T12:00:00Z"
    }
  }
}
```

This cache supports request construction and diagnostics only. Major mutating
actions and gates refresh GitHub context before relying on it. Reports cannot
write back into the observation.
