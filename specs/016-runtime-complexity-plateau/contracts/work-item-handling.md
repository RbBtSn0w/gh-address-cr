# Contract: Work Item Handling Boundary

## Purpose

Define the runtime-owned contract for selecting and executing work item handling without continuing to grow implicit branches inside broad workflow code.

## Boundary Summary Shape

```json
{
  "boundary_id": "github-thread-fix",
  "item_id": "github-thread:THREAD_ID",
  "item_kind": "github_thread",
  "applicability": "matched",
  "required_evidence": ["classification", "commit", "files", "validation", "reply"],
  "completion_criteria": ["accepted_evidence", "published_reply", "resolved_thread", "final_gate"],
  "terminal_failure_reasons": ["UNSUPPORTED_WORK_ITEM", "BOUNDARY_CONFLICT", "MISSING_REQUIRED_EVIDENCE"],
  "next_action": "issue_action_request"
}
```

## Required Behavior

- Runtime must evaluate work item handling boundaries deterministically.
- Exactly one boundary owns a work item after priority resolution.
- Boundary conflicts without deterministic priority fail loudly with `BOUNDARY_CONFLICT`.
- Unsupported items fail loudly with `UNSUPPORTED_WORK_ITEM` and preserve session state.
- A boundary cannot publish, resolve, or complete an item without required runtime evidence.
- The first implementation slice must migrate at least one high-value work item type and prove parity for user-visible behavior.

## Compatibility

Existing public commands and machine-readable summaries remain compatible. New boundary summaries are additive and must be documented before agents depend on them.
