# Data Model: Remove Legacy Compatibility

## CurrentWorkflowSurface

Represents the active user-facing runtime behavior that remains supported.

**Fields**:

- `command_name`: Public command name.
- `classification`: `high_level`, `utility`, `runtime`, or `diagnostic`.
- `status`: `supported`.
- `evidence`: Documentation and tests that prove the command remains current.

**Validation rules**:

- Supported commands must be visible in current CLI help or current skill
  guidance when user-facing.
- Supported review commands must preserve machine summaries, reason codes, and
  final-gate behavior.

## SupersededCompatibilityPath

Represents historical behavior that must no longer be active.

**Fields**:

- `path_or_command`: The obsolete command name, script path, or input shape.
- `prior_purpose`: Why the path existed historically.
- `current_status`: `removed`, `unsupported`, or `archival`.
- `migration_target`: Current supported workflow or command.

**Validation rules**:

- Active runtime code must not dispatch through superseded script paths.
- Unsupported commands must fail before mutating session state or calling
  GitHub write operations.
- Retained docs must label the path as superseded or archival.

## UnsupportedUsageOutcome

Represents the result when a user attempts a removed compatibility path.

**Fields**:

- `exit_status`: Non-zero unsupported-usage exit.
- `message`: Clear reason that the legacy usage is unsupported.
- `migration_guidance`: Current supported command or workflow.
- `side_effects`: Must be empty for session mutation and GitHub writes.

**Validation rules**:

- Must be produced before review side effects.
- Must be actionable without requiring the user to inspect source code.

## HistoricalArtifact

Represents retained specs, plans, tasks, or references that mention old behavior
for audit context.

**Fields**:

- `artifact_path`: Repository path.
- `historical_reference`: The old behavior mentioned.
- `label_status`: `archival_marked` or `active_removed`.
- `authority_pointer`: Current feature/spec that owns active behavior.

**Validation rules**:

- Retained historical references must not be presented as current instructions.
- Active guidance must point to current runtime commands.
