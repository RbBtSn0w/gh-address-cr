# Development and Release

## Testing

Run the current automated checks with:

```bash
python3 -m unittest discover -s tests
gh-address-cr --help
gh-address-cr review --help
```

Current test layout:

- `tests/test_session_engine_cli.py`
  - PR session state machine and gate behavior
- `tests/test_python_wrappers.py`
  - Python entrypoints for GitHub/local-review flows
- `tests/test_aux_scripts.py`
  - helper scripts such as reply generation, batch resolve, and state cleanup
- `tests/helpers.py`
  - shared test harness


## Optional Telemetry Export

Local audit files remain the canonical repository contract:

- `audit.jsonl`
- `trace.jsonl`
- `audit_summary.md`

Telemetry network export is opt-in. By default, the CLI writes only local audit
and trace files. To use the hosted relay, set:

```bash
export GH_ADDRESS_CR_TELEMETRY=1
```

The hosted relay endpoint is:

- `https://gh-address-cr.hamiltonsnow.workers.dev/v1/logs`

When enabled, each audit/trace event is emitted as an OTLP/HTTP JSON `logs`
record to that Cloudflare Worker.

Recommended deployment shape:

- CLI client
- Cloudflare Worker as the security relay
- Better Stack as the backend

This keeps the Better Stack source token out of the CLI runtime while preserving
local audit artifacts for final-gate archives and tests.

Repository-root reference docs:

- setup guide: `skill/references/otel-worker-better-stack.md`
- Worker example: `skill/references/otel-worker-better-stack/worker.mjs`
- Wrangler example: `skill/references/otel-worker-better-stack/wrangler.example.jsonc`

For self-hosting or explicit override, CLI-side OpenTelemetry configuration still
supports standard env vars. Setting an explicit OTLP endpoint also enables
network export:

```bash
export OTEL_SERVICE_NAME="gh-address-cr-cli"
export OTEL_RESOURCE_ATTRIBUTES="deployment.environment=personal,service.namespace=skills"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://gh-address-cr-telemetry.example.workers.dev"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/json"
```

Notes:

- `OTEL_EXPORTER_OTLP_ENDPOINT` is treated as a base URL, so `/v1/logs` is appended automatically
- `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` may be used instead when you want an exact logs endpoint
- local audit files are still written even if telemetry export is disabled or fails
- export failures are recorded locally as `telemetry_export` diagnostics in `trace.jsonl`


## AI Agent Feedback

When the skill itself blocks progress, file a feedback issue in this repository instead of silently dropping the problem.

- By default, feedback issues are filed to `RbBtSn0w/gh-address-cr`. Override `--target-repo` only when the skill owner explicitly directs you to use a different feedback repository.
- Use feedback issues for skill-level problems such as contradictory instructions, missing automation, documentation gaps, or repeatable tooling failures that are not caused by the repository under review.
- Do not file feedback issues for normal PR findings, target-repository bugs, or expected wait states such as `WAITING_FOR_EXTERNAL_REVIEW`.
- Do not include usernames, emails, tokens, machine names, or absolute local paths in feedback issues.
- Prefer safe technical diagnostics such as failing command, exit code, status, `reason_code`, `waiting_on`, `run_id`, and skill version.
- For PR-scoped feedback, always provide `--using-repo` and `--using-pr` so the issue body names the repository and pull request under review. If they are omitted, `submit_feedback.py` will try to infer them from `--source-command` or `--failing-command`, but explicit values are preferred.
- When `--using-repo` and `--using-pr` are provided, the helper auto-collects the latest local evidence from the PR workspace when available:
  - `last-machine-summary.json`
  - `session.json`
  - `audit_summary.md`
  - cached PR head SHA from `github_pr_cache.json`
- The helper deduplicates repeated reports by fingerprint and skips creating a new issue when the same feedback issue is already open or was closed recently within the cooldown window.
- The repository issue format lives in `.github/ISSUE_TEMPLATE/ai-agent-feedback.md`.
- Repository-root helper command:

```bash
gh-address-cr submit-feedback \
  --category workflow-gap \
  --title "blocked without a recovery step" \
  --summary "review stopped in a blocked state without enough operator guidance." \
  --expected "the skill should identify the next command or artifact to inspect." \
  --actual "the workflow stopped and the next action was ambiguous." \
  --source-command "gh-address-cr review owner/repo 123" \
  --failing-command "gh-address-cr final-gate owner/repo 123" \
  --exit-code 5 \
  --status BLOCKED \
  --reason-code WAITING_FOR_FIX \
  --waiting-on human_fix \
  --run-id review-20260417T120000Z \
  --skill-version 1.2.0 \
  --using-repo owner/repo \
  --using-pr 123 \
  --artifact /tmp/loop-request.json
```

- Unified CLI passthrough:

```bash
gh-address-cr submit-feedback --category workflow-gap --title "..." --summary "..." --expected "..." --actual "..."
```


## CI semantic release (tag + changelog)

This repo includes a `semantic-release` workflow:

- Trigger: push to `main`
- Input: Conventional Commits history
- Output: semantic version tag (`vX.Y.Z`) + GitHub Release + `CHANGELOG.md`
- Python package release: `pyproject.toml` and `src/gh_address_cr/__init__.py` are synchronized to the semantic-release version before wheel/sdist build.
- Stable Python package registry: PyPI remains the authoritative Python runtime package registry.
- Homebrew tap: production PyPI releases update `RbBtSn0w/homebrew-tap` after the PyPI sdist is available. Homebrew is the documented macOS/Linuxbrew CLI installation channel.
- GitHub Releases remain release-note, tag, source-archive, and optional provenance surfaces; they are not the primary Python package registry.
- Dry-run/staging validation: use the `workflow_dispatch` `dry-run` or `testpypi` target before enabling production PyPI publishing. These targets build the package and render a local-sdist Homebrew formula but do not write the tap.
- Production PyPI publishing: requires PyPI Trusted Publishing and package-name ownership. It runs without a GitHub deployment environment approval gate; do not use long-lived PyPI API tokens unless a separate explicit release-policy change approves that fallback.
- Production Homebrew publishing: uses the shared release-bot GitHub App to mint a short-lived token scoped to `RbBtSn0w/homebrew-tap`; install the app on `RbBtSn0w/homebrew-tap` with `Contents: Read and write`, expose `RELEASE_BOT_APP_ID` as an Actions variable, and expose `RELEASE_BOT_PRIVATE_KEY` as an Actions secret to this repository. The workflow validates the formula with `brew update-python-resources`, `brew audit --formula --strict`, source install, and `brew test` before pushing.
- No-release runs: if semantic-release finds no qualifying commit and does not create a tag, PyPI and Homebrew publishing both skip explicitly.
- Failed or partial publish recovery: inspect the PyPI project state and release artifacts before retrying; immutable package files may require a follow-up semantic-release version.

Commit format examples:

```text
feat: add strict unresolved-thread guard in final gate
fix: avoid duplicate handled-state writes when thread already resolved
docs: clarify npx skills update behavior
```

## Historical Breaking Changes (2026-04-09)

- Direct batch resolve helper usage was superseded by the current agent publish workflow. The old helper required an approved list format:
  - one thread per line: `APPROVED <thread_id>`
  - empty lines and `#` comments are allowed
  - raw thread-id lines now fail fast
- The old thread listing helper used the latest thread comment as primary context and emitted:
  - `comment_source` (`latest|first|none`)
  - `first_url`, `latest_url`
  - `url`/`body` remain available, now latest-first with fallback
