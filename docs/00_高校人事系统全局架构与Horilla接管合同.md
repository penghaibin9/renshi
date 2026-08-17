# 00_高校人事系统全局架构与Horilla接管合同（终极冻结版）

> 产品：跃科高校人事管理与教师发展系统  
> 文件级别：00｜HR01–HR18 全系统最高级架构与 Horilla 接管合同  
> 版本：V1.0 终极冻结版  
> 适配底座：Horilla HRMS 2.0，仓库 `penghaibin9/renshi`；任何施工先以目标分支真实代码为准  
> 核心原则：**一个事实一个 Authority；旧系统只能被接管、投影和退出，不能永久双主；历史必须 effective-dated；跨域必须 Provider/Event；所有正式结果可追溯、可对账、可回滚入口但不可删除事实。**  
> 编写日期：2026-08-09

# 0. 文件定位

本文件不是第 19 个业务模块，而是 18 个模块共同遵守的“系统宪法”。
它只冻结跨模块不变量、Horilla 接管/退出、技术合同和最终验收，不重复每册页面施工卡。
发生冲突：**00 全局不变量 > 旧 Horilla 行为；业务事实归对应 HRxx Authority；其他域只能消费。**

# 1. 为什么必须存在

HR01–HR17 已经反复使用 A0 tenant fail-closed、as-of、Provider、Outbox、RuleVersion、Snapshot、Legacy Projection、DUAL_READ_COMPARE、异步 Job、文件安全等公共规则。
如果没有 00，同一规则会在多个模块被编码 AI 各自解释，最终形成双写、历史污染、权限不一致和无法总验收。
因此在 HR18 前补 00 最合理：现在已有足够多已冻结边界可反向汇总成真实全局合同。

# 2. 18 模块总目录

- **HR01 人事工作台**：人事运营控制台，聚合可信事实/待办/预警，不拥有下游业务真值
- **HR02 组织机构与编制岗位**：组织、部门、岗位、编制/岗位供给与结构历史 Authority
- **HR03 教职工主档**：Person/Staff/EmploymentRelationship/Assignment 人事基础事实 Authority
- **HR04 招聘与人才引进**：用人计划、招聘、应聘、选拔、拟录用/Offer Authority
- **HR05 入职管理**：待报到、报到、材料、协同、激活、试用转正编排 Authority
- **HR06 人事异动**：校内调动/转岗/组织岗位变更的有效期 Case Authority
- **HR07 合同与聘用**：合同/协议/聘期/签署/续签/变更/解除终止 Authority
- **HR08 兼职外聘教师**：兼职/外聘/产业专家 External Engagement Authority
- **HR09 教师资格与双师型**：教师资格、双师型认定及复核 Authority
- **HR10 培训进修与企业实践**：教师发展、培训、进修、企业实践 VERIFIED 事实 Authority
- **HR11 考勤与请假**：制度、日历、排班、考勤、请假、加班、月结时间事实 Authority
- **HR12 年度与聘期考核**：年度/聘期/平时/专项/师德考核正式结果 Authority
- **HR13 职称评审**：职称申报、评议、公示、备案、正式结果 Authority
- **HR14 岗位聘任**：竞聘、资格、评议、排序、拟聘、公示、聘任/聘期 Authority
- **HR15 薪酬福利**：薪酬档案、规则、月结、调资、社保公积金、支付/财务对账 Authority
- **HR16 退休与离校**：辞职/调出/解除/退休、离校编排与 Exit/Retirement Fact Authority
- **HR17 教职工服务中心**：统一 ESS 体验 Authority；只聚合本人事实和动作
- **HR18 人事数据中心**：指标、报表、数据质量、交换、正式上报与报送档案 Authority

# 3. 产品边界

本产品是高校人事管理与教师发展系统，不是财务总账、教务、科研、资产、IAM、OA、通用档案全文库或无限制 BI。
外部系统通过 Provider/API/Event/数据交换对接；不得为了方便把外部 Authority 复制进 HR。

# 4. 总架构

```text
Authoritative Domain Facts
        ↓
Versioned Rule / Effective Decision
        ↓
Outbox Events / Providers
        ↓
Read Models / HR01 / HR17 / HR18
        ↓
External Systems / Reporting
```
禁止 `Dashboard/Report/Legacy/External callback → direct overwrite Authority`。

# 5. Authority 单一事实源

同一事实只有一个正式写 Authority。
其他模块只能 reference、snapshot、projection、Provider read、event consume、review task。
禁止共享 ORM 模型跨域 `.save()` 正式事实；禁止前端“双接口写入保持一致”。

# 6. Fact / Case / Projection 三层

