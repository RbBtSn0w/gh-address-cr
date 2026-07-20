# Mode / Producer Dispatch Matrix

`gh-address-cr` is the PR session control plane. This matrix defines which execution path should run for each `mode + producer` combination.

## Canonical user modes

- `address` / `处理评审`: route to the remote-only workflow. Do not start a new
  local review producer. If the runtime reports existing blocking local
  findings, follow the status-action map instead of ignoring them.
- `review` / `完整审查`: route to the mixed workflow. Require a structured
  findings producer before treating the producer handoff as complete.

Named producer skills are explicitly composed, never selected by default:

```text
Use $gh-address-cr review PR #123 with $engineering:code-review as the findings producer.
```

For that invocation, require `$engineering:code-review` to emit only a JSON
array. Every finding requires `title`, `body`, `path`, and `line`; supported
optional fields include `category`, `confidence`, `head_sha`, and explicit
P0-P4 `severity`. A clean review emits `[]`, not empty output. Ingest the result
without an ad-hoc workspace file:

```text
$engineering:code-review <PR_URL> [structured findings JSON output]
  | gh-address-cr findings <owner/repo> <pr_number> --input - --sync --source code-review
gh-address-cr review <owner/repo> <pr_number>
```

The pipe above expresses the data flow; a host may pass the producer's JSON to
stdin directly. Narrative Markdown is invalid input. Use `review-to-findings`
only when a producer emits the documented fixed `finding` block format.

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

## Intake Decision Table (#124)

Pick one intake route by what you already have; all converge on the same PR session.

| You have | Run |
| --- | --- |
| Findings JSON file | `gh-address-cr findings <r> <pr> --input findings.json --sync --source <producer>` |
| Findings on stdout/stdin | `<producer> | gh-address-cr findings <r> <pr> --input - --sync --source <producer>` (`[]` is a valid empty result; empty stdin is not) |
| An executable that prints findings JSON | `gh-address-cr adapter <r> <pr> <adapter_cmd...>` |
| Fixed Markdown `finding` blocks only | `<producer> | gh-address-cr review-to-findings <r> <pr> --input - > findings.json`, then `findings`/`review --input` |
| GitHub review threads only | `gh-address-cr review <r> <pr> --auto-simple` (alias: `address`) |

## Telemetry Coverage Decision Table (#124)

Telemetry is optional, PR-scoped, runtime-owned observed evidence, and never
mutates review state.

| You have | Run |
| --- | --- |
| Measured validation timing | Record `--validation "<cmd>=passed@<n>ms"` (or `@<n>s`) before `final-gate` |
| A normal single-agent PR flow | Run `review` / `address` / `agent resolve` / `agent publish` / `final-gate`; telemetry coverage is reported by `final-gate` |
| Coverage is `runtime-only` or `unavailable` | Re-run the same PR flow and ensure real timing is recorded in `--validation` values |
