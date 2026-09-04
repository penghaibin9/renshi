# HR10_TASK_TREE — 施工任务树（S0→S13）

> 全局合同：`00_高校人事系统全局架构与旧系统接管合同.md`
> 业务事实源：`10_HR10_培训进修与企业实践_施工总册_终极版.md`
> 基线复审：`HR10_GAP_MATRIX.md`、`legacy/HR10_LegacyDevelopmentMapping.md`
> 施工顺序：严格按总册 §179–192 执行
> 版本：`S0_V1`
> 日期：2026-08-09

---

## 施工纪律

- **一个阶段一个 commit**；每个阶段完成全部验收项才进入下一阶段
- **全程 Draft PR**；未经授权不合并 main
- **禁止越界**：不重写 HR03/HR08/HR09/HR11/HR12/HR15/教务/科研；不把"报名"当"完成"
- **tenant fail-closed** 从 S1 落地到每一模型和 API
- **前端中文化**：所有模板/JS 中文；Django i18n；JSON camelCase + xxxLabel 成对
- **每阶段末尾跑 tests** 并报告真实通过/失败数

---

## S0 基线复审 ✅ (当前阶段)

**任务**：
- [x] 读取总册 + 全局合同
- [x] 搜索全仓库 17 个关键词
- [x] 审计 HR03/HR08/HR11/HR07/horilla_documents 已有 authority
- [x] 输出 HR10_GAP_MATRIX.md
- [x] 输出 LegacyDevelopmentMapping.md
- [x] 输出 DevelopmentActivityTaxonomy.md
- [x] 输出 TrainingProviderMatrix.md
- [x] 输出 EnterprisePracticePolicyMap.md
- [x] 输出 PracticeEvidenceMatrix.md
- [x] 输出 HR10_INTEGRATION_MATRIX.md
- [x] 输出 HR10_TASK_TREE.md
- [x] 输出 HR10_RISK_REGISTER.md
- [x] 不修改业务代码

---

## S1 基础骨架

**目标**：建好 enums/catalogs/permissions/API envelope（`/api/v1/hr/development/*` per 00 §28.1）/Provider 接口/shared UI components/base migrations/tenant fail-closed tests。

**产出文件**：
```
renshi/hr10_development/
├─ __init__.py
├─ apps.py                    # AppConfig with ready()
├─ constants.py               # All enums/choices/error codes/event types/permissions
├─ models/
│  ├─ __init__.py
│  ├─ base.py                 # DevelopmentTenantModel abstract base
│  ├─ catalog.py              # DevelopmentActivityType catalog
│  ├─ provider_org.py         # HrDevelopmentProviderOrganization
│  ├─ audit.py                # HrDevelopmentAuditEvent
│  └─ outbox.py               # HrDevelopmentOutboxEvent
├─ api/
│  ├─ __init__.py
│  ├─ urls.py                 # /api/v1/hr/development/* 路由（00 §28.1 canonical root）
│  ├─ envelope.py             # Success/error envelope + meta (dataFreshness)
│  └─ health.py               # health probe
├─ providers/
│  └─ base.py                 # Abstract Provider interfaces (13 contracts)
├─ migrations/
│  └─ 0001_initial.py         # Base migrations
└─ tests/
   ├─ __init__.py
   └─ test_s1_tenant.py       # Tenant fail-closed tests
```

**验收**：
- [ ] `hr10_development` app 注册到 INSTALLED_APPS
- [ ] 所有模型继承 `DevelopmentTenantModel` (tenant_id fail-closed)
- [ ] constants.py 覆盖：
  - `DevelopmentActivityType` (17+ types: INTERNAL_TRAINING..OTHER)
  - `DeliveryMode` (9 types)
  - `PlanLifecycleStatus` (15 states)
  - `ProgramLifecycleStatus`
  - `RequestLifecycleStatus` (25+ states)
  - `ProjectLifecycleStatus` (15 states)
  - `EnrollmentStatus` + `SeatStatus`
  - `CompletionStatus` (PASS/FAIL/INCOMPLETE/WITHDRAWN/NO_SHOW)
  - `VerificationStatus` (MIGRATED_FREE_TEXT..PROVIDER_VERIFIED)
  - `FactType` (4 types)
  - `DevelopmentErrorCode` (40+ error codes)
  - `DevelopmentEventType` (21+ event types)
  - `DevelopmentPermissionCode` (12+ perms)
  - `DevelopmentDataScope` (8 scope types)
