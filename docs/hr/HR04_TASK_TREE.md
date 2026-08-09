# HR04 Task Tree（S1–S12 · 文件级任务树）

> 依据：《04_HR04_招聘与人才引进_施工总册_终极版》第 53 节 AI 施工顺序 + HR04_S0 审计。
> 原则：一个阶段一个可验证提交；全程 Draft PR；未授权不合并 main；不做越界改造。
> 约定：新增 app 建议名 `hr_recruitment`（总册 16 节）；Horilla `recruitment/` 旧代码逐步收拢到 `recruitment/legacy/`。

---

## 依赖图

```
S1 契约/公共组件 ─────────────┐
S2 权威模型骨架 + migrations ──┼──── S3 HR04-01 ─┐
                              │                  ▼
                              ├──── S4 HR04-02 ──┤ (HR02 预占，硬门)
                              │                  ▼
                              ├──── S5 HR04-03 ──┼─────┐ (公开门户 token)
                              │                  │     ▼
                              ├──── S6 HR04-04 ──┼─────┤
                              │                  │     ▼
                              ├──── S7 HR04-05 ──┼─────┤
                              │                  │     ▼
                              └──── S8 HR04-06 ──┼─────┘ (HR05 handoff)
                                                 ▼
S9 Legacy Projection → S10 DUAL_READ_COMPARE → S11 生产验收 → S12 封板
```

- S3–S8 全部依赖 S1（权限/enum/envelope/UI）+ S2（模型/migrations/约束）。
- S4 依赖 HR02 预占接口或 LEGACY_CURRENT_SNAPSHOT 降级。
- S8 依赖 S5 幂等提交、S6 资格结论、S7 评分快照。
- S9–S10 是横切收口，任何阶段完成后可逐步叠投影。

---

## HR04-S1 契约 / 公共组件

**目标**：权限码、enum、API envelope、UI 组件、路由骨架、projection 契约；不建业务表。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `renshi/hr_recruitment/__init__.py` / `apps.py` | 新增 app；`ready()` 注册 urls（前缀 `/hr/recruitment/`）+ INSTALLED_APPS 追加 |
| 2 | `renshi/hr_recruitment/constants.py` | 冻结 enum：`ApplicationCanonicalStatus`（总册 14.1 全套 24 值）、`CampaignStatus`、`PositionStatus`、`PlanStatus`、`ReservationStatus`、`DecisionType`、`RuleSeverity`、`SchemeStatus`、`AssessmentMode`、`ConflictStatus`、`ScoreSheetStatus`、`MedicalStatus`、`NoticeStatus`、`ObjectionStatus`、`OfferStatus`、`CandidateStatus`、`NeedType` |
| 3 | `renshi/hr_recruitment/permissions.py` | HR04 权限码（总册 6.3：hr04.plan.* / campaign.* / application.* / qualification.* / assessment.* / proposed_hire.* / public_notice.* / offer.* / handoff_hr05）+ `HrRecruitmentPermissionMeta(managed=False)` 注册 |
| 4 | `renshi/hr_recruitment/api/base.py` | `HrApiEnvelope`（apiVersion/schemaVersion/requestId/data/generatedAt）、`HrApiError`（错误信封：code/message/details）、`_request_id`、幂等键读取、If-Match/version 读取 |
| 5 | `renshi/hr_recruitment/api/exceptions.py` | `TenantContextRequiredError(403)`、`PermissionDeniedError(403)`、`VersionConflict(409)`、`PositionCapacityConflict(409)`、`InvalidStateTransition(409)`、`ScoreAlreadyLocked(409)`、`ApplicationAlreadySubmitted(409)`、`NotFoundError(404)`、`IdempotencyReplay` |
| 6 | `renshi/hr_recruitment/context.py` | `Hr04RequestContext`（tenant/school_timezone/user/scope/as_of/authority_mode），复用 `hr_control_center.context.build_hr_context` + `resolve_tenant_from_request`；无 tenant → 403 |
| 7 | `renshi/hr_recruitment/policies/` | `policies/__init__.py`、`state_machine.py`（canonical_status 合法迁移表 + 禁止路径 RETURNED→HIRED 等）、`capacity.py`（position 额度校验接口桩）、`idempotency.py`（Idempotency-Key 处理器接口） |
| 8 | `renshi/hr_recruitment/projections/` | `projections/__init__.py`、`projections/contracts.py`（Horilla Recruitment/Stage/Candidate → HR04 投影契约类型定义） |
| 9 | `renshi/templates/hr/recruitment/components/*.html` | 公共组件：`status_badge.html`、`funnel.html`、`capacity_card.html`、`timeline.html`、`application_status_rail.html`、`candidate_avatar.html`、`candidate_summary.html`、`qualification_matrix.html`、`score_sheet.html`、`risk_banner.html`、`portal_stepper.html`（复用 `static/hr/css/hr-tokens.css`，不复制 CSS） |
| 10 | `renshi/hr_recruitment/urls.py`（骨架） | 占位 include（S3–S8 逐模块挂载），保证系统 check 通过 |
| 11 | `renshi/hr_recruitment/tests/test_contracts.py` | enum 冻结值、权限码、envelope 序列化测试 |

