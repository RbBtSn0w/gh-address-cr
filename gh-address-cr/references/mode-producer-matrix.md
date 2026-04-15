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
  1. `python3 scripts/cli.py run-once <owner/repo> <pr_number>`
  2. process GitHub review threads
  3. `python3 scripts/cli.py post-reply ...` + `python3 scripts/cli.py resolve-thread ...` for handled GitHub items
  4. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

### `local code-review`

- input:
  - `local code-review <owner/repo> <pr_number>`
- actions:
  1. generate the standard producer prompt with `python3 scripts/cli.py prepare-code-review local <owner/repo> <pr_number>`
  2. run a local code-review workflow
  3. require structured findings JSON, not only Markdown
  4. `python3 scripts/cli.py run-local-review --source local-agent:code-review <owner/repo> <pr_number> python3 scripts/cli.py code-review-adapter --input findings.json`
  5. process local findings through session status transitions
  6. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

Typical invocation:

```text
<review-command> <PR_URL> --output findings.json
$gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync

# If the upstream tool only emits Markdown review blocks:
<review-command> <PR_URL> | $gh-address-cr review-to-findings <owner/repo> <pr_number> > findings.json
$gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync
```

### `local json`

- input:
  - `local json <owner/repo> <pr_number>`
- actions:
  1. read provided findings JSON
  2. `python3 scripts/cli.py ingest-findings --input findings.json <owner/repo> <pr_number>`
  3. process local findings through session status transitions
  4. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

### `local adapter`

- input:
  - `local adapter <owner/repo> <pr_number>`
- actions:
  1. `python3 scripts/cli.py run-local-review <owner/repo> <pr_number> <adapter_cmd...>`
  2. process local findings through session status transitions
  3. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

### `mixed code-review`

- input:
  - `mixed code-review <owner/repo> <pr_number>`
- actions:
  1. `python3 scripts/cli.py run-once <owner/repo> <pr_number>`
  2. generate the standard producer prompt with `python3 scripts/cli.py prepare-code-review mixed <owner/repo> <pr_number>`
  3. run a local code-review workflow
  4. require structured findings JSON
  5. `python3 scripts/cli.py run-local-review --source local-agent:code-review <owner/repo> <pr_number> python3 scripts/cli.py code-review-adapter --input findings.json`
  6. process GitHub threads and local findings as one session queue
  7. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

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
```

### `mixed json`

- input:
  - `mixed json <owner/repo> <pr_number>`
- actions:
  1. `python3 scripts/cli.py run-once <owner/repo> <pr_number>`
  2. read provided findings JSON
  3. `python3 scripts/cli.py ingest-findings --input findings.json <owner/repo> <pr_number>`
  4. process GitHub threads and local findings as one session queue
  5. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

Typical invocation:

```text
$gh-address-cr findings <owner/repo> <pr_number> --input findings.json --sync
```

### `mixed adapter`

- input:
  - `mixed adapter <owner/repo> <pr_number>`
- actions:
  1. `python3 scripts/cli.py run-once <owner/repo> <pr_number>`
  2. `python3 scripts/cli.py run-local-review <owner/repo> <pr_number> <adapter_cmd...>`
  3. process GitHub threads and local findings as one session queue
  4. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

### `ingest json`

- input:
  - `ingest json <owner/repo> <pr_number>`
- actions:
  1. read provided findings JSON
  2. `python3 scripts/cli.py ingest-findings --input findings.json <owner/repo> <pr_number>`
  3. process local findings through session status transitions
  4. `python3 scripts/cli.py final-gate <owner/repo> <pr_number>`

## Producer rules

- `code-review`
  - must produce findings JSON before session handling starts
  - do not stop at a Markdown summary
  - use `prepare-code-review` to generate the bridge prompt shape
  - intake is normalized by the built-in `code-review-adapter`
- `json`
  - assumes findings already exist in machine-readable form
- `adapter`
  - assumes an executable command exists that prints findings JSON

## Non-negotiable rules

- GitHub review threads require both reply and resolve.
- Local findings require valid status transitions and notes for terminal handling.
- `python3 scripts/cli.py final-gate` must pass before any completion statement.
