# Contract: Action Request Helper

## Purpose

The packaged helper prepares an agent response artifact from either a runtime `ActionRequest` or a legacy loop request. It must not become an authoritative workflow engine.

## Runtime Request Input

Required fields:

```json
{
  "schema_version": "1.0",
  "request_id": "req_123",
  "lease_id": "lease_123",
  "agent_role": "fixer",
  "item": {
    "item_id": "github-thread:abc",
    "item_kind": "github_thread"
  },
  "repository_context": {
    "repo": "owner/repo",
    "pr_number": "123"
  }
}
```

## Runtime Response Output

For runtime requests, the helper writes an `ActionResponse` JSON file:

```json
{
  "schema_version": "1.0",
  "request_id": "req_123",
  "lease_id": "lease_123",
  "agent_id": "agent",
  "resolution": "fix",
  "note": "Fixed the thread.",
  "files": ["src/example.py"],
  "validation_commands": [
    {
      "command": "python3 -m unittest tests.test_example",
      "result": "passed"
    }
  ],
  "fix_reply": {
    "summary": "Fixed the thread.",
    "commit_hash": "abc123",
    "files": ["src/example.py"]
  }
}
```

## Legacy Request Input

Legacy loop requests remain supported when repository identity is top-level:

```json
{
  "repo": "owner/repo",
  "pr_number": "123",
  "item": {
    "item_id": "local-finding:abc",
    "item_kind": "local_finding"
  }
}
```

## Failure Contract

The helper exits with code 2 and writes no response artifact when:

- The request file is missing or invalid JSON.
- Repository identity cannot be found in `repository_context` or top-level fields.
- `item` is missing.
- Runtime request identity is incomplete.
- Required evidence for the selected resolution is missing.

## Side-Effect Boundary

The helper may write local response and shell helper artifacts. It must not post GitHub replies, resolve threads, mutate session state, or claim completion.
