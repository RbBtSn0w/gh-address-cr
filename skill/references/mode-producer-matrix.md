# Mode / Producer Dispatch Matrix

`gh-address-cr` is the PR session control plane. This matrix defines which execution path should run for each `mode + producer` combination.

## Supported combinations

### `loop`

- input:
  - `loop <mode> [producer] <owner/repo> <pr_number>`
- actions:
  1. initialize/load the PR session
  2. run the mode-specific intake path
  3. select the next blocking item
  4. if `--fixer-cmd` is provided, call the external fixer command
  5. otherwise write an internal fixer request artifact for the current AI agent
  6. apply `fix`, `clarify`, or `defer`
  7. run gate
  8. repeat until `PASSED`, `NEEDS_HUMAN`, or `BLOCKED`

### `remote`

- input:
  - `remote <owner/repo> <pr_number>`
- actions:
  1. `gh-address-cr address <owner/repo> <pr_number>`
  2. process GitHub review threads through the runtime workflow
  3. publish replies and resolve handled GitHub items through runtime-owned side effects
  4. `gh-address-cr final-gate <owner/repo> <pr_number>`

### `local code-review`

- input:
  - `local code-review <owner/repo> <pr_number>`
- actions:
  1. run a local code-review workflow
  2. require structured findings JSON, not only Markdown
  3. `gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync --source code-review`
  4. process local findings through session status transitions
  5. `gh-address-cr final-gate <owner/repo> <pr_number>`

Typical invocation:

```text
<review-command> <PR_URL> --output findings.json
$gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync --source code-review

# If the upstream tool only emits Markdown review blocks:
<review-command> <PR_URL> | $gh-address-cr review-to-findings <owner/repo> <pr_number> > findings.json
$gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync --source code-review
```

### `local json`

- input:
  - `local json <owner/repo> <pr_number>`
- actions:
  1. read provided findings JSON
  2. `gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync --source json`
  3. process local findings through session status transitions
  4. `gh-address-cr final-gate <owner/repo> <pr_number>`

### `local adapter`

- input:
  - `local adapter <owner/repo> <pr_number>`
- actions:
  1. `gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>`
  2. process local findings through session status transitions
  3. `gh-address-cr final-gate <owner/repo> <pr_number>`

### `mixed code-review`

- input:
  - `mixed code-review <owner/repo> <pr_number>`
- actions:
  1. run a local code-review workflow
  2. require structured findings JSON
  3. `gh-address-cr review <owner/repo> <pr_number> --input findings.json`
  4. process GitHub threads and local findings as one session queue
  5. `gh-address-cr final-gate <owner/repo> <pr_number>`

Typical invocation:

```text
<review-command> <PR_URL> --output findings.json
$gh-address-cr review <PR_URL> --input findings.json

# If the upstream tool only emits Markdown review blocks:
<review-command> <PR_URL> | $gh-address-cr review-to-findings <owner/repo> <pr_number> > findings.json
$gh-address-cr review <PR_URL> --input findings.json

# If findings are not available yet and you want the external handoff flow:
$gh-address-cr review <PR_URL>
# Populate incoming-findings.json or incoming-findings.md, then rerun the same command.
# Or ingest source-scoped findings with:
$gh-address-cr findings <owner/repo> <pr_number> --input - --sync --source code-review
# `[]` is a valid explicit empty producer result; empty stdin is not.
```

### `mixed json`

- input:
  - `mixed json <owner/repo> <pr_number>`
- actions:
  1. read provided findings JSON
  2. `gh-address-cr review <owner/repo> <pr_number> --input findings.json`
  3. process GitHub threads and local findings as one session queue
  4. `gh-address-cr final-gate <owner/repo> <pr_number>`

Typical invocation:

```text
$gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync --source json
$gh-address-cr review <owner/repo> <pr_number>
```

### `mixed adapter`

- input:
  - `mixed adapter <owner/repo> <pr_number>`
- actions:
  1. `gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>`
  3. process GitHub threads and local findings as one session queue
  4. `gh-address-cr final-gate <owner/repo> <pr_number>`

### `ingest json`

- input:
  - `ingest json <owner/repo> <pr_number>`
- actions:
  1. read provided findings JSON
  2. `gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync --source json`
  3. process local findings through session status transitions
  4. `gh-address-cr final-gate <owner/repo> <pr_number>`

## Producer rules

- `code-review`
  - must produce findings JSON before session handling starts
  - do not stop at a Markdown summary
  - use `review-to-findings` only when the upstream tool emits fixed Markdown finding blocks
  - intake is normalized by the current `findings`, `review`, or `adapter` command
- `json`
  - assumes findings already exist in machine-readable form
- `adapter`
  - assumes an executable command exists that prints findings JSON

## Non-negotiable rules

- GitHub review threads require both reply and resolve.
- Local findings require valid status transitions and notes for terminal handling.
- `gh-address-cr final-gate` must pass before any completion statement.

External fixer commands must read a JSON payload from stdin and return a JSON object containing:
- `resolution`: `fix`, `clarify`, or `defer`
- `note`
- for GitHub thread `fix`: `fix_reply`
  - `summary`
  - `files`
  - optional `commit_hash` when known; publish hydrates commit evidence otherwise
  - optional `severity`, `why`, `test_command`, `test_result`
  - `validation_commands` may be used as the default validation evidence when `test_command` / `test_result` are omitted
- for GitHub thread `clarify` or `defer`: `reply_markdown`
- optional `validation_commands`
