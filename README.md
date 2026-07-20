# gh-address-cr

Auditable pull request review-resolution workflow for AI coding agents.

`gh-address-cr` is a deterministic CLI runtime plus a thin Codex skill/plugin
adapter. It coordinates GitHub review threads, local AI review findings,
evidence, replies, resolves, and final-gate proof in one PR-scoped session.

It is not a code-review producer and not a generic GitHub bot. The runtime owns
state and side effects; agents return structured evidence and the runtime
publishes GitHub replies/resolves.

> **Upgrading from 2.x?** 3.0 is a breaking release: the `agent fix`,
> `agent trivial-fix`, `agent fix-all`, `agent resolve-stale`, and
> `agent submit-batch` commands are replaced by a single `agent resolve`.

Project architecture governance lives in `.specify/memory/constitution.md`.
The installed skill contract remains `skill/SKILL.md`.

## 60-second quickstart

Install the runtime:

```bash
pipx install gh-address-cr
gh-address-cr --help
gh-address-cr agent manifest
```

Install the Codex/agent skill adapter:

```bash
npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill skill
npx skills check
```

Build the Codex community plugin payload:

```bash
python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr
```

Then install from the generated marketplace path when working from a built
checkout or release artifact:

```bash
codex plugin marketplace add .agents/plugins/marketplace.json
codex plugin marketplace upgrade
codex plugin add gh-address-cr@gh-address-cr-community
```

## When to use it

Use it when:

- a pull request has unresolved GitHub review threads
- an AI review producer emits normalized findings for the PR
- stale or outdated review threads need explicit evidence and handling
- completion requires a fresh `gh-address-cr final-gate <owner/repo> <pr_number>` proof

Do not use it as:

- a replacement for a code-review producer
- a generic GitHub issue bot
- a ChatGPT Apps SDK app or MCP server
- a shortcut for posting GitHub replies or resolving threads outside the runtime

## First PR walkthrough

```bash
gh-address-cr active-pr --repo owner/repo
gh-address-cr review owner/repo 123
gh-address-cr address owner/repo 123 --lean
gh-address-cr agent publish owner/repo 123
gh-address-cr final-gate owner/repo 123
```

Completion means the latest final gate reports:

- zero unresolved review threads
- zero pending reviews for the authenticated login
- no blocking session items
- terminal GitHub threads have durable reply evidence
- a compact metrics line via `completion_summary_line` or `PR Completion Summary Guidance`
- a telemetry coverage label and structured efficiency report path
- an audit summary path with a sha256 hash

A zero unresolved-thread count alone is not sufficient.

## OpenTelemetry traces

`otel-tracing.v1` is the versioned public behavior and architecture boundary
for process tracing.

- Process-level observability owner: the CLI process
- External inputs: command invocation and environment-based telemetry opt-out
- Span projection: one root span per CLI invocation
- Export policy: OTLP/HTTP through the configured relay
- Side-effect boundary: tracing observes runtime behavior and remains separate from PR-scoped workflow telemetry
- Artifact truth boundary: trace artifacts are observability outputs, not runtime truth
- Recovery and replay: tracing is fail-open and must not block command completion

The installed CLI exports one process-level OTLP/HTTP trace to:

```text
https://telemetry-gateway.hamiltonsnow.workers.dev/v1/traces
```

The service name is `gh-address-cr`. The client contains no API key; the
Cloudflare Worker as the security relay injects backend credentials. To disable
network tracing:

```bash
export DISABLE_TELEMETRY=1
# or
export DO_NOT_TRACK=1
```

Tests use a separate service name to avoid polluting production telemetry:

```bash
export GH_ADDRESS_CR_TELEMETRY_ENVIRONMENT=test
# service.name = gh-address-cr-test
```

The CLI entrypoint initializes tracing before dispatch and calls
`shutdown_telemetry()` in a `finally` block. It attempts to flush spans for up
to 200 ms, then returns fail-open if the gateway remains unavailable.
For a custom operation:

```python
from opentelemetry.trace import Status, StatusCode

from gh_address_cr.telemetry import initialize_telemetry, shutdown_telemetry

tracer = initialize_telemetry()
try:
    with tracer.start_as_current_span("my-task") as span:
        span.set_attribute("cli.argument", "value")
        try:
            run_task()
        except Exception as error:
            span.record_exception(RuntimeError(type(error).__name__))
            span.set_status(Status(StatusCode.ERROR))
            raise
finally:
    shutdown_telemetry()
```

Do not attach tokens, raw prompts, usernames, machine identifiers, or local
paths as span attributes.

### CLI span attributes for AI agent scenarios

