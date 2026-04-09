# gh-address-cr skill

An auditable GitHub PR review-comments workflow skill for AI coding agents.

It is designed to process CR threads one by one, enforce evidence-first replies,
and require a final freshness gate before declaring completion.
For handled threads, replying and resolving are two separate required operations.

By default, the skill stores its PR progress + audit artifacts in a user cache directory
(override with `GH_ADDRESS_CR_STATE_DIR`). If the cache is purged, the workflow can be rebuilt
from GitHub thread state; the main downside is potential repeated work.

## Core Workflow

```text
       [ Start PR Review Resolution ]
                   |
                   v
+-------------------------------------+      (Fetch PR threads, exclude handled)
|          1. run_once.sh             | <-----------------------------------------+
+------------------+------------------+                                           |
                   |                                                              |
                   v [Generates Snapshot & Unresolved List]                       |
                   |                                                              |
+------------------+------------------+      (THE "BRAIN" STEP: Analyze & Decide) |
|    2. Analysis & Decision Matrix    |                                           |
+------------------+------------------+                                           |
                   |                                                              |
         +---------+---------+-----------------------+                            |
         |                   |                       |                            |
    [ ACCEPT ]          [ CLARIFY ]             [ DEFER ]                         |
   (Bug/Logic)        (Misunderstood)       (High-cost Nit)                       |
         |                   |                       |                            |
         v                   v                       v                            |
+--------+--------+ +--------+--------+     +--------+--------+                   |
| 3a. Change Code | | 3b. Explain     |     | 3c. Explain     |                   |
|     & Test      | |     Logic       |     |     Trade-offs  |                   |
+--------+--------+ +--------+--------+     +--------+--------+                   |
         |                   |                       |                            |
         v                   v                       v                            |
+--------+--------+ +--------+--------+     +--------+--------+                   |
| 4a. generate_   | | 4b. generate_   |     | 4c. generate_   |                   |
|    reply.sh     | |    reply.sh     |     |    reply.sh     |                   |
|    --mode fix   | |  --mode clarify |     |   --mode defer  |                   |
+--------+--------+ +--------+--------+     +--------+--------+                   |
         |                   |                       |                            |
         +---------+---------+-----------------------+                            |
                   |                                                              |
                   v [Generates /tmp/reply.md]                                    |
                   |                                                              |
+------------------+------------------+      (GitHub API: Reply)                  |
|         5. post_reply.sh            |                                           |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (MANDATORY for all paths)            |
|       6. resolve_thread.sh          |      (Local state marked 'Handled')       |
+------------------+------------------+                                           |
                   |                                                              |
+------------------+------------------+      (HARD GATE: Re-fetch GitHub state)   |
|         7. final_gate.sh            |-------------------------------------------+
+------------------+------------------+      [ Failed: Unresolved > 0 (Loop back) ]
                   |
                   | [ Passed: Unresolved == 0 ]
                   v
+-------------------------------------+
|         8. Audit Summary            |      (Output SHA256 & Final Confirmation)
+-------------------------------------+
                   |
                   v
               [ Done ]
```

## Install with npx skills

```bash
npx skills add https://github.com/RbBtSn0w/gh-address-cr-skill --skill gh-address-cr
```

## Breaking changes (2026-04-09)

- `scripts/batch_resolve.sh` now requires an approved list format:
  - one thread per line: `APPROVED <thread_id>`
  - empty lines and `#` comments are allowed
  - raw thread-id lines now fail fast
- `scripts/list_threads.sh` now uses the latest thread comment as primary context and emits:
  - `comment_source` (`latest|first|none`)
  - `first_url`, `latest_url`
  - `url`/`body` remain available, now latest-first with fallback

## Update model (official `skills` behavior)

`npx skills update` is driven by the lock file and remote folder hash, not by git tag directly.

- Lock file name: `.skill-lock.json`
- Typical path: `~/.agents/.skill-lock.json`
- Optional path when `XDG_STATE_HOME` is set: `$XDG_STATE_HOME/skills/.skill-lock.json`
- Update comparison key: `skills.<skill-name>.skillFolderHash` (GitHub tree SHA of the skill folder)

### User-side update commands

```bash
# Check whether updates are available
npx skills check

# Update installed skills
npx skills update
```

### Provider-side release policy

- Keep skill identifier stable:
  - `SKILL.md` frontmatter `name` should stay stable
  - skill folder path should stay stable
  - source repo (`owner/repo`) should stay stable
- Publish all releasable changes to `main` so `skillFolderHash` can change and be detected by `check/update`.
- Use semantic version tags + changelog for human-readable release management.

## What this skill provides

- Strict per-thread CR handling workflow
- Required evidence format (commit/files/test result)
- Mandatory final gate (`final_gate.sh`) before completion
- PR-scoped state tracking to avoid duplicate work
- Audit log + audit summary + summary hash output

## Skill folder

- `gh-address-cr/`
  - `SKILL.md`
  - `agents/openai.yaml`
  - `scripts/*.sh`
  - `assets/reply-templates/*`
  - `references/cr-triage-checklist.md`

## Quick usage after installation

```bash
scripts/run_once.sh --audit-id run-YYYYMMDD owner/repo 123
scripts/post_reply.sh --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id> /tmp/reply.md
scripts/resolve_thread.sh --repo owner/repo --pr 123 --audit-id run-YYYYMMDD <thread_id>
scripts/final_gate.sh --auto-clean --audit-id run-YYYYMMDD owner/repo 123
```

## Troubleshooting final gate failure

If `scripts/final_gate.sh` fails:

1. Read the pending table in terminal output and the printed audit summary path.
2. For each pending thread, verify both operations were completed: `post_reply` and `resolve_thread`.
3. Re-run `scripts/run_once.sh --show-all ...` to compare unresolved vs handled state.
4. Resolve remaining threads, then re-run `scripts/final_gate.sh`.

## CI semantic release (tag + changelog)

This repo includes a `semantic-release` workflow:

- Trigger: push to `main`
- Input: Conventional Commits history
- Output: semantic version tag (`vX.Y.Z`) + GitHub Release + `CHANGELOG.md`

Commit format examples:

```text
feat: add strict unresolved-thread guard in final gate
fix: avoid duplicate handled-state writes when thread already resolved
docs: clarify npx skills update behavior
```
