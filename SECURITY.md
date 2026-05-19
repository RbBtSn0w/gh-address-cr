# Security Policy

## Supported Versions

Security fixes target the current released `gh-address-cr` runtime and the
current `skill/` plus Codex plugin payload in the default branch.

## Responsible Disclosure

Please report security issues privately before opening a public issue. Use the
GitHub repository's private vulnerability reporting flow when available, or
contact the maintainer through the repository profile.

Useful details include:

- affected runtime version
- affected command
- whether GitHub writes were possible or performed
- relevant `reason_code`, `status`, and sanitized diagnostics
- whether telemetry export was enabled

Do not include tokens, private repository contents, email addresses, machine
names, or absolute local paths in public reports.

## Security Model

`gh-address-cr` relies on the local GitHub CLI (`gh`) and its configured
authentication. The runtime owns GitHub side effects, reply evidence, thread
resolve behavior, and final-gate evaluation. Skill and plugin instructions must
not bypass those runtime controls.

Telemetry export is opt-in and local audit files remain canonical.