- [ ] API envelope: `{"data":..,"meta":{"requestId","sourceUpdatedAt","calculatedAt","dataFreshness"}}`
- [ ] API error envelope: `{"error":{"code","message","details","requestId"}}`
- [ ] Provider 抽象接口全部定义（Person / ExternalTeacher / Qualification / TimeConflict / DevelopmentTime / Assessment / Finance / Academic / Research / Agreement / Document / Notification，共 13 契约，见 HR10_INTEGRATION_MATRIX.md）
- [ ] health probe: `GET /api/v1/hr/development/health`
- [ ] tenant fail-closed tests: 无 tenant context→403; 跨租户 ID→403

**Commit**: `HR10-S1: enums/catalogs/permissions/API envelope/Provider interfaces/base migrations/tenant fail-closed`

---

## S2 教师发展计划 Authority (HR10-01)

**目标**：Plan/Version/Need/Target/Budget 全模型 + workflow + publish freeze + metrics + UI。

**产出文件**：
```
renshi/hr10_development/
├─ models/
│  ├─ plan.py                 # HrDevelopmentPlan + PlanLifecycleStatus state machine
│  ├─ plan_version.py         # HrDevelopmentPlanVersion (DRAFT→FROZEN immutable)
│  ├─ need.py                 # HrDevelopmentNeed (7 source types)
│  ├─ target.py               # HrDevelopmentTarget (metric_definition binding)
│  └─ budget.py               # HrDevelopmentBudgetPlan (预留/承诺/实际)
├─ services/
│  ├─ plan_service.py         # Plan CRUD + lifecycle transitions
│  ├─ plan_version_service.py # Version create/freeze/publish + content_hash
│  └─ budget_service.py       # Budget reservation/commitment
├─ api/
│  └─ plans.py                # Plan REST API (11 endpoints)
├─ migrations/
│  └─ 0002_plan.py            # Plan migrations
└─ tests/
   └─ test_s2_plan.py
```

**验收**：
- [ ] Plan 增删查改 + 状态机全路径（DRAFT→PREPARING→READY_FOR_REVIEW→UNDER_REVIEW→APPROVED→PUBLISHED→ACTIVE→CLOSING→CLOSED→ARCHIVED）
- [ ] PlanVersion: DRAFT→FROZEN, PUBLISHED after frozen; content_hash 校验
- [ ] Need: 7 source types (SELF/MANAGER/HR/HR12/ACADEMIC/POLICY/SKILL_GAP)
- [ ] Target: metric_definition_id 引用 + unit 支持 HOURS/DAYS/MONTHS/CREDITS/COUNT
- [ ] BudgetPlan: planned/reserved/committed/actual_paid_projection 分离
- [ ] 计划审批: ApprovalSnapshot 带 hash→409 冲突检测
- [ ] 计划指标: 9 KPIs 定义
- [ ] Excel 导入: 需求导入模板→上传→parse→error workbook→confirm
- [ ] Plans UI 首页 (5 KPI cards + 过滤 + 列表)
- [ ] Plans 详情 (10 tabs)
- [ ] DB: UNIQUE(tenant_id, plan_no), CHECK(start_date <= end_date)
- [ ] tenant + data scope tests
- [ ] state transition tests (非法跳转 409)

**Commit**: `HR10-S2: 教师发展计划 authority (Plan/Version/Need/Target/Budget + workflow + publish freeze + metrics + UI)`

---

## S3 培训项目 Authority (HR10-02)

**目标**: Provider Organization + Program/Version/Offering/Session + capacity/waitlist + completion rules + UI。

**产出文件**：
```
renshi/hr10_development/
├─ models/
│  ├─ learning_program.py      # HrLearningProgram + ProgramLifecycleStatus
│  ├─ program_version.py       # HrLearningProgramVersion
│  ├─ offering.py              # HrLearningOffering + DeliveryMode + capacity
│  ├─ session.py              # HrLearningSession
│  ├─ instructor.py           # ProgramInstructorRef
│  └─ provider_org_full.py    # HrDevelopmentProviderOrganization full model
├─ services/
│  ├─ program_service.py
│  ├─ offering_service.py     # capacity control (SELECT FOR UPDATE)
│  └─ provider_service.py     # Provider verification/risk
├─ api/
│  └─ programs.py             # Program REST API (10 endpoints)
├─ migrations/
│  └─ 0003_program.py
└─ tests/
   └─ test_s3_program.py
```