**验收**：Django system check 通过；权限码可导入；envelope 契约测试绿；无业务表。

---

## HR04-S2 权威模型骨架 + migrations

**目标**：六域权威模型全建 + migrations + DB 约束（总册 46/47 节）；此阶段不接 UI/API。

| # | 文件 | 模型 |
|---|---|---|
| 1 | `hr_recruitment/models/plan.py` | `HrHiringPlanCycle`、`HrHiringPlanRequest`、`HrHiringPlanLine`（总册 8.3；tenant_id 全表带；状态机枚举；approval 时间线） |
| 2 | `hr_recruitment/models/campaign.py` | `HrRecruitmentCampaign`、`HrRecruitmentPosition`、`HrRecruitmentAnnouncementVersion`（总册 9.3；public_slug；版本链 supersedes） |
| 3 | `hr_recruitment/models/candidate.py` | `HrRecruitmentCandidate`（identity：legal_name/email/mobile/national_id_cipher/national_id_hash/consent/retention）、`HrCandidateIdentityMatch`（EXACT/POSSIBLE/NO_MATCH/INSUFFICIENT） |
| 4 | `hr_recruitment/models/application.py` | `HrJobApplication`（application_no、canonical_status、workflow_stage_id、版本冻结引用、form_snapshot）、`HrApplicationTransition`（ledger，总册 14.3）、`HrApplicationMaterial`（type/version/SHA-256/verification/敏感级/retention） |
| 5 | `hr_recruitment/models/qualification.py` | `HrQualificationRuleSetVersion`、`HrQualificationRule`（severity/operator/expected_value/evidence）、`HrQualificationReview`、`HrQualificationDecision`（总册 11.2/11.3） |
| 6 | `hr_recruitment/models/assessment.py` | `HrSelectionSchemeVersion`、`HrSelectionComponent`、`HrAssessmentEvent`、`HrEvaluatorAssignment`、`HrScoreSheetTemplate`、`HrScoreCriterion`、`HrCandidateScoreSheet`、`HrCandidateScore`、`HrSelectionResultSnapshot`（总册 12） |
| 7 | `hr_recruitment/models/selection.py` | `HrMedicalCheck`、`HrBackgroundCheck`（高敏字段敏感级标注） |
| 8 | `hr_recruitment/models/offer.py` | `HrProposedHire`、`HrPublicNotice`、`HrPublicNoticeEntry`、`HrNoticeObjection`、`HrRecruitmentOffer`、`HrRecruitmentHandoff`（总册 13） |
| 9 | `hr_recruitment/models/audit.py` | `HrRecruitmentAuditEvent`、`HrSensitiveCandidateAccessLog`（总册 26） |
| 10 | `hr_recruitment/models/__init__.py` | 统一导出 |
| 11 | `hr_recruitment/migrations/0001_initial.py` + 后续 | 全量迁移 |
| 12 | `hr_recruitment/models/constraints.py`（或 Meta 内联） | DB 约束：application_no tenant unique、campaign code tenant unique、active duplicate application policy、score evaluator+candidate+event unique、handoff proposed_hire unique、version>=1、额度非负（总册 46） |
| 13 | `hr_recruitment/models/indexes.py` | (tenant,status)、(tenant,campaign,status)、(tenant,position,canonical_status)、(tenant,candidate_id)、(tenant,application_no)、(tenant,submitted_at)、(tenant,due_at)、(event,application)、(proposed_hire,status)（总册 47） |
| 14 | `hr_recruitment/tests/test_models.py` / `test_constraints.py` / `test_state_machine.py` | 模型字段、约束、状态机测试 |

