# Data Model: Runtime Native Refactor

## Session (`src/gh_address_cr/core/session.py`)
The Session object represents the state of a PR review process. It is stored as `session.json`.

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Unique UUID for the session |
| `repo` | `str` | Repository identifier (owner/repo) |
| `pr_number` | `str` | Pull Request number |
| `status` | `str` | Overall session status (OPEN, ACTIVE, COMPLETED, etc.) |
| `items` | `dict[str, Item]` | Map of item IDs to their state and metadata |
| `leases` | `dict[str, Lease]` | Map of active/expired claim leases |
| `metadata` | `dict` | Extension-specific metadata |

## Finding (`src/gh_address_cr/intake/findings.py`)
A normalized finding before it is converted into a session item.

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | File path relative to repository root |
| `line` | `int` | Line number (1-based) |
| `title` | `str` | Brief summary of the finding |
| `body` | `str` | Detailed description or AI instruction |
| `source` | `str` | Identifier of the review producer |

## Item State Transitions
Transitions are governed by the `src/gh_address_cr/core/workflow.py` module.

- `OPEN` -> `CLAIMED` (via `agent next`)
- `CLAIMED` -> `ACCEPTED` / `FIXED` / `CLARIFIED` / `DEFERRED` (via `agent submit`)
- `FIXED` -> `VERIFIED` (via `agent submit` by verifier)
- `VERIFIED` -> `CLOSED` (via `final-gate`)
- `*` -> `STALE` (via timeout) -> `OPEN` (via `reclaim`)