- Fact：正式真值，FINAL/EFFECTIVE/CLOSED 后受不可变规则保护。
- Case/Workflow：形成真值的过程。
- Projection/ReadModel：为首页、ESS、报表、Legacy 兼容生成，可重建。
Projection 丢失可重建；Authority 丢失是生产事故。

# 7. effective-dated 总合同

业务状态区间统一优先 `[effective_from,effective_to)`；无固定结束使用 NULL，不用 2099-12-31。
业务有效时间、决定时间、创建时间、更新时间分别存储。
任何历史查询必须基于当时 Fact/Version/Snapshot，禁止拿 current 字段回填过去。

# 8. Tenant Root

所有学校级事实必须显式 tenant_id 或可从聚合根唯一解析 tenant。
request/job/event/provider 均携带 tenant context。
无法确定 tenant 时 fail-closed；禁止默认第一学校、`all`、前端过滤。

# 9. Horilla Company 接管

`Company` / selected_company 只能作为 Legacy/兼容来源。
S0 必须给出 Tenant ↔ Company 映射、跨法人策略、后台 Job tenant 解析与退出 thread-local 的计划。
新 Authority 不能依赖有 HTTP request 才能保证租户隔离。

# 10. Person / User / Staff 分层

`Person != User != Staff != EmploymentRelationship != Assignment != ExternalEngagement`。
同一自然人可以退休后返聘、多段聘用、多 Engagement、多角色。
禁止继续用单一 Employee 表吞掉全生命周期。

# 11. 统一 Provider Status

```text
OK
PARTIAL
UNAVAILABLE
STALE
ERROR
NOT_APPLICABLE
```
`UNAVAILABLE != 0 != false != empty list`。

# 12. 统一可信度

```text
AUTHORITY_VERIFIED
PROVIDER_VERIFIED
DOCUMENT_VERIFIED
MANUAL_VERIFIED
SELF_REPORTED
MIGRATED_VERIFIED
MIGRATED_PARTIAL
MIGRATED_UNVERIFIED
UNAVAILABLE
DISPUTED
REVOKED
```

# 13. Provider Contract

每个 Provider 固定 owner domain、consumer、tenant、ids、as_of、sourceVersion、freshness、timeout、sensitivity、authorization、errors、cache policy。
Provider 不可用不得 silent fallback legacy。

# 14. 跨域写合同

跨域写只能通过 source domain command API、durable event 或受控 Provider action。
消费者不得 import 对方 Authority model 后直接写。

# 15. 事件信封

```json
{"eventId":"uuid","eventType":"AppointmentEffective","eventVersion":1,"tenantId":"t","aggregateType":"...","aggregateId":"...","aggregateVersion":7,"occurredAt":"...","effectiveAt":"...","correlationId":"...","causationId":"...","payload":{}}
```

# 16. Outbox / Inbox

正式事务必须 `domain state + audit + outbox` 同事务；发布失败可重试。
消费者按 eventId/providerEventId 幂等；重复 10 次结果一致；旧 aggregateVersion 不覆盖新状态。

# 17. Correlation

跨 HR04→05→03→07→15 等长链用 correlationId/causationId；事故排查必须能从 UI 一直追到源事件。

# 18. RuleVersion

资格、审批、考核、配额、工资、退休、报表、映射、文书等会变化规则必须版本化。
PUBLISHED immutable；同优先级命中冲突必须显式 CONFLICT，禁止 `.first()`。

# 19. Snapshot

批次、考核、职称、聘任、工资、报送等关键节点冻结 subject/org/position/policy/source/version/value/hash。
今天的 current 值不能改变旧结论。

# 20. 正式结果不可原地改

FINAL/EFFECTIVE/CLOSED 之后用 Amendment/Revision/Correction/Revocation/Delta/NewTerm/Supersede。
禁止普通 CRUD UPDATE 和 hard delete。

# 21. 业务状态与技术状态

`Payroll FINAL != PAID`；`Document GENERATED != SIGNED`；`Submission SENT != ACCEPTED`；`Exit EFFECTIVE != IAM REVOKED`；`Contract SIGNED != ACTIVE`。
禁止一个 boolean 替代完整状态链。

# 22. RETURN / REJECT

RETURNED=可补正并产生新版本；REJECTED=正式否决本轮。
权限、通知、统计和再次提交规则分离。

# 23. 统一幂等

create staff、activation、signature callback、effect transition、payroll finalize/payment、import confirm、submission send 均需 idempotency key。
网络超时后先 query/reconcile，不盲目重复正式动作。

# 24. 并发

使用 optimistic version、DB unique、row lock、atomic conditional update、deadlock retry。
禁止 read-then-write 无锁抢最后岗位、编号、额度、finalize。

# 25. Person Transition Lock

