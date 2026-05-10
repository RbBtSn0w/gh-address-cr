# Local Review Adapter Contract

`gh-address-cr run-local-review` executes an adapter command and expects a JSON array on stdout.
If your tool already emits findings JSON, use `gh-address-cr ingest-findings` directly instead of writing an adapter.

## Required fields per finding

- `title`
- `body`
- `path`
- `line`

## Optional fields

- `start_line`
- `end_line`
- `severity`
- `category`
- `confidence`
- `head_sha`

## Example

```json
[
  {
    "title": "Missing nil guard",
    "body": "The result of fetch_user may be null here.",
    "path": "src/service.py",
    "line": 33,
    "severity": "P1",
    "category": "correctness",
    "confidence": "high"
  }
]
```

## Notes

- The adapter should not mutate repo state.
- The adapter should not post directly to GitHub.
- `gh-address-cr` assigns stable local item ids and stores them in the PR session.
- `gh-address-cr ingest-findings` accepts these payload shapes:
  - JSON array
  - JSON object with `findings`, `issues`, or `results`
  - NDJSON
- `gh-address-cr ingest-findings` also accepts these alias fields for easier interoperability:
  - `path` / `file` / `filename`
  - `line` / `start_line` / `position`
  - `title` / `rule` / `check`
  - `body` / `message` / `description`
