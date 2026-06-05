# Feature Specification: Runtime Complexity Plateau

**Feature Branch**: `016-runtime-complexity-plateau`  
**Created**: 2026-06-04  
**Status**: In Review
**Input**: User description: "系统正处于复杂度平台期：核心模块语义密度过载，需要将不同类型 WorkItem 处理逻辑解耦为独立 Handler 插件架构；租约过期会造成代理挫败感，需要更优雅的宽限期或续约机制；telemetry 在性能与一致性之间需要明确取舍；风险判定不能长期只依赖正则 markers，需要轻量逻辑验证器。此次 spec 文档用中文。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 拆分可演进的工作项处理边界 (Priority: P1)

作为维护 `gh-address-cr` 的工程师，我希望不同类型的 review work item 拥有清晰、可替换、可测试的处理边界，这样新增 GitHub 边缘情况或建议回复形态时，不需要继续扩大核心控制流程的复杂度。

**Why this priority**: 当前最大风险是核心流程文件继续吸收所有语义分支，导致行为难以审计、回归难以定位，并使后续 PR review edge case 的实现成本持续上升。

**Independent Test**: 选择一种现有 work item 类型和一种新增边缘情况，验证它们可以通过独立处理边界完成分类、处理、证据产出和完成状态判断，同时核心会话结果与原有用户可见行为保持一致。

**Acceptance Scenarios**:

1. **Given** 一个 PR session 包含多种 review work item 类型，**When** 用户启动处理流程，**Then** 每个 work item 都由明确的处理边界声明其适用范围、所需证据、完成条件和失败原因。
2. **Given** 新增一种 GitHub review 边缘情况，**When** 维护者加入对应处理能力，**Then** 既有 work item 类型的验收结果不需要重新定义，且核心流程不新增隐式分支语义。
3. **Given** 某个 work item 类型无法被任何处理边界安全接管，**When** 用户请求下一步操作，**Then** 系统以明确 reason code 停止或要求人工介入，而不是落入通用猜测路径。

---

### User Story 2 - 降低租约过期造成的代理挫败感 (Priority: P1)

作为使用 AI agent 处理 PR review 的工程师，我希望当模型响应较慢或处理时间超过租约窗口时，系统能给出可恢复、可理解的下一步，而不是让 agent 因租约错误进入重复提交失败的循环。

**Why this priority**: 租约是多 agent 安全的核心机制，但过短或不可恢复的租约体验会让 agent 在最需要恢复指导时失去上下文，造成重复 IO、无效 retry 和人工介入成本。

**Independent Test**: 模拟 agent 在租约临近过期、刚过期、已被其他 worker 接管三种状态下提交结果，验证系统分别给出续约、重新申领、停止提交的明确路径。

**Acceptance Scenarios**:

1. **Given** agent 持有的租约即将过期但 work item 仍归其所有，**When** agent 请求继续处理，**Then** 系统提供可验证的续约或宽限路径，并保持 work item 所有权可审计。
2. **Given** agent 提交结果时租约已经过期但 work item 尚未被他人接管，**When** 提交内容带有匹配的工作上下文，**Then** 系统提供重新申领或安全重放路径，而不是只返回不可行动错误。
3. **Given** 过期租约对应的 work item 已被其他 worker 接管或完成，**When** 原 agent 再次提交，**Then** 系统拒绝该提交并提供刷新状态的明确 next action。

---

### User Story 3 - 明确 Telemetry 可用性与一致性边界 (Priority: P2)

作为依赖效率报告和 final-gate 证据的维护者，我希望 telemetry 写入、脱敏和报告失败拥有明确的性能预算与 fail-open/fail-loud 边界，这样核心 PR 处理不会被观测系统拖垮，同时报告可信度不会被静默削弱。

**Why this priority**: Telemetry 已经是重要的审计与优化证据，但它不应成为 review resolution 的单点阻塞；另一方面，静默丢失或不一致的 telemetry 会误导效率分析和完成声明。

**Independent Test**: 在 telemetry 可用、写入缓慢、写入失败、脱敏拒绝四种情况下完成一次 PR session，验证核心处理完成状态、coverage label、诊断输出和报告一致性符合预期。