HR05 activation、HR06 transfer、HR14 appointment effect、HR16 exit 对同一关系建立 transition lock/impact check。
future-effective 事件也参与冲突检测。

# 26. 数据库目标（PATCH-00 冻结：MySQL-only）

- **Production / Development / Test / CI / Migration Acceptance 全部按 MySQL 执行**（00 最高合同；复审 P0-03/P1-06 冻结）。
- **禁止新增 PostgreSQL 专属 Authority 设计**：`daterange / btree_gist / GIST / ExclusionConstraint` 一律改为 MySQL 可落地的 `effective_from/effective_to + service validation + transaction lock + unique/current invariant + concurrency test`。
- 旧册中 PostgreSQL 描述仅作为**迁移识别知识**，不作为新 Authority 设计约束。
- migrations、FK/unique、Decimal、JSON、locking、deadlock、indexes、rollback、backup/restore 在 MySQL 目标版本全绿后才能生产封板。
- SQLite 只可做轻量单测，不是最终数据库验收。
- 搜索索引按 MySQL collation/generated/hash/index 能力重新设计。

# 27. Migration 分类

```text
ADDITIVE_SAFE
BACKFILL_REQUIRED
DUAL_WRITE_TEMPORARY
CUTOVER_REQUIRED
DESTRUCTIVE_POST_CUTOVER
```
跨 app migration 建依赖图，删除旧结构只能在 Authority cutover 之后。

# 28. API 版本

统一 `/api/v1/hr/...`；响应带 apiVersion/schemaVersion/requestId；破坏性变更新 major path，普通升级 additive。

# 28.1 Canonical API Root（PATCH-00 冻结）

- 全系统唯一新 API Root：**`/api/v1/hr`**。
- 旧 `/api/hr/v1/...` 只能作为 **Legacy Adapter / redirect / reverse proxy**：只读/重定向/兼容，有 deprecation metric，不新增业务 handler，客户端迁完后删除。
- 所有新契约测试只以 `/api/v1/hr/...` 为 Authority。
- 一级资源：`dashboard / organizations / staff / recruitment / onboarding / changes / contracts / external / qualifications / development / time / assessments / titles / appointments / payroll / exit / self / data`。

# 28.2 Canonical Permission Registry（PATCH-00 冻结）

统一 `hr.<domain>.<resource>.<action>`，18 个 domain slug 固定：

| 模块 | Prefix | 模块 | Prefix |
|---|---|---|---|
| HR01 | `hr.dashboard` | HR10 | `hr.development` |
| HR02 | `hr.organization` | HR11 | `hr.time` |
| HR03 | `hr.staff` | HR12 | `hr.assessment` |
| HR04 | `hr.recruitment` | HR13 | `hr.title` |
| HR05 | `hr.onboarding` | HR14 | `hr.appointment` |
| HR06 | `hr.change` | HR15 | `hr.payroll` |
| HR07 | `hr.contract` | HR16 | `hr.exit` |
| HR08 | `hr.external` | HR17 | `hr.self` |
| HR09 | `hr.qualification` | HR18 | `hr.data` |

- 旧 `hr04.* / hr05.* / hr08.* ...` 通过 `PermissionAliasMapping` 迁移，Authority code 只保留一套，alias 不重复授权。
- SELF 与平台权限单独 namespace。

# 28.3 Global Event Registry（PATCH-00 冻结）

统一正式跨域事件（禁止继续使用 `ProfessionalTitleAppointmentEffective`、模糊 `AppointmentEffective` 等同义词）：

```text
StaffActivated / PersonnelChangeEffective / ContractEffective / ContractTerminated
QualificationResultEffective / DevelopmentFactVerified / TimePeriodClosed / AssessmentResultFinalized
ProfessionalTitleResultEffective / ProfessionalTitleResultRevised / ProfessionalTitleResultRevoked
PositionAppointmentEffective / CompensationReevaluationRequested / PayrollFinalized
ExitEffective / RetirementEffective
```

- HR13 → `ProfessionalTitleResultEffective*`；HR14 → `PositionAppointmentEffective`；HR14/HR03/HR06 → `CompensationReevaluationRequested` → HR15。
- 每事件冻结：eventVersion / owner / consumers / aggregate / tenant / effectiveAt / payload schema / PII classification / idempotency / replay rule。
- 所有跨域事件由 registry 生成契约测试，禁止总册各自造同义词。

# 28.4 Metric Authority（PATCH-00 冻结）