**验收**：migrations 可 apply；system check 绿；DB 约束生效（SQLite/Postgres 两引擎测试）。

---

## HR04-S3 年度用人计划（HR04-01 完整闭环）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_recruitment/services/plan_service.py` | 周期/请求/行的 CRUD + submit/return/resubmit/approve 状态机 + RETURNED≠REJECTED |
| 2 | `hr_recruitment/selectors/plan.py` | 列表（status 过滤、scope 过滤、分页） |
| 3 | `hr_recruitment/integrations/hr02.py` | HR02 资源校验 provider：`query_org_capacity()` → LEGACY_CURRENT_SNAPSHOT 降级返回 `ProviderResult(status/available/reserved/UNAVAILABLE)`；S4 重检 |
| 4 | `hr_recruitment/api/plan.py` | `GET/POST /api/hr/v1/recruitment/plans`、`GET .../plans/{id}`、`POST .../plans/{id}/submit|approve`、`POST/PATCH plan-requests` 系列（总册 8.5；envelope；tenant 403） |
| 5 | `hr_recruitment/policies/approval.py` | 批准时事务重查 HR02 额度（并发控制） |
| 6 | `renshi/templates/hr/recruitment/plans/` | 列表页（5 统计 + 状态 tabs）、需求详情三栏（需求事实/HR02 校验/审批时间线） |
| 7 | `hr_recruitment/jobs/plan_export.py` | Excel 导出（模板→staging→异步） |
| 8 | `hr_recruitment/tests/` | model/service/policy/API/state-machine/tenant-isolation/idempotency/audit 测试 |

**验收**（总册 35）：创建计划、学院提交、RETURNED 可改重提、REJECTED 不可重提、批准并发重检、跨学院 scope、Excel、审计。

---

## HR04-S4 招聘项目与岗位（HR04-02 + HR02 预占）

