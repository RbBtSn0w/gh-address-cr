# Contract: Batch Action Response

## Purpose

`agent submit-batch` accepts shared fix evidence for multiple GitHub review threads when all included items already have active fixer leases.

## Accepted Input Shape

```json
{
  "schema_version": "1.0",
  "agent_id": "codex-1",
  "resolution": "fix",
  "common": {
    "files": ["src/example_one.py", "src/example_two.py"],
    "validation_commands": [
      {
        "command": "python3 -m unittest tests.test_examples",
        "result": "passed"
      }
    ],
    "fix_reply": {
      "commit_hash": "abc123",
      "test_command": "python3 -m unittest tests.test_examples",
      "test_result": "passed"
    }
  },
  "items": [
    {
      "request_id": "req_one",
      "lease_id": "lease_one",
      "item_id": "github-thread:one",
      "summary": "Fixed first thread.",
      "why": "The first thread now uses the shared guarded path."
    },
    {
      "request_id": "req_two",
      "lease_id": "lease_two",
      "item_id": "github-thread:two",
      "summary": "Fixed second thread.",
      "why": "The second thread now uses the shared guarded path."
    }
  ]
}
```

## Acceptance Rules

- Every item must reference an active fixer lease.
- Every item must be a GitHub review thread.
- Every item must use resolution `fix`.
- Shared files and validation evidence may live under `common`.
- Each item must provide a distinct request id, lease id, and item id.
- Each item must provide a per-thread summary or note.

## Rejection Rules

The runtime rejects the whole batch without partial acceptance when any item has:

- Duplicate lease id.
- Duplicate item id.
- Missing request id or lease id.
- Stale, expired, or missing lease.
- Local finding item kind.
- Unsupported role.
- Non-fix resolution.
- Missing required fix evidence.

## Next Action

After acceptance, agents must run:

```bash
gh-address-cr agent publish owner/repo 123
```

Publishing remains serialized and runtime-owned.
