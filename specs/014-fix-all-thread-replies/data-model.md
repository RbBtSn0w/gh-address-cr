# Data Model: Fix-All Thread Replies

## ReviewThreadQuestion

Represents the reviewer concern that must be answered.

Fields:

- `item_id`: Runtime work item identity for the GitHub review thread.
- `thread_id`: GitHub review thread identity used for reply publication.
- `body`: Reviewer question or comment text when available.
- `path`: File path attached to the review thread.
- `line`: Review line or location when available.
- `state`: Runtime/GitHub state such as open, stale, publish-ready, or resolved.
- `priority_evidence`: Reviewer priority or first-scene severity signal when present.

Validation rules:

- A review-thread fix cannot be considered answered by shared commit evidence
  alone when the thread body asks a distinct question.
- If `body` is missing or unreadable, the workflow must require explicit
  per-thread rationale before accepting a generic shortcut.

## PerThreadReplyEvidence

Represents the item-specific answer for one review thread.

Fields:

- `item_id`: ReviewThreadQuestion identity being answered.
- `request_id`: Issued action request identity.
- `lease_id`: Active fixer lease identity.
- `summary`: One-sentence explanation of what changed for this thread.
- `why`: Rationale explaining why the change answers this review thread.
- `fix_reply`: Optional item-level reply details that override shared fields.

Validation rules:

- `summary` or equivalent item-specific note is required.
- `why` is required for mixed or uncertain multi-thread handling.
- `why` must not be generic boilerplate such as only "fixed in this commit".
- `item_id`, `request_id`, and `lease_id` must match an active runtime claim.

## SharedFixEvidence

Represents evidence that can apply to more than one review thread.

Fields:

- `commit_hash`: Commit containing the fix.
- `files`: Files changed by the fix.
- `validation_commands`: Validation commands and outcomes.
- `severity`: Optional explicit severity evidence.
- `severity_note`: Required when overriding first-scene severity evidence.

Validation rules:

- Shared evidence may satisfy commit, file, validation, and severity fields.
- Shared evidence must not replace PerThreadReplyEvidence for distinct review
  questions.

## HomogeneousFixAllBatch

Represents a narrow `fix-all` shortcut group.

Fields:

- `homogeneous_reason`: Explanation of why all matched threads repeat the same
  low-risk concern.
- `concern_label`: Short label for the repeated issue.
- `items`: ReviewThreadQuestion identities included in the shortcut.
- `shared_evidence`: SharedFixEvidence for the batch.

Validation rules:

- Homogeneity is based on equivalent reviewer concern and equivalent rationale,
  not file matching alone.
- Homogeneous batches must still preserve item identity, active leases,
  validation evidence, reply evidence, and final-gate proof.
- Stale/outdated handling must remain on the explicit stale-thread path unless
  the runtime-mediated stale evidence rules are satisfied.

## PerItemEvidenceInput

Represents structured per-thread answers supplied to a shortcut or batch path.

Fields:

- `agent_id`: Agent submitting the evidence.
- `common`: SharedFixEvidence.
- `items`: List of PerThreadReplyEvidence.
- `resolution`: Must be `fix` for GitHub-thread batch fixes.

Validation rules:

- Every item must be a GitHub review thread with an active fixer lease.
- Duplicate item identities and duplicate leases reject the whole input.
- Missing item-specific rationale rejects mixed or uncertain batches.
- Accepted item evidence must survive through publishing without being replaced
  by generic common text.

## State Transitions

```text
open review thread
  -> classified as fix
  -> fixer lease issued
  -> per-thread reply evidence accepted
  -> publish_ready
  -> reply posted and thread resolved
  -> final-gate verified
```

For generic `fix-all` attempts against mixed or uncertain threads:

```text
open review thread set
  -> fix-all requested without per-item evidence
  -> rejected before evidence acceptance
  -> next action points to per-thread batch skeleton
```