**硬门（已过）**：HR02 `HrOrganization/HrPostCatalog/HrPosition/HrPositionReservation` 模型就绪、`hr_structure` 已注册+0001 迁移、**预占 API 已暴露**（`PositionService.reserve/commit/release`，幂等键+事务锁）。S4 经 `integrations/hr02.py` 接入（`source_domain="hr04"`），预占失败显式 `HR02_POSITION_NOT_AVAILABLE`。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_recruitment/services/campaign_service.py` | Campaign CRUD + 状态机（DRAFT→APPROVED→PUBLISHED→OPEN→CLOSED→COMPLETED）+ 从 approved plan 创建 |
| 2 | `hr_recruitment/services/position_service.py` | Position 创建/状态机（DRAFT→READY→OPEN→...→FILLED/PARTIALLY_FILLED/CANCELLED）+ 额度逻辑 |
| 3 | `hr_recruitment/services/announcement_service.py` | 公告版本（发布后 immutable；amendment 新建版本+生效时间+原因+影响判定） |
| 4 | `hr_recruitment/services/reservation_service.py` | 预占封装：`reserve/release/commit/expire` + 幂等键；HR02 就绪走 `HrPositionReservation`，否则内部降级 `mode=LEGACY_SNAPSHOT` |
| 5 | `hr_recruitment/selectors/campaign.py` | 控制台 KPI、漏斗、超期岗位、近期截止 |
| 6 | `hr_recruitment/api/campaign.py` | `/api/hr/v1/recruitment/campaigns` 系列 + publish + positions 子资源 |
| 7 | `renshi/templates/hr/recruitment/campaigns/` | 招聘控制台（5 KPI+漏斗+项目卡）、项目详情 tabs、岗位详情首屏（额度/预占/报名/资格/当前阶段） |
| 8 | `hr_recruitment/tests/` | 版本不可变、amendment 不覆盖、关闭释放 reservation、额度并发、投影 |

**验收**（总册 36）：从 approved plan 创建 campaign、多 position、reservation 正确、发布产生 immutable version、关闭释放额度、Horilla projection 可显示。

---

## HR04-S5 候选人/申请 + 公开门户（HR04-03）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_recruitment/services/candidate_service.py` | 候选身份 CRUD、identity match（EXACT/POSSIBLE/NO_MATCH/INSUFFICIENT）、禁止自动 merge |
| 2 | `hr_recruitment/services/application_service.py` | 草稿保存→材料上传→验证→提交事务→生成 application_no→冻结引用版本→outbox 事件→确认通知（总册 49）；幂等 |
| 3 | `hr_recruitment/api/candidate.py` | 人才库列表/详情/搜索（高敏 exact-match 单独受控接口）、`identity-match` |
| 4 | `hr_recruitment/api/application.py` | Application 详情/撤回/状态 rail；candidate self scope |
| 5 | `hr_recruitment/public/` | 公开门户：`resolve_school_by_token(slug)`（禁止客户端传 tenant_id）、`GET /recruit/:tenantSlug/:campaignSlug`、岗位卡、申请页、`/recruit/my-applications`、`/recruit/apply/:applicationToken` |
| 6 | `hr_recruitment/services/material_service.py` | 材料版本/SHA-256/MIME/大小/malware scan 状态/短期签名 URL/访问日志 |
| 7 | `hr_recruitment/selectors/candidate.py` | 列表过滤（DB 层 WHERE/COUNT/ORDER，禁止先分页后 Python 过滤） |
| 8 | `hr_recruitment/policies/privacy.py` | 敏感字段服务端裁剪（recruiter/reviewer/expert/hiring manager/auditor 视图）、手机号遮罩 |
| 9 | `renshi/templates/hr/recruitment/candidates/` + `portal/` | 人才库、候选 profile-layout、application 详情三栏、public portal（mobile-first 375px） |
| 10 | `hr_recruitment/jobs/` | 大批量导入 staging→异步执行 |
| 11 | `hr_recruitment/tests/` | 幂等提交、self scope、高敏裁剪、材料版本、不泄漏他人 |

**验收**（总册 37）：同一候选多 Application、不以 email 自动合并、draft、submit 幂等、self scope、字段裁剪、材料版本、历史完整。

---

## HR04-S6 资格审查（HR04-04）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_recruitment/services/qualification_service.py` | 规则集版本管理（LOCKED/ACTIVE/SUPERSEDED）、Review/Decision、RETURNED/RESUBMITTED |
| 2 | `hr_recruitment/services/rule_engine.py` | 预检输出 PASS/FAIL/DATA_MISSING/NEEDS_MANUAL_REVIEW/NOT_APPLICABLE；**只建议不终审** |
| 3 | `hr_recruitment/api/qualification.py` | 工作台队列、逐条结论、批量（低风险一致结论才批量；DISQUALIFIED 逐件） |
| 4 | `hr_recruitment/selectors/qualification.py` | 待审/已审/退回统计，队列跨页准确 |
| 5 | `renshi/templates/hr/recruitment/qualification/` | 三栏工作台（候选人队列/条件核验矩阵/材料与决策）、evidence 展开、RETURNED 缺项清单+补交截止 |
| 6 | `hr_recruitment/tests/` | 条件版本锁定、规则变化不重写旧申请、override 有 reason、审核人数据范围 |

