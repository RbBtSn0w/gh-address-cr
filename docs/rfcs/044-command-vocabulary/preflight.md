# Spec 044: One vocabulary for command names

Architecture Preflight and decision record for consolidating the hand-maintained
command-name lists. Current code, tests, and `AGENTS.md` govern execution. This is a
static design reference, not an active-task pointer.

## Decision

Converge the **vocabulary**, not the **behavior**.

1. Add one small module that owns the passive command names: the top-level public
   commands and the `agent` subcommands. `src/gh_address_cr/cli.py`,
   `src/gh_address_cr/commands/agent.py`, the telemetry allowlist in
   `src/gh_address_cr/core/telemetry_safety.py` and the argparse `metavar` all derive from it.
2. Route the nine non-`manifest` `agent` handlers through a dispatch dictionary. Their shared
   signature makes the dictionary the source of the routed names. `manifest` is the tenth
   `AGENT_SUBCOMMANDS` entry and remains a separate special case. Derive the usage text from
   the complete ordered vocabulary.
3. Do **not** introduce a command registry or framework, and do **not** move command
   validation into argparse (`choices` or subparsers).

This is a separate refactor change. It must not be bundled into a telemetry privacy fix
(Spec 042 addendum) or a telemetry attribute change (Spec 043).

## Problem (verified)

