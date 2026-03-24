# gh-address-cr skill

An auditable GitHub PR review-comments workflow skill for AI coding agents.

It is designed to process CR threads one by one, enforce evidence-first replies,
and require a final freshness gate before declaring completion.

By default, the skill stores its PR progress + audit artifacts in a user cache directory
(override with `GH_ADDRESS_CR_STATE_DIR`). If the cache is purged, the workflow can be rebuilt
from GitHub thread state; the main downside is potential repeated work.

## Install with npx skills

```bash
npx skills add https://github.com/RbBtSn0w/gh-address-cr-skill --skill gh-address-cr
```

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