**验收**（总册 38）：条件版本锁定、系统预检、RETURNED、RESUBMITTED、QUALIFIED、DISQUALIFIED、手工 override 有 reason、规则变化不重写旧申请。

---

## HR04-S7 考试面试与考察（HR04-05）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_recruitment/services/assessment_service.py` | 方案版本、组件权重、场次排期、参与分配、冲突检查 |
| 2 | `hr_recruitment/services/scoring_service.py` | 评分表、服务端总分、锁定（DRAFT→SUBMITTED→LOCKED）、解锁（REOPEN_REQUESTED→APPROVED→DRAFT，保留旧版本）、结果快照 |
| 3 | `hr_recruitment/services/conflict_service.py` | 专家时间冲突/候选场次/场地/容量/时区 |
| 4 | `hr_recruitment/services/medical_background_service.py` | 体检/考察结论、高敏材料隔离（普通管理员只看结论） |
| 5 | `hr_recruitment/api/assessment.py` | 场次、专家分配、盲评裁剪、评分提交、锁定/解锁（特权+reason）、快照 |
| 6 | `renshi/templates/hr/recruitment/assessment/` | 专家评分页（顶:项目/岗位/场次；左:候选编号；中:材料/成果；右:评分表；底:草稿/提交）、盲评（服务端裁剪非 CSS）、冲突徽章 |
| 7 | `hr_recruitment/tests/` | 权重合计、回避、盲评、服务端算分、锁定、reopen、tie-break、快照不可变 |

**验收**（总册 39）：多组件、权重、专家分配、回避、排期冲突、盲评、服务端评分、lock、reopen、tie-break、快照、体检/考察敏感隔离。

---

## HR04-S8 录用公示/Offer（HR04-06 + HR05 handoff）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_recruitment/services/proposed_hire_service.py` | 拟录用创建校验（资格 QUALIFIED、Selection 完成、体检/考察、额度、不超上限）、决策/审批 |
| 2 | `hr_recruitment/services/notice_service.py` | 公示（public_display 字段白名单）、异议案件（RECEIVED→UNDER_REVIEW→...→RESOLVED_*）、结果版本 |
| 3 | `hr_recruitment/services/offer_service.py` | Offer DRAFT→APPROVED→ISSUED→VIEWED→ACCEPTED/DECLINED/EXPIRED/WITHDRAWN，接受幂等 |
| 4 | `hr_recruitment/services/handoff_service.py` | `HANDOFF_TO_HR05` 幂等（unique proposed_hire；Idempotency-Key 重复返回同一 HR05 case）、前置条件（APPROVED+公示 CLOSED_NO_BLOCKER+Offer ACCEPTED+Reservation VALID） |
| 5 | `hr_recruitment/integrations/hr03.py` | **不实现** Employee.save()；仅预留 `hr03_match_person()` 接口供 HR05 调用 |
| 6 | `hr_recruitment/api/proposed_hire.py` | `/proposed-hires` 列表/详情、`POST .../{id}/handoff-to-hr05`（Idempotency-Key） |
| 7 | `renshi/templates/hr/recruitment/proposed_hires/` + `notices/` | 拟录用工作台（综合成绩/排名/额度/资格/体检/考察/公示/Offer/HR05）、公示页、异议处理 |
| 8 | `hr_recruitment/tests/` | 不超额度、公示期间禁止 handoff、异议结果变更新版本、Offer 幂等、handoff 幂等 |

**验收**（总册 40）：拟录用不超额度、公示、异议、结果变更版本、Offer、Accepted/Expired、handoff 幂等、未公示完成禁 handoff、reservation 提交/释放。

