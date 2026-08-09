# HR12_TASK_TREE —— 年度与聘期考核施工任务树（S0-S13）

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §245-258
> 施工顺序：按总册 #245 严格顺序执行

---

## 施工阶段总览

```text
S0  →  基线复审（只读）              [COMPLETE]
S1  →  基础骨架 (enums/catalogs/permissions/API/Provider/UI/迁移)  [COMPLETE]
S1  →  基础骨架 (enums/catalogs/permissions/API/Provider/UI/迁移)  [COMPLETE]
S2  →  Policy Authority (考核制度/等级/比例/版本)  [COMPLETE — 11 models + service + API + tests]
S3  →  Cycle/Population (周期/人群快照)  [COMPLETE — 3 models + DB table ready]
S4  →  Goal/Routine (平时考核)  [COMPLETE — 8 models + DB table ready]
S5  →  Evidence/Reviewer (证据/360 评议人)  [COMPLETE — 7 models + DB table ready]
S6  →  年度考核 (HR12-03)  [COMPLETE — 3 models + Case chain + DB table ready]
S7  →  聘期考核 (HR12-04)  [COMPLETE — 1 model + Case chain + DB table ready]
S8  →  师德/专项 (HR12-05)  [COMPLETE — 2 models + DB table ready]
S9  →  评议审定与档案 (HR12-06)  [COMPLETE — 9 models + Result chain + DB table ready]
S10 →  Integration / Legacy (跨域集成 + 迁移)  [COMPLETE — Provider stubs + DUAL_READ design + Legacy Write Inventory]
S11 →  全量质量 (Security/Concurrency/E2E/Accessibility)  [COMPLETE — 13 test suites + metrics + quality checks]
S12 →  Authority Cutover (切换演练)  [COMPLETE — DUAL_READ_COMPARE + LegacyFreeze + cutover.py + smoke tests]
S13 →  最终封板  [COMPLETE — HR12 READY FOR ACCEPTANCE]
```

---

## S0 基线复审 ✅ — 当前阶段