**验收**：
- [ ] ProviderOrganization: provider_code + provider_kind + verification_status/risk_status
- [ ] Program: program_code unique + version_id + lifecycle_status
- [ ] ProgramVersion: objectives/curriculum/completion_rule/evaluation_rule/cost_rule JSON
- [ ] Offering: capacity + waitlist_capacity + delivery_mode + enrollment_open_at/close_at
- [ ] Capacity 并发: 两人争最后一个名额→1 enrolled + 1 WAITLISTED/409
- [ ] Session: 多 session + 学时从 session 计算（非手填）
- [ ] Instructor refs: internal staff / HR08 external / provider external
- [ ] Provider snapshot: 项目发布时冻结 provider snapshot
- [ ] Programs UI 首页 + 详情 (版本/班次/对象规则/课程/师资/费用/材料/完成规则/评价/历史)
- [ ] Catalog discovery UI (教师端)
- [ ] DB: UNIQUE(tenant_id, program_code), UNIQUE(tenant_id, offering_no), CHECK(capacity>=0)
- [ ] tenant + data scope tests
- [ ] capacity 并发测试

**Commit**: `HR10-S3: 培训项目 authority (Provider/Program/Version/Offering/Session + capacity/waitlist + completion rules + UI)`

---

## S4 报名与审批 (HR10-03)

**目标**：Request + ApprovalSnapshot + Enrollment + schedule conflict + budget reservation + return/reject/withdraw/cancel/no-show + teacher portal。

**产出文件**：
```
renshi/hr10_development/
├─ models/
│  ├─ training_request.py      # HrTrainingRequest (4 request types)
│  ├─ enrollment.py            # HrLearningEnrollment
│  └─ approval_snapshot.py     # HrDevelopmentApprovalSnapshot
├─ services/
│  ├─ request_service.py       # Request lifecycle transitions
│  ├─ enrollment_service.py    # Enrollment + capacity atomic
│  ├─ approval_service.py      # Multi-step approval with snapshot hash
│  ├─ conflict_service.py      # Schedule conflict check (via TimeConflictProvider)
│  └─ budget_reservation_service.py
├─ api/
│  ├─ requests.py              # Request API
│  ├─ enrollments.py           # Enrollment API
│  └─ approvals.py             # Approval actions
├─ migrations/
│  └─ 0004_enrollment.py
└─ tests/
   └─ test_s4_enrollment.py
```

**验收**：
- [ ] Request: DRAFT→SUBMITTED→审批链→APPROVED→ENROLLMENT_PENDING→ENROLLED→IN_PROGRESS→COMPLETION_REVIEW→COMPLETED→ARCHIVED
- [ ] RETURNED vs REJECTED: returned 可修改后重提; rejected 今次终结
- [ ] ApprovalSnapshot: workflow_policy_version_id + snapshot_hash + object_version
- [ ] Self-approval prohibition: applicant==final_approver → blocked
- [ ] Schedule conflict: PASS/WARNING/BLOCKED/SOURCE_UNAVAILABLE
- [ ] Budget reservation: reserved_amount 并发安全
- [ ] Enrollment: unique(offering_id, staff_master_id) active
- [ ] Waitlist 转正: 名额释放→候补第一名转正（并发安全）
- [ ] Withdraw: APPLICANT_WITHDRAWN; Cancel: ORG_CANCEL/PROVIDER_CANCEL
- [ ] No-show: NO_SHOW 状态 + 纪律/名额浪费/费用记录
- [ ] External learning request: 外部学习申请/补录/核验
- [ ] Teacher portal: `/me/development/requests` + 申请/报名/历史
- [ ] Supervisor team view: 待审批/覆盖/预算摘要
- [ ] DB: UNIQUE(offering_id, staff_master_id) WHERE enrollment active
- [ ] Capacity 并发测试 + schedule conflict 测试 + self-approval 拦截测试

**Commit**: `HR10-S4: 报名与审批 (Request/ApprovalSnapshot/Enrollment + schedule conflict + budget reservation + return/reject/withdraw/cancel/no-show + teacher portal)`

---

## S5 培训完成与进修（培训完成核验 + 进修管理 + HR03 学历写回）

**目标**：Participation + Completion + External Learning + FurtherStudyCase/Milestone + verification + HR03 Education writeback contract。