- 正式指标定义 Authority 统一归 **HR18**（MetricDefinition / MetricDefinitionVersion / Population / Dimension / as-of）。
- **HR01 = Metric Consumer + Dashboard Presentation Authority**：只拥有首页布局、卡片顺序、角色化展示、Alert/Todo/QuickAction、stale 展示政策；不再拥有公式和 population。
- HR01 原 `MetricDefinitionRegistry` 内容迁到 HR18/共享 Metric Registry；HR18 未施工时可临时使用 `EmbeddedMetricRegistryAdapter`，cutover 后只能投影/兼容。
- 同一 metricKey 只有一个 definitionVersion；HR01 值与 HR18 drilldown 守恒。

# 29. 错误信封

```json
{"error":{"code":"DOMAIN_REASON","message":"...","details":{},"retryable":false},"requestId":"..."}
```
前端不得解析数据库/英文异常文本决定业务。

# 30. HTTP 语义

400 validation；401 unauthenticated；403 permission/scope；404 hidden/not found；409 version/state conflict；429 rate；503 provider unavailable。

# 31. 分页

统一数据库 `WHERE → COUNT/hasNext → ORDER → LIMIT/OFFSET or cursor`；禁止先分页再 Python 过滤或全表拉内存。

# 32. 异步 Job

```text
PENDING → RUNNING → SUCCESS / FAILED / CANCELLED / EXPIRED
```
Job 保存 tenant/type/params hash/progress/result/error/retry/created_by；同步完成后伪装任务严格禁止。

# 33. Excel 总合同

所有核心 Excel：versioned template → upload → staging → validation → error workbook → preview → confirm → async execute → result ledger → audit。
Excel 不能直接覆盖 FINAL、签署、支付、上报成功或跨 tenant。

# 34. 文件安全

private object storage；MIME/extension/size/virus scan/hash；authorization→download ticket→short signed URL。
敏感文件可 reauth/watermark；日志禁止裸 URL/正文。

# 35. 审计

记录 tenant、actor/on-behalf、object、action、before/after/revision ref、reason、requestId、time。
正式审计不可由业务管理员 CRUD 删除；Legal Hold 高于 purge。

# 36. 数据分级

PUBLIC / INTERNAL / PERSONAL / SENSITIVE_PERSONAL / HIGHLY_RESTRICTED；工资、身份证、银行卡、医疗、处分、匿名评议、家庭税务信息为高敏。

# 37. 字段加密

身份证/银行卡/税号等加密或 tokenization；mask/reveal permission/key rotation/access audit；禁止进日志。

# 38. Data Scope

统一 SCHOOL / COLLEGE / DEPARTMENT / ASSIGNED / SELF。
KPI、列表、导出、drilldown 同一个 ResolvedScope；有页面权限不等于有字段权限。

# 39. SoD

合同解除、职称 final、聘任 final、工资调整/final/payment、离校 effect、正式上报等支持 maker-checker。

# 40. 平台运营

平台运营只看 tenant/system health/capacity/licensing；默认无学校人事/工资/档案权限。Break-glass 要 reason/timebox/audit。

# 41. IAM 边界

IAM 管账号/session/MFA/group/access；HR 管 Person/Employment；provision/deprovision 用 Provider receipt + reconciliation。

# 42. 通知

业务事件→templateVersion→recipient→channel→dedupe→delivery status；消息已读不等于业务完成。

# 43. 缓存

缓存只优化 read；业务 action 前按风险实时/版本校验。
Dashboard metric 带 sourceUpdatedAt/calculatedAt/maxStale/status；只允许非交易页面 stale-on-error。

# 44. 可观测性

每域至少 request、provider、jobs、outbox lag、reconciliation drift、security denial、legacy write attempts、data quality metrics。

# 45. 结构化日志

requestId/tenant/actor/domain/aggregate/action/status/errorCode/duration；禁止高敏 payload。

# 46. 数据质量

`DataQualityFinding` 只发现/跟踪，不直接改 Authority。
ruleVersion/severity/objectRef/observed/expected/owner/status/resolution/evidence 必须齐全。

# 47. Reconciliation

定期对账 HR02 position↔HR03 assignment↔HR14 appointment；HR07 contract↔HR03 relationship；HR15 payroll↔payment/finance；HR16 exit↔HR03/HR14/IAM；HR18 submission↔source snapshot。

# 48. UI Design System

统一 PageHeader/StatusBadge/RiskBanner/FilterBar/DataTable/StickyHeader/Timeline/TaskMatrix/EvidencePanel/Empty/Error/Stale/Partial/Pagination。

# 49. 抽屉规则

短查看/简单编辑可 Drawer；合同、考核、职称、竞聘、工资月结、退休、批量/正式报送必须 Full Page/Workbench。

# 50. 响应式

后台管理 1440/1280 主设计，768 fallback；375 重点用于 HR17 与高频移动动作，复杂后台不强求完整移动编辑。

# 51. Accessibility