**Acceptance Scenarios**:

1. **Given** telemetry 正常可用，**When** 用户完成 PR review 流程，**Then** 完成证据包含 coverage label、关键效率指标和可共享报告位置。
2. **Given** telemetry 写入失败或存储不可用，**When** 用户执行核心 review resolution 流程，**Then** 核心流程继续完成并明确标记 telemetry 覆盖不足或不可用。
3. **Given** telemetry 输入包含敏感或不安全内容，**When** 用户执行 telemetry 相关操作，**Then** 系统拒绝或净化该观测数据，并给出可行动诊断，不污染公开报告。

---

### User Story 4 - 引入轻量逻辑验证信号 (Priority: P3)

作为 reviewer 或 gatekeeper，我希望系统能在 agent 产出的回复、分类或完成声明中识别更高层的逻辑风险信号，而不是只依赖关键词或正则 markers，这样隐蔽但高影响的错误能在发布前被提示出来。

**Why this priority**: 文本 marker 能覆盖显性风险，但难以发现推理跳跃、证据不足、完成声明与实际状态冲突等逻辑问题。轻量验证信号可以提高最终 gate 的质量，同时避免把 review resolution 变成昂贵的二次审查系统。

**Independent Test**: 准备包含证据缺口、状态矛盾、过度承诺和正常完成声明的样例，验证系统能对高风险样例给出可解释信号，并且不会阻断无风险的常规流程。

**Acceptance Scenarios**:

1. **Given** agent 的回复声明已经修复但缺少 required evidence，**When** gatekeeper 检查完成状态，**Then** 系统标记证据不足并要求补充或重新分类。
2. **Given** agent 的分类理由与 work item 当前状态矛盾，**When** 用户请求发布或 final-gate，**Then** 系统提示逻辑一致性风险并阻止错误完成声明。
3. **Given** agent 的回复、证据和状态一致，**When** 系统执行轻量验证，**Then** 不应引入额外人工步骤或显著延迟。

### Edge Cases

- 当两个处理边界都声称可以处理同一个 work item 时，系统必须给出确定性的选择结果或明确失败，而不是随机选择。
- 当没有处理边界能处理某个 work item 时，系统必须保留当前 session 状态并提供人工处理或后续扩展路径。
- 当首个迁移的 work item 类型无法覆盖所有既有变体时，系统必须保持未迁移类型的既有公共行为，并清楚标记哪些类型仍在旧路径上。
- 当 agent 在租约宽限期内提交但 session 状态已发生变化时，系统必须优先保护最新 runtime truth，拒绝或重新路由旧提交。
- 当多个 agent 同时尝试续约或重新申领同一个 work item 时，系统必须保持单一有效 owner，并记录冲突诊断。
- 当 telemetry 写入路径变慢时，核心 review resolution 的用户可见完成路径必须仍可预测，且报告必须诚实标记覆盖状态。
- 当 telemetry 与 runtime completion evidence 不一致时，review item 的完成真相必须以 runtime 状态、reply/resolve 证据和 final-gate 为准。
- 当逻辑验证信号无法判断风险时，系统必须将结果表达为低置信或需人工复核，不能伪装为确定结论。
- 当逻辑验证信号只发现低置信提示而没有 completion contradiction 时，系统必须保持 advisory，不引入额外阻塞。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide explicit handling boundaries for each supported work item type, including applicability, required evidence, completion criteria, and terminal failure reasons.
- **FR-002**: System MUST make work item handling independently testable so a new handling boundary can be validated without redefining unrelated work item behavior.
- **FR-003**: System MUST preserve existing public review-resolution behavior unless a change is explicitly documented, versioned, and covered by executable acceptance criteria.
- **FR-004**: System MUST fail fast when a work item cannot be safely matched to a handling boundary or when multiple boundaries conflict without a deterministic priority.
- **FR-005**: System MUST support incremental adoption by allowing the first delivery slice to migrate at least one high-value work item type while preserving parity for unmigrated public behavior.
- **FR-006**: System MUST provide an agent-safe recovery path for near-expired and recently expired leases when the work item remains eligible for the same agent.
- **FR-007**: System MUST reject stale lease submissions when ownership, work item state, or required evidence has changed, and MUST return a machine-readable next action for refreshing or reclaiming work.
- **FR-008**: System MUST expose lease recovery outcomes in a way that agents can distinguish between `renew`, `reclaim`, `refresh_state`, `stop`, and `already_completed` states.
- **FR-009**: System MUST keep lease ownership auditable across renewals, grace handling, reclaims, conflicts, and rejected stale submissions.
- **FR-010**: System MUST define telemetry behavior for normal operation, slow writes, write failures, unsafe data, damaged stored telemetry, and report generation failures.
- **FR-011**: System MUST keep core review-resolution flows fail-open for telemetry unavailability while telemetry-specific operations fail loudly with actionable diagnostics.
- **FR-012**: System MUST preserve telemetry source attribution, coverage labels, privacy filtering, and report honesty when telemetry is partial, unavailable, delayed, or rejected.
- **FR-013**: System MUST keep normal telemetry overhead within 250ms of additional user-visible delay per core workflow command, or degrade to coverage diagnostics without blocking the core workflow.
- **FR-014**: System MUST provide lightweight logic validation signals for evidence gaps, state contradictions, unsupported completion claims, and high-risk reply/classification inconsistencies.
- **FR-015**: System MUST make logic validation results explainable enough for an agent or maintainer to decide whether to supplement evidence, reclassify, defer, or request human review.
- **FR-016**: System MUST treat lightweight validation as advisory unless it detects a completion contradiction, missing required evidence, or a state conflict that would make final-gate evidence false.
- **FR-017**: System MUST prevent lightweight validation from mutating review item state by itself; it may inform gates, diagnostics, or next actions but not replace evidence-first handling.
- **FR-018**: System MUST document the scope boundaries for this feature so broad rewrites, vendor-specific review production, and organization-wide analytics remain out of scope unless separately specified.