**产出文件**：
```
renshi/hr10_development/
├─ models/
│  ├─ participation.py         # HrLearningParticipation
│  ├─ learning_completion.py   # HrLearningCompletion (immutable after VERIFIED)
│  └─ further_study.py         # HrFurtherStudyCase + HrFurtherStudyMilestone
├─ services/
│  ├─ completion_service.py    # Completion CRUD + verification + revision
│  └─ further_study_service.py # FurtherStudy lifecycle + HR03 writeback
├─ api/
│  └─ completions.py           # Completion REST
├─ migrations/
│  └─ 0005_completion.py
└─ tests/
   └─ test_s5_completion.py
```

**验收**：
- [ ] Participation: session_id + source(ONLINE_PROVIDER/OFFLINE_SIGNIN/MANUAL) + trust
- [ ] Attendance 状态: ATTENDED/LATE/LEFT_EARLY/ABSENT/EXCUSED/UNKNOWN
- [ ] Completion: PASS/FAIL/INCOMPLETE/WITHDRAWN/NO_SHOW
- [ ] Completion verification: 8 verification types (SYSTEM_PROVIDER_VERIFIED..SELF_REPORTED)
- [ ] Only VERIFIED source→DevelopmentFact
- [ ] Completion certificate: COMPLETION_CERTIFICATE→HR10 document/fact; PROFESSIONAL_CREDENTIAL→submit to HR09
- [ ] VERIFIED completion immutable: 纠错走 revision_no + supersedes_id
- [ ] FurtherStudyCase: VISITING/NON_DEGREE/DEGREE/CERTIFICATE_PROGRAM/RESEARCH_VISIT
- [ ] FurtherStudyMilestone: ADMITTED→REGISTERED→MID_REVIEW→COURSE_COMPLETED→THESIS→GRADUATED→CERTIFICATE→RETURNED_TO_POST
- [ ] Degree writeback contract: 通过 Provider Contract 提交 HR03 EducationHistory 核验
- [ ] External learning: request→approval→evidence submission→verification→history
- [ ] No 一键 VERIFIED from uploaded certificate
- [ ] tenant + data scope + concurrent completion tests

**Commit**: `HR10-S5: 培训完成与进修 (Participation/Completion/External Learning/FurtherStudyCase/Milestone + verification + HR03 writeback contract)`

---

## S6 企业实践项目 (HR10-04)

**目标**：Practice Project/Version + Provider/Base + PositionScene + Placement/Assignment + Mentor + Practice Plan + prerequisite gate + UI。

**产出文件**：
```
renshi/hr10_development/
├─ models/
│  ├─ practice_project.py      # HrEnterprisePracticeProject (15 states)
│  ├─ practice_project_version.py  # HrEnterprisePracticeProjectVersion
│  ├─ practice_scene.py        # HrPracticePositionScene
│  ├─ practice_placement.py    # HrEnterprisePracticePlacement
│  ├─ practice_assignment.py   # HrEnterprisePracticeAssignment
│  ├─ practice_mentor.py       # HrEnterprisePracticeMentor
│  └─ practice_plan.py         # HrEnterprisePracticePlan
├─ services/
│  ├─ practice_project_service.py
│  ├─ practice_assignment_service.py
│  ├─ practice_mentor_service.py
│  └─ practice_prerequisite_service.py  # safety/confidentiality/IP gate
├─ api/
│  └─ practice_projects.py     # Practice Project REST
├─ migrations/
│  └─ 0006_practice_project.py
└─ tests/
   └─ test_s6_practice.py
```

**验收**：
- [ ] PracticeProject: 15 状态机 (DRAFT→DESIGNING→READY_FOR_REVIEW→APPROVED→PUBLISHED→MATCHING→READY_TO_START→ACTIVE→COMPLETION_REVIEW→COMPLETED→CLOSED→ARCHIVED)
- [ ] ProjectVersion: objectives/position_scene/module_task/mentor/evaluation/safety/confidentiality/IP/output requirements JSON
- [ ] PositionScene: scene_code + real_position_name + production_or_service_scene + core_tasks + safety_level + confidentiality_level
- [ ] Placement: batch_no + start_date/end_date + capacity + mentor_refs
- [ ] Assignment: staff→placement→scene + mentor binding + planned_hours/days + actual_verified_hours/days
- [ ] Mentor: person_display_name + credential_summary + access_identity_ref + verification_status
- [ ] PracticePlan: both enterprise and school approval + frozen_at + content_hash
- [ ] Prerequisite gate: safety_training + confidentiality/agreement/IP acknowledgment
- [ ] All prerequisites met→READY_TO_START; any missing→fail-closed
- [ ] Provider snapshot: 企业信息 + 基地级别 + 安全联系人 + 紧急联系人
- [ ] Practice UI 首页 + 详情 (14 tabs)
- [ ] DB: CHECK(verified_hours>=0), CHECK(verified_days>=0)
- [ ] tenant + data scope + mentor scoped access tests

