# Architecture Preflight: Spec 039 R2 (primary_action recommends `agent resolve`)

Trigger: changes Status-to-Action Map behavior (AGENTS.md blast-radius list).
Decision input: Q1 resolved by the maintainer as "recommend `agent resolve`".

| Item | Answer |
|---|---|
| Authoritative state owner | Unchanged. The runtime store owns item state, classification evidence, and leases. `primary_action` stays an advisory projection (`core/primary_action.py`) that reads the session and mutates nothing. |
| External facts / event inputs | Unchanged: refreshed GitHub review threads and session items. |
| Projection shape | Same `primary_action` fields. For an unresolved, unreplied GitHub thread: `kind` `claim` → `resolve`; `command` `agent next --role fixer --item-id <id>` → `agent resolve <repo> <pr> <id> --commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed>`. The action vocabulary set is unchanged (`claim` stays a valid kind). |
| Decision function | One branch of `project_primary_action`. Ordering is unchanged: publish-ready before unresolved threads, `wait` after a recorded side effect, local findings after threads. |
| Side-effect plan | None added. `agent resolve` already owns claim → classify → submit in one lease (`handle_agent_resolve`); GitHub side effects remain behind `agent publish`. |
| Artifact truth / telemetry self-reference | No new artifacts. The `primary_action.projected` span event keeps reporting `kind`; dashboards keyed on `kind=claim` for threads will now see `resolve`. |
| Contract docs | `skill/references/status-action-map.md` and `README.md` now allow placeholders only for agent-produced evidence (`<sha>`, `<paths>`, `<text>`, `<cmd=passed>`). |
| Recovery / replay | A session projected before the change and resumed after it just gets the new recommendation; no persisted state depends on the old command. |
| Executable contract tests | `tests/test_primary_action.py` (projection), `tests/contract/test_agent_journey_contract.py::test_i1_every_primary_action_command_is_accepted` (the README loop completes to `final-gate PASSED` with zero rejections). |

Reduces state space: the recommendation no longer depends on whether classification evidence exists, because the recommended command records it.
