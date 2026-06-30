# Contract: `run-manifest.v1`

## Purpose

Provide one public-safe correlation envelope for an archived PR-resolution run. The manifest is evaluation input evidence, not review-completion authority. Final-gate truth remains in runtime/final-gate evidence.

## Artifact

```text
archive/<owner>__<repo>/pr-<pr>/<run_id>/run-manifest.v1.json
```

For `--no-auto-clean`, the manifest is written to the stable active workspace. For auto-clean, it is written directly to the archive only after copied audit, trace, summary, and efficiency artifacts have completed path rewriting.

## Required Shape

```json
{
  "schema_version": "run-manifest.v1",
  "run_id": "default",
  "session_id": "owner/repo#123",
  "repo": "owner/repo",
  "pr_number": "123",
  "runtime_version": "3.2.0",
  "runtime_commit": null,
  "skill_version": null,
  "head_sha": "abc123",
  "started_at": "2026-06-30T01:00:00Z",
  "final_gate_observed_at": "2026-06-30T01:10:00Z",
  "final_gate_status": "PASSED",
  "final_gate_counts": {
    "unresolved_remote_threads_count": 0,
    "github_threads_missing_reply_count": 0
  },
  "workflow_variant": "review",
  "telemetry_sources": ["runtime", "codex"],
  "complexity": {
    "review_item_count": 3,
    "changed_file_count": 2,
    "diff_line_count": 84,
    "classification_mix": {"fix": 2, "clarify": 1, "defer": 0, "reject": 0},
    "language_toolchain": ["python"],
    "required_check_duration_ms": null,
    "bucket_key": "items:2-5|files:1-3|diff:1-100|mix:mixed"
  },
  "artifacts": [
    {"path": "session.json", "sha256": "..."},
    {"path": "evidence.jsonl", "sha256": "..."},
    {"path": "efficiency-report.json", "sha256": "..."}
  ],
  "diagnostics": []
}
```

## Rules

- Artifact paths are archive-relative and MUST NOT contain absolute paths or `..` traversal.
- Artifact digests are calculated from final-target bytes after all archive path rewriting. The manifest MUST NOT hash itself.
- Missing optional metadata remains `null` and reduces the relevant evaluation coverage.
- `final_gate_status` and counts MUST be copied from the runtime result, never inferred from evaluation output.
- Existing final-gate machine fields and efficiency-report contracts remain unchanged.
- Manifest generation failure is diagnostic-only for normal final-gate. Explicit evaluation validation/rebuild fails loudly.
- The evaluator verifies listed digests when present and returns `EVALUATION_ARCHIVE_INTEGRITY_FAILED` on mismatch.

## Compatibility

- Unknown future fields are ignored only when `schema_version` is supported.
- Unsupported schema versions fail evaluation commands with `UNSUPPORTED_EVALUATION_SCHEMA`.
- Archives without this manifest are diagnostic/import candidates but are not eligible for supported cross-version comparisons.