**Commit**: `HR10-S6: 企业实践项目 (Practice Project/Version + Provider/Base + PositionScene + Placement/Assignment + Mentor + Practice Plan + prerequisite gate + UI)`

---

## S7 实践过程与成果 (HR10-05)

**目标**：Activity + AttendanceFact + Evidence + Mentor Feedback + School Evaluation + Final Evaluation + Output + duration ledger + mentor portal。

**产出文件**：
```
renshi/hr10_development/
├─ models/
│  ├─ practice_activity.py     # HrEnterprisePracticeActivity
│  ├─ practice_attendance.py   # HrEnterprisePracticeAttendanceFact
│  ├─ practice_evidence.py     # HrEnterprisePracticeEvidence
│  ├─ mentor_feedback.py       # HrEnterpriseMentorFeedback
│  ├─ school_evaluation.py     # HrPracticeSchoolEvaluation
│  ├─ practice_evaluation.py   # HrEnterprisePracticeEvaluation (final)
│  ├─ development_output.py    # HrDevelopmentOutput
├─ services/
│  ├─ duration_service.py      # Verified segments→ledger
│  ├─ practice_process_service.py
│  ├─ evidence_service.py
│  ├─ evaluation_service.py
│  ├─ output_service.py
│  └─ duration_service.py      # Verified segments→ledger
├─ api/
│  ├─ practice_process.py
│  └─ outputs.py
├─ migrations/
│  └─ 0007_practice_process.py
└─ tests/
   └─ test_s7_process.py
```

**验收**：
- [ ] Activity: 13 activity types + DRAFT→SUBMITTED→VERIFIED→REJECTED
- [ ] AttendanceFact: 4 sources (ENTERPRISE_SYSTEM/MENTOR/SCHOOL_CHECK/SELF_WITH_EVIDENCE/IMPORT) + trust_level
- [ ] Evidence: evidence_type + verification_status + content_hash + sensitivity
- [ ] Mentor Feedback: rubric_version_id + ratings_json + revision_no
- [ ] School Evaluation: rubric_version_id + evidence_package + completion_recommendation + revision_no
- [ ] Final Evaluation: enterprise+school combined + PASS/FAIL/INCOMPLETE/EARLY_TERMINATED + immutable_hash
- [ ] Duration ledger: verified segments + attendance segments → dedup → eligible duration
- [ ] Practice hours→days conversion per policy version
- [ ] Output: 30+ output types + duplicate_group_id + duplicate detection
- [ ] Teaching transformation: output→academic ref (PENDING_EXTERNAL_LINK when no integration)
- [ ] Suspicious evidence: duplicate hash/time overlap/future time→RiskCase
- [ ] Suspend/resume: ACTIVE→SUSPENDED→ACTIVE with reason/time/impact
- [ ] Transfer: PracticeTransferEvent + old/new placement snapshot + remaining objectives
- [ ] Mentor portal: scoped access (assignment-link+expiry+field policy)
- [ ] No forced GPS; feature flag off by default
- [ ] OFFLINE evidence: enterprise signed sheet/mentor verification/school spot check→source/trust explicit
- [ ] Completion review pre-check: required duration/met/task modules/met/evidence/met/evaluations/met/incidents open?/output submitted?
- [ ] tenant + data scope + mentor portal access + evidence security tests

**Commit**: `HR10-S7: 实践过程与成果 (Activity/AttendanceFact/Evidence/MentorFeedback/SchoolEval/FinalEval/Output + duration ledger + mentor portal)`

---

## S8 发展档案 (HR10-06)

**目标**：DevelopmentFact + MetricLedger + Compliance Engine + Risk Center + HR10-06 UI + as-of。

