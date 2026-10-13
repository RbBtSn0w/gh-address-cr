# 先修重试与退避，再治调用量

**直接结论：gh 命令频繁失败，更可能是“失败后没有任何有效重试和退避”，而不是“单 session 的 gh 调用太多”。** 代码上，所有 `GitHubClient` 读写最终都以 `retries=1` 调用 `run_cmd`，两层重试实际都只尝试 1 次，且没有超时（`src/gh_address_cr/github/client.py:546`、`:492`）。因此任何一次 502/503/网络抖动都会让 `address` 或 `final-gate` 以 BLOCKED/exit 5 中止，用户只能整轮重跑。单 session 的调用量确实偏大且存在真正的 N+1（`agent publish` 每个线程至少 3 次 gh 调用，且全部串行），但按 GitHub 官方限额，单 PR 的量级远低于主限额：粗估一轮 40-60 次进程调用，对比每小时 5,000 请求。真正会触达的是多 session 共享同一 token 时的二级限制（并发、内容创建速率），而当前架构对此毫无共享预算、限流、退避协调的支持。**需要强调：仓库内没有任何真实失败日志或遥测基线，上述归因是基于代码与官方文档的推断，尚未经实测证实**；第一步应当用现有 OTel 数据量化，而不是直接改架构。建议分四个阶段推进：先测量并修复退避语义，再削减冗余调用，然后引入 flock 级别的跨进程节流与熔断，最后才评估缓存或常驻进程。

## 失败的首要嫌疑是“零重试 + 零超时”，而非调用总量

`GitHubClient` 的重试机制存在，但被配置成了空转。`core/command_runner.run_cmd` 默认 `retries=3`，遇到退出码 124 或瞬时错误文本时按 `2**attempt` 秒睡眠重试（`src/gh_address_cr/core/command_runner.py:129-178`）；`GitHubClient._run_gh` 也有同样的逻辑（`src/gh_address_cr/github/client.py:520-540`）。但 `_default_runner` 固定传 `retries=1`（`src/gh_address_cr/github/client.py:543-546`），`_read_json` 默认也是 `retries=1`（`:492`），于是 `attempts = max(1, 1) = 1`，两层都不会重试。写操作不重试符合 `tests/test_network_write_contracts.py:212` 所固化的意图（回复不是幂等的），但读操作不重试看起来并非有意为之：仅 `submit_feedback` 的读路径有显式重试测试（`tests/` 中 `:197`）。这意味着 `review`/`address` 的 5-6 次读取、`final-gate` 的 5 次读取中任何一次遇到瞬时错误，整个命令就失败，重跑还要把所有调用重新付一遍。

即使开启重试，现有的瞬时错误判定也太窄。`src/gh_address_cr/github/transient_failures.py:3-18` 只匹配 `502`、`503`、`error connecting`、`timeout`、`graphql error` 等子串，不含 `500`、`504`、`429`、`secondary rate limit`、`retry-after`，也不含 GraphQL 的 `RESOURCE_LIMITS_EXCEEDED`。而 GitHub 文档明确说，GraphQL 请求超过 10 秒会以 502 或 504 终止，并额外扣减下一小时的主限额 ([GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api))，所以 504 缺失会漏掉一类典型的“请求过大”故障。子串 `"502"` 还可能误匹配 ID 等无关文本（推断）。另一个顺序问题是：GraphQL 以 exit 0 返回 `{"errors":[...]}` 时，错误检查发生在重试循环之后（`src/gh_address_cr/github/client.py:509-517`），因此这类瞬时错误永远不会被重试。

超时同样缺位。`GitHubClient._default_runner` 不传 `timeout`，`src/gh_address_cr/cli.py:679` 的预检 `gh auth status` 直接用裸 `subprocess.run`，也没有超时；只有 `src/gh_address_cr/commands/active_pr.py` 用了 30 秒超时（`:17`）。一个挂住的 gh 进程会永久阻塞整条流水线。此外还有两类错误归类问题：预检中未知或 `api` 类错误会落入默认的 `GH_AUTH_FAILED`（`src/gh_address_cr/cli.py:652-656`），把 `gh auth status` 上的 5xx 误报为认证问题；而一个不含 “rate limit”/“secondary rate” 字样的二级限流 403，可能被 `command_runner` 归为 `permission_denied`（`src/gh_address_cr/core/command_runner.py:~261`，推断，未复现）。`retryable` 字段只是元数据，没有任何调用方据此自动重试。