键盘、focus、label、error association、table semantics、status text、contrast、zoom；颜色不能是唯一状态。

# 52. AI 总边界

AI 可搜索、解释、摘要、辅助填表/测试。
AI 不得决定录用、考核 final、职称/聘任、工资、解除/退休；不得绕权限或编造个人事实。
个人状态回答必须 grounded 到结构化 Authority/Provider。

# 53. Legacy 裁决类型

```text
KEEP
ADAPT
REWRITE
PROJECT
READONLY
DEPRECATE
DROP_AFTER_CUTOVER
```
每个旧对象/路由在 S0 必须标策略、owner、cutover condition。

# 54. LegacyDataMapping

旧字段→新 Authority 记录 transform、trust、tenant/person resolution、effective date、conflict、evidence。旧库数据不自动 VERIFIED。

# 55. Legacy Projection

切换后只允许 `New Authority → Legacy Projection`；旧 UI/form 进入 readonly/redirect。禁止双向同步形成双主。

# 56. 统一 Cutover

```text
LEGACY_ACTIVE
→ NEW_STAGING
→ DUAL_READ_COMPARE
→ SHADOW_EXECUTION
→ FREEZE_LEGACY_FORMAL_WRITES
→ NEW_AUTHORITY
→ LEGACY_READONLY_PROJECTION
→ POST_CUTOVER_CLEANUP
```

# 57. No silent fallback

Authority 切换后严禁 catch Exception → legacy。迁移模式必须显式 flag + metric + audit。

# 58. Horilla Signal 治理

S0 清点 signal/save hook/thread-local side effects；正式跨域副作用迁 domain service + outbox。

# 59. Background Context

Job/Event consumer 显式带 tenant、system actor、correlation、timezone、service principal；不能依赖当前 request。

# 60. Security Negative Tests

每模块 tenant、IDOR、scope、field、file、export、callback spoof、mass assignment、CSRF/XSS（适用）全覆盖。

# 61. 目标库测试

生产目标数据库跑全迁移、锁、并发、Decimal、JSON、索引 EXPLAIN、rollback、restore；测试库与生产数据库语义差异要列清。

# 62. 备份恢复

DB、object storage、keys、config、migration state 全部纳入；恢复后做 outbox/provider/reconciliation，而不是只看 health=200。

# 63. Secret

Secret 不进 git；provider credentials tenant-scoped；生产 debug/mock-login 关闭；支持 rotation。

# 64. Feature Flag

用于 rollout/shadow/UI entry，不允许同时存在两个 formal write authority。

# 65. 统一 Actor

USER / SYSTEM / SERVICE / IMPORT / MIGRATION；on-behalf 同时记录真实操作者与业务主体。

# 66. 批量动作

Batch header + item states；逐项幂等，可部分失败/error workbook；高风险先 impact preview。

# 67. Metric Registry

HR01/HR18 共用定义：numerator/denominator/population/exclusion/time grain/as_of/scope/source/rounding/privacy/drilldown；正式 KPI 不在前端临时计算。

# 68. 正式上报

一定形成 SubmissionPackage：definition version、snapshot、validation、approval、payload/file hash、submitted_at、receipt、correction chain、archive。

# 69. External Exchange

API / FILE / SFTP / MESSAGE / DB_STAGING / MANUAL_UPLOAD；不存在真实接口时不得声称已对接。EXPORTED/SENT != ACCEPTED。

# 70. 全系统施工阶段

G0 baseline → G1 A0/security → G2 authority foundations → G3 cross-domain contracts → G4 features → G5 dual compare → G6 cutover → G7 full regression → G8 production readiness。

# 71. HR01 Authority 总合同

**HR01 人事工作台**：人事运营控制台，聚合可信事实/待办/预警，不拥有下游业务真值。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 72. HR02 Authority 总合同

**HR02 组织机构与编制岗位**：组织、部门、岗位、编制/岗位供给与结构历史 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 73. HR03 Authority 总合同

**HR03 教职工主档**：Person/Staff/EmploymentRelationship/Assignment 人事基础事实 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 74. HR04 Authority 总合同

**HR04 招聘与人才引进**：用人计划、招聘、应聘、选拔、拟录用/Offer Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 75. HR05 Authority 总合同

**HR05 入职管理**：待报到、报到、材料、协同、激活、试用转正编排 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 76. HR06 Authority 总合同

**HR06 人事异动**：校内调动/转岗/组织岗位变更的有效期 Case Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 77. HR07 Authority 总合同

**HR07 合同与聘用**：合同/协议/聘期/签署/续签/变更/解除终止 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 78. HR08 Authority 总合同

**HR08 兼职外聘教师**：兼职/外聘/产业专家 External Engagement Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 79. HR09 Authority 总合同