**产出文件**：
```
renshi/hr10_development/
├─ models/
│  ├─ development_fact.py      # HrDevelopmentFact (4 types + immutable_hash)
│  ├─ metric_ledger.py         # HrDevelopmentMetricLedger
│  ├─ compliance_rule.py       # HrDevelopmentComplianceRule
│  └─ risk_case.py             # HrDevelopmentRiskCase
├─ services/
│  ├─ fact_service.py          # Generate fact from VERIFIED source
│  ├─ compliance_service.py    # Compliance evaluation (as-of window)
│  ├─ metric_service.py        # Metric definition + calculation
│  └─ risk_service.py          # Risk detection + case management
├─ api/
│  ├─ development_records.py
│  ├─ dashboard.py
│  └─ metrics.py
├─ migrations/
│  └─ 0008_development_fact.py
└─ tests/
   └─ test_s8_record.py
```

**验收**：
- [ ] DevelopmentFact: TRAINING_COMPLETION/FURTHER_STUDY/ENTERPRISE_PRACTICE/DEVELOPMENT_OUTPUT
- [ ] Only generate from VERIFIED source (LearningCompletion.VERIFIED/PracticeEvaluation finalized+verified/FurtherStudy milestone verified/Output verified)
- [ ] DRAFT/SUBMITTED/SELF_REPORTED→not generate fact
- [ ] Fact immutable hash + supersedes_fact_id for corrections
- [ ] MetricLedger: raw_value+raw_unit + normalized_value+normalized_unit + conversion_rule_version
- [ ] Training hours/credits/practice hours/practice days→separate ledgers, no mixed total_hours
- [ ] ComplianceRule: population_rule + metric_code + time_window_type + minimum_value + eligible_activity_types + minimum_trust_level
- [ ] Rule change does not recompute historical facts; only affects new as-of evaluations
- [ ] RiskCase: 12 risk types + OPEN→ACKNOWLEDGED→IN_PROGRESS→RESOLVED/WAIVED
- [ ] Development Records UI: 11 tabs with as-of summer
- [ ] Dashboard: 13 KPIs with as-of + dataFreshness
- [ ] as-of: 2025-12-31 query returns facts as they existed then with then-version rules
- [ ] DB: UNIQUE(staff_master_id, fact_type, valid_from) + CHECK(verified_hours>=0)
- [ ] tenant + data scope + as-of regression tests

**Commit**: `HR10-S8: 发展档案 (DevelopmentFact/MetricLedger/ComplianceEngine/RiskCenter + HR10-06 UI + as-of)`

---

## S9 跨域联动

**目标**：HR03/HR08/HR09/HR11/HR12/HR15/Academic/Research Provider contract implementations + Outbox events + reconciliation。

**产出文件**：
```
renshi/hr10_development/
├─ providers/
│  ├─ person_provider.py       # HR03 Person/Staff read (已就绪)
│  ├─ external_teacher_provider.py  # HR08 ExternalEngagement ref
│  ├─ qualification_provider.py     # HR09 Evidence Provider
│  ├─ time_provider.py         # HR11 TimeConflictProvider + DevelopmentTimeProvider
│  ├─ assessment_provider.py   # HR12 Assessment Provider
│  ├─ finance_provider.py      # HR15 Finance Provider
│  ├─ academic_provider.py     # Academic Provider
│  ├─ research_provider.py     # Research Provider
│  └─ __init__.py
├─ events/
│  ├─ publisher.py             # Outbox event publisher
│  ├─ consumer.py              # Inbox event consumer
│  └─ registry.py              # 21 event types registry
├─ jobs/
│  ├─ outbox_dispatcher.py     # PENDING→PUBLISHED dispatcher
│  ├─ hr09_evidence_index.py   # HR09 evidence index rebuild
│  └─ compliance_scan.py       # Periodic compliance scan
├─ api/
│  └─ internal.py              # Internal Provider APIs
└─ tests/
   └─ test_s9_integration.py
```

**验收**：
- [ ] HR03 Person/Staff Provider: read with as-of (复用现有模型)
- [ ] HR08 External Teacher Provider: read engagement status + allowed activity types
- [ ] HR09 Evidence Provider: `GET /internal/hr/development/evidence/staff/{id}?asOf=&types=` 只返回 VERIFIED facts
- [ ] HR11 TimeConflictProvider: schedule conflict→PASS/WARNING/BLOCKED/SOURCE_UNAVAILABLE
- [ ] HR11 DevelopmentTimeProvider: training/practice time windows for schedule exceptions
- [ ] HR12 Assessment Provider: verified facts + plan completion indicators
- [ ] HR15 Finance Provider: budget status read + payment projection (不建支付)
- [ ] Academic Provider: teaching calendar + course reference (未接时 PENDING_EXTERNAL_LINK)
- [ ] Research Provider: research output reference (未接时 PENDING_EXTERNAL_LINK)
- [ ] Outbox: 21 events all in registry + publisher/dispatcher
- [ ] Inbox: consumer with idempotency (source_business_type + source_business_id)
- [ ] `DevelopmentFactVerified` event→HR09/HR12 consumers
- [ ] Provider fail→显式 UNAVAILABLE; no silent fallback to 0/Pass/legacy
- [ ] Provider stale→dataFreshness: STALE/SOURCE_UNAVAILABLE
- [ ] tenant isolation in all provider calls
- [ ] integration contract tests (Provider failures/exceptions)