Every CLI invocation also emits exactly one `gh-address-cr.cli` span (kind
`INTERNAL`) carrying a fixed set of attributes, so agent hosts can correlate
tool calls without extra instrumentation:

- `process.executable.name`, `process.pid`, `process.parent_pid`,
  `process.exit.code` — execution identity and the honest exit code (including
  non-zero Status-to-Action codes; these are not errors)
- `error.type` — present only when an exception actually propagated (a crash),
  drawn from a bounded set: `keyboard_interrupt`, `timeout`, `_OTHER`
- `process.command_args`, `gen_ai.tool.call.arguments` — sanitized argv via
  `safe_command_args(...)`; tokens, credentials, and PR `owner/repo` slots are
  replaced with `"[redacted]"` in place (position-preserving), never dropped
- `gen_ai.operation.name` (`execute_tool`), `gen_ai.tool.name` — GenAI tool
  vocabulary for the invoked command
- `gen_ai.conversation.id` (+ `.source`), `gen_ai.agent.name` — passive
  session correlation. Set `GH_ADDRESS_CR_CONVERSATION_ID` (preferred,
  vendor-neutral) or `CLAUDE_CODE_SESSION_ID` (passive fallback) to a stable
  per-session value so repeated invocations group together; set `AI_AGENT` to
  label the calling agent. All three are absent when no session env is set.
- `vcs.change.id`, `vcs.provider.name` (`github`), `vcs.repository.name` — for
  PR-scoped commands only (`owner/repo <pr_number>`); `vcs.repository.name` is
  a stable one-way hash, never the plain `owner/repo` string.
  `vcs.change.state` appears only when already available from session data.
  Non-PR commands (`version`, `doctor`) carry no `vcs.*` attributes.
- The root CLI span may also include phase events for long-running workflows
  such as preflight, session load, ingestion, gate evaluation, summary
  emission, and nested command-session or subprocess milestones. These events
  keep the single-span contract intact while making the Honeycomb timeline
  easier to read.

A malformed or missing `TRACEPARENT` never blocks or changes the CLI's exit
code; a well-formed one makes the span a child of that remote context. See
[`specs/026-cli-otel-agent-integration/contracts/cli-otel-span-attributes.md`](specs/026-cli-otel-agent-integration/contracts/cli-otel-span-attributes.md)
for the full enforced contract.

## Public surface

Primary commands:

- `active-pr`
- `review`
- `address`
- `final-gate`

Advanced integration commands:

- `threads`
- `findings`
- `adapter`
- `review-to-findings`
- `agent manifest`
- `agent classify`
- `agent next`
- `agent next --batch`
- `agent submit`
- `agent resolve` — (`<item_id>` | `--files`/`--file` | `--input`) x (`--disposition fix|trivial|reject|clarify`) x (`--stale`)
- `agent evidence`
- `agent publish`
- `agent leases`
- `agent reclaim`
- `command-session`
- `doctor`

High-level commands emit machine-readable JSON summaries by default. Use
`--human` when a person needs narrative output and `--lean` where supported for
low-token agent context.

Every final efficiency summary reports one coverage label: `complete`,
`partial`, `runtime-only`, or `unavailable`. The runtime records process and
workflow telemetry for the surviving core path and keeps telemetry fail-open:
reduced coverage is reported in the summary, but it does not change the review
verdict by itself.
For GitHub review-thread replies, the single mutating entrypoint is
`agent resolve`; it records classification internally, so no separate
`agent classify` round-trip is needed. It resolves along three independent
axes: disposition (`--disposition fix|trivial|reject|clarify`), selection
(an `<item_id>`, `--files`/`--file`, or `--input`), and condition (`--stale`).
Shared files/validation evidence is not the same as a shared reviewer answer.
Use `agent resolve --input <batch-response.json>` with per-thread summary/why
entries for ordinary multi-thread handling. Commit evidence is hydrated by the
runtime during publish, so independent worker evidence does not need to wait
for a final commit hash. Use `agent resolve --why <why>` only for a
homogeneous repeated concern. When `resolve` reports
`PER_THREAD_EVIDENCE_REQUIRED`, run `agent next --batch --agent-id <id>` to
claim eligible GitHub review threads and write a fillable
`batch-response-skeleton.json` before `agent resolve --input <batch-response.json>`.

When exactly one PR session is cached, PR-scoped commands such as `address`,
`review`, `threads`, and `final-gate` may omit `<owner/repo> <pr_number>`.
No-session and multi-session cases fail loud with
`NO_ACTIVE_PR_SCOPE` or `AMBIGUOUS_PR_SCOPE`.

