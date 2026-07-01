# Troubleshooting

## Troubleshooting final gate failure

If `gh-address-cr final-gate` fails:

1. Read the pending table in terminal output and the printed audit summary path.
2. Prefer the returned `next_action` and `commands` templates; common recovery starts with `gh-address-cr address <owner/repo> <pr_number> --lean` or `gh-address-cr agent publish <owner/repo> <pr_number>`.
3. For each pending or invalid terminal thread, verify both operations were completed through the runtime: reply evidence and thread resolve.
4. For file-matched stale threads, use `gh-address-cr agent resolve <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --stale --match-files`, then publish and rerun final-gate. This also recovers a thread that was batch-claimed (`agent next --batch`) and then became STALE: the command releases the resolving agent's own dangling lease before re-claiming, so it no longer deadlocks between the `--batch` resolve path (`STALE_THREADS_REQUIRE_RESOLVE_STALE`) and the `--stale` resolve path (`NO_ELIGIBLE_ITEM`).
5. If the summary reports missing reply evidence, publish the accepted evidence before re-running `gh-address-cr final-gate`.
6. If a thread was resolved out-of-band (a manual `gh` reply the runtime never posted) and the summary still reports `FINAL_GATE_MISSING_REPLY_EVIDENCE`, ingest the reply with `gh-address-cr agent evidence add <owner/repo> <pr_number> --reply-url <comment_url> --thread-id <PRRT_id>`, then rerun final-gate. `--author-login` defaults to the authenticated `gh` login and must match the login that runs final-gate.
7. If the summary reports a blocking `missing_required_evidence` logic-validation signal on a thread that is already resolved on GitHub (classified `fix` but resolved out-of-band, so the runtime never recorded validation evidence and `agent resolve --stale` returns `NO_MATCHING_GITHUB_THREADS`), ingest the validation evidence with `gh-address-cr agent evidence add <owner/repo> <pr_number> --item-id <github-thread:PRRT_id> --commit <sha> --files <paths> --validation <cmd=passed>`, then rerun final-gate. This reconcile path only accepts terminal `github_thread` items and a success-like validation result; use `agent resolve` for threads that are still claimable.


## Troubleshooting installation and release

- Unsupported Python: use Python 3.10 or newer through `pipx`, `uv tool`, or a local virtual environment.
- Missing PyPI package: `gh-address-cr` may not have been published yet. Use the GitHub-direct runtime validation install for pre-release validation.
- Missing Trusted Publishing: production PyPI publishing must use GitHub OIDC with the PyPI project `gh-address-cr`, repository `RbBtSn0w/gh-address-cr`, workflow `.github/workflows/release.yml`, no GitHub environment constraint, and `id-token: write`.
- Missing release-bot GitHub App credentials: production Homebrew publishing requires the shared release-bot GitHub App installed on `RbBtSn0w/homebrew-tap`, `RELEASE_BOT_APP_ID` exposed as an Actions variable, and `RELEASE_BOT_PRIVATE_KEY` exposed as an Actions secret to this repository.
- Stale artifact version: release-built wheel and sdist metadata must match the semantic-release version. If a publish partially succeeds, inspect PyPI before retrying because uploaded files are immutable.
- Homebrew tap update failure: inspect the `publish-homebrew` job after confirming PyPI upload succeeded. The job renders `Formula/gh-address-cr.rb` from the PyPI sdist with the runtime dependency closure, then runs `brew audit --formula --strict`, `brew install --build-from-source`, and `brew test` before pushing the tap update.
- Installed smoke domain failure: `agent orchestrate status` may report a missing session and `final-gate` may report `Final gate failed to evaluate: error connecting to api.github.com` when GitHub state or network access is unavailable. These are acceptable smoke outcomes only when there is no traceback, missing import, or missing console entrypoint.
- Skill install confusion: `npx skills add ... --skill skill` installs the packaged skill adapter only. It does not install the runtime CLI package.
- Skill-shim migration confusion: `python3 skill/scripts/cli.py` has been removed. Install the runtime CLI with `pipx` or `uv tool`.
- Telemetry summary shows events with `0ms` durations: validation commands were reported without a timing suffix. The report emits a `TELEMETRY_TIMING_UNAVAILABLE` diagnostic and omits the Slowest Operations section instead of presenting misleading `0ms` rows. Re-record validation evidence with `--validation "<cmd>=<result>@<n>ms"` (or `@<n>s`) to populate timing.
- Telemetry summary is empty (`coverage_label: unavailable`) with no traceback: no runtime workflow ran under that PR scope and no host telemetry was ingested. This is an expected coverage outcome, not a failure. Run the workflow under the same `<owner/repo> <pr_number>`, or ingest host telemetry via `telemetry ingest`, then re-run `telemetry summary`.