### Scope Boundaries

- **Phase 1**: Establish work item handling boundaries and lease recovery semantics for at least one high-value work item type, while preserving public behavior for unmigrated types.
- **Phase 2**: Apply telemetry performance, consistency, privacy, and coverage rules to the core review-resolution path without turning telemetry into completion authority.
- **Phase 3**: Introduce lightweight logic validation signals for gate-quality risks, keeping them advisory except when they expose false completion evidence.
- **Out of Scope**: A full rewrite of all large modules, vendor-specific review production, organization-wide analytics, and any hidden compatibility layer that is not documented and tested as a public contract.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: 本功能影响 runtime session state、work item ownership、lease lifecycle、telemetry artifacts、audit evidence、logic validation diagnostics 和 final-gate 输入。确定性 runtime 仍是状态转换、GitHub side effect、证据判断、租约协调和报告边界的唯一权威。
- **CLI / Agent Contract Impact**: 本功能会影响 agent-safe next action、lease recovery reason codes、work item handling summaries、telemetry coverage labels 和 gate diagnostics。既有 high-level review flow 必须保持稳定；新增或变更的 machine-readable 字段必须被视为公共契约并可测试。
- **Evidence Requirements**: 每个 work item 必须继续证明 verified、classified、replied、resolved 和 gated。处理边界、租约恢复、telemetry 诊断和逻辑验证信号都不能替代 reply URL、resolve 状态、required evidence 或 final-gate 结果。
- **Packaged Skill Boundary**: `skill/` 只能说明 agent 如何响应新的 next action、lease recovery 结果、coverage label 和 validation signal；处理边界选择、状态转换、telemetry 安全、租约仲裁与 gate 判断属于 repo-root runtime。
- **External Intake Replaceability**: 本功能不改变 normalized findings intake 的可替换边界，也不绑定特定 review producer。逻辑验证信号只评价处理证据和状态一致性，不生成或替代 review findings。
- **Telemetry Evidence Boundary**: Telemetry 仍是 observed workflow evidence，不是 review-resolution state。它必须保留 source attribution、coverage labels、privacy filtering、safe diagnostics、report honesty，以及 telemetry-command fail-loud/core-flow fail-open 的边界。
- **Fail-Fast Behavior**: 未支持的 work item、处理边界冲突、过期且不可恢复的租约、陈旧提交、unsafe telemetry、损坏报告输入、无法解释的高风险 validation signal 都必须明确失败或要求人工复核，不能静默 fallback。