On `develop` today the command names are encoded in six places that are edited by hand;
the command-name allowlist change (#357) adds a seventh, listed last:

| Place | Names | State today |
| --- | --- | --- |
| `PUBLIC_COMMANDS` in `src/gh_address_cr/cli.py` | 14 top-level | built from several behavior sets |
| `PUBLIC_COMMANDS` in `src/gh_address_cr/commands/agent.py` | 14 top-level | literal copy of the one above |
| `_PUBLIC_TELEMETRY_COMMANDS` in `src/gh_address_cr/core/telemetry_safety.py` | 13 top-level | **omits `version`** |
| argparse `metavar` in `parse_args` (`src/gh_address_cr/cli.py`) | 13 top-level | **omits `agent`** |
| `usage:` string in `_route_agent_command` (`src/gh_address_cr/commands/agent.py`) | 10 `agent` subcommands | literal |
| the `if args.repo == ...` chain in `_route_agent_command` | 10 `agent` subcommands (`manifest` plus nine handlers) | literal |
| `AGENT_SUBCOMMANDS` in `src/gh_address_cr/commands/agent.py` | 10 `agent` subcommands | **not on `develop` yet**: introduced by #357 |

Drift that has already happened:

- The telemetry allowlist was written in one step by #219 (2026-07-25). No document gives a
  reason for leaving out `version`, and no test depends on it; it reads as an omission.
- `agent` is missing from the user-facing `--help` command list (it was already missing
  when #51 edited that line on 2026-05-11, and still is).
- When the retired `telemetry` command was removed, the `metavar` changed on 2026-07-01
  (#175) and the dispatcher on 2026-07-02 (#182): two commits, synchronized by hand.

How often the sets change (first appearance of each literal in the git history):

- The 14 top-level commands were all added between 2026-04-29 and 2026-06-04.
- The 10 `agent` subcommands were all added between 2026-04-29 and 2026-06-13.
- Nothing has been added since, about four months.

Constraints that bound the solution:

- The unknown-command message is asserted at five test sites: `Unknown command. Supported
  commands:` exactly in `tests/test_cr_loop.py`, `tests/test_python_wrappers.py` (twice) and
  `tests/test_runtime_packaging.py`, and `unknown command` case-insensitively in the same file.
  It is a tested public error contract.
- `agent manifest` exposes `public_commands` (sorted). Tests rely on it (documented commands
  must be a subset of it in `tests/test_skill_docs.py`; membership checks in
  `tests/test_runtime_packaging.py`). It is a machine-readable contract (AGENTS.md Principle II)
  and must stay byte-identical.
- `src/gh_address_cr/cli.py` has six behavior sets (`OUTPUT_MODE_COMMANDS`, `NATIVE_REVIEW_COMMANDS`,
  `UTILITY_COMMANDS`, `PR_SCOPED_IMPLICIT_COMMANDS`, `GITHUB_PRECHECK_COMMANDS`,
  `INPUT_REQUIRED_COMMANDS`) used across three dispatch stages. They say what a command
  does, not what it is called.
- The nine `handle_agent_*` handlers routed by `_route_agent_command` all have the signature
  `(repo, passthrough)`. `manifest` is the tenth subcommand name; it is answered by
  `build_agent_manifest()` and is special-cased.
- The repository has no registry or dispatch-table precedent (Principle X: no new layer
  without a recorded justification).

## Preflight

| Item | Decision |
| --- | --- |
| Authoritative state owner | None. A static vocabulary in code, not runtime state. `runtime.sqlite3` is unaffected. |
| External facts / inputs | The set of command names the CLI accepts. Changes only when a command is added or removed. |
| Projection | `src/gh_address_cr/core/command_names.py`: `PUBLIC_COMMANDS` (frozenset) and `AGENT_SUBCOMMANDS` (an ordered tuple, because its order is the order shown in usage text). The module imports nothing from `src/gh_address_cr/cli.py` or `src/gh_address_cr/commands/`, so `core` can depend on it. |
| Policy | Membership only. Consumers derive their sets from the vocabulary. The behavior sets stay in `src/gh_address_cr/cli.py` and are tested to be subsets of `PUBLIC_COMMANDS`. `agent` routing becomes a dictionary from the nine non-`manifest` names to handlers; `manifest` stays a special case, and all ten names remain in `AGENT_SUBCOMMANDS`. |
| Side-effect plan | None. No IO, no GitHub writes. |
| Artifact truth boundary | `agent manifest` output is unchanged. `--help` output changes in exactly one way: `agent` appears in the command list. |
| Self-reference risk | None. |
| Telemetry impact | Decision: the telemetry allowlist becomes the public vocabulary, which adds `version`. For `version` invocations (a few hundred root spans per week) the root `gen_ai.tool.name` changes from `gh-address-cr` to `version`, and `process.command_args` keeps the `version` token instead of redacting it. The command name is not sensitive. If maintainers prefer to keep `version` out, express it as an explicit, commented exclusion rather than an accidental omission. Record the chosen outcome in the change description. |
| Recovery / replay | Revert the change. No data migration. |

## Options considered

| | A. Keep, guard with tests | **B. Vocabulary module and dictionary dispatch for `agent`** | C. Full command registry | D. argparse subparsers or `choices` |
| --- | --- | --- | --- | --- |
| Complexity | Low | Low to medium | High | High |
| Size | none | about +55 / -45 source lines, 4 files | rewrite of 3 dispatch stages and 6 sets | rewrite of the parsing layer |
| Drift protection | tests only | passive duplicates removed structurally | strongest | strongest |
| Public contract risk | none | low (one `--help` line) | medium | **high**: error wording and usage output change, five tests fail |
| Principle X (minimal baseline) | fine | fine | needs a written justification and yields almost no benefit at zero additions in four months | not justified |

## Trade-off analysis

1. **Vocabulary versus behavior.** Names that are only displayed, validated or allowlisted
   benefit from one source. Sets that decide how a command runs are logic; folding them into
   a table would hide which dispatch stage owns a command and add an abstraction with a single
   consumer.
2. **The consequence of drift is mild and silent.** Telemetry mislabels a real command, help
   text omits one. Nothing crashes, so the cost of leaving it is low. That argues against C
   and for a small structural fix (B).
3. **Why dictionary dispatch for `agent`.** The nine routed handlers share one signature, so
   the table is almost free and makes the routed names structural instead of something a test
   must infer. The shared vocabulary, not the dictionary, supplies the top-level command set
   that telemetry needs. (An earlier draft of the command-name allowlist change, #357, scraped
   `_route_agent_command` source text to check the routed names; review replaced that with a
   behavioral probe, which stays valid after this change.)
4. **Why not D.** The unknown-command message and exit behavior are tested public behavior;
   argparse's own `invalid choice` output would change both.

## Consequences

- Easier: adding a command or `agent` subcommand cannot be silently treated as `unknown` by
  telemetry; `--help` lists every command; fewer lists to keep in step by hand.
- Harder: one more small module; a visible one-line `--help` change that must be called out.
- To revisit: if two or more commands are added in a quarter, or a third consumer needs
  per-command attributes, reconsider option C.

## Work breakdown

One refactor PR, after the Spec 042 addendum and Spec 043 changes have landed, branched from
`origin/develop`. High-risk tier, so about 100 source lines or fewer:

1. `src/gh_address_cr/core/command_names.py` with the two constants;
   `src/gh_address_cr/cli.py`, `src/gh_address_cr/commands/agent.py` and
   `src/gh_address_cr/core/telemetry_safety.py` import from it; the `metavar` is generated
   from it.
2. `_route_agent_command` dispatches the nine non-`manifest` names through a dictionary;
   `AGENT_SUBCOMMANDS` contains those names plus `manifest`, and the usage line derives from
   the complete ordered vocabulary.
3. Keep the behavioral routing probe, the usage-line test and the list-consistency test from
   #357; with dictionary dispatch they guard a structural guarantee rather than being the
   only protection.
4. Commits: vocabulary module first, then `agent` dispatch, then tests and docs.

## Executable contract tests

- `agent manifest` output is byte-identical before and after (golden comparison).
- `--help` differs only by the added `agent`; `Unknown command. Supported commands:` output,
  and its exit code, are unchanged.
- Every behavior set in `src/gh_address_cr/cli.py` is a subset of `PUBLIC_COMMANDS`; `cli`, `agent` and
  telemetry use the same object or an equal set.
- The dictionary keys plus `manifest` equal `AGENT_SUBCOMMANDS`, and the `usage:` line lists
  exactly all ten names in order.
- Telemetry: `version` is exported by name; unrecognized text is still exported as `unknown`
  (Spec 042 addendum).

## Limitations

- The change-frequency figures come from the first appearance of each literal in git history,
  an approximation.
- No code was changed to produce this record; it rests on reading `src/`, `tests/` and the
  git history as of 2026-10-12.