还有一个值得单独验证的嫌疑是 macOS Keychain。二手来源称 gh 对 keyring 操作有硬性 3 秒超时（cli/cli#7580，自 v2.31.0），Keychain 读取超时后 token 为空，请求以未认证身份发出而返回 401（cli/cli#13317）([claudeissues.com 67055](https://claudeissues.com/issue/67055-desktop-false-github-cli-authentication-expired-toast-any-gh-auth-status-failure))。这与“并行读取 + 预检 `gh auth status` 偶发被判为认证失败”的症状吻合，而本仓库的 `gather_reads` 恰好并行拉起多个 gh 进程。**但这两个 cli/cli issue 本次调研未能打开核实，修复状态未知，只能当作待验证假设。**

## 调用量偏大是真的，但瓶颈在串行往返与 N+1，不在主限额

按代码逐命令计数，小 PR 上 `review`/`address` 约 6 个 gh 进程：1 次无遥测的 `gh auth status`、1 次 stack、`gh api user` 加 threads（同一分支内两次串行往返）、checks、files，关键路径是 3 次串行往返（`src/gh_address_cr/cli.py:679`；`src/gh_address_cr/commands/high_level.py:932-937`；`src/gh_address_cr/github/client.py:168`）。`final-gate` 为 5 次（不带 `--require-checks` 为 4 次），分两个波次（`src/gh_address_cr/core/gate.py:173,193-199`，`tests/test_gh_call_reduction.py:124-134`）。PR #352 已经通过 `viewer_login` 记忆化与 `gather_reads` 把串行往返从 5 降到 2，这是已完成的一轮优化，不应重复提议。

剩余的真问题集中在三处。其一，`agent publish` 对每个线程严格串行执行回复、解决，再执行一次 `_wait_for_remote_thread_resolution`，后者调用完整的 `client.list_threads`（全 PR 线程、每页 100、含评论），最多 2 次并间隔 1 秒，仅为确认一个线程的 `isResolved`（`src/gh_address_cr/core/publisher.py:230,265,371-397`）。N 个线程约 2+3N 到 2+4N 次调用，且每次读的载荷随总线程数增长，即 O(N×线程数)。而 `client.resolve_thread` 已在 mutation 返回值中检查 `isResolved`，不为 true 就抛错（`src/gh_address_cr/github/client.py:340-344`），这个回读看起来冗余（推断，需确认其是否针对最终一致性设计）。其二，`list_pending_reviews` 循环直到空页才停，导致 ≤100 条 review 的 PR 也固定多一次请求，而 `list_pr_files` 与 `list_pr_commit_shas` 已用“短页即停”（`src/gh_address_cr/github/client.py:350-367` 对比 `:433`）。其三，每个 agent 子命令都是新进程，stack context 与 viewer login 在进程间完全不复用，唯一的 gh 结果缓存是实例级 `_viewer_login`（`src/gh_address_cr/github/client.py:31-32,453-461`），而 `src/gh_address_cr/commands/agent.py:766` 还会为同一目的另建客户端再发一次 `gh api user`。粗估一个 5 线程 PR 的一轮处理共约 40-60 次进程调用，其中多数是对未变事实的重复读取；**这是代码阅读估算，未经实测**。

把这些数字放进官方限额里看，主限额并非瓶颈。REST 个人 token 为 5,000 请求/小时，GraphQL 为 5,000 点/小时，且 GraphQL 按“连接请求数除以 100”计点、最低 1 点 ([REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)；[GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api))。单 session 一轮几十次调用，远不到一个数量级。真正逼近的是二级限制：最多 100 并发请求（REST 与 GraphQL 共享）、GraphQL 每分钟 2,000 点、含 mutation 的 GraphQL 请求计 5 点、内容创建约 80 次/分钟与 500 次/小时，并且官方最佳实践要求请求串行、变更请求之间至少间隔 1 秒 ([Best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api))。reply+resolve 每线程两次 mutation，若两者都计入内容创建，上限约为每分钟 40 个线程（推断，`resolveReviewThread` 是否计入内容创建，文档未说明）。

## 多 session 场景在 GitHub 侧完全耦合，在本地架构上完全隔离

