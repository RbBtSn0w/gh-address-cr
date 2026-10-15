# Spec 043: Root-span invocation kind

Architecture Preflight for a change that adds one attribute to the telemetry
reporting contract. Current code, tests, and `AGENTS.md` govern execution. This
is a static design reference, not an active-task pointer.

## Problem (verified)

Production Honeycomb data (7 days, 1214 root spans of `gh-address-cr.cli`):

- 617 (50.8%) reached command dispatch and carry `gh_address_cr.command.path` and
  `gh_address_cr.command.exit_code`.
- 591 (48.7%) were `--help`, `-h`, `--version` or no-argument calls. They exit inside
  argparse before dispatch, so they carry only `process.exit.code`, last under a
  millisecond, and appear in every released version. Their source is not established:
  only 17 of the 591 (2.9%) carry an agent session, and 499 have a parent PID below 5000
  (container or automation style PIDs) in per-version bursts, so the traffic cannot be
  attributed to interactive agents. (The skill does document `--help` as the command
  inventory step, but the data does not show that this explains the volume.)

Any metric that counts root spans as invocations is therefore inflated by roughly
2x, and there is no field that separates a help probe from a real command or from
a usage error. `process.exit.code` alone cannot (a probe and a successful command
both exit 0).

## Preflight

| Item | Decision |
| --- | --- |
| Authoritative state owner | None new. The attribute is observed evidence on the root span (Principle VIII); it never feeds review state or `final-gate`. |
| External facts / inputs | Whether `argparse` exited inside `parse_args`, and how: the `SystemExit` type (`--version` raises a dedicated subclass) and its exit status. argv text is not an input. |
| Projection | `gh_address_cr.invocation.kind`, a closed enum: `command` (parsing succeeded and the command was dispatched or rejected by dispatch), `help` (parsing exited 0 on `-h`/`--help`), `version` (parsing exited 0 on `-v`/`--version`), `usage_error` (parsing exited non-zero). |
| Policy | Observed, not inferred. `--version` is handled by a custom argparse action that prints the same text as before and raises a `SystemExit` subclass, so `cli.main` classifies it by type. Any other exit during parsing is classified by status: 0 is `help`, non-zero is `usage_error`. No parsing of argv text, so combined short flags (`-vh`), abbreviations and future options need no special cases. |
| Side-effect plan | None. One span attribute; exit codes, output and routing are unchanged (the `SystemExit` is re-raised untouched). |
| Artifact truth boundary | Not written to any artifact and not read by `final-gate`. |
| Self-reference risk | None. The value is known before the span ends and does not depend on telemetry. |
| Telemetry privacy | Fixed four-value enum. No argv text, paths, or identifiers. This is independent of the command-name allowlist (a parse-accepted unknown command stays `command`; its name is exported as `unknown`). |
| OTel layering | Attribute on the existing root span. No new child span and no promoted checkpoint. Nested `main` calls (command sessions) set it on the current child span only. |
| Recovery / replay | Both writes go through a best-effort helper (`_record_invocation_kind` in `src/gh_address_cr/cli.py`): an exception from the span write is swallowed, so a telemetry failure can neither replace the original `SystemExit` nor stop the command. The OpenTelemetry SDK's `set_attribute` does not raise for invalid values (it drops them), so this guards non-SDK span implementations. A missing value means an older runtime. |

## Alternatives rejected

- **Infer `help` versus `version` from argv text.** Re-implements argparse's matching
  (combined short flags such as `-vh`, abbreviations) outside argparse and drifts when the
  parser changes; an earlier draft did this and misclassified `-vh`.
- **Infer the kind from `command.path` presence in the backend.** Works today but
  silently breaks if dispatch ever sets the path earlier, and cannot tell `help`
  from `usage_error`.
- **Set it in `run_traced` on `SystemExit`.** `run_traced` is generic across CLI
  entry points; the argparse semantics belong in `cli.main` next to `parse_args`.
- **Add `invocation.kind` values per subcommand.** That duplicates `command.name`.
- **Stop the `--help` probes at their source.** The source is not identified (see the
  problem statement) and the probes are legitimate behaviour, not a telemetry defect, so
  this is out of scope.

## Executable contract tests

- `tests/test_invocation_kind.py`: kind for `--help`, `-h`, abbreviations (`--he`, `--vers`),
  `--version`, `-v`, combined short flags (`-vh`, `-hv`), flag order, global flags, no arguments
  and unknown or ambiguous flags (`usage_error`); kind `command` for `version`, `address -h`,
  `agent manifest` and a rejected unknown command; exit codes unchanged; `--version` and `-v`
  still print `gh-address-cr <version>` and `--help` still prints usage; the value always belongs
  to the closed enum; only dispatched invocations carry `command.path`; command-session
  operations classify themselves on their own spans without changing the root; a failing
  attribute write changes neither the exit code nor the command.

## Measure of success

In Honeycomb `production/gh-address-cr`, after upgrade: counting only
`gh_address_cr.invocation.kind = command` should remove roughly half of the
current root-span volume, and `help` should account for most of the remainder.