Use `agent resolve <item_id> --disposition trivial` only for documentation or
typo-only GitHub review threads, and `agent resolve --stale` for
STALE/outdated threads. The
runtime rejects security-sensitive, API-sensitive, performance, or ambiguous
comments with `TRIVIAL_THREAD_NOT_ELIGIBLE`; normal reply, resolve, validation,
and final-gate evidence still applies.

Agents that need a schema-defined triage handoff may emit
`workflow_decision.v1` JSON with `schema_version`, `request_id`, `item_id`,
`decision`, and `reason`. Existing Markdown decision blocks remain a documented
compatibility path, but JSON avoids whitespace-sensitive parsing.

`command-session --input <json>|-` executes multiple one-shot runtime commands
inside one process and returns one result per operation. Failed operations do
not suppress later operations.

`agent orchestrate` remains an optional advanced surface. The default supported
path is still single-agent `review` / `address` / `agent resolve` /
`agent publish` / `final-gate`; no orchestration session is required for normal
PR handling.

## Architecture and Packaging

`gh-address-cr` is the preferred and stable automation entrypoint.

- Published skill payload: the entire `skill/` directory
- Repo-level verification harness: `tests/`
- If a rule or instruction must ship with the installed skill, it must live inside `skill/`

When blast radius requires kernel-style modeling, the design follows
`external facts -> events -> projections -> policy -> command plan/outbox`.
Architecture Preflight must name the artifact truth boundary, any
self-referential completion risk, and the recovery model. If review feedback
keeps adding edge cases without reducing state space, stop expanding
conditionals and update the architecture spec instead.

## Runtime and adapter boundary

The deterministic implementation belongs to the Python runtime package:

- console entrypoint: `gh-address-cr`
- module entrypoint: `python3 -m gh_address_cr`
- source package: `src/gh_address_cr/`

The packaged skill remains under `skill/` and acts as a thin adapter:

- `skill/SKILL.md` explains agent behavior
- `skill/runtime-requirements.json` declares runtime compatibility
- `skill/agents/` and `skill/references/` provide hints and reference docs

The Codex plugin payload is generated from `skill/` into a build artifact such
as `dist/plugin/gh-address-cr`:

```bash
python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr
python3 scripts/build_plugin_payload.py --check
```

The OpenAI curated Plugin Directory is not a self-service publish target in this
repository. The committed `.agents/plugins/marketplace.json` points at the
generated community distribution artifact.

## Command Topology (ASCII)

```text
active-pr
review
review [--auto-simple]
address [--lean|--summary]
threads [--lean|--summary]
findings --input <json|->
adapter <adapter_cmd...>
doctor
command-session --input <operations.json|->
final-gate
review-to-findings --input <finding-blocks.md|->
submit-feedback
submit-action <action-request.json>
version / --version
--machine
--human

manifest
classify
next --role <role>
next --batch
submit
resolve <item_id>
resolve <item_id> --disposition trivial
resolve --input <batch-response.json>
resolve --why <why>
resolve --disposition reject|clarify --why <why>
resolve --stale
evidence add
evidence list
publish
leases
reclaim
orchestrate start/status/step/resume/stop/submit/autopilot

WAITING_FOR_EXTERNAL_REVIEW
WAITING_FOR_SIMPLE_ADDRESS
PER_THREAD_EVIDENCE_REQUIRED -> next --batch
producer output
session items
agent classify
ActionResponse or BatchActionResponse
agent submit or agent resolve --input <batch-response.json>
accepted evidence
agent publish (GitHub thread side effects only)
final-gate
completion_summary_line
completion_summary
runtime-owned leases + request_id values
agent resolve --input <batch-response.json> validates lease ownership and request context
```

Stable machine summary fields:

- `status`
- `repo`
- `pr_number`
- `item_id`
- `item_kind`
- `counts`
- `artifact_path`
- `reason_code`
- `waiting_on`
- `next_action`
- `commands`
- `exit_code`

Use `--lean` or `--summary` when reducing token load. Machine summaries also
surface the current-login pending review count.

## Advanced / Developer Integration

The public user flow above does not require manual `--input`, producer
selection, or mode routing.

For explicit automation or repository-root invocation, the main command is:
`gh-address-cr review <owner/repo> <pr_number>`.

`adapter` is for adapter-produced findings plus PR orchestration.

`review` handles both local findings and GitHub review threads in one run.
`findings` handles local findings only; it does not process GitHub review
threads.

`findings --sync` requires an explicit `--source`.
`review-to-findings` does not accept arbitrary Markdown. It only accepts the
fixed `finding` block format.