本地状态按 PR 工作区隔离：`<state>/<owner>__<repo>/pr-<N>` 下各有一个 `runtime.sqlite3`（`src/gh_address_cr/core/paths.py:46-66`，`src/gh_address_cr/core/runtime_store.py:262-265`），租约按 `(session_id, item_id)` 唯一（`src/gh_address_cr/core/runtime_store.py:164-165`），唯一的 OS 级锁是单个 outbox 命令的 flock 存活证明（`src/gh_address_cr/core/process_lock.py`）。这些机制仲裁同一 PR 内的 item，不涉及 GitHub 预算。结果是：不同 PR 的两个 session 在本地毫无冲突，但共享同一个 token 的主限额与全部二级限制。仓库中也没有任何读取限额状态的路径：grep 未发现 `x-ratelimit`、`Retry-After`、`gh api rate_limit` 或 GraphQL `rateLimit{}`，只有对 stderr 文本的 “rate limit”/“secondary rate” 子串分类（`src/gh_address_cr/github/diagnostics.py:41,93,120`，`src/gh_address_cr/core/command_runner.py:258-259`）。N 个 session 各自独立轮询、各自重复 `gh api user`，同时因为退避无抖动，一旦同时失败，会以相同的 `2**attempt` 节奏同步重试，形成惊群（推断；但目前客户端路径因 `retries=1` 实际不重试，这个风险要等阶段一放开重试后才会显现）。同一 PR 上的多进程则会各自轮询、可能各自发 mutation，outbox 只保证单个命令不重复执行。

