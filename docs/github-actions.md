# GitHub Actions navigation

Five repository-owned workflows describe operator intents. Run titles identify
PRs, branches, versions or proposal operations; job names identify execution
phases. GitHub-managed CodeQL, Copilot and Dependency Graph remain separate.

## Workflow map

| Sidebar entry | File | Trigger and result |
| --- | --- | --- |
| Checks / Python | `ci.yml` | PR opened/updated/reopened, metadata edits, trunk push, weekly schedule. Validate PR target, lint, type-check, test Python 3.12–3.14 and installed packages; eligible PRs produce preview artifacts. |
| Preview | `homebrew-preview.yml` | Successful eligible Checks run. Validate provenance, test source installation, publish dev preview assets/formula and instructions. |
| Release | `release.yml` | Main push or manual. Analyze version, publish GitHub/PyPI and call Homebrew when a new version is released. |
| Homebrew | `homebrew.yml` | Called by Release or manual recovery. Build and verify four platform bottles; update stable tap only after all four pass. |
| Branches | `branches.yml` | Friday schedule proposes develop -> main; successful main Release completion proposes main -> develop. Manual operation selects one proposal. Neither job merges PRs. |

PR target validation remains `Validate base branch`: only develop may target
main. Moving it into Checks retains its opened/edited/synchronize/reopened
coverage and uses no checkout or write permission. This consolidation preserves
the full Python matrix, lower-bound OTel tests and installed wheel journey.
PR edits run only the metadata guard via `pull_request_target: edited`. That
job has no checkout, actions, secrets or token permissions. All source-executing
jobs reject this event, and Preview accepts only ordinary `pull_request` runs.
Consequently editing a PR does not rerun the matrix or enqueue a new preview that
could replace an unrelated pending run. Verify base/default-branch deployment
before claiming remote metadata routing is active.

## Manual operations

| Intent | Workflow and inputs | Side effects |
| --- | --- | --- |
| Propose release | Branches, `operation=propose-release` | Create/update a reviewed develop -> main PR; no publication or automatic merge. |
| Propose sync | Branches, `operation=propose-sync` | Create/reuse an immutable main snapshot and propose its merge into develop; no trunk write or automatic merge. |
| Validate packaging | Release, `publish_target=dry-run` | No production Release, PyPI or tap writes. |
| Test staging upload | Release, `publish_target=testpypi` | Writes TestPyPI only. |
| Publish stable packages | Release, `publish_target=pypi` | Production publication; requires explicit release approval. Main pushes select this target automatically. |
| Recover Homebrew | Homebrew, `version`, `rebuild` | Restore the published version's snapshot/bottles; can upload production assets and update the tap. Keep rebuild unchanged for an unchanged retry. |

Use filenames for CLI lookup and dispatch. For example:

```bash
gh workflow run branches.yml -f operation=propose-release
gh workflow run branches.yml -f operation=propose-sync
gh run list --workflow release.yml
```

Dispatch is an operation, not an approval mechanism. Review exact refs/checks
and follow [release governance](release-train.md) before any merge/publication.
See [Homebrew distribution](homebrew-distribution.md) for bottle acceptance and
same-version recovery. Promotion and sync require normal merge, not squash or
rebase. Separate proposal jobs retain their own permissions and concurrency
locks; unrelated proposal operations do not share a global queue.

## Trust and rollout

Checks executes PR code with read-only credentials. Preview consumes the exact
triggering run's artifact using trusted default-branch tooling; source execution
never receives tap-write credentials. Release and Homebrew retain their existing
production boundaries and immutable recovery artifacts.

The published main preview consumer already accepts both `ci` and
`Checks / Python`, so the Checks producer can now use the staged new name without
an event gap. Keep both names until old PR branches/runs no longer use `ci`.
The trusted producer path stays `.github/workflows/ci.yml`.

Branches accepts both `Release / 2 Publish` and `Release` completions during the
publish-name transition. Only successful main runs select its sync job; schedules
select only release proposals and dispatch selects only its explicit operation.
The new default-branch workflow must be deployed before claiming remote Branches
activation. Local tests and develop PR CI do not establish schedule activation.
GitHub matches `workflow_run` producers by display name, not filename; see the
[official event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

The retired source workflows are `pr-target.yml`, `scheduled-release-pr.yml`
and `sync-main-to-develop.yml`. Their responsibilities move into Checks and
Branches. Historical GitHub workflow registrations (including older
`pr-dev-preview.yml` and `pr-dev-release.yml`) may remain visible after source
removal. Do not recreate obsolete YAML or delete run evidence to tidy the sidebar.
Remote disabling/history cleanup is a separate administrative operation.

## Presentation

Use short sidebar names for intents, descriptive run titles for objects/actions,
and job names for phases. Release stage order belongs in the execution graph,
not four numbered sidebar entries. Text carries meaning without reliance on
color or emoji; keep GitHub's native typography and keyboard/focus behavior.
A green branch proposal means a proposal was prepared, not software published.