**HR09 教师资格与双师型**：教师资格、双师型认定及复核 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 80. HR10 Authority 总合同

**HR10 培训进修与企业实践**：教师发展、培训、进修、企业实践 VERIFIED 事实 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 81. HR11 Authority 总合同

**HR11 考勤与请假**：制度、日历、排班、考勤、请假、加班、月结时间事实 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 82. HR12 Authority 总合同

**HR12 年度与聘期考核**：年度/聘期/平时/专项/师德考核正式结果 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 83. HR13 Authority 总合同

**HR13 职称评审**：职称申报、评议、公示、备案、正式结果 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 84. HR14 Authority 总合同

**HR14 岗位聘任**：竞聘、资格、评议、排序、拟聘、公示、聘任/聘期 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 85. HR15 Authority 总合同

**HR15 薪酬福利**：薪酬档案、规则、月结、调资、社保公积金、支付/财务对账 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 86. HR16 Authority 总合同

**HR16 退休与离校**：辞职/调出/解除/退休、离校编排与 Exit/Retirement Fact Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 87. HR17 Authority 总合同

**HR17 教职工服务中心**：统一 ESS 体验 Authority；只聚合本人事实和动作。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 88. HR18 Authority 总合同

**HR18 人事数据中心**：指标、报表、数据质量、交换、正式上报与报送档案 Authority。
自身总册必须定义 aggregate roots、write APIs、read Providers、events、snapshots、FINAL/EFFECTIVE、permissions/scope、Legacy mapping/cutover/reconciliation。
其他模块不得通过共享 ORM 直接写本域正式事实。

# 89. 关键跨域边界｜HR02→HR03

HR02 定义组织/岗位供给；HR03 记录谁在何时实际任职。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 90. 关键跨域边界｜HR02→HR04

招聘引用批准 Position/供给，不自建岗位真值。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 91. 关键跨域边界｜HR04→HR05

拟录用/Offer 完成后幂等 handoff；录用不等于入职。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 92. 关键跨域边界｜HR05→HR03

Activation Gate 后创建/激活 Person/Staff/Relationship/Assignment。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 93. 关键跨域边界｜HR03→HR07

合同绑定 EmploymentRelationship，不重建聘用关系。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 94. 关键跨域边界｜HR03→HR06

异动正式改变 Assignment/Relationship 历史。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 95. 关键跨域边界｜HR03→HR08

Person 可复用；External Engagement 不等于正式 Staff。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 96. 关键跨域边界｜HR10→HR09

VERIFIED 培训/企业实践仅作为双师证据，不自动认定。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 97. 关键跨域边界｜HR11→HR12

只消费 closed/frozen 时间事实，不读 raw punch。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 98. 关键跨域边界｜HR12→HR13

正式考核可作职称证据，不能反向改考核。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 99. 关键跨域边界｜HR13→HR14

职称是聘任资格输入，不自动占岗。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 100. 关键跨域边界｜HR14→HR03

EFFECTIVE Appointment 才驱动 Assignment/聘任投影。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 101. 关键跨域边界｜HR14→HR15

EFFECTIVE 聘任触发薪酬复核，不直接等于金额。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 102. 关键跨域边界｜HR16→HR14

ExitEffective 后关闭 appointment，再释放 position。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 103. 关键跨域边界｜HR16→HR15

只给 final dates/settlement request，HR15 算最终金额。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 104. 关键跨域边界｜HR03–16→HR17

HR17 聚合 SELF read/action，不复制真值。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 105. 关键跨域边界｜HR01–17→HR18

HR18 消费规范正式事实/事件/快照，不反向写源域。
必须有 Provider/Event contract、idempotency、source version、失败状态和 reconciliation。

# 106. Horilla 接管矩阵｜employee.Employee / EmployeeWorkInformation

- 目标域：**HR03**
- 裁决：**REWRITE + PROJECT**
- 说明：旧 current snapshot 只做兼容，不能承担历史。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 107. Horilla 接管矩阵｜base Company/Department/JobPosition

- 目标域：**A0/HR02**
- 裁决：**REWRITE/ADAPT**
- 说明：映射 Tenant/Org/Position，旧对象逐步只读。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 108. Horilla 接管矩阵｜recruitment

- 目标域：**HR04**
- 裁决：**REWRITE**
- 说明：复用 pipeline/UI 技术，重建高校招聘 Authority。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 109. Horilla 接管矩阵｜onboarding

- 目标域：**HR05**
- 裁决：**REWRITE**
- 说明：复用 task/portal，重建 Activation 与跨域事务。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 110. Horilla 接管矩阵｜payroll.Contract

