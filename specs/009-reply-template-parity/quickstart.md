# Quickstart: Reply Template Parity

## Validate Fix Rendering

Run the native workflow tests:

```bash
PYENV_VERSION=3.10.19 /opt/homebrew/bin/pyenv exec python -m unittest tests.test_native_workflow
```

Expected result:
- Fix replies use severity-specific v1 template wording.
- Clarify/defer replies are templated instead of raw markdown.

## Validate Skill Parity

Run the auxiliary script tests:

```bash
PYENV_VERSION=3.10.19 /opt/homebrew/bin/pyenv exec python -m unittest tests.test_aux_scripts tests.test_skill_docs
```

Expected result:
- `skill/scripts/generate_reply.py` output matches runtime rendering.
- `skill/assets/reply-templates/*` stays aligned with the renderer contract.

## Full Verification

```bash
ruff check src tests
PYENV_VERSION=3.10.19 /opt/homebrew/bin/pyenv exec python -m unittest discover -s tests
PYTHONPATH=src PYENV_VERSION=3.10.19 /opt/homebrew/bin/pyenv exec python -m gh_address_cr --help
PYENV_VERSION=3.10.19 /opt/homebrew/bin/pyenv exec python skill/scripts/cli.py --help
git diff --check
```
