# Contract: GitHub Reply Template Rendering

## Fix

Input:
- `resolution`: `fix`
- `fix_reply.commit_hash`
- `fix_reply.files` or top-level `files`
- validation command/result evidence
- severity from `fix_reply.severity`, item severity, or default P2

Output:
- Starts with `Fixed in `<commit_hash>`.`
- Includes `Severity: `<P1|P2|P3>``
- Includes `What I changed:`
- Includes `Why this addresses the CR:`
- Includes `Validation:`
- Uses severity-specific risk/closing wording matching the packaged skill templates.

## Clarify

Input:
- `resolution`: `clarify`
- `reply_markdown`: non-empty rationale

Output:
- Starts with `Thanks for the review.`
- Includes `Analysis & Rationale:`
- Includes the rationale as a bullet
- Includes `Decision:` and `No code changes were made for this specific comment.`

## Defer

Input:
- `resolution`: `defer`
- `reply_markdown`: non-empty defer reason

Output:
- Starts with `Thanks, this is valid feedback.`
- Includes `Decision:`
- Includes the reason in the defer decision line
- Includes `Follow-up plan:` with issue/PR tracking, exact scope, and risk bullets.

## Failure Behavior

Missing required evidence returns `MISSING_PUBLISH_REPLY` or the existing fix-specific reason before posting a reply or resolving a thread.
