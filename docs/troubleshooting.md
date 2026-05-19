# Troubleshooting

## Troubleshooting final gate failure

If `gh-address-cr final-gate` fails:

1. Read the pending table in terminal output and the printed audit summary path.
2. Prefer the returned `next_action` and `commands` templates; common recovery starts with `gh-address-cr address <owner/repo> <pr_number> --lean` or `gh-address-cr agent publish <owner/repo> <pr_number>`.
3. For each pending or invalid terminal thread, verify both operations were completed through the runtime: reply evidence and thread resolve.
4. For file-matched stale threads, use `gh-address-cr agent resolve-stale <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --match-files`, then publish and rerun final-gate.
5. If the summary reports missing reply evidence, publish the accepted evidence before re-running `gh-address-cr final-gate`.


## Troubleshooting installation and release

- Unsupported Python: use Python 3.10 or newer through `pipx`, `uv tool`, or a local virtual environment.
- Missing PyPI package: `gh-address-cr` may not have been published yet. Use the GitHub-direct runtime validation install for pre-release validation.
- Missing Trusted Publishing: production PyPI publishing must use GitHub OIDC with the PyPI project `gh-address-cr`, repository `RbBtSn0w/gh-address-cr`, workflow `.github/workflows/release.yml`, no GitHub environment constraint, and `id-token: write`.
- Missing release-bot GitHub App credentials: production Homebrew publishing requires the shared release-bot GitHub App installed on `RbBtSn0w/homebrew-tap`, `RELEASE_BOT_APP_ID` exposed as an Actions variable, and `RELEASE_BOT_PRIVATE_KEY` exposed as an Actions secret to this repository.
- Stale artifact version: release-built wheel and sdist metadata must match the semantic-release version. If a publish partially succeeds, inspect PyPI before retrying because uploaded files are immutable.
- Homebrew tap update failure: inspect the `publish-homebrew` job after confirming PyPI upload succeeded. The job renders `Formula/gh-address-cr.rb` from the PyPI sdist, runs `brew update-python-resources`, `brew audit --formula --strict`, `brew install --build-from-source`, and `brew test` before pushing the tap update.
- Installed smoke domain failure: `agent orchestrate status` may report a missing session and `final-gate` may report `Final gate failed to evaluate: error connecting to api.github.com` when GitHub state or network access is unavailable. These are acceptable smoke outcomes only when there is no traceback, missing import, or missing console entrypoint.
- Skill install confusion: `npx skills add ... --skill skill` installs the packaged skill adapter only. It does not install the runtime CLI package.
- Skill-shim migration confusion: if `python3 skill/scripts/cli.py` works from a checkout but `gh-address-cr` is unavailable, install or reinstall the runtime CLI with `pipx` or `uv tool`.
