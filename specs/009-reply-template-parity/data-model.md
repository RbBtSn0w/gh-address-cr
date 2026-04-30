# Data Model: Reply Template Parity

## ReplyTemplateContract

Represents the public Markdown structure used for GitHub review-thread replies.

Fields:
- `mode`: `fix`, `clarify`, or `defer`
- `severity`: P1/P2/P3 for fix mode
- `commit_hash`: fix mode commit identifier
- `files`: fix mode changed files
- `validation`: commands and result text
- `rationale`: clarify/defer rationale from accepted response evidence

Validation:
- Fix mode requires commit hash, file list, validation command, and validation result.
- Clarify mode requires non-empty rationale.
- Defer mode requires non-empty reason.
- Unknown severity normalizes to P2 before rendering.

## ActionResponse Evidence

Existing accepted response payload used to populate reply templates.

Fields used:
- `resolution`
- `reply_markdown`
- `fix_reply`
- `files`
- `validation_commands`

State transitions:
- `publish_ready` items render a reply body before any GitHub side effect.
- Invalid or incomplete evidence blocks publish and preserves the existing failure behavior.
