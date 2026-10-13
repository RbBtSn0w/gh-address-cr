# GitHub API / gh CLI efficiency for PR review-thread processing

Research date: 2026-10-12. Docs pages were fetched via WebFetch (summarized by a small model); numbers below are as reported from those fetches. The REST/GraphQL rate-limit pages carry no explicit revision date.

## 1. GraphQL batching, cost model, and limits

### Takeaway
Aliased root fields in one `mutation { a: ... b: ... }` document are the standard way to batch, and the points/node model makes batching cheap on primary limits. GitHub docs say nothing about batching mutations, and the content-creation secondary limit (80/min, 500/h) is most likely the binding constraint. Whether it counts per aliased mutation is undocumented.

### Cited Findings
- Every connection needs `first` or `last` (1-100). A single call may request at most 500,000 total nodes. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- Primary cost: add the requests needed for each unique connection (assuming each reaches its first/last bound), divide by 100, round; minimum 1. The docs' example of 5,101 requests scores 51. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- User primary budget: 5,000 points/hour (10,000 for user requests through a GitHub App or OAuth app owned by, or approved for, a GitHub Enterprise Cloud org the user belongs to). GitHub App installation not on a GitHub Enterprise Cloud organization: 5,000 base, +50 per repo and +50 per user beyond 20, cap 12,500; installation on a GitHub Enterprise Cloud organization: 10,000 flat. Actions `GITHUB_TOKEN`: 1,000/h per repo (15,000/h per repo for resources in a GitHub.com enterprise account). — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- The docs do not give a primary-limit cost for mutations. The secondary point value is 1 for a GraphQL non-mutation and 5 for a GraphQL request containing a mutation. Secondary budget is 2,000 points/min for the GraphQL endpoint. — [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- Requests running over 10 seconds are terminated with 502 or 504, and each timeout deducts extra points from the next hour's primary limit. Queries exceeding resource limits return partial results plus an error. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- Checking: use `x-ratelimit-*` response headers (`x-ratelimit-resource: graphql`) in preference to querying `rateLimit { cost remaining resetAt }`. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- The GraphQL limits page does not mention batching multiple queries and only advises splitting large queries into simpler ones. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- GraphQL aliases let you request the same field several times with different arguments in one request. — [graphql.org queries](https://graphql.org/learn/queries/)
- Partial-failure behavior is server-dependent. Errors carry a `path` pointing to the alias; non-null failures can null out parents, so `data` may be null or partial while `errors` is set. A document may contain multiple named operations, including multiple `mutation` operations; a request containing several must provide `operationName` to select one to execute. Multiple root fields within one mutation operation are a separate case and execute serially. The partial-failure points above come from third-party sources, not GitHub's. — [overblog/GraphQLBundle #346](https://github.com/overblog/GraphQLBundle/issues/346), [nuwave/lighthouse #2418](https://github.com/nuwave/lighthouse/issues/2418)

### Inferences
- A review-thread pass is cheap on primary points. One mutation document with N aliased `addPullRequestReviewThreadReply` / `resolveReviewThread` fields should be a single HTTP request. Primary cost scales with request count, not alias count, though this is not documented for mutations.
- Query side: fetching `reviewThreads(first:100){ comments(first:N) }` costs roughly 1 + 100*... node requests / 100. Keep nested `first` small and paginate comments only for threads whose `comments.pageInfo.hasNextPage` is true.
- The 10 s server timeout and the secondary content-creation limit argue for chunking aliased mutations (e.g. 10-25 per document, my suggestion, not a documented number). That bounds blast radius when one alias fails.
- Per-alias result extraction: return `comment { url id }` under each reply alias and map via alias name. Always parse `errors[].path[0]` to attribute failures, and never treat non-null `data` as success.
- Mutation root fields are executed serially per the GraphQL spec (from my memory only, not verified this session), so ordering reply-then-resolve within one document should hold. Verify against spec.graphql.org before relying on it.

### Gaps
- Input/return fields of `addPullRequestReviewThreadReply` and `resolveReviewThread`: the docs mutations index page fetched contained no schema detail. Check the GraphQL public schema or `gh api graphql` introspection.
- Whether GitHub counts each aliased mutation toward the 80/min content-creation limit: undocumented in the pages fetched.
- Exact GitHub behavior on partial mutation failure in one document (does a failed alias null all of `data`?): no GitHub-specific source found; test empirically.
- GraphQL spec text (serial execution, error propagation): spec.graphql.org fetch was blocked.

## 2. Primary and secondary rate limits, retries

### Takeaway
Primary budgets are not the problem at PR-thread scale. Secondary limits (100 concurrent, 80 content requests/min and 500/h, 1 s between mutations, 2,000 GraphQL points/min) are what bite. Retry rules are explicit: honor `retry-after`, else `x-ratelimit-reset` if remaining is 0, else wait at least 60 s, then back off exponentially with a bounded attempt count.

### Cited Findings
- REST primary: 60/h unauthenticated; 5,000/h for PAT or user token (15,000/h for Enterprise Cloud org-owned apps); `GITHUB_TOKEN` in Actions 1,000/h per repo. — [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- Secondary: at most 100 concurrent requests (shared REST and GraphQL); 900 points/min per REST endpoint, 2,000 points/min for GraphQL; 90 s CPU per 60 s real time (max 60 s for GraphQL); 80 content-generating requests/min and 500/h (some endpoints lower). — [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- Points: REST GET/HEAD/OPTIONS = 1; POST/PATCH/PUT/DELETE = 5; some endpoints have undisclosed costs. There is no way to check secondary-limit status. — [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- Primary exceeded: 403 or 429 with `x-ratelimit-remaining: 0`; do not retry before `x-ratelimit-reset` (UTC epoch seconds). Secondary exceeded: 403 or 429 with a message naming the secondary limit; use `retry-after` if present, else `x-ratelimit-reset` if remaining is 0, else wait at least one minute; on continued failure back off exponentially and stop after a set number of attempts. Continuing while limited may get the integration banned. — [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- Make requests serially, not concurrently (a request queue is suggested); wait at least 1 second between each POST/PATCH/PUT/DELETE when making many. — [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- The GraphQL limits page also says to pause at least 1 second between mutative requests. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- 502/504 on GraphQL occur when a request exceeds 10 s. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- Don't hammer repeated 4xx/5xx; repeated requests for a missing resource waste rate limit and can trigger secondary limits. — [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- Header values can vary between responses (multi-region); response headers are authoritative over `GET /rate_limit`. — [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

### Inferences
- Classification: 403/429 with rate-limit signals are retryable per the rules above; 502/504 are retryable but may indicate an oversized query (shrink the request rather than only retrying); other 403s (permissions, SSO) and 404 are not transient.
- At 80 content requests/min, a per-thread reply+resolve loop is bounded to roughly 40 threads/min if both mutations count. Aliased batching may or may not change that count, so measure.
- Multi-session operation multiplies concurrency and content-creation counts across processes for the same token, so a cross-process lock or shared queue is needed to stay inside the serial guidance.

### Gaps
- Whether `resolveReviewThread` counts as content creation: undocumented in fetched pages.
- Jitter recommendations: the docs specify exponential backoff but not jitter.

## 3. Conditional requests and caching

### Takeaway
ETag / If-None-Match works for REST GETs and a 304 is free on the primary limit if authenticated. No source found that GraphQL supports an equivalent. For GraphQL use a short-TTL local snapshot, with REST conditional GETs as a cheap change detector.

### Cited Findings
- Send the saved `etag` in `if-none-match` (or `last-modified` in `if-modified-since`); a 304 does not count against the primary limit if the request is authorized with an `Authorization` header. — [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- Conditional requests for POST/PUT/PATCH/DELETE are not supported unless an endpoint's docs say so. Use identical parameters on each poll, since page size or filter changes the etag. Respect `x-poll-interval` when present. — [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- A different access token yields a different etag, so cached etags don't validate across tokens. — [github/docs #34689](https://github.com/github/docs/issues/34689) (as reported by a search-result summary; not opened directly)

### Inferences
- GraphQL queries are POST bodies, so the unsafe-method exclusion implies no ETag/304 for GraphQL. I found no GitHub doc stating this directly, so treat it as likely but unverified.
- A snapshot cache keyed by (repo, PR, token identity) with a short TTL, invalidated after the tool's own mutations, avoids re-querying thread lists. Cheap REST probes (e.g. PR review comments with ETag) could signal when to refresh, but pagination and parameter stability must match.

### Gaps
- No authoritative statement about GraphQL and ETag.
- No GitHub guidance on TTL values for snapshots; any TTL is a design choice.

## 4. gh CLI specifics and known flakiness

### Takeaway
`gh api graphql` is the right shelling-out primitive, and `GH_TOKEN` plus `GH_PROMPT_DISABLED` removes auth and prompt variance. Per-call process cost and keyring access are the real per-call overheads. Several flakiness reports involve macOS Keychain timeouts under parallel load, but they come from secondary sources and need verification.

### Cited Findings
- `gh api --cache <dur>` takes a TTL like "3600s", "60m", "1h", and caching is enabled only when the TTL is greater than zero. `--paginate` is rejected for non-GET requests except `graphql`, cannot be combined with `--input`, and for GraphQL the query must accept `$endCursor: String` and select `pageInfo { hasNextPage endCursor }`. `--slurp` requires `--paginate` and cannot be combined with `--jq` or `--template`. — [gh api source](https://raw.githubusercontent.com/cli/cli/trunk/pkg/cmd/api/api.go) (cli.github.com manual fetch was blocked; source used instead)
- Error handling: for GraphQL or JSON error responses with status 400+, gh prints `gh: <message>` to stderr; otherwise `gh: HTTP <status>`; it returns a silent error (nonzero exit). Numeric exit codes are not documented in this source. — [gh api source](https://raw.githubusercontent.com/cli/cli/trunk/pkg/cmd/api/api.go)
- `GH_TOKEN` (precedence over `GITHUB_TOKEN`) skips login prompts and overrides stored credentials. `GH_PROMPT_DISABLED` disables interactive prompts. `GH_NO_UPDATE_NOTIFIER` stops the 24-hourly update check. `GH_CONFIG_DIR` relocates config. `GH_DEBUG=api` logs HTTP traffic. `GH_TELEMETRY=false` or `DO_NOT_TRACK=1` disables telemetry. `GH_HOST` and `GH_REPO` set host and repo. — [gh help environment](https://cli.github.com/manual/gh_help_environment)
- Reported: gh wraps keyring operations in a hard 3 s timeout (cli/cli#7580, since v2.31.0), and when a macOS Keychain read times out the token comes back empty so the request goes out unauthenticated and returns 401 (cli/cli#13317, fix PR #13318 reportedly unmerged). Secondary mirror of a Claude desktop bug report; I could not open the cli/cli issues (fetch timed out). — [claudeissues.com 67055](https://claudeissues.com/issue/67055-desktop-false-github-cli-authentication-expired-toast-any-gh-auth-status-failure)
- A sandbox blocking `~/Library/Keychains/` makes keyring-based gh auth fail. An injected `GITHUB_TOKEN` overrides gh's stored OAuth token. — [claudeissues.com 44195](https://claudeissues.com/issue/44195-sandbox-blocks-macos-keychain-access-breaking-cli-tools-that-use-keyring-auth-gh), [claudeissues.com 31502](https://claudeissues.com/issue/31502-bug-claude-code-injects-github-token-pat-into-bash-environment-conflicting-with)
- Analogous (glab, not gh): concurrent processes racing on a shared macOS keychain sentinel item caused false "keyring not accepting writes" errors (`security add-generic-password -U` is non-atomic, error -25299). — [GitLab CLI MR 3780](https://gitlab.com/gitlab-org/cli/-/merge_requests/3780)

### Inferences
- Resolving the token once (`gh auth token`, or `GH_TOKEN` in the environment) and passing `GH_TOKEN` to every gh subprocess avoids repeated Keychain reads, which are the plausible source of the load-dependent 401s above.
- Setting `GH_PROMPT_DISABLED=1`, `GH_NO_UPDATE_NOTIFIER=1`, and a bounded subprocess timeout makes failures deterministic and fail fast. Treat a 401 on a previously authenticated session as possibly transient token-read failure: retry once after re-resolving the token before declaring auth lost.
- `--paginate` for GraphQL concatenates pages but only works when the query uses `$endCursor` for a single connection; nested pagination (comments inside threads) needs manual follow-up.

### Gaps
- No measurement of gh process spawn overhead (typically tens of ms of Go startup plus config/keyring read); no source found, and it would need a local benchmark (`hyperfine gh api rate_limit`).
- cli/cli issues #7580 and #13317 not verified at source; version and merge status unconfirmed.
- Config-file locking and concurrent-invocation issues specific to gh: nothing found.
- `gh help exit-codes` and the cli.github.com manual were not retrievable (domain fetch blocked).

## 5. Tradeoffs: gh subprocess vs long-lived HTTP client; per-thread vs aliased mutations

### Takeaway
No official source compares these; the following is analysis from the cited facts. A long-lived HTTP client with keep-alive saves process spawn, config and keyring reads, and TLS handshakes per call. Aliased batching saves round trips but weakens per-item failure isolation.

### Cited Findings
- Requests should be serial and spaced at least 1 s between mutations. — [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- GraphQL responses carry `x-ratelimit-*` headers usable for adaptive throttling. — [GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- Errors in GraphQL batches are attributable through `path`; failures may null `data`. — [overblog/GraphQLBundle #346](https://github.com/overblog/GraphQLBundle/issues/346)

### Inferences
- gh subprocess: keeps GitHub Enterprise host config, SSO, and token storage handled by gh, with a smaller attack surface for token handling. Costs: process and TLS setup per call, keyring dependency (flaky on macOS under parallel load), and `--cache` only for reads.
- Direct HTTPS via `gh auth token` plus a pooled client (httpx/requests session): reuse of connections, direct access to response headers (`retry-after`, `x-ratelimit-*`) for exact backoff, and finer timeouts. Costs: own token lifecycle and host handling, new dependency surface, and AGENTS.md telemetry-privacy rules apply to a new transport.
- Middle path: keep `gh api graphql` but batch via aliases and pass `GH_TOKEN`, reducing call count without a new transport. Note `gh api` does not expose response headers unless `--include` is used, which complicates `retry-after` handling.
- Per-thread mutations: simple evidence mapping and independent retries, N round trips and N times the content-creation count. Aliased batch: one round trip; require per-alias `errors[].path` parsing, per-alias `comment.url` extraction, idempotency checks before re-sending (a retry of a whole document may duplicate replies already created), and a chunk-size cap. Resolve is idempotent in effect, but replies are not, so retries after ambiguous 502/504 must re-read thread state first.

### Gaps
- No benchmarks or official guidance on gh vs persistent client; the choice needs local measurement.
- HTTP/2 availability and connection reuse behavior of the GitHub GraphQL endpoint not verified.