GitHub 文档对退避的要求是明确的：触发限制时返回 403 或 429；有 `retry-after` 则照办，否则 `x-ratelimit-remaining` 为 0 时等到 `x-ratelimit-reset`，否则至少等 1 分钟，之后指数退避并限制尝试次数，限流期间继续请求可能导致封禁 ([REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api))。而且二级限制的状态无法查询，同一页明确说明“没有办法检查”，因此跨 session 协调只能依赖自己观察到的失败信号。Octokit 的 throttling 插件提供了成熟的先例：基于 Bottleneck、遵循 `retry-after`、二级限流默认回退 60 秒，并可通过 Redis 在进程间共享节流状态 ([plugin-throttling.js](https://github.com/octokit/plugin-throttling.js))。

**当前架构的限制与已有的约束决定了答案是“不是更好支持，而是没有支持”**，并且 RFC 033 明确推迟了文件锁/CAS 协议，RFC 041 以原则 X 为由否决了常驻/脱离式 helper（`docs/rfcs/033-lease-state-machine/plan.md:159-170`，`docs/rfcs/041-telemetry-shutdown-wait/preflight.md`）。这决定了方案应当是“无守护进程”的：用 flock 槽位、共享 backoff-until 文件，而不是新建 daemon 或第二个权威存储。

## 分阶段建议：先测量与退避，后节流与缓存

下表按影响与成本排序。所有阶段都受 AGENTS.md 约束：公共 CLI 与机器可读契约（如预检层的 `GH_RATE_LIMITED` 与 `GitHubClient` 层的 `GITHUB_RATE_LIMITED` 等 reason code，两组前缀不同）变更需同步代码、文档、测试，并版本化；遥测遵循原则 VIII 的分层模型与隐私规则；`final-gate` 是受保护的内核面，不可用缓存替代新鲜读取。

| 阶段 | 内容 | 影响 | 成本 | 约束与前置 |
|---|---|---|---|---|
| 0 测量 | 在现有 `gh_address_cr.subprocess` span 上统计每 session 的 `github.*` 调用数、按命令分布、失败的 `error.category` 分布；用真实失败样本验证上文三个嫌疑（零重试、限流、Keychain） | 高（决定后续优先级） | 低 | 仅用现有属性即可；新增属性须低基数、公共安全，遵守 `sanitize_cli_argv`/`command_label`。没有这一步，其余建议均属推断 |
| 1 退避与分类 | 读操作开启有限次重试（幂等读，带抖动，次数受限）；给 GitHub 调用加统一超时；扩充瞬时判定（500/504/429/`RESOURCE_LIMITS_EXCEEDED`）并改为错误分类驱动而非裸子串；把“exit 0 + GraphQL errors”纳入重试判定；解析 `retry-after`/`x-ratelimit-reset`（需 `gh api -i` 或等价手段，因 `gh api` 默认不暴露响应头）；修正预检默认归类 `GH_AUTH_FAILED`；预检遇 401 先重试一次再宣布认证失败 | 高 | 低-中 | 属于公共错误契约变更，须版本化并补契约测试；写操作保持不重试，歧义的 502/504 后必须先回读线程状态再决定是否重发。不触发完整 Architecture Preflight（不新增状态） |
| 2 削减冗余调用 | 去掉发布后的全量 `list_threads` 回读，改用 mutation 返回值或单个 `node(id:)` 查询（先确认其是否为最终一致性而设）；`list_pending_reviews` 改为短页即停；预检 `gh auth status` 并入已需要的 `gh api user`；`address` 在不需要时跳过 checks/files；统一 `viewer_login` 来源；可选地用 GraphQL 别名批量提交 reply/resolve | 中-高 | 低-中 | 别名批量需保持逐项 outbox 幂等键、逐 alias 解析 `errors[].path`、按块限制大小（10-25 为本报告的建议值，非官方数字），且 reply 非幂等，批量重发前必须回读。批量会改变 GitHub 副作用形态，应先写短 preflight（扩大 GitHub side effects 触发器） |
| 3 跨进程节流 | 机器级 flock 槽位信号量（复用 `src/gh_address_cr/core/process_lock.py`）限制并发 gh 进程数；共享的 `gh-backoff-until` 咨询文件让多个 session 同步暂停；mutation 间至少 1 秒的写间隔；有界等待后放行并发出诊断事件 | 高（针对多 session） | 中 | 对应原则 VI/X：这是多 session 才有的爆炸半径，须记录 blast-radius 理由并写 preflight（状态所有者为无、锁只证明存活不构成真相、咨询文件是非权威投影）。须文档说明 `GH_ADDRESS_CR_STATE_DIR` 被每个 session 单独覆盖时会使节流失效。“阻塞等待”与“fail-fast/fail-open”如何取舍需要明确的决策记录 |
| 4 缓存与进阶 | 仅缓存身份（viewer login）；只读 REST 列表（commits/files）用 ETag 条件请求，304 在带认证时不计主限额 ([Best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api))；评估常驻进程、直连 HTTP 客户端、SQLite 令牌桶，仅当阶段 0-3 之后仍有实测证据才做 | 低-中 | 中-高 | 不得缓存线程快照来替代 `final-gate` 读取（原则 III、IX，artifact 不得成为真相）；常驻进程已被 RFC 041 否决；第二个 SQLite 违反“唯一权威存储”倾向，且 GitHub 不提供二级限制可见性，边际收益有限 |

## 尚未验证的主张与开放缺口

首先，最大的缺口是没有真实数据：仓库内没有存储的 session 遥测，因此“每 session 实际 gh 次数”“失败率”“失败的具体 HTTP 状态”全部未知；issue #347 的正文与任何限流事故 issue 在 GitHub 上，本调研未读取，建议先执行 `gh issue view 347`。其次，以下关键事实均未验证：`resolveReviewThread` 与别名 mutation 是否计入 80 次/分钟的内容创建限制；GraphQL 部分失败时 GitHub 是否将整个 `data` 置空（第三方来源只支持“服务端依赖实现”）；GraphQL 不支持 ETag/304 只是由“条件请求不支持 POST”推出，没有 GitHub 原文；mutation 根字段串行执行来自记忆而非规范原文（spec.graphql.org 抓取被阻止）；`gh` 自身是否对二级限流重试；`gh pr checks` 内部发出多少请求；`gh` 进程启动开销（建议用 `hyperfine gh api rate_limit` 本地测量）；多少并发 session 会在此负载下触发二级限制。再者，限额数字来自对官方文档的 WebFetch 摘要而非逐页核对原文，页面未标注修订日期；cli/cli#7580、#13317 与 glab 的 keychain 竞态案例都是二手或类比来源。最后，`evaluation_observations()` 在 `src/` 中无调用点是 grep 推断，Windows 下 flock 槽位的跨进程语义也未测试。

## Conclusion

最有价值的新认识是：这个问题的杠杆点和直觉相反。PR #352 已经压缩了串行往返，而现在更大的结构性缺陷是“重试层存在却被配置成空转”，以及“系统对 GitHub 的限流信号完全失明”。前者让每次瞬时故障变成整轮失败，后者让多 session 只会在撞墙后各自盲目重跑。这两处修复成本低、不增加运行时状态，也不触碰 `final-gate` 的真相语义，应排在任何缓存、批量或守护进程方案之前。

其次，多 session 支持不需要新子系统。仓库已有经过验证的 flock 存活证明原语，加上一个共享的 backoff-until 咨询文件，就足以把并发和写入速率约束在 GitHub 的串行指引之内，并且符合原则 X 对复杂度预算的要求；但前提是阶段 0 的测量先证明失败确实来自限流而非 Keychain 或网络抖动，否则会把工程投入花在错误的假设上。