### Key Entities *(include if feature involves data)*

- **Work Item Handling Boundary**: 表示某类 review work item 的处理责任、适用条件、所需证据、完成条件、失败原因和用户可见 next action。
- **Lease Recovery State**: 表示一个 work item 在租约临近过期、宽限期、过期、可重新申领、已被接管或已完成时的可恢复状态。
- **Telemetry Coverage State**: 表示当前 PR session 中 telemetry 的覆盖程度、来源、可用性、脱敏状态、失败诊断和报告可信度。
- **Logic Validation Signal**: 表示对 agent 处理结果的轻量一致性检查结果，包括风险类型、置信度、解释、建议下一步和是否影响 gate。
- **Runtime Completion Evidence**: 表示 work item 完成所需的分类、回复、resolve、验证、审计和 final-gate 证据，是完成真相的权威来源。
- **Delivery Slice**: 表示本 feature 内可独立验收的阶段性能力，用于防止一次性大重构并保持每个阶段都有可验证用户价值。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 新增一种 supported work item handling boundary 时，维护者可以通过独立验收样例证明该类型行为，不需要重写 unrelated work item 的验收定义。
- **SC-002**: 首个 delivery slice 至少迁移一种高价值 work item 类型，并证明该类型在 migrated path 与既有 public behavior 之间保持用户可见 parity。
- **SC-003**: 至少 90% 的可恢复租约过期场景能返回 `renew`、`reclaim`、`refresh_state`、`stop` 或 `already_completed` 中的一种明确 next action。
- **SC-004**: 过期或陈旧租约提交不会覆盖已完成、已接管或状态已变化的 work item。
- **SC-005**: 在 telemetry 不可用或写入失败时，核心 PR review resolution 流程仍可完成，并且最终证据包含 runtime-only、partial 或 unavailable 覆盖说明。
- **SC-006**: Telemetry 正常路径的额外用户可感知延迟不超过 250ms；超出预算时系统降级为明确 coverage/diagnostic 输出而不是阻塞核心流程。
- **SC-007**: 包含敏感内容的 telemetry 样例不会出现在可共享报告中，并且用户能看到被拒绝或净化的原因。
- **SC-008**: 逻辑验证样例集中，证据缺口、状态矛盾和过度完成声明都能产生可解释风险信号；正常完成样例和低置信 advisory 信号不会被错误阻断。
- **SC-009**: 完成一次包含 work item handling、lease recovery、telemetry coverage 和 validation signal 的 PR session 后，final-gate 仍能明确区分 review completion truth 与 observed workflow evidence。
- **SC-010**: 每个 delivery slice 都能独立展示用户价值、验收证据和未完成范围，避免把成功定义绑定到一次性全量重构。

## Assumptions

- 本 spec 关注降低复杂度平台期风险，不要求一次性完成所有核心模块重写。
- 现有 review、address、agent、publish、resolve 和 final-gate 的用户可见契约默认保持兼容，除非后续计划明确列出版本化变更。
- Work item handling 可以分阶段迁移；首个阶段应优先覆盖最常见或最容易引发复杂分支的 work item 类型。
- 租约机制仍是多 agent 安全的基础；宽限期或续约能力必须服从 runtime truth，不能允许旧 owner 覆盖新状态。
- Telemetry 的价值是审计和优化，不是 completion authority；任何 telemetry 失败都不得让未完成 review item 被视为完成。
- 逻辑验证器的目标是轻量风险信号，不是替代 human review、完整静态分析或 vendor-specific AI judge。
- 这条路线会增加显式契约数量，但目标是减少隐藏分支和重复重试带来的长期复杂度；执行效率通过 250ms telemetry 预算、阶段化迁移和 advisory-first validation 边界来保护。