**Commit**: `HR10-S9: 跨域联动 (HR03/HR08/HR09/HR11/HR12/HR15/Academic/Research Provider contracts + Outbox events + reconciliation)`

---

## S10 Legacy 迁移

**目标**：Mapping→trust levels→staging→historical import→projection→DUAL_READ_COMPARE→rollback。

**产出文件**：
```
renshi/hr10_development/
├─ legacy/
│  ├─ staging.py               # Legacy staging models
│  ├─ migration_trust.py       # 7 migration trust levels
│  ├─ import_job.py            # Async import job model
│  └─ projection.py            # Legacy projection service
├─ api/
│  └─ legacy_import.py         # Import API
├─ jobs/
│  └─ legacy_import_worker.py  # Async import execution
└─ tests/
   └─ test_s10_legacy.py
```

**验收**：
- [ ] Migration trust levels: VERIFIED_SOURCE→DOCUMENT_BACKED→ADMIN_CONFIRMED→MIGRATED_STRUCTURED→MIGRATED_FREE_TEXT→SELF_REPORTED→UNKNOWN
- [ ] Only trust≥policy threshold generates formal fact; else stays staging
- [ ] Employee.qualification 自由文本→staging rows（解析→人工核验）
- [ ] EmployeeNote 培训备注→staging（关键字匹配→人工核验）
- [ ] Document 培训证书→evidence staging（文件链接→不自动 VERIFIED）
- [ ] Import job: PENDING→RUNNING→SUCCESS/FAILED（可 retry）
- [ ] Legacy projection: 旧页面显示由 HR10 authority 投影，只读
- [ ] DUAL_READ_COMPARE: LEGACY_ONLY→DUAL_READ_COMPARE→HR10_AUTHORITY→LEGACY_READONLY_PROJECTION
- [ ] Drift report: 旧 vs 新差异可查
- [ ] Rollback: 每个 wave 可独立回滚
- [ ] No free-text→AUTHORITY without explicit verification
- [ ] No VERIFIED facts from legacy Excel without evidence rules

**Commit**: `HR10-S10: Legacy 迁移 (Mapping/trust levels/staging/historical import/projection/DUAL_READ_COMPARE/rollback)`

---

## S11 全量质量

**目标**：Security + concurrency + performance + API contract + E2E + accessibility + visual regression + provider failure + migration + reconciliation + data quality。

**产出文件**：
```
renshi/hr10_development/
├─ tests/
│  ├─ test_security.py         # Tenant/IDOR/scope/field/file/export/callback/fail-closed
│  ├─ test_concurrency.py      # Capacity/budget/enrollment/waitlist/finalize concurrent
│  ├─ test_performance.py      # N+1/pagination/bulk/aggregation
│  ├─ test_e2e.py              # Full E2E chains (18 happy + 18 error paths)
│  ├─ test_accessibility.py    # Keyboard/aria/contrast/focus
│  ├─ test_visual.py           # 375/768/1280/1440 + empty/loading/error/stale/partial
│  ├─ test_provider_failure.py # All 11 Providers failure modes
│  └─ test_data_quality.py     # Orphan detection/duplicate/impossible overlap/negative duration
└─ observability/
   ├─ metrics.py               # 9+ Prometheus metrics
   └─ logging.py               # Structured logging
```

**验收**：
- [ ] Security: 11+ negative test scenarios (tenant/scope/field/file/export/callback)
- [ ] Concurrency: 8 concurrent scenarios (capacity/budget/enrollment/waitlist/finalize/completion/evidence/fact)
- [ ] Performance: all list queries EXPLAIN-validated; no N+1; async for bulk
- [ ] E2E: 18 happy paths + 18 error paths (total 36 scenarios)
- [ ] Accessibility: keyboard + label + contrast + focus + table semantics
- [ ] Visual regression: 4 breakpoints × 10 states = 40 screenshots
- [ ] Provider failure: all cascaded error→UNAVAILABLE (no silent fallback)
- [ ] Migration: staging→backfill→checksum→compare→cutover
- [ ] Reconciliation: HR10 fact↔HR09 evidence; budget reserved↔committed↔HR15 projection
- [ ] Data quality: 10+ anomaly detection rules + RiskCase generation
- [ ] All tests green