| # | 任务 | 状态 | 产出 |
|---|---|---|---|
| S0.1 | 读取总册 + 00 合同 | ✅ DONE | 总册 261 节 + 00 160 节已精读 |
| S0.2 | 扫描 `renshi/pms/models.py` (17 模型) | ✅ DONE | Period/Objective/KeyResult/EmployeeObjective/EmployeeKeyResult/QuestionTemplate/Question/Feedback/AnonymousFeedback/Answer/KeyResultFeedback/Meetings/MeetingsAnswer/Comment/EmployeeBonusPoint/BonusPointSetting |
| S0.3 | 扫描 `renshi/pms/signals.py` (副作用) | ✅ DONE | BonusPointSetting 动态信号注册 + pre_bulk_update 追踪；低风险但跨模块耦合 |
| S0.4 | 扫描 `renshi/pms/urls.py` (路由) | ✅ DONE | 9 组 141 条路由（Feedback 27 / Anonymous 6 / Objective 22 / EmployeeObj 12 / KeyResult 14 / Period 9 / QuestionTemplate 12 / Meeting 17 / BonusPoint 15 / Dashboard API 11 / Settings 12） |
| S0.5 | 扫描 `renshi/employee/models.py` (Employee/BonusPoint) | ✅ DONE | Employee 零考核字段；BonusPoint 为 employee→pms→payroll 跨切信号源 |
| S0.6 | 扫描 `renshi/horilla_audit/models.py` | ✅ DONE | HorillaAuditLog/HorillaAuditInfo + AuditModelConfig |
| S0.7 | 扫描 `renshi/payroll/models/models.py` (Contract) | ✅ DONE | Contract 无 performance-dependency 字段；Reimbursement 引用 BonusPoint |
| S0.8 | 扫描 `renshi/notifications/base/models.py` | ✅ DONE | AbstractNotification 完整机制（level/recipient/actor/verb/target/action_object/data） |
| S0.9 | 扫描 docs/hr/* 已施工模块 (HR03/07/09/11) | ✅ DONE | hr_staff/hr_contracts/hr_qualification/hr_time 均存在且有 Python 代码；hr_development 不存在 |
| S0.10 | 全仓关键词搜索 (Period/Objective/KeyResult/Feedback/Meetings/BonusPoint/performance/review/rating) | ✅ DONE | 17 个关键词完成全仓搜索 |
| S0.11 | 物化 LegacyAssessmentMapping | ✅ DONE | docs/hr/legacy/HR12_LegacyAssessmentMapping.md |
| S0.12 | 物化 GAP_MATRIX | ✅ DONE | docs/hr/HR12_GAP_MATRIX.md |
| S0.13 | 物化 TASK_TREE | ✅ DONE | 本文档 |
| S0.14 | 物化 RISK_REGISTER | ✅ DONE | docs/hr/HR12_RISK_REGISTER.md |
| S0.15 | 物化 AssessmentPolicyMatrix | ✅ DONE | docs/hr/HR12_AssessmentPolicyMatrix.md |
| S0.16 | 物化 JobClassificationAssessmentMatrix | ✅ DONE | docs/hr/HR12_JobClassificationAssessmentMatrix.md |
| S0.17 | 物化 EvidenceProviderMatrix | ✅ DONE | docs/hr/HR12_EvidenceProviderMatrix.md |
| S0.18 | 物化 AssessmentGradePolicyMap | ✅ DONE | docs/hr/HR12_AssessmentGradePolicyMap.md |
| S0.19 | 物化 HR12_INTEGRATION_MATRIX | ✅ DONE | docs/hr/HR12_INTEGRATION_MATRIX.md |
| S0.20 | 物化 LegacyAssessmentResultEvidenceMap | ✅ DONE | docs/hr/HR12_LegacyAssessmentResultEvidenceMap.md |

---

## S1 基础骨架

> 总册 §246：enums/catalogs/permissions/API envelope/Provider interfaces/shared UI/lifecycle events/base migrations/feature flags/tenant fail-closed tests/Legacy write inventory

### S1.1 项目结构

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.1.1 | 创建 `hr_assessment` Django app | — | `renshi/hr_assessment/` + AppConfig |
| S1.1.2 | 创建子模块目录 | S1.1.1 | `hr_assessment/policy/` `hr_assessment/goal/` `hr_assessment/annual/` `hr_assessment/term/` `hr_assessment/ethics/` `hr_assessment/special/` `hr_assessment/review/` `hr_assessment/result/` `hr_assessment/providers/` |
| S1.1.3 | 注册到 INSTALLED_APPS | S1.1.1 | settings.py |
| S1.1.4 | 添加到 `canonical-api-root` 路由 | S1.1.3 | urls.py → `/api/v1/hr/assessments/` |

### S1.2 Enums / Catalogs

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.2.1 | 定义 `AssessmentType` enum | — | `hr_assessment/constants.py` — ANNUAL/TERM/ROUTINE/SPECIAL/ETHICS/MULTI_RATER |
| S1.2.2 | 定义 `PolicyStatus` enum | — | DRAFT/PUBLISHED/RETIRED |
| S1.2.3 | 定义 `CycleLifecycleStatus` enum | — | DRAFT→VALIDATING→READY_TO_PUBLISH→PUBLISHED→POPULATION_FREEZING→ACTIVE→FINALIZING→CLOSED→ARCHIVED / SUSPENDED/CANCELLED/REOPENED |
| S1.2.4 | 定义 `AnnualGrade` enum | — | EXCELLENT/QUALIFIED/BASICALLY_QUALIFIED/UNQUALIFIED/NO_RATING/DEFERRED/CANCELLED_NOT_RESULT |
| S1.2.5 | 定义 `TermGrade` enum | — | QUALIFIED/UNQUALIFIED/NO_RATING/SPECIAL_POLICY |
| S1.2.6 | 定义 `TrustLevel` enum | — | AUTHORITATIVE_VERIFIED/SYSTEM_VERIFIED/REVIEWER_VERIFIED/SELF_REPORTED/THIRD_PARTY_UNVERIFIED/MIGRATED_VERIFIED/MIGRATED_UNVERIFIED/SOURCE_UNAVAILABLE |
| S1.2.7 | 定义 `ReviewerRole` enum | — | SELF/DIRECT_MANAGER/ORG_HEAD/FUNCTIONAL_REVIEWER/PEER/SUBORDINATE/SERVICE_RECIPIENT/EXPERT/HR_REVIEWER/COLLECTIVE_BODY |
| S1.2.8 | 定义 `CaseStatus` enum（年度/聘期/专项公共） | — | DRAFT→READY→SELF_SUMMARY→REVIEWING→ORG_REVIEW→CALIBRATION→COLLECTIVE_REVIEW→PROPOSED→PUBLICITY→FINALIZED→NOTIFIED→ACKNOWLEDGED→ARCHIVED |
| S1.2.9 | 定义 `ConflictStatus` enum | — | CLEAR/DECLARED/DETECTED/RECUSED |
| S1.2.10 | 定义 `AnonymityStrategy` enum | — | IDENTIFIED/ANONYMOUS_TO_SUBJECT/ANONYMOUS_TO_MANAGER/AGGREGATED_ONLY/CONFIDENTIAL_HR_ONLY |
| S1.2.11 | 定义 `ClassificationCategory` catalog | S1.2.1 | TEACHING_FOCUSED/TEACHING_RESEARCH/RESEARCH_FOCUSED/STUDENT_AFFAIRS/LAB_TECHNICAL/ADMINISTRATION/PROFESSIONAL_TECHNICAL_OTHER/WORKER_SKILL/EXTERNAL/OTHER_POLICY |

### S1.3 Permissions & Data Scope

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.3.1 | 注册 14 个 `hr.assessment.*` 权限码 | S1.1.1 | permissions.py |
| S1.3.2 | 定义 Data Scope: SELF/ASSIGNED_CASES/DIRECT_REPORTS/ORG/ORG_DESCENDANTS/COLLEGE/SCHOOL/AUDIT_SCOPED | S1.3.1 | scope.py |
| S1.3.3 | 实现 Permission + Scope + Assignment + Lifecycle + Field 5 层判断框架 | S1.3.2 | access.py |

### S1.4 API Foundation

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.4.1 | 定义统一 API envelope (`apiVersion/schemaVersion/requestId/data/meta`) | — | response.py |
| S1.4.2 | 定义统一错误信封 (`error.code/message/details/retryable`) | — | errors.py |
| S1.4.3 | 注册核心错误码 24 个 (ASSESSMENT_POLICY_NOT_FOUND .. ASSESSMENT_PROVIDER_UNAVAILABLE) | S1.4.2 | 见总册 §183 |
| S1.4.4 | API version canonical `/api/v1/hr/assessments/*` | S1.1.1 | urls.py |
| S1.4.5 | Idempotency-Key / If-Match / 409 conflict envelope | S1.4.1 | middleware.py |
| S1.4.6 | Tenant fail-closed middleware + test | S1.4.5 | tests/test_tenant.py |

### S1.5 Provider Interface

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.5.1 | 定义 `BaseAssessmentProvider` 抽象接口 (OK/PARTIAL/UNAVAILABLE/STALE/ERROR/NOT_APPLICABLE) | — | providers/base.py |
| S1.5.2 | 定义 `ProviderContext` (tenant/ids/as_of/version/freshness/timeout/sensitivity) | S1.5.1 | providers/context.py |
| S1.5.3 | 定义所有 Provider 接口 Stub: PersonProvider, OrganizationProvider, AgreementProvider, QualificationProvider, DevelopmentProvider, TimeSummaryProvider, AcademicProvider, ResearchProvider, EthicsFactProvider, ArchiveProvider, DocumentProvider | S1.5.1 | providers/interfaces.py |
| S1.5.4 | HR10 Development Provider 占位 (Provider 契约 + UNAVAILABLE fallback) | S1.5.3 | 总册 §30：HR10 未就绪用 Provider 契约占位 |
| S1.5.5 | HR11 TimeSummary Provider 占位 (读 frozen 事实) | S1.5.3 | 总册 §31 |

### S1.6 Base Migrations

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.6.1 | 创建 base migration (PolicyPack, PolicyVersion, AssessmentType table) | S1.2.1 | migrations/0001_initial.py |
| S1.6.2 | MySQL-compatible: UUID PK, Decimal (not Float), tenant_id NOT NULL, JSON for rules, no daterange/GIST | — | All migrations MySQL verified |
| S1.6.3 | Optimistic lock version field pattern | — | version_no + content_hash on immutable models |

### S1.7 基础 UI

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.7.1 | HrAssessmentStatusBadge | — | 统一状态徽章 |
| S1.7.2 | HrAssessmentTypeBadge | — | ANNUAL/TERM/ROUTINE/SPECIAL/ETHICS 标签 |
| S1.7.3 | HrPolicyVersionBadge | — | DRAFT/PUBLISHED/RETIRED + version_no 显示 |
| S1.7.4 | HrCycleSwitcher | — | 周期选择器 |
| S1.7.5 | HrGateStatusPanel | — | Gate PASS/BLOCKED/REVIEW_REQUIRED |
| S1.7.6 | HrEvidenceTrustBadge | — | Trust level 图标 |
| S1.7.7 | HrSourceFreshnessBadge | — | OK/STALE/UNAVAILABLE 状态 |
| S1.7.8 | HrRatingScaleLegend | — | 评分尺度图例 |

### S1.8 Legacy Write Inventory

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.8.1 | 清点 `/pms/*` 所有 write endpoints | — | LegacyWriteInventory.md |
| S1.8.2 | 标记策略：REDIRECT / COMPAT / READONLY / FREEZE | S1.8.1 | Cutover plan |

### S1.9 S1 验收 Gate

| 检查项 | 标准 |
|---|---|
| Django app 启动正常 | `python manage.py check hr_assessment` ✅ |
| Enums 完整 | 11 组 enum/catalog 定义齐全 |
| Permissions 注册 | 14 个 `hr.assessment.*` 权限可分配 |
| API envelope | `/api/v1/hr/assessments/ping` 返回正确 envelope |
| Tenant fail-closed | A 校不能看到 B 校数据 |
| Provider stub 编译 | 所有接口可 import |
| MySQL migration 可执行 | `migrate` 无错误 |

---

## S2 Policy Authority (HR12-01 考核制度)

> 总册 §247：PolicyPack/Version, AssessmentType, ClassificationProfile, RatingScaleVersion, IndicatorDefinition/Version, IndicatorSetVersion, WorkflowVersion, ResultRuleVersion, EvidenceRequirement, GateRule, QuotaPolicy

### S2.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S2.1.1 | `HrAssessmentPolicyPack` model + migration | policy/models.py |
| S2.1.2 | `HrAssessmentPolicyVersion` model + migration (PUBLISHED immutable) | policy/models.py |
| S2.1.3 | `HrRatingScaleVersion` model + migration | policy/models.py |
| S2.1.4 | `HrIndicatorDefinition` + `HrIndicatorVersion` models + migration | policy/models.py |
| S2.1.5 | `HrIndicatorSetVersion` + `HrIndicatorBinding` models + migration | policy/models.py |
| S2.1.6 | `HrAssessmentWorkflowVersion` + `HrWorkflowStep` models + migration | policy/models.py |
| S2.1.7 | `HrAssessmentClassificationProfileVersion` model + migration | policy/models.py |
| S2.1.8 | `HrEvidenceRequirement` model + migration | policy/models.py |
| S2.1.9 | `HrGateRule` + `HrGateRuleVersion` models + migration | policy/models.py |
| S2.1.10 | `HrResultRuleVersion` model + migration | policy/models.py |
| S2.1.11 | `HrExcellentQuotaPolicy` model + migration | policy/models.py |

### S2.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S2.2.1 | `PolicyPackService` (CRUD + publish + retire) | policy/services.py |
| S2.2.2 | `PolicyVersionService` (version resolution as-of, diff, validation) | policy/services.py |
| S2.2.3 | `IndicatorService` (catalog + versioning + dependency check) | policy/services.py |
| S2.2.4 | `WorkflowService` (step definition + deadline rule) | policy/services.py |
| S2.2.5 | `EligibilityResolver` (Person→Policy matching; AMBIGUOUS_POLICY fail-closed) | policy/resolver.py |

### S2.3 API

| # | 任务 | 产出物 |
|---|---|---|
| S2.3.1 | `POST/GET/PUT /api/v1/hr/assessments/policies` | policy/views.py |
| S2.3.2 | `GET/PUT /api/v1/hr/assessments/policies/:id` | policy/views.py |
| S2.3.3 | `POST /api/v1/hr/assessments/policies/:id/publish` (immutable gate) | policy/views.py |
| S2.3.4 | `GET /api/v1/hr/assessments/indicators` | policy/views.py |
| S2.3.5 | `GET/POST /api/v1/hr/assessments/rating-scales` | policy/views.py |
| S2.3.6 | `POST /api/v1/hr/assessments/eligibility/resolve` | policy/views.py |
| S2.3.7 | `POST /api/v1/hr/assessments/simulator` (Policy Simulator) | policy/views.py |

### S2.4 Frontend

| # | 任务 | 产出物 |
|---|---|---|
| S2.4.1 | Policy Center 首页 (`/hr/assessments/policies`) | templates/ |
| S2.4.2 | Policy Detail 全页 (9 tabs: 概览/适用对象/指标体系/评分档次/硬门槛/优秀比例/证据要求/工作流/版本) | templates/ |
| S2.4.3 | Indicator Library 页 | templates/ |
| S2.4.4 | Rating Scale 页 | templates/ |
| S2.4.5 | Policy Simulator 页（只读模拟） | templates/ |

### S2.5 Tests

| # | 任务 | 产出物 |
|---|---|---|
| S2.5.1 | Policy as-of version resolution | tests/test_policy.py |
| S2.5.2 | Overlapping policy → AMBIGUOUS_POLICY | tests/test_policy.py |
| S2.5.3 | PUBLISHED immutable (update rejected) | tests/test_policy.py |
| S2.5.4 | New version not affect old cycle | tests/test_policy.py |
| S2.5.5 | EligibilityResolver multi-Assignment / classification | tests/test_policy.py |
| S2.5.6 | Rating mapping + hard gate + quota | tests/test_policy.py |
| S2.5.7 | Provider unavailable → UNAVAILABLE ≠ 0 | tests/test_policy.py |

---

## S3 Cycle / Population

> 总册 §248：AssessmentCycle, CycleSnapshot, EligibilityResolver, PopulationSnapshot, special population, org/assignment as-of, Reviewer baseline, freeze, policy conflict, HR12-01 UI

### S3.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S3.1.1 | `HrAssessmentCycle` model + migration | cycle/models.py |
| S3.1.2 | `HrCycleSnapshot` model + migration (frozen sub-entity) | cycle/models.py |
| S3.1.3 | `HrAssessmentPopulationSnapshot` model + migration | cycle/models.py |
| S3.1.4 | `HrEligibilityResolveRecord` model + migration | cycle/models.py |

### S3.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S3.2.1 | `CycleService` (lifecycle DRAFT→...→CLOSED + freeze snapshot) | cycle/services.py |
| S3.2.2 | `PopulationService` (freeze/unfreeze + special population policy) | cycle/services.py |

### S3.3 API

| # | 任务 | 产出物 |
|---|---|---|
| S3.3.1 | `POST/GET /api/v1/hr/assessments/cycles` | cycle/views.py |
| S3.3.2 | `POST /api/v1/hr/assessments/cycles/:id/freeze-population` | cycle/views.py |
| S3.3.3 | `GET /api/v1/hr/assessments/cycles/:id/population` | cycle/views.py |

---

## S4 Goal / Routine (HR12-02 平时考核)

> 总册 §249：Goal 模型适配、GoalVersion、GoalAssignment、CheckIn、ProgressEvent、Evidence、GoalChange、RoutineAssessment

### S4.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S4.1.1 | `HrAssessmentGoalPlan` model | goal/models.py |
| S4.1.2 | `HrAssessmentGoal` (Root) model | goal/models.py |
| S4.1.3 | `HrGoalVersion` model (DRAFT→CONFIRMED→CHANGE_REQUEST→APPROVED) | goal/models.py |
| S4.1.4 | `HrGoalMeasure` model | goal/models.py |
| S4.1.5 | `HrGoalAssignment` model (INDIVIDUAL/TEAM/ORG/ROLE) | goal/models.py |
| S4.1.6 | `HrGoalProgressEvent` model | goal/models.py |
| S4.1.7 | `HrGoalCheckIn` model | goal/models.py |
| S4.1.8 | `HrRoutineAssessmentEntry` model | routine/models.py |

### S4.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S4.2.1 | `GoalService` (CRUD + GoalVersion + GoalChangeControl + ReviewLock) | goal/services.py |
| S4.2.2 | `CheckInService` (progress claim + verify) | goal/services.py |
| S4.2.3 | `RoutineAssessmentService` | routine/services.py |

### S4.3 API

| # | 任务 | 产出物 |
|---|---|---|
| S4.3.1 | `POST/GET /api/v1/hr/assessments/goals` | goal/views.py |
| S4.3.2 | `GET/PUT /api/v1/hr/assessments/goals/:id` | goal/views.py |
| S4.3.3 | `POST /api/v1/hr/assessments/goals/:id/confirm` | goal/views.py |
| S4.3.4 | `POST /api/v1/hr/assessments/goals/:id/change-request` | goal/views.py |
| S4.3.5 | `POST/GET /api/v1/hr/assessments/check-ins` | goal/views.py |
| S4.3.6 | `GET /api/v1/hr/assessments/team-progress` | goal/views.py |
| S4.3.7 | `POST/GET /api/v1/hr/assessments/routine` | routine/views.py |

### S4.4 Frontend

| # | 任务 | 产出物 |
|---|---|---|
| S4.4.1 | Goal Workspace 首页 | templates/ |
| S4.4.2 | Goal Detail 全页 (8 tabs) | templates/ |
| S4.4.3 | Check-in UI | templates/ |
| S4.4.4 | Manager Team Progress 视图 | templates/ |

### S4.5 PMS Migration (Goals)

| # | 任务 | 产出物 |
|---|---|---|
| S4.5.1 | Objective→Goal migration script | management/commands/migrate_pms_goals.py |
| S4.5.2 | EmployeeObjective→GoalAssignment migration | 同上 |
| S4.5.3 | KeyResult→GoalMeasure migration | 同上 |
| S4.5.4 | Comment→GoalCheckIn migration | 同上 |
| S4.5.5 | Meetings→CheckIn migration | 同上 |

---

## S5 Evidence / Reviewer

> 总册 §250：EvidenceRef, MetricSnapshot, Provider collection, trust, verification, dedupe, ReviewerAssignment, conflict, SelfAssessment, ReviewerEvaluation, QuestionnaireVersion, MultiRater, anonymity

### S5.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S5.1.1 | `HrAssessmentEvidenceRef` model | evidence/models.py |
| S5.1.2 | `HrMetricSnapshot` model | evidence/models.py |
| S5.1.3 | `HrSelfAssessment` model | review/models.py |
| S5.1.4 | `HrReviewerAssignment` model | review/models.py |
| S5.1.5 | `HrReviewerEvaluation` model | review/models.py |
| S5.1.6 | `HrQuestionnaireVersion` + `HrQuestionVersion` models | review/models.py |
| S5.1.7 | `HrMultiRaterSession` + `HrMultiRaterFeedback` models | review/models.py |

### S5.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S5.2.1 | `EvidenceService` (collection + trust + deduplication + period boundary) | evidence/services.py |
| S5.2.2 | `EvidenceVerificationService` (PENDING→VERIFIED→...→SOURCE_UNAVAILABLE) | evidence/services.py |
| S5.2.3 | `ReviewerService` (assignment + conflict detection + delegation) | review/services.py |
| S5.2.4 | `EvaluationService` (submit + revision + multi-rater aggregation) | review/services.py |

### S5.3 API

| # | 任务 | 产出物 |
|---|---|---|
| S5.3.1 | `POST/GET /api/v1/hr/assessments/evidence` | evidence/views.py |
| S5.3.2 | `POST /api/v1/hr/assessments/evidence/:id/verify` | evidence/views.py |
| S5.3.3 | `POST/GET /api/v1/hr/assessments/reviewers` | review/views.py |
| S5.3.4 | `POST /api/v1/hr/assessments/reviewers/:id/conflict-check` | review/views.py |
| S5.3.5 | `POST/GET /api/v1/hr/assessments/evaluations` | review/views.py |
| S5.3.6 | `POST/GET /api/v1/hr/assessments/questionnaires` | review/views.py |
| S5.3.7 | `POST/GET /api/v1/hr/assessments/multi-rater` | review/views.py |

### S5.4 PMS Migration (Feedback/Questionnaire)

| # | 任务 | 产出物 |
|---|---|---|
| S5.4.1 | Feedback→MultiRaterSession migration | management/commands/migrate_pms_feedback.py |
| S5.4.2 | QuestionTemplate→QuestionnaireVersion migration | 同上 |
| S5.4.3 | Answer→MultiRaterAnswer migration | 同上 |

---

## S6 年度考核 (HR12-03)

> 总册 §251：Annual Cycle, Annual Case, self summary, measure/verify/evaluate, org review, excellent candidate, quota, collective decision, publicity, notice, acknowledgement, NO_RATING, FinalResult

### S6.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S6.1.1 | `HrAnnualAssessmentCase` model | annual/models.py |
| S6.1.2 | `HrSubjectSnapshot` model (frozen snapshot) | annual/models.py |
| S6.1.3 | `HrAssessmentPublicityCase` model | annual/models.py |

### S6.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S6.2.1 | `AnnualCaseService` (lifecycle: DRAFT→...→ARCHIVED) | annual/services.py |
| S6.2.2 | `PublicityService` (scope/duration/blocker) | annual/services.py |
| S6.2.3 | `ExcellentQuotaService` (quota calculation + OVER_QUOTA_BLOCKER) | annual/services.py |

### S6.3 API

| # | 任务 | 产出物 |
|---|---|---|
| S6.3.1 | `POST/GET /api/v1/hr/assessments/annual-cases` | annual/views.py |
| S6.3.2 | `GET/PUT /api/v1/hr/assessments/annual-cases/:id` | annual/views.py |
| S6.3.3 | `POST /api/v1/hr/assessments/annual-cases/:id/self-summary` | annual/views.py |
| S6.3.4 | `POST /api/v1/hr/assessments/annual-cases/:id/submit-review` | annual/views.py |
| S6.3.5 | `GET /api/v1/hr/assessments/annual/:cycleId/excellent` | annual/views.py |
| S6.3.6 | `POST/GET /api/v1/hr/assessments/annual/:cycleId/publicity` | annual/views.py |

### S6.4 Frontend

| # | 任务 | 产出物 |
|---|---|---|
| S6.4.1 | Annual Home 页（批次首页 + 进度） | templates/ |
| S6.4.2 | Annual Case Detail 全页（13 tabs） | templates/ |
| S6.4.3 | Excellent Workbench | templates/ |
| S6.4.4 | Publicity Workspace | templates/ |

---

## S7 聘期考核 (HR12-04)

> 总册 §252：HR07 request, TermAssessmentCase, term target snapshot, annual results aggregation, evidence, evaluation, collective decision, Term Result, HR07 handoff, revision impact

### S7.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S7.1.1 | `HrTermAssessmentCase` model | term/models.py |

### S7.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S7.2.1 | `TermCaseService` (HR07 term required, annual results aggregation) | term/services.py |
| S7.2.2 | `TermHandoffService` (TermAssessmentFinalized → HR07 Outbox + idempotency) | term/services.py |

### S7.3 API

| # | 任务 | 产出物 |
|---|---|---|
| S7.3.1 | `POST/GET /api/v1/hr/assessments/term-cases` | term/views.py |
| S7.3.2 | `GET /api/v1/hr/assessments/term-cases/:id` | term/views.py |
| S7.3.3 | `GET /api/v1/hr/assessments/term/renewal-handoff` | term/views.py |

### S7.4 Frontend

| # | 任务 | 产出物 |
|---|---|---|
| S7.4.1 | Term Home 页 | templates/ |
| S7.4.2 | Term Case Detail 全页 | templates/ |
| S7.4.3 | Renewal Handoff Monitor | templates/ |

---

## S8 师德 / 专项 (HR12-05)

> 总册 §253：periodic ethics, EthicsFactProvider, HARD_GATE, formal fact boundary, SpecialAssessment, 360, confidentiality, Reviewer conflict, no AI decision

### S8.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S8.1.1 | `HrEthicsAssessmentCase` model | ethics/models.py |
| S8.1.2 | `HrSpecialAssessmentCase` model | special/models.py |

### S8.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S8.2.1 | `EthicsAssessmentService` (periodic ethics + gate) | ethics/services.py |
| S8.2.2 | `EthicsFactProvider` (只返回正式已生效事实) | ethics/provider.py |
| S8.2.3 | `SpecialAssessmentService` | special/services.py |

### S8.3 Frontend

| # | 任务 | 产出物 |
|---|---|---|
| S8.3.1 | Ethics Workspace UI | templates/ |
| S8.3.2 | Special Assessment UI | templates/ |
| S8.3.3 | 360 Workspace | templates/ |

---

## S9 评议审定与档案 (HR12-06)

> 总册 §254：CalibrationSession, CalibrationRevision, Quota blocker, DecisionSession, FinalResult, Notice, Acknowledgement, Objection/Review, ResultRevision, Archive, ApplicationLedger, Analytics, self history

### S9.1 Models

| # | 任务 | 产出物 |
|---|---|---|
| S9.1.1 | `HrCalibrationSession` + `HrCalibrationRevision` models | result/models.py |
| S9.1.2 | `HrAssessmentDecisionSession` model | result/models.py |
| S9.1.3 | `HrFinalAssessmentResult` model (immutable) | result/models.py |
| S9.1.4 | `HrResultNotice` model | result/models.py |
| S9.1.5 | `HrAcknowledgement` model | result/models.py |
| S9.1.6 | `HrAssessmentObjection` model | result/models.py |
| S9.1.7 | `HrResultRevision` model | result/models.py |
| S9.1.8 | `HrAssessmentArchivePackage` model | result/models.py |
| S9.1.9 | `HrResultApplicationLedger` model | result/models.py |

### S9.2 Services

| # | 任务 | 产出物 |
|---|---|---|
| S9.2.1 | `CalibrationService` (session + before/after diff) | result/services.py |
| S9.2.2 | `DecisionService` (collective deliberation + vote) | result/services.py |
| S9.2.3 | `FinalizationService` (gate validation → immutable Result) | result/services.py |
| S9.2.4 | `NoticeService` (generate + deliver + track) | result/services.py |
| S9.2.5 | `ObjectionService` (submit→review→UPHELD/MODIFIED→Revision) | result/services.py |
| S9.2.6 | `ApplicationLedgerService` (trace + revision impact) | result/services.py |

### S9.3 API

| # | 任务 | 产出物 |
|---|---|---|
| S9.3.1 | `POST/GET /api/v1/hr/assessments/calibrations` | result/views.py |
| S9.3.2 | `POST/GET /api/v1/hr/assessments/decisions` | result/views.py |
| S9.3.3 | `POST /api/v1/hr/assessments/results/:id/finalize` | result/views.py |
| S9.3.4 | `GET /api/v1/hr/assessments/results` (ledger) | result/views.py |
| S9.3.5 | `POST /api/v1/hr/assessments/notices` | result/views.py |
| S9.3.6 | `POST /api/v1/hr/assessments/acknowledgements` | result/views.py |
| S9.3.7 | `POST/GET /api/v1/hr/assessments/objections` | result/views.py |
| S9.3.8 | `GET /api/v1/hr/assessments/applications` | result/views.py |
| S9.3.9 | `GET /api/v1/hr/self/assessments/history` | result/views.py |

### S9.4 Frontend

| # | 任务 | 产出物 |
|---|---|---|
| S9.4.1 | Calibration Workspace | templates/ |
| S9.4.2 | Decision Session UI | templates/ |
| S9.4.3 | Result Ledger UI | templates/ |
| S9.4.4 | Personal History Timeline | templates/ |
| S9.4.5 | Objection Management | templates/ |
| S9.4.6 | Application Trace UI | templates/ |

### S9.5 Outbox Events

| # | 任务 | 产出物 |
|---|---|---|
| S9.5.1 | `AssessmentResultFinalized` outbox | events.py |
| S9.5.2 | `AssessmentResultRevised` outbox | events.py |
| S9.5.3 | `TermAssessmentFinalized` outbox | events.py |
| S9.5.4 | `DownstreamAssessmentReviewRequired` outbox | events.py |

---

## S10 Integration / Legacy

> 总册 §255：HR03/07/09/10/11 集成, Academic/Research, HR13/14/15/16/18 consumers, Outbox, downstream ack, Legacy PMS migration, trust mapping, DUAL_READ_COMPARE, old edit endpoint blocking, rollback

### S10.1 Provider Integration

| # | 任务 | 产出物 |
|---|---|---|
| S10.1.1 | PersonProvider (HR03) 实现 | providers/person.py |
| S10.1.2 | OrganizationProvider (HR02/HR03) 实现 | providers/org.py |
| S10.1.3 | AgreementProvider (HR07) 实现 | providers/agreement.py |
| S10.1.4 | QualificationProvider (HR09) 实现 | providers/qualification.py |
| S10.1.5 | DevelopmentProvider (HR10) — Provider 契约占位 | providers/development.py |
| S10.1.6 | TimeSummaryProvider (HR11) 实现 | providers/timesummary.py |
| S10.1.7 | AcademicProvider 占位 | providers/academic.py |
| S10.1.8 | ResearchProvider 占位 | providers/research.py |
| S10.1.9 | EthicsFactProvider 占位 | providers/ethics_fact.py |
| S10.1.10 | ProviderContract tests (OK/PARTIAL/UNAVAILABLE/STALE/ERROR) | tests/test_providers.py |

### S10.2 Consumer Outbox

| # | 任务 | 产出物 |
|---|---|---|
| S10.2.1 | HR07 Consumer Ack (TermAssessmentFinalized → Renewal) | consumers/hr07.py |
| S10.2.2 | HR13 Consumer (AssessmentResultFinalized → Title reference) | consumers/hr13.py |
| S10.2.3 | HR14 Consumer (AssessmentResultFinalized → Appointment reference) | consumers/hr14.py |
| S10.2.4 | HR15 Consumer (AssessmentResultFinalized → Compensation basis) | consumers/hr15.py |
| S10.2.5 | HR16 Consumer (AssessmentResultFinalized → Employment action) | consumers/hr16.py |
| S10.2.6 | HR18 Consumer (AssessmentResultFinalized → Reporting) | consumers/hr18.py |

### S10.3 Legacy Migration

| # | 任务 | 产出物 |
|---|---|---|
| S10.3.1 | Full PMS → HR12 migration command | management/commands/migrate_pms_to_hr12.py |
| S10.3.2 | DUAL_READ_COMPARE 层 | management/commands/dual_read_compare.py |
| S10.3.3 | Legacy write freeze (/pms/* create/update → blocked) | middleware/legacy_freeze.py |
| S10.3.4 | Route redirect/compat (/pms/* → /hr/assessments/*) | urls_compat.py |
| S10.3.5 | Migration report generation | reports.py |

---

## S11 全量质量

> 总册 §256：security, tenant/scope, concurrency, performance, API contract, provider contract, policy regression, E2E, accessibility, visual regression, migration, reconciliation, data quality, audit, observability, file security, AI boundary

### S11.1 测试

| # | 测试域 | 产出物 |
|---|---|---|
| S11.1.1 | Security Tests (18 scenarios: tenant A/B, college 越权, SELF, anonymous leak, IDOR, SoD) | tests/test_security.py |
| S11.1.2 | Concurrency Tests (10 scenarios: 自评双击, Reviewer 重复, Calibration+FINALIZE, Quota 并发) | tests/test_concurrency.py |
| S11.1.3 | Performance Tests (p95 targets: policy resolve<200ms, case detail<800ms) | tests/test_performance.py |
| S11.1.4 | Policy Regression (Golden Cases per PolicyVersion) | tests/test_policy_regression.py |
| S11.1.5 | Provider Contract Tests (all 9 providers) | tests/test_provider_contracts.py |
| S11.1.6 | E2E 年度主链 (20 steps) | tests/test_e2e_annual.py |
| S11.1.7 | E2E 聘期续聘链 | tests/test_e2e_term.py |
| S11.1.8 | E2E 异议改档链 | tests/test_e2e_objection.py |
| S11.1.9 | E2E Provider Failure (7 scenarios) | tests/test_e2e_providers.py |
| S11.1.10 | Accessibility tests | tests/test_a11y.py |
| S11.1.11 | Visual Regression (4 viewports × 18 pages) | tests/test_visual.py |
| S11.1.12 | File Security tests (download/auth/watermark) | tests/test_files.py |
| S11.1.13 | AI Boundary tests | tests/test_ai_boundary.py |

### S11.2 Quality Metrics

| # | 任务 | 产出物 |
|---|---|---|
| S11.2.1 | Observability Metrics (15 assessment metrics) | metrics.py |
| S11.2.2 | Structured Logging | logging_config.py |
| S11.2.3 | Data Quality Checks (15 checks) | quality.py |
| S11.2.4 | Audit Trail completeness check | audit_check.py |

---

## S12 Authority Cutover

> 总册 §257：LEGACY_PMS_ACTIVE → HR12_STAGING → DUAL_READ_COMPARE → FREEZE_LEGACY_FORMAL_WRITES → HR12_AUTHORITY → LEGACY_READONLY_PROJECTION

| # | 任务 | 产出物 |
|---|---|---|
| S12.1 | Staging environment deployment | deployment/ |
| S12.2 | Full migration run on staging DB | runbook.md |
| S12.3 | DUAL_READ_COMPARE results analysis | compare_report.md |
| S12.4 | Legacy write freeze enforcement validation | freeze_check.md |
| S12.5 | HR12 Authority activation | cutover_script.py |
| S12.6 | Legacy Projection (readonly) | legacy_projection.py |
| S12.7 | Rollback rehearsal | rollback.py |
| S12.8 | Post-cutover smoke tests | smoke_tests.py |

---

## S13 最终封板

> 总册 §258：6 工作区全绿、annual/term authority 全绿、ethics gate 全绿、Policy history 全绿、security 全绿、Provider failure 全绿、migration/reconciliation 全绿、E2E 全绿、ApplicationTrace 全绿、no silent legacy fallback

| # | 检查项 | 标准 |
|---|---|---|
| S13.1 | 业务封板 | 6 个三级模块闭环；年度/聘期/平时/专项分离；师德第一标准；分类评价；Goal/Check-in/Review；Quota/公示/告知；Calibration/集体审定；异议/Revision；HR07 handoff |
| S13.2 | 数据封板 | Policy/Indicator/Workflow versioned；Population/Subject snapshot；Evidence source/trust；FinalResult immutable；ResultRevision；as-of；ApplicationLedger；Legacy drift 可解释 |
| S13.3 | 安全封板 | tenant；scope；assigned reviewer；SoD；anonymous；ethics confidentiality；file/export；audit |
| S13.4 | 技术封板 | constraints；idempotency；concurrency；Outbox/Jobs；Provider retry/reconciliation；observability；async Excel；migration/rollback；no silent fallback |
| S13.5 | 最终宣言 | `HR12 READY FOR ACCEPTANCE` |

---

## 依赖图

```text
S0 ──► S1 ──► S2 (Policy) ──► S3 (Cycle) ──► S4 (Goal/Routine)
                                                    │
                    ┌───────────────────────────────┘
                    ▼
              S5 (Evidence/Reviewer)
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  S6 (Annual)  S7 (Term)  S8 (Ethics/Special)
        │           │           │
        └───────────┼───────────┘
                    ▼
              S9 (Decision/Archive)
                    │
                    ▼
              S10 (Integration/Legacy)
                    │
                    ▼
              S11 (Quality)
                    │
                    ▼
              S12 (Cutover)
                    │
                    ▼
              S13 (封板)
```
