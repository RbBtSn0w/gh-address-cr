# CI Generated Plugin Payload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `skill/` the single maintained source for the Codex plugin payload and have CI/release generate `dist/plugin/gh-address-cr` instead of requiring developers to keep a copied tree in sync.

**Architecture:** `scripts/build_plugin_payload.py` remains the deterministic builder for plugin manifests, assets, and bundled skill content. CI and release workflows generate the plugin payload into an ignored build directory, validate that generated directory, and upload or publish it as the deployable product artifact. Repository docs and tests describe `skill/` as the source and the generated plugin directory as a build output.

**Tech Stack:** Python 3.10+, `unittest`, GitHub Actions, semantic-release.

---

### Task 1: Contract Tests For Generated Payload

**Files:**
- Modify: `tests/test_plugin_packaging.py`
- Modify: `tests/test_cli_skill_sync_artifacts.py`

- [ ] **Step 1: Replace committed-tree assumptions with generated-output assertions**

Update plugin packaging tests so they build into a temporary directory and validate `plugin.json`, `.codex-plugin/plugin.json`, assets, and bundled skill files there.

- [ ] **Step 2: Run targeted tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_plugin_packaging tests.test_cli_skill_sync_artifacts
```

Expected: fail because `scripts/build_plugin_payload.py` does not yet support an output directory contract and docs/workflows still depend on the committed plugin tree.

### Task 2: Builder Output Contract

**Files:**
- Modify: `scripts/build_plugin_payload.py`

- [ ] **Step 1: Add explicit `--output` support**

Allow callers to generate a plugin payload outside `plugin/gh-address-cr`.

- [ ] **Step 2: Keep repo-local default for manual builds**

Running `python3 scripts/build_plugin_payload.py` should still build `plugin/gh-address-cr` for local inspection, but CI/release should use explicit generated directories.

- [ ] **Step 3: Make `--check` validate generated content without requiring committed duplicated payload files**

The check should build into a temporary directory and report success when the builder can create a valid payload. It should not compare against `plugin/gh-address-cr` as a committed source tree.

### Task 3: CI And Release Generation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `release.config.cjs`

- [ ] **Step 1: Generate plugin payload in CI**

Replace the old payload sync check with generation into `dist/plugin/gh-address-cr` or another ignored build location.

- [ ] **Step 2: Generate and upload release plugin artifact**

Release should generate a plugin payload after resolving the package version and upload it as an artifact for deployment/inspection.

- [ ] **Step 3: Stop semantic-release from committing generated plugin manifests**

Semantic-release should commit version and changelog files, while plugin payload manifests are generated in CI/release.

### Task 4: Docs And Marketplace Boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/installation.md`
- Modify: `.agents/plugins/marketplace.json` if the install path contract changes

- [ ] **Step 1: Document `skill/` as source and plugin as generated artifact**

Remove wording that tells developers to maintain or commit a duplicated plugin tree.

- [ ] **Step 2: Document the CI/release generation command**

Show explicit `--output dist/plugin/gh-address-cr` usage for generated deployment artifacts.

### Task 5: Verification And Review

**Files:**
- All changed files

- [ ] **Step 1: Run required verification**

```bash
ruff check src tests scripts/build_plugin_payload.py
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
python3 -m gh_address_cr agent manifest
python3 scripts/build_plugin_payload.py --check
git diff --check
```

- [ ] **Step 2: Review diff for contract regressions**

Inspect `git diff` and ensure public identity remains `gh-address-cr`, the published skill boundary remains `skill/`, and CI/release now generate the plugin payload.

- [ ] **Step 3: Commit and open PR**

Use a Conventional Commit message and create a PR that explains the CI-generated payload boundary and verification output.