**Commit**: `HR10-S11: 全量质量 (Security/Concurrency/Performance/E2E/Accessibility/Visual/Provider failure/Migration/Reconciliation)`

---

## S12 Authority 切换

**目标**：LEGACY_OR_NONE→HR10_STAGING→DUAL_READ_COMPARE→HR10_AUTHORITY→LEGACY_READONLY_PROJECTION→POST_CUTOVER_CLEANUP。

**产出文件**：
```
renshi/hr10_development/
├─ services/
│  └─ authority_cutover_service.py
└─ tests/
   └─ test_s12_cutover.py
```

**验收**：
- [ ] Authority mode per tenant: LEGACY_OR_NONE/HR10_STAGING/DUAL_READ_COMPARE/HR10_AUTHORITY/LEGACY_READONLY
- [ ] Drift=ACCEPTABLE/EXPLAINED before HR10_AUTHORITY
- [ ] No formal write to legacy after HR10_AUTHORITY
- [ ] Legacy projection read-only
- [ ] Rollback plan per step
- [ ] Feature flag controls which mode is active
- [ ] No silent fallback to legacy when mode=HR10_AUTHORITY

**Commit**: `HR10-S12: Authority 切换 (LEGACY_OR_NONE→→HR10_AUTHORITY→LEGACY_READONLY_PROJECTION with drift control)`

---

## S13 最终封板

**目标**：All 194 acceptance criteria passed → `HR10 READY FOR ACCEPTANCE`。

**验收**：
- [ ] 6 三级模块全部闭环（业务）
- [ ] 发展需求→计划→项目→申请→参与→核验→档案主链通（业务）
- [ ] 企业实践→岗位场景→派出→过程→评价→成果→档案主链通（业务）
- [ ] Person/Staff 单一身份根（数据）
- [ ] Plan/Program/Practice 版本冻结（数据）
- [ ] Completion/Final Evaluation 有 revision（数据）
- [ ] DevelopmentFact immutable source（数据）
- [ ] as-of 可复现（数据）
- [ ] 学时/学分/实践时长分账（数据）
- [ ] tenant/data scope/self-only/mentor scoped access/PII 最小化（安全）
- [ ] constraints/idempotency/concurrency/outbox/retry/API version/Excel/observability（技术）
- [ ] 6 三级工作区 + 教师 Portal + 企业导师 Portal + 计划/项目/审批/过程/档案首屏（前端）
- [ ] 375/768/1280/1440 + Accessibility + Visual Regression（前端）
- [ ] Empty/error/stale/permission/partial/source unavailable 全状态（前端）
- [ ] All tests green; P0=0; P1=0

**Commit**: `HR10-S13: 最终封板 HR10 READY FOR ACCEPTANCE`

---

## 依赖图

```
HR03 (Person/Staff) ────────────┐
HR08 (External Teacher) ────────┤
HR11 (Time/Leave/Attendance) ───┼── S1 基础骨架
HR07 (Agreement) ───────────────┤
horilla_documents ──────────────┘
                │
                ▼
         S2 教师发展计划 ──────────────┐
                │                     │
         S3 培训项目 ─────────────────┤
                │                     │
         S4 报名与审批 ───────────────┤
                │                     │
    ┌───────────┴───────────┐         │
    ▼                       ▼         │
 S5 培训完成与进修    S6 企业实践项目   │
    │                       │         │
    └───────────┬───────────┘         │
                ▼                     │
         S7 实践过程与成果             │
                │                     │
                ▼                     │
         S8 发展档案 ─────────────────┤
                │                     │
                ▼                     ▼
         S9 跨域联动 ──────── S10 Legacy 迁移
                │                     │
                ▼                     ▼
         S11 全量质量 ──────── S12 Authority 切换
                │                     │
                └───────────┬─────────┘
                            ▼
                     S13 最终封板
```

---

**文档状态：S0_V1 — 任务树定版。严格按 S1→S13 顺序施工，一个阶段一个 commit。**
