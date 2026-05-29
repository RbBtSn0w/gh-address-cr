# Contract: Rich Reply Protocol

## fix_reply Object
The `fix_reply` object in an `ActionResponse` MUST follow this enhanced structure:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `commit_hash` | string | Yes | The full or short SHA of the fixing commit. |
| `files` | string/list | Yes | Comma-separated string or list of changed files. |
| `summary` | string | Yes | 1-sentence summary of the fix. |
| `severity` | string | No | One of: `P0`, `P1`, `P2`, `P3`, `P4`. |
| `why` | string | No | Multi-paragraph technical rationale. Supports markdown. |
| `test_command` | string | No | Command used for verification. |
| `test_result` | string | No | Human-readable result of verification. |

## Validation Rules
1. If `severity` is `P0` or `P1`, the `why` field MUST contain at least 150 characters or two distinct paragraphs.
2. The `severity` field MUST NOT contain values other than `P0`, `P1`, `P2`, `P3`, `P4`.
3. The `why` field MUST NOT use generic boilerplate like "Fixed as requested."