- 目标域：**HR07/HR15**
- 裁决：**DEPRECATE + PROJECT**
- 说明：合同归 HR07；工资归 HR15。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 111. Horilla 接管矩阵｜attendance/leave

- 目标域：**HR11**
- 裁决：**REWRITE**
- 说明：保留采集/申请能力，重建高校规则与月结。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 112. Horilla 接管矩阵｜pms

- 目标域：**HR12**
- 裁决：**REWRITE**
- 说明：保留 goal/feedback 技术，重建正式考核。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 113. Horilla 接管矩阵｜payroll

- 目标域：**HR15**
- 裁决：**REWRITE**
- 说明：保留 payslip/allowance/job，重建薪酬 Authority。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 114. Horilla 接管矩阵｜offboarding

- 目标域：**HR16**
- 裁决：**REWRITE**
- 说明：保留 Task/Pipeline，重建 ExitCase/RetirementFact。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 115. Horilla 接管矩阵｜employee ESS/dashboard

- 目标域：**HR17**
- 裁决：**REWRITE**
- 说明：管理指标回 HR01；普通员工统一 HR17。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 116. Horilla 接管矩阵｜report

- 目标域：**HR18**
- 裁决：**REWRITE**
- 说明：保留 dynamic report/pivot/template，重建指标/质量/交换/上报。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 117. Horilla 接管矩阵｜horilla_documents

- 目标域：**全域**
- 裁决：**KEEP/ADAPT**
- 说明：做安全 Document Provider。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 118. Horilla 接管矩阵｜horilla_audit

- 目标域：**全域**
- 裁决：**KEEP/ADAPT**
- 说明：补 correlation/高敏审计。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 119. Horilla 接管矩阵｜notifications

- 目标域：**全域**
- 裁决：**KEEP/ADAPT**
- 说明：事件驱动、模板版本、去重和回执。
- S0 必须再次从目标分支核验字段、路由、signals、permissions、副作用和 Legacy 写入口，不能按文档名称假装完成。

# 120. 全局治理｜全局权限命名

`hr.<domain>.<resource>.<action>`；SELF 与平台权限单独 namespace。

# 121. 全局治理｜事件命名

事实事件过去式 `StaffActivated/AppointmentEffective/PayrollFinalized`；请求显式 `...Requested`。

# 122. 全局治理｜金额

正式金额/比例使用 Decimal；禁止 Float 进入薪酬/额度计算。

# 123. 全局治理｜JSON

规则/快照可用 JSON；关键关系/金额/状态/索引字段不能全部塞 JSON。

# 124. 全局治理｜soft delete

业务终止优先 status/end/supersede；soft delete 不是业务事实。

# 125. 全局治理｜hard delete

FINAL/EFFECTIVE/审计/正式文件禁止；草稿删除也检查引用。

# 126. 全局治理｜Legal Hold

合同、薪酬、离退、争议、评审等 hold 优先于 retention purge。

# 127. 全局治理｜敏感脱敏

list/export/log/search index 分别治理；CSS 隐藏不是权限。

# 128. 全局治理｜搜索索引

高敏正文不进通用搜索；permission/filter before ranking。

# 129. 全局治理｜小样本保护

分析敏感维度按 policy suppress/aggregate；正式上报另走 Submission。

# 130. 全局治理｜导出审计

高敏导出可要求 reason/reauth/watermark/TTL/audit。

# 131. 全局治理｜浏览器安全

CSP、secure cookie、SameSite、CSRF、frame-ancestors、敏感页 no-store。

# 132. 全局治理｜Webhook

signature/timestamp/replay window/providerEventId；IP 不是唯一信任。

# 133. 全局治理｜Rate Limit

login/public portal/search/download-ticket/OTP/webhook/action 分开限流。

# 134. 全局治理｜Public Portal

招聘/入职外部入口使用 public slug/token；裸 tenant id 不是授权。

# 135. 全局治理｜Mobile

复用同一业务 Authority/API；禁止 mobile mock 第二套真值。

# 136. 全局治理｜公式引擎

禁止任意 SQL/Python eval/exec；使用 typed DSL/sandbox。

# 137. 全局治理｜CI

lint/static/security/unit/integration/e2e/migration/target-db/visual 分层；关键检查不得永久 continue-on-error。

# 138. 全局治理｜测试数据

factory 必须多 tenant、多关系、多历史 effective date；不能所有测试只有一个公司/一个 Employee。

# 139. 全局治理｜生产迁移

staging/backfill/checksum/compare/cutover；现场 SQL 手改必须补正式修复记录。

# 140. 全局治理｜权限缓存

角色/组织变化及时失效；员工调离后不能继续缓存旧学院权限。

# 141. 全局治理｜Django Admin

正式 Authority 默认受限/只读/高权限；不能成为绕工作流后门。