---

## HR04-S9 Legacy Projection

| # | 文件 | 内容 |
|---|---|---|
| 1 | `recruitment/legacy/` | 原 Horilla 兼容代码收拢目录（不删表） |
| 2 | `hr_recruitment/projections/horilla_recruitment.py` | Recruitment→Campaign 投影 |
| 3 | `hr_recruitment/projections/horilla_stage.py` | Stage→WorkflowStage + stage_type→canonical_status 映射（配置驱动） |
| 4 | `hr_recruitment/projections/horilla_candidate.py` | Candidate→Candidate+Application 投影（读取侧） |
| 5 | `hr_recruitment/projections/pipeline.py` | Pipeline/Kanban 从投影渲染，Authority 后不再读 legacy 写入 |
| 6 | `hr_recruitment/tests/test_projections.py` | 投影正确性 + 权威回读一致 |

**验收**：HR04 页面可从投影渲染；legacy 表未删；旧写入口按 Authority 开关关闭。

---

## HR04-S10 DUAL_READ_COMPARE / 迁移

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_recruitment/jobs/legacy_migrate.py` | Candidate 拆分迁移（identity match + 人工队列，禁止 email 自动合并） |
| 2 | `hr_recruitment/jobs/dual_read_compare.py` | 新旧同时计算 campaign/applications/candidate counts/stage mapping/hired/interview → discrepancy report |
| 3 | `hr_recruitment/selectors/reconcile.py` | 对账查询（禁止"哪边有值用哪边"） |
| 4 | `hr_recruitment/tests/test_migration.py` / `test_dual_read.py` | 拆分、匹配、对账门槛 |

**验收**：迁移完成、POSSIBLE_MATCH 归零或人工确认、discrepancy 达门槛、回滚 runbook 可执行。

---

## HR04-S11 生产级验收

| # | 内容 |
|---|---|
| 1 | Security：tenant 隔离、data scope、expert assignment、candidate self、敏感字段、材料安全、IDOR、public slug 不可枚举、XSS/CSRF/rate limit/恶意附件（总册 33） |
| 2 | Performance：列表 p95、资格工作台切换、Pipeline 500 申请、人才库 10 万分页、公开提交、评分保存、无 N+1（总册 31） |
| 3 | Concurrency：双提交/最后名额/双人审核/专家重复提交/Offer 重击/handoff 幂等（总册 25） |
| 4 | E2E：16 个场景 + 非 happy path（总册 41） |
| 5 | Accessibility：WCAG 2.1 AA（总册 42） |
| 6 | Visual regression：重点截图清单（总册 43） |
| 7 | Migration rollback：权威切换演练、禁止 fallback、runbook |
| 8 | Docker/CI 实测迁移+测试 |

**验收**：S11 全部绿。

---

## HR04-S12 封板

| 条件 | 说明 |
|---|---|
| 业务 | 六模块闭环、RETURNED/不合格/撤回语义正确、不超额度、不重复 HR05 Case |
| 数据 | Candidate/Application 分离、版本化、正式结果不可变、Legacy mapping、对账达门槛 |
| 安全 | tenant/scope/self/expert/敏感字段/文档/审计全绿 |
| 技术 | migrations/API contract/idempotency/concurrency/async/outbox/observability/备份 |
| 前端 | 6 工作区 UI + public portal + 四档分辨率 + 可访问性 + visual regression |
| 迁移 | HR04_AUTHORITY 切换演练、禁 fallback、rollback runbook、discrepancy 可审 |

输出：`HR04 READY FOR ACCEPTANCE` 或 `HR04 NOT READY` + blocking 列表。

---

## 提交边界（总册 55）

每阶段提交 = migration + model/service + API + UI + tests + docs，一个三级模块一个可审提交；全程 Draft PR；未授权不合并 main。

> 状态：`DRAFT_V1`。
