# Installation and Distribution

## Installation

### Install the released runtime CLI

Use this path when you want the stable `gh-address-cr` executable from PyPI. The runtime CLI requires Python 3.10 or newer.

```bash
pipx install gh-address-cr
gh-address-cr --help
python -m gh_address_cr --help
```

The `uv` equivalent is:

```bash
uv tool install gh-address-cr
gh-address-cr --help
python -m gh_address_cr --help
```

These commands install the Python runtime package. They do not install or update the packaged skill adapter under `skill/`.

### Install with Homebrew

Use this path when you want the stable `gh-address-cr` executable through Homebrew on macOS or Linuxbrew. Homebrew installs the same released runtime package from the PyPI sdist through the `RbBtSn0w/homebrew-tap` formula.

```bash
brew tap RbBtSn0w/tap
brew install gh-address-cr
gh-address-cr --help
gh-address-cr agent manifest
```

Upgrade and test the installed formula with:

```bash
brew upgrade gh-address-cr
brew test gh-address-cr
```

The Homebrew tap installs the runtime CLI only. It does not install or update the packaged skill adapter under `skill/`.

### GitHub-direct runtime validation install

Use this path only for pre-release validation of the current repository state before a PyPI release is available.

```bash
pipx install git+https://github.com/RbBtSn0w/gh-address-cr.git
gh-address-cr --help
gh-address-cr agent manifest
```

The `uv` equivalent is:

```bash
uv tool install git+https://github.com/RbBtSn0w/gh-address-cr.git
gh-address-cr --help
gh-address-cr agent manifest
```

### Local editable development install

Use this path when editing this repository.

```bash
python3 -m pip install -e .
gh-address-cr --help
python3 -m gh_address_cr --help
gh-address-cr agent manifest
```

### Packaged skill install

Use this path when installing the Codex/agent skill adapter. This does not install the runtime CLI package; install the runtime separately with `pipx`, `uv tool`, GitHub-direct validation, or local editable development commands above.

```bash
npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill skill
npx skills check
```

After installing the skill, verify that a runtime CLI is available:

```bash
gh-address-cr --help
gh-address-cr adapter check-runtime
```

### Repo-local Codex Plugin package

The repo-local plugin wrapper is generated from `skill/` and lives at
`plugin/gh-address-cr/`. It packages the existing skill instructions for Codex
Plugin installation surfaces and does not add MCP servers, ChatGPT UI, or runtime
business logic.

```bash
python3 scripts/build_plugin_payload.py
python3 scripts/build_plugin_payload.py --check
```

### Community Codex Marketplace install

This repository includes a repo marketplace at `.agents/plugins/marketplace.json`.
After the plugin payload is committed to `main`, developers can add the
marketplace and install `gh-address-cr` from Codex:

```bash
codex plugin marketplace add RbBtSn0w/gh-address-cr --ref main
codex plugin marketplace upgrade
```

For releases, prefer pinning a tag:

```bash
codex plugin marketplace add RbBtSn0w/gh-address-cr --ref v2.5.1
```

The OpenAI curated Plugin Directory is not a self-service publish target in this
repository. Use this marketplace file as the community distribution path and
prepare a curated-review packet with the repository URL, plugin path
(`plugin/gh-address-cr`), privacy/terms/security links, screenshots, and current
verification output.

### Upgrade from skill-shim usage

If you previously relied on `python3 skill/scripts/cli.py` from an older version of the packaged skill, that path has been removed. Install the runtime CLI with `pipx` or `uv tool`:

```bash
pipx reinstall gh-address-cr
# or
uv tool upgrade gh-address-cr
```

Then verify:

```bash
gh-address-cr --help
gh-address-cr agent manifest
```

If PyPI does not yet contain `gh-address-cr`, use the GitHub-direct runtime validation install until a release is published.

Runtime install for local development:

```bash
python3 -m pip install -e .
gh-address-cr --help
python3 -m gh_address_cr --help
gh-address-cr adapter check-runtime
```

Native runtime ownership is now split by responsibility:

- `src/gh_address_cr/core/session.py`: PR-scoped session loading, saving, and workspace paths
- `src/gh_address_cr/core/workflow.py`: agent classification, leases, action requests, accepted responses, and deterministic publishing transitions
- `src/gh_address_cr/core/gate.py`: final-gate policy evaluation and the native `Gatekeeper`
- `src/gh_address_cr/github/client.py`: GitHub CLI IO for thread listing, replies, resolves, and pending reviews
- `src/gh_address_cr/intake/findings.py`: findings parsing, normalization, source-scoped fingerprints, and fixed finding blocks
- `src/gh_address_cr/commands/`: current internal command modules behind supported public commands

The native packages under `core/`, `github/`, and `intake/` must not depend on removed script-path compatibility shims.
Public commands such as `active-pr`, `review`, `address`, `threads`, `findings`, `adapter`, `agent`, and `final-gate` are routed through the native runtime package. Historical direct script commands are rejected with unsupported-legacy guidance.


## Install with npx skills

```bash
npx skills add https://github.com/RbBtSn0w/gh-address-cr --skill skill
```


## Build the repo-local Codex Plugin

```bash
python3 scripts/build_plugin_payload.py
python3 scripts/build_plugin_payload.py --check
```

The generated plugin package is `plugin/gh-address-cr/`. It contains
`.codex-plugin/plugin.json`, one bundled skill at `skills/gh-address-cr/`, and
presentation assets. It intentionally does not include `.app.json`, `.mcp.json`,
or any ChatGPT Apps SDK server metadata.


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