# 142. 全局治理｜Clock

业务时间可注入；避免到处 `date.today()` 造成时区和历史不可测。

# 143. 全局治理｜数据字典

记录 owner/type/sensitivity/definition/source/history/export/reporting。

# 144. 全局治理｜Integration Registry

provider endpoint/auth owner/SLA/schema/sensitivity/test status。

# 145. 全局治理｜Rule Registry

所有 PUBLISHED RuleVersion 有 owner/source/effective/hash。

# 146. 全局治理｜Document Registry

类型/source/template/signature/verification/retention。

# 147. 全局治理｜SourceStatus UI

OK/PARTIAL/UNAVAILABLE/STALE/ERROR 统一组件。

# 148. 全局治理｜Conflict UX

409 必须提示重新加载/比较；禁止 last-write-wins。

# 149. 全局治理｜Async UX

progress/failure/retry/download/expiry/cancel；不能只 toast。

# 150. 全局治理｜Help

帮助绑定 feature/version；废弃菜单、假功能、未来规划型帮助下线。

# 151. 全局治理｜事故等级

P0=跨租户/重复支付/正式事实严重错误；P1=核心链阻塞/对账失败；其余分级处理。

# 152. 全局治理｜Runbook

provider outage、stuck job、drift、security、rollback 都要 owner/检测/隔离/恢复/复核。

# 153. 全系统生命周期 E2E

```text
用人计划 → 招聘 → Offer → 入职 → Staff/Relationship/Assignment → 合同
→ 资格/培训/考勤 → 年度/聘期考核 → 职称 → 岗位聘任 → 薪酬
→ 异动 → 退休/离校 → Retiree/返聘 → HR18 as-of/reporting
```
每一步必须保留历史，不允许后续 current 值覆盖前一阶段正式事实。

# 154. 全系统历史抽验

随机选人员跨 3–5 个历史日期查询组织、岗位、合同、资格、考核、职称、聘任、工资、离退状态。
今天修改组织/岗位/职称后，历史结果必须保持当时事实。

# 155. 全系统角色验收

学校人事管理员、人事负责人、学院秘书、学院负责人、普通教职工、评委/专家、工资员、财务、IAM/资产/档案、退休人员、外聘人员、平台运营均做正/负权限测试。

# 156. 全系统故障注入

Provider 500、DB deadlock、worker down、duplicate event、timeout-after-success、storage outage、IAM outage、payment/report partial success。
必须无重复正式事实，可恢复、可对账。

# 157. 全系统上线顺序原则

优先 HR02/HR03 基础 Authority，再逐步招聘/入职/合同/外聘/发展/考勤/考核/职称/聘任/薪酬/离退，之后 HR17 统一 ESS，最后 HR18 统一数据中心。
实际顺序以已施工状态和依赖图为准，不允许 18 个域同夜无演练切换。

# 158. 全系统 Final Gate

只有 00 合同落实、HR01–HR18 各自 READY、cross-domain reconciliation 全绿、Legacy formal writes 冻结、目标数据库全绿、backup/restore、安全/E2E/性能/可观测/rollback rehearsal 全绿且 P0/P1=0，才能：
```text
SYSTEM READY FOR PRODUCTION ACCEPTANCE
```

# 159. 00 最终验收口径

```text
GLOBAL ARCHITECTURE CONTRACT READY
```
若任何 Authority 重叠、tenant fail-open、silent legacy fallback、历史污染、跨域直写、目标数据库未验收、回滚/恢复缺失，则只能：
```text
GLOBAL ARCHITECTURE CONTRACT NOT READY
blocking:
- <精确缺口>
```

# 160. 00 编码 AI 首条执行指令

```text
你现在先执行全系统 Global-S0，只审计和物化治理清单，不大改业务代码。
唯一全局合同：00_高校人事系统全局架构与Horilla接管合同.md
业务事实源：01_HR01 至 18_HR18 各模块终极总册。

必须输出：
- GlobalAuthorityOwnershipMatrix.md
- HorillaGlobalTakeoverMatrix.md
- CrossDomainProviderEventMatrix.md
- TenantIdentityPermissionMatrix.md
- LegacyDataMappingIndex.md
- MigrationDependencyGraph.md
- TargetDatabaseCompatibilityMatrix.md
- GlobalReconciliationMatrix.md
- GlobalProductionGateChecklist.md

禁止：git add -A；未经授权 push/merge main/生产部署；silent fallback legacy；关闭403；跨域直接写；用 mock 冒充正式外部结果。
最终只允许 GLOBAL ARCHITECTURE CONTRACT READY + HR01..HR18 READY + SYSTEM READY FOR PRODUCTION ACCEPTANCE。
```