The wrapper `--human` and `--machine` belong before `adapter`; remaining flags
are passed through to the adapter command unchanged.

```text
$gh-address-cr --human adapter <owner/repo> <pr_number> <adapter_cmd...>
$gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...> --human --machine
gh-address-cr --human adapter owner/repo 123 python3 tools/review_adapter.py
gh-address-cr adapter owner/repo 123 python3 tools/review_adapter.py --base main --human
```

Any external review producer may satisfy the handoff.

- `producer-request.md`
- `incoming-findings.json`
- `incoming-findings.md`
- `WAITING_FOR_EXTERNAL_REVIEW`
- source-scoped producer result
- `[]` is a valid explicit producer result

Published fix replies surface exactly one canonical `Review signal:` line when
severity or reviewer priority evidence exists.

## Workflow Patterns

## Automatic Review Workflow

1. Run `gh-address-cr review <owner/repo> <pr_number>`.
2. Ingest existing findings or wait for external review handoff.
3. Resolve items through `agent resolve` and publish through `agent publish`.
4. Finish with `final-gate`.

for GitHub thread `fix`: `fix_reply`
- `summary`
- `files`

for GitHub thread `clarify` or `defer`: `reply_markdown`

Minimal user prompt:

`Run gh-address-cr review for this PR, follow the machine summary, and finish with final-gate.`

Ready-to-use prompt variants:

- Short generic:
  `Review this PR through gh-address-cr and follow the runtime status map.`
- Existing GitHub review threads (`address` / `处理评审`):
  `Use $gh-address-cr address PR #123.`
- Explicit `$code-review` producer:
  For a full mixed review (`review` / `完整审查`), use
  `Use $gh-address-cr review PR #123 with $engineering:code-review as the findings producer.`
- Any external review producer:
  `Any external review producer may satisfy the handoff if it emits findings JSON or fixed finding blocks.`

For the explicit `$engineering:code-review` composition, override its default
Markdown report and require findings JSON with `title`, `body`, `path`, and
`line`; use `[]` when no findings exist. Ingest it with
`findings --input - --sync --source code-review`, then continue `review`.

如果你自己就是外部 review producer，请直接输出 findings JSON 或固定 `finding` blocks。

不要只输出普通 Markdown 审查报告。

Advanced producer categories:

- adapter-produced findings
- fixed `finding` block conversion
- explicit `findings --sync --source <producer>` handoff

## Runtime Distribution

Install the released runtime CLI:

- `pipx install gh-address-cr`
- `uv tool install gh-address-cr`

Install with Homebrew:

- `brew tap RbBtSn0w/tap`
- `brew install gh-address-cr`
- `brew upgrade gh-address-cr`
- `brew test gh-address-cr`

GitHub-direct runtime validation install:

- `pipx install git+https://github.com/RbBtSn0w/gh-address-cr.git`

Local editable development install:

- `python3 -m pip install -e .`

Packaged skill install:

- `npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill skill`

The packaged skill does not install the runtime CLI package.

Upgrade from skill-shim usage:

- Install the runtime CLI with `pipx` or `uv tool`
- Keep `--skill skill` for the packaged adapter
- Homebrew tap distribution remains available

## Compatibility Inventory

Preserved Public Contracts:

- `review`
- `address`
- `threads`
- `findings`
- `submit-action`
- `final-gate`

Unsupported historical root commands:

- `legacy_scripts`

Removed Or Unsupported Surfaces:

- removed migration/evaluation command surfaces
- legacy script entrypoints

Internal Naming Rule:

- the shipped runtime and packaged skill remain `gh-address-cr`

## Troubleshooting

When machine output is ambiguous, inspect:

- `status`
- `reason_code`
- `waiting_on`
- `next_action`
- `commands`
- `artifact_path`

Outdated / `STALE` GitHub threads still count as unresolved until explicitly
handled. Prefer `agent resolve --stale`.

## Additional Repository Files

- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Terms](TERMS.md)

## Development checks

Run the local verification gate before submitting changes:

```bash
ruff check src tests scripts/build_plugin_payload.py
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr
python3 scripts/build_plugin_payload.py --check
```

Package smoke:

```bash
rm -rf dist build
python3 -m build
python3 -m twine check dist/*
```

## Repository model

This repository has two scopes:

- repository root: development, verification, CI, release metadata, and contributor guidance
- `skill/`: the installable and published skill folder

The product/runtime identity remains `gh-address-cr`: the Python package,
console entrypoint, repository URL, `SKILL.md` frontmatter `name`, plugin name,
and `/gh-address-cr` invocation must not be renamed.
