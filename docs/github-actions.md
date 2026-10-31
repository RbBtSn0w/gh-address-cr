# GitHub Actions navigation

Choose a workflow by intent. Repository-owned sidebar names share a category
prefix; release numbers show the operational order, not independent approvals.
Run titles identify the PR, branch, target or package version. Workflow filenames
and job/check identifiers remain stable for scripts and branch rules.

## Workflow map

| Sidebar entry | Trigger | Result and side effects |
| --- | --- | --- |
| ci (planned: Checks / Python) | PR, trunk push, weekly schedule | Lint, type checks, tests and package validation; eligible same-repository PRs also produce preview artifacts. Run titles already use Checks / Python. |
| Checks / PR target | PR opened, edited or updated | Validate target branch; only develop may target main. |
| Preview / Homebrew | Successful ci or Checks / Python PR run | Validate provenance, test source installation, publish dev preview assets/formula and installation instructions. This writes preview distribution, not stable distribution. |
| Release / 1 Propose PR | Friday schedule or manual | Create/update a develop -> main proposal only; no merge or package publication. Equal trees or no releasable commits produce a successful no-op. |
| Release / 2 Publish | Main push or manual | Analyze version, publish GitHub/PyPI releases and invoke stable Homebrew distribution when a version is released. Manual dry-run and TestPyPI modes have different side effects below. |
| Release / 3 Homebrew | Called by Publish, or manual recovery | Prepare fixed resources, build four bottles, publish immutable assets, verify four bottles, then update the stable tap only after all targets pass. |
| Release / 4 Propose sync | Successful Publish run on main, or manual | Propose a reviewed main -> develop sync PR; does not merge it. |

The two `workflow_run` consumers match producer **display names**, not filenames:
ci (later Checks / Python) -> Preview / Homebrew, and Release / 2 Publish -> Release / 4
Propose sync. Stage producer/consumer renames as described below. The preview
publisher separately verifies the trusted producer path `.github/workflows/ci.yml`.
GitHub documents these separate surfaces in
[workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
and [workflow_run events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

## Pick the correct manual entry

| Intent | Entry | Boundary |
| --- | --- | --- |
| Prepare a stable-release proposal | Release / 1 Propose PR | Does not release software. Review fresh refs/checks and follow the release policy before any merge. |
| Validate packaging without publication | Release / 2 Publish, target `dry-run` | No production Release assets, PyPI or tap writes. |
| Exercise staging package upload | Release / 2 Publish, target `testpypi` | Writes TestPyPI; does not publish production artifacts or update the tap. |
| Publish stable packages | Release / 2 Publish, target `pypi` | Production side effects; requires separate explicit release approval. Main pushes select this target automatically. |
| Retry Homebrew after PyPI already succeeded | Release / 3 Homebrew | Use the already published version and original rebuild number. This can upload production bottles and change the stable tap. |
| Prepare post-release synchronization | Release / 4 Propose sync | Wait for publication/version-writer settlement; merging the resulting PR needs separate approval. |

Use filenames for CLI dispatch and run lookup so display-name changes do not
break operator commands. For example, `gh run list --workflow release.yml` reads
the publishing workflow, while `gh run list --workflow scheduled-release-pr.yml`
reads proposal runs. A green proposal is not evidence of a published package.

See [release governance](release-train.md) for exact-SHA approval, writer pauses,
normal merge requirements and reviewed sync-back. See
[Homebrew distribution](homebrew-distribution.md) for bottle acceptance and
same-version recovery. Never use squash/rebase for promotion or sync.

## Sidebar ownership and historical entries

CodeQL, Copilot and Dependency Graph entries are GitHub-managed workflows. They
are outside this repository's YAML naming scheme. Their labels and visibility
must be managed through the corresponding GitHub feature settings.

The 2026-10-31 Actions inventory also lists `.github/workflows/pr-dev-preview.yml`
and `.github/workflows/pr-dev-release.yml`, although neither file exists in the
current source. They are historical registrations, not additional preview
implementations. The current preview path is ci -> Preview /
Homebrew. Retain historical run evidence during release recovery; do not recreate
obsolete YAML files just to rename the entries or delete runs to tidy the sidebar.
Any remote disabling or historical-run cleanup is a separate administrative
operation and is not performed by this source change.

Names and run titles become visible when the corresponding GitHub workflow
revision is loaded. Default-branch consumers and retained historical entries may
continue to show older labels during rollout; local lint does not establish that
the remote sidebar has changed.

The CI rename uses a two-phase rollout to keep PR previews working:

1. This change retains the producer name `ci` and stages the preview consumer
   with both `ci` and `Checks / Python` filters. CI run titles already use the
   grouped label; the sidebar retains `ci` during this transition. The trusted
   producer path and provenance checks remain unchanged.
2. After a separately approved main promotion, inspect the live default-branch
   consumer and verify both names are accepted. Only then may a follow-up PR
   rename the producer to `Checks / Python` and update the phase-one test.
3. Verify a fresh eligible PR preview after that rename. Keep the old `ci`
   filter while older PR branches/runs still use it; remove it in a reviewed
   follow-up only after that inventory is clear. Missed runs are not replayed
   automatically, so do not introduce a deliberate gap or dispatch production
   merely to refresh sidebar labels.

The publish/sync rename reaches main together; verify its trigger during the
approved release settlement. A failed bottle verification may leave immutable
assets on the release, while the stable tap still retains its prior formula.

## Design rationale

The previous sidebar mixed file paths, generic `ci`/`release` labels, product
names and scheduled tasks at the same level. File paths drew disproportionate
attention, while "Scheduled Release PR" obscured the difference between proposing
and publishing a release. Consistent category prefixes support scanning; numbered
release verbs make the lifecycle visible without merging workflows across their
different execution and credential boundaries.

Keep GitHub's native typography, contrast, focus states and target sizes. The
source change addresses text hierarchy and operational clarity; screenshot
inspection alone does not establish contrast ratios or keyboard accessibility.
Text prefixes carry meaning without color or emoji. Existing distinct preview
and stable labels remain explicit because those paths have different costs and
publication consequences.
