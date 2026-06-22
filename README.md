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
> `agent submit-batch` commands are replaced by a single `agent resolve`. See the
> [3.0 migration guide](docs/migration-3.0.md).

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

## Public surface

Primary commands:

- `active-pr`
- `review`
- `address`
- `final-gate`
- `telemetry ingest`
- `telemetry summary`

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
- `agent resolve` (`<item_id>` | `--trivial` | `--batch --input` | `--homogeneous-reason` | `--stale --match-files`)
- `agent evidence`
- `agent publish`
- `agent leases`
- `agent reclaim`
- `agent orchestrate autopilot`
- `command-session`
- `doctor`

High-level commands emit machine-readable JSON summaries by default. Use
`--human` when a person needs narrative output and `--lean` where supported for
low-token agent context.

Telemetry commands are PR-scoped and do not mutate review item state:

```bash
gh-address-cr telemetry ingest owner/repo 123 --source generic-agent --format agent-jsonl --input agent-telemetry.jsonl
gh-address-cr telemetry summary owner/repo 123 --format markdown
gh-address-cr telemetry ingest owner/repo 123 --source codex --format codex-host-json --input codex-host.json
```

Assistant hosts can also provide a final-gate ingestion hook by setting:

```bash
export GH_ADDRESS_CR_HOST_TELEMETRY_INPUT=agent-telemetry.jsonl
export GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE=assistant-host
gh-address-cr final-gate owner/repo 123
```

`GH_ADDRESS_CR_HOST_TELEMETRY_FORMAT` defaults to `agent-jsonl`. The hook uses
the same telemetry ingestion contract before final-gate artifacts are written.
When `GH_ADDRESS_CR_HOST_TELEMETRY_INPUT` is not set, `final-gate` can
auto-discover first-party Claude Code and Codex native session logs through
packaged host profiles. Codex native capture emits the same `agent-jsonl`
contract as other hosts; `codex-host-json` remains available for explicit
aggregate Codex exports.

Every final efficiency summary reports one coverage label: `complete`,
`partial`, `runtime-only`, or `unavailable`. Imported events are normalized to
runtime-owned `event_fingerprint` values; duplicate or overlapping imports are
reported through `accepted_fingerprints` and `duplicate_fingerprints` without
inflating counts, durations, or slowest-operation rankings. Corrupted external
telemetry remains fail-open for review and final-gate flows, while telemetry
commands fail loudly with reason codes and diagnostics.

For GitHub review-thread replies, the single mutating entrypoint is
`agent resolve`; it records classification internally, so no separate
`agent classify` round-trip is needed. Shared files/validation evidence is not the
same as a shared reviewer answer. Use `agent resolve --batch --input <batch-response.json>`
with per-thread summary/why entries for ordinary multi-thread handling. Commit
evidence is hydrated by the runtime during publish, so independent worker evidence
does not need to wait for a final commit hash. Use
`agent resolve --homogeneous-reason <why>` only for a homogeneous repeated concern.
When `resolve` reports `PER_THREAD_EVIDENCE_REQUIRED`, run
`agent next --batch --agent-id <id>` to claim eligible GitHub review threads and
write a fillable `batch-response-skeleton.json` before `agent resolve --batch`.

When exactly one PR session is cached, PR-scoped commands such as `address`,
`review`, `threads`, `final-gate`, and `telemetry summary` may omit
`<owner/repo> <pr_number>`. No-session and multi-session cases fail loud with
`NO_ACTIVE_PR_SCOPE` or `AMBIGUOUS_PR_SCOPE`.

Use `agent resolve --trivial` only for documentation or typo-only GitHub review
threads, and `agent resolve --stale --match-files` for STALE/outdated threads. The
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

`agent orchestrate autopilot` is guarded dry-run planning by default. It emits a
deterministic plan for classify, lease, submit, publish, and final-gate steps.
Side-effecting autopilot execution is not enabled in this v1 contract.

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

## Documentation

- [3.0 migration guide](docs/migration-3.0.md)
- [Installation and distribution](docs/installation.md)
- [CLI reference](docs/cli-reference.md)
- [Workflows](docs/workflows.md)
- [Architecture](docs/architecture.md)
- [Compatibility inventory](docs/compatibility-inventory.md)
- [Development and release](docs/development.md)
- [Troubleshooting](docs/troubleshooting.md)
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
