# Release train

The active policy is the [Main release train](release/main-train.md). `main` is
the only integration trunk; task PRs use Conventional Commit squash metadata.
Friday 07:00 UTC and manual main dispatch use the same verification and dependent
publication path. `RELEASE_ENABLED` must explicitly equal `true`.

The previous develop promotion, sync-back, guarded branch-controller and preview
workflows are retired by this migration. Historical reports and approvals do not
authorize their reactivation. Do not delete remote branches, rewrite history or
change external timers, protection or credentials as part of this source change.
