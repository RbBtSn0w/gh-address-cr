---
name: speckit-superb-respond
description: Verify supplied review feedback and apply only accepted in-scope fixes.
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: github-spec-kit
  source: superb:commands/respond.md
---

# Respond - Review Feedback

## User Context

```text
$ARGUMENTS
```

Resolve `receiving-code-review`. For each supplied finding, verify it against
the active Spec Kit artifacts and code, then classify it as accepted, rejected,
or requiring clarification.

If feedback changes requirement meaning, architecture, or task scope, stop code
changes and route to the earliest owning Spec Kit command: `speckit.clarify`,
`speckit.plan`, or `speckit.tasks`. Apply accepted in-scope fixes test-first and
report fresh evidence. Do not invent findings, broaden scope, or mark completion.

If the skill is unavailable, run
`bash .specify/extensions/superb/scripts/bash/ensure-skills.sh --print-guidance`
and direct the user to `/speckit.superb.check`; do not apply feedback blindly.