# Mode / Producer Dispatch Matrix

`gh-address-cr` is the PR session control plane. This matrix defines which execution path should run for each `mode + producer` combination.

## Supported combinations

### `remote`

- input:
  - `remote <owner/repo> <pr_number>`
- actions:
  1. `run_once.sh`
  2. process GitHub review threads
  3. `post_reply.sh` + `resolve_thread.sh` for handled GitHub items
  4. `final_gate.sh`

### `local code-review`

- input:
  - `local code-review <owner/repo> <pr_number>`
- actions:
  1. generate the standard producer prompt with `prepare-code-review`
  2. run a local code-review workflow
  3. require structured findings JSON, not only Markdown
  4. `ingest_findings.sh`
  5. process local findings through session status transitions
  6. `final_gate.sh`

### `local json`

- input:
  - `local json <owner/repo> <pr_number>`
- actions:
  1. read provided findings JSON
  2. `ingest_findings.sh`
  3. process local findings through session status transitions
  4. `final_gate.sh`

### `local adapter`

- input:
  - `local adapter <owner/repo> <pr_number>`
- actions:
  1. `run_local_review.sh`
  2. process local findings through session status transitions
  3. `final_gate.sh`

### `mixed code-review`

- input:
  - `mixed code-review <owner/repo> <pr_number>`
- actions:
  1. `run_once.sh`
  2. generate the standard producer prompt with `prepare-code-review`
  3. run a local code-review workflow
  4. require structured findings JSON
  5. `ingest_findings.sh`
  6. process GitHub threads and local findings as one session queue
  7. `final_gate.sh`

### `mixed json`

- input:
  - `mixed json <owner/repo> <pr_number>`
- actions:
  1. `run_once.sh`
  2. read provided findings JSON
  3. `ingest_findings.sh`
  4. process GitHub threads and local findings as one session queue
  5. `final_gate.sh`

### `mixed adapter`

- input:
  - `mixed adapter <owner/repo> <pr_number>`
- actions:
  1. `run_once.sh`
  2. `run_local_review.sh`
  3. process GitHub threads and local findings as one session queue
  4. `final_gate.sh`

### `ingest json`

- input:
  - `ingest json <owner/repo> <pr_number>`
- actions:
  1. read provided findings JSON
  2. `ingest_findings.sh`
  3. process local findings through session status transitions
  4. `final_gate.sh`

## Producer rules

- `code-review`
  - must produce findings JSON before session handling starts
  - do not stop at a Markdown summary
  - use `prepare-code-review` to generate the bridge prompt shape
- `json`
  - assumes findings already exist in machine-readable form
- `adapter`
  - assumes an executable command exists that prints findings JSON

## Non-negotiable rules

- GitHub review threads require both reply and resolve.
- Local findings require valid status transitions and notes for terminal handling.
- `final_gate.sh` must pass before any completion statement.
