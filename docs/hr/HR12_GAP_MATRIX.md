# HR12_GAP_MATRIX —— 年度与聘期考核缺口矩阵（S0 基线复审）

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §245 + `renshi/pms/models.py` 真实代码基线扫描

---

## 1. 总览

| 缺口类别 | 数量 | 严重度 | 说明 |
|---|---|---|---|
| Aggregates / 领域模型缺失 | 48+ | **CRITICAL** | 六大工作区核心模型全缺 |
| Service / Domain Service 缺失 | 20+ | **CRITICAL** | 无 Policy/Goal/Assessment/Result Service |
| Provider 缺失 | 9 | **HIGH** | HR03/HR07/HR09/HR10/HR11/教务/科研/Ethics/HR18 |
| API 缺失 | 30+ | **HIGH** | 无 `/api/v1/hr/assessments/*` 端点 |
| Frontend 缺失 | 28+ UI 组件 + 20+ 页面 | **HIGH** | 全量待建 |
| Security / Permissions 缺失 | 14 权限码 | **HIGH** | 无 hr.assessment.* 权限体系 |
| Integration / Outbox 缺失 | 6 事件 + 跨域契约 | **MEDIUM** | 无 AssessmentResultFinalized 等事件 |
| Migration / Legacy 缺失 | 141 PMS URL 路由 + 17 模型 + DUAL_READ | **MEDIUM** | 旧 /pms/* 全量 141 条 URL 路由待接管 |
| Test / Quality 缺失 | 15 测试套件 | **MEDIUM** | 全量待建 |
| **合计** | **195+** | — | — |

---

## 2. Aggregates / 领域模型缺口（CRITICAL — 48+）

### 2.1 HR12-01 考核制度与指标体系（13 模型）

| ID | 缺口模型 | 总册节号 | 核心字段 |
|---|---|---|---|
| M01 | `HrAssessmentPolicyPack` | §39 | tenant_id, code, name, assessment_domain, current_published_version_id |
| M02 | `HrAssessmentPolicyVersion` | §40 | version_no, effective_from/to, PUBLISHED immutable, content_hash |
| M03 | `HrAssessmentType` (Catalog) | §41 | ANNUAL/TERM/ROUTINE/SPECIAL/ETHICS/MULTI_RATER |
| M04 | `HrRatingScaleVersion` | §49 | scale_type, min/max, levels[], rounding_rule |
| M05 | `HrIndicatorDefinition` | §52 | code, name, dimension, default_value_type |
| M06 | `HrIndicatorVersion` | §53 | source_provider, aggregation_method, evidence_requirement, human_judgment_required |
| M07 | `HrIndicatorSetVersion` + `HrIndicatorBinding` | §54 | indicator_version_id, weight, min/max, required, hard_gate |
| M08 | `HrAssessmentWorkflowVersion` + `HrWorkflowStep` | §57-58 | steps[GOAL_CONFIRM...ARCHIVE], actor_role, deadline_rule |
| M09 | `HrEvidenceRequirement` | §60 | indicator_version_id, accepted_provider_types, min_trust_level |
| M10 | `HrResultRuleVersion` | §59 | score_to_grade_mapping, gate_effects, quota_rule |
| M11 | `HrGateRule` + `HrGateRuleVersion` | §18 | gate_type, effect_code (HARD_GATE/SOFT_BLOCKER) |
| M12 | `HrExcellentQuotaPolicy` | §110 | quota_basis_population, max_excellent_ratio |
| M13 | `HrAssessmentClassificationProfileVersion` | §48 | job_family, applicable_indicator_set, reviewer_structure |

### 2.2 HR12-02 目标任务与平时考核（8 模型）

| ID | 缺口模型 | 总册节号 | 核心字段 |
|---|---|---|---|
| M14 | `HrAssessmentGoalPlan` | §61 | cycle_id, name, goal_type, status |
| M15 | `HrAssessmentGoal` (Root) | §62 | goal_code, owner_type, owner_ref, current_version_id |
| M16 | `HrGoalVersion` | §63 | title, description, measures[], DRAFT→CONFIRMED→CHANGE_REQUEST→APPROVED |
| M17 | `HrGoalMeasure` | §64 | measure_type, baseline, target, unit, source_provider |
| M18 | `HrGoalAssignment` | §65 | INDIVIDUAL/TEAM/ORG/ROLE, contribution_role |
| M19 | `HrGoalProgressEvent` | — | self_claimed/verified, change_delta, comment |
| M20 | `HrGoalCheckIn` | §66 | goal_id, progress_claim, blockers, support_needed |
| M21 | `HrRoutineAssessmentEntry` | §131 | staff_id, period, category, observation, rating(optional) |

### 2.3 HR12-03/04/05/06 考核 Case 链（15+ 模型）

| ID | 缺口模型 | 总册节号 | 核心字段 |
|---|---|---|---|
| M22 | `HrAssessmentCycle` | §42 | cycle_no, assessment_type, lifecycle_status |
| M23 | `HrCycleSnapshot` | §43 | frozen policy/org/population/rating/workflow/deadlines |
| M24 | `HrAssessmentPopulationSnapshot` | §46 | staff_id, employment_relationship_id, org_id, classification_profile, snapshot_at |
| M25 | `HrAssessmentCase` (Base) | §87/104 | case_id, assessment_type, staff_id, subject_snapshot_id, cycle_id, status |
| M26 | `HrAnnualAssessmentCase` | §104 | business_year, annual_goal_plan_id, routine_snapshot_id |
| M27 | `HrTermAssessmentCase` | §121 | term_id, agreement_id, term_goal_snapshot, annual_result_refs[] |
| M28 | `HrSpecialAssessmentCase` | §135 | special_type, trigger_event, scope, target_snapshot |
| M29 | `HrEthicsAssessmentCase` | §13/138 | Gate status, source_refs[], policy_version_id |
| M30 | `HrSubjectSnapshot` | §76 | 姓名/工号/人员类别/组织/主岗/岗位类别/教师类型 |
| M31 | `HrAssessmentEvidenceRef` | §69 | case_id, indicator_id, provider_type, source_object_id, trust_level, snapshot_hash |
| M32 | `HrMetricSnapshot` | §70 | metric_code, value, unit, period, provider, status (VERIFIED/STALE/UNAVAILABLE) |
| M33 | `HrSelfAssessment` | §79 | summary, goal_reflections[], self_rating(optional), submitted_at |
| M34 | `HrReviewerAssignment` | §77 | reviewer_role, reviewer_staff_id, conflict_status, delegation |
| M35 | `HrReviewerEvaluation` | §80 | indicator_evaluations[], rating, comment, recommendation |
| M36 | `HrQuestionnaireVersion` + `HrQuestionVersion` | §82-83 | TEXT/RATING/BOOLEAN/SINGLE_CHOICE/MULTI_CHOICE/LIKERT |
| M37 | `HrMultiRaterSession` + `HrMultiRaterFeedback` | §81/143 | anonymity_strategy, min_responses |
| M38 | `HrCalibrationSession` + `HrCalibrationRevision` | §86-88 | scope_org_ids, before/after, reason_code |
| M39 | `HrAssessmentDecisionSession` | §90 | body/org, quorum_policy, vote_summary |
| M40 | `HrFinalAssessmentResult` | §93 | grade_code, display_grade_snapshot, policy_version_id, finalized_at, content_hash |
| M41 | `HrResultNotice` | §95 | notice_no, delivery_channel, delivery_status |
| M42 | `HrAcknowledgement` | §96 | received_at, employee_opinion, confirmed_at |
| M43 | `HrAssessmentObjection` | §97 | reason, evidence, reviewer, conflict_check, conclusion |
| M44 | `HrResultRevision` | §100 | previous_version, new_version, revision_type, before/after snapshot |
| M45 | `HrAssessmentPublicityCase` | §111 | scope, candidate_result_refs, minimum_duration_rule, announcement_ref |
| M46 | `HrResultApplicationLedger` | §102 | consumer_domain, consumer_object_id, result_id, result_version, consumed_at |
| M47 | `HrAssessmentArchivePackage` | §101 | archive_package_id, document_refs, archive_status |
| M48 | `HrEligibilityResolveRecord` | §45 | eligible, policy_version_id, classification_profile_id, reason_codes[] |

---

## 3. Service / Domain Service 缺口（CRITICAL — 20+）

| ID | 缺口 | 说明 |
|---|---|---|
| S01 | `PolicyPackService` | CRUD + publish(immutable) + retire |
| S02 | `PolicyVersionService` | version resolution (as-of) + diff + validation |
| S03 | `IndicatorService` | 指标库管理 + versioning + dependency check |
| S04 | `RatingScaleService` | scale CRUD + mapping + normalization |
| S05 | `WorkflowService` | 工作流步骤定义 + actor resolver + deadline enforcement |
| S06 | `EligibilityResolver` | Person→Policy matching; AMBIGUOUS_POLICY fail-closed |
| S07 | `CycleService` | lifecycle (DRAFT→...→CLOSED) + freeze snapshot |
| S08 | `PopulationService` | freeze/unfreeze; special population policy execution |
| S09 | `GoalService` | CRUD + GoalVersion + GoalChangeControl + ReviewLock |
| S10 | `CheckInService` | progress claim + verify; private visibility |
| S11 | `EvidenceService` | evidence collection + trust + deduplication + period boundary |
| S12 | `ReviewerService` | assignment + conflict detection + delegation |
| S13 | `EvaluationService` | self/manager/org/multi-rater submission + revision |
| S14 | `CalibrationService` | session + before/after diff + quota blocker |
| S15 | `DecisionService` | collective deliberation + decision record + vote summary |
| S16 | `FinalizationService` | final gate validation → FinalResult immutable |
| S17 | `NoticeService` | generate + deliver + track delivery |
| S18 | `ObjectionService` | submit→review→UPHELD/MODIFIED→ResultRevision |
| S19 | `RevisionService` | CORRECTION/REASSESSMENT → SUPERSEDED history |
| S20 | `ApplicationLedgerService` | trace downstream consumers + revision impact |

---

## 4. Provider 缺口（HIGH — 9）

| ID | 缺口 | 源域 | HR12 使用方式 |
|---|---|---|---|
| P01 | `PersonProvider` | HR03 | Staff identity, employment, assignment, org as-of |
| P02 | `OrganizationProvider` | HR02/HR03 | org hierarchy, position supply |
| P03 | `AgreementProvider` | HR07 | Contract term, duty snapshot, term goals, review due |
| P04 | `QualificationProvider` | HR09 | Qualification status, double-teacher facts (reference) |
| P05 | `DevelopmentProvider` | HR10 | VERIFIED TrainingCompletion/EnterprisePractice/DevelopmentOutput |
| P06 | `TimeSummaryProvider` | HR11 | Frozen period close: scheduled/worked/absence/late_early_summary |
| P07 | `AcademicProvider` | 教务 | Teaching assignments, hours, evaluation, quality facts |
| P08 | `ResearchProvider` | 科研 | Projects, publications, patents, roles, contributions |
| P09 | `EthicsFactProvider` | 正式师德事实源 | Verified formal ethics decisions (not complaints/rumors) |

---

## 5. API 缺口（HIGH — 30+ 资源端点）

统一 namespace: `/api/v1/hr/assessments/*`

| ID | 资源 | 说明 |
|---|---|---|
| A01 | `policies` | PolicyPack CRUD |
| A02 | `policy-versions` | publish/diff/resolve |
| A03 | `indicators` | indicator catalog + versioning |
| A04 | `rating-scales` | scale definition |
| A05 | `cycles` | AssessmentCycle lifecycle |
| A06 | `population` | freeze/snapshot/query |
| A07 | `goals` | Goal CRUD + GoalVersion |
| A08 | `check-ins` | create/update/query |
| A09 | `annual-cases` | Annual Case lifecycle |
| A10 | `term-cases` | Term Case lifecycle |
| A11 | `routine` | Routine entry CRUD |
| A12 | `special` | Special case management |
| A13 | `ethics` | Ethics case + gate |
| A14 | `reviewers` | assignment + conflict |
| A15 | `evaluations` | submit/review/revise |
| A16 | `evidence` | evidence collection + verification |
| A17 | `calibrations` | session + revision |
| A18 | `decisions` | collective deliberation |
| A19 | `results` | FinalResult query/ledger |
| A20 | `notices` | generate/deliver/track |
| A21 | `objections` | submit/review/decide |
| A22 | `applications` | downstream trace |
| A23 | `exports` | batch export |
| A24 | `jobs` | async job status |
| A25 | `multi-rater` | 360/multi-rater session |
| A26 | `questionnaires` | questionnaire version management |
| A27 | `publicity` | 公示 case management |
| A28 | `acknowledgements` | 本人意见确认 |
| A29 | `archive` | 档案归档 |
| A30 | `eligibility` | eligibility resolve API |

---

## 6. Frontend 缺口（HIGH — 28+ UI 组件 + 20+ 页面）

### 6.1 公共 UI 组件（28+ 个）

见总册 §144，核心包括：
`HrAssessmentHeader`, `HrAssessmentStatusBadge`, `HrAssessmentTypeBadge`, `HrPolicyVersionBadge`, `HrCycleSwitcher`, `HrSubjectSnapshotCard`, `HrIndicatorScorecard`, `HrGateStatusPanel`, `HrEvidencePanel`, `HrEvidenceTrustBadge`, `HrSourceFreshnessBadge`, `HrGoalProgressCard`, `HrCheckInTimeline`, `HrReviewerProgress`, `HrRatingScaleLegend`, `HrCalibrationDiff`, `HrQuotaMeter`, `HrDecisionTimeline`, `HrPublicityStatus`, `HrResultNoticePanel`, `HrObjectionTimeline`, `HrResultVersionTimeline`, `HrApplicationTrace`

### 6.2 页面（20+）

| 页面 | 路由 | 说明 |
|---|---|---|
| Policy Center | `/hr/assessments/policies` | 政策总览首页 |
| Policy Detail | `/hr/assessments/policies/:id` | 9 tab 全页编辑 |
| Indicator Library | `/hr/assessments/indicators` | 指标目录 |
| Rating Scale | `/hr/assessments/rating-scales` | 评分尺度管理 |
| Goal Workspace | `/hr/assessments/goals` | 目标管理首页 |
| Goal Detail | `/hr/assessments/goals/:id` | 8 tab 详情 |
| Check-in | `/hr/assessments/check-ins` | 进展更新 |
| Team Progress | `/hr/assessments/team-progress` | 主管视图 |
| Annual Home | `/hr/assessments/annual` | 年度批次首页 |
| Annual Case | `/hr/assessments/annual/:cycleId/cases/:caseId` | 13 tab 评审详情 |
| Excellent Workbench | `/hr/assessments/annual/:cycleId/excellent` | 优秀候选工作区 |
| Publicity | `/hr/assessments/annual/:cycleId/publicity` | 公示工作区 |
| Term Home | `/hr/assessments/term` | 聘期首页 |
| Term Case | `/hr/assessments/term/cases/:caseId` | 聘期详情 |
| Ethics | `/hr/assessments/ethics` | 师德工作区 |
| Special | `/hr/assessments/special` | 专项考核 |
| Calibration | `/hr/assessments/calibration` | 校准工作区 |
| Decisions | `/hr/assessments/decisions` | 集体审定 |
| Result Ledger | `/hr/assessments/results` | 结果台账 |
| History | `/hr/self/assessments/history` | 个人档案 |
| Objection | `/hr/assessments/objections` | 异议管理 |

---

## 7. Security / Permissions 缺口（HIGH — 14 权限码）

见总册 §184，前缀 `hr.assessment.*`：

| ID | 权限码 | 说明 |
|---|---|---|
| PM01 | `hr.assessment.policy.admin` | PolicyPack/Version CRUD + publish |
| PM02 | `hr.assessment.cycle.admin` | Cycle lifecycle + population freeze |
| PM03 | `hr.assessment.hr_reviewer` | 校级人事评审员 |
| PM04 | `hr.assessment.college_reviewer` | 学院级评审员 |
| PM05 | `hr.assessment.manager_reviewer` | 直接主管评审 |
| PM06 | `hr.assessment.panel_member` | 评审委员会成员 |
| PM07 | `hr.assessment.calibration_manager` | 校准主持人 |
| PM08 | `hr.assessment.final_decider` | 集体审定决策人 |
| PM09 | `hr.assessment.ethics_reviewer` | 师德专项评审 |
| PM10 | `hr.assessment.special_reviewer` | 专项任务评审 |
| PM11 | `hr.assessment.archive_manager` | 档案归档管理 |
| PM12 | `hr.assessment.auditor` | 考核审计员 |
| PM13 | `hr.assessment.employee_self` | 本人自助（SELF scope enforced） |
| PM14 | `hr.assessment.analytics_view` | 统计分析查看 |

---

## 8. Integration / Outbox 缺口（MEDIUM — 6 事件）

| ID | 事件 | 发布者→消费者 |
|---|---|---|
| E01 | `AssessmentResultFinalized` | HR12 → HR13/HR14/HR15/HR16/HR18 |
| E02 | `AssessmentResultRevised` | HR12 → all consumers (downstream review) |
| E03 | `TermAssessmentFinalized` | HR12 → HR07 (renewal handoff) |
| E04 | `DownstreamAssessmentReviewRequired` | HR12 → HR07/HR13/HR14/HR15 |
| E05 | `AssessmentResultNotified` | HR12 → HR17 (ESS) |
| E06 | `AssessmentPolicyPublished` | HR12 → HR18 (reporting awareness) |

---

## 9. Migration / Legacy 缺口（MEDIUM）

| ID | 缺口 | 说明 |
|---|---|---|
| L01 | PMS Model Migration Scripts | Period→Cycle, Objective→Goal, EmployeeObjective→GoalAssignment, KeyResult→Measure, Feedback→MultiRater, QuestionTemplate→Questionnaire |
| L02 | Employee→HrStaffMaster 映射 | Old Employee IDs → new HrStaffMaster |
| L03 | Company→Tenant 映射 | Company resolver + ambiguous 处理 |
| L04 | DUAL_READ_COMPARE 层 | Legacy PMS vs HR12 Staging 对账 |
| L05 | Route Redirect/Compat | /pms/* → /hr/assessments/* (deprecation metric) |
| L06 | Legacy Write Freeze | 旧 PMS create/update 端点逐步冻结 |

---

## 10. Test / Quality 缺口（MEDIUM — 15 套件）

| ID | 测试领域 | 说明 |
|---|---|---|
| T01 | Policy Engine Tests | as-of version, overlapping, classification, gate, quota (总册 §219) |
| T02 | Goal Tests | GoalVersion lock, self vs verified, team contribution, ReviewLock (总册 §220) |
| T03 | Annual Assessment Tests | PopulationFreeze, SelfReview, ReviewerAssignment, quota, PublicityGate, FinalResult (总册 §221) |
| T04 | Term Assessment Tests | HR07 term required, TermGoalSnapshot, annual history, Handoff idempotency (总册 §222) |
| T05 | Routine/Special Tests | CheckIn revision, confidentiality, RoutineSnapshot (总册 §223) |
| T06 | Ethics Tests | FormalFactProvider, unresolved complaint, HARD_GATE, confidentiality (总册 §224) |
| T07 | 360/Anonymous Tests | min responses, anonymity, export, aggregation (总册 §225) |
| T08 | Calibration Tests | session scope, before/after, concurrent adjust, Finalize lock (总册 §226) |
| T09 | Result/Objection Tests | FinalResult immutable, Notice version, SUPERSEDED history (总册 §227) |
| T10 | E2E 年度主链 | HR03→Policy→Cycle→Population→Goal→SelfReview→ManagerEval→Quota→Decision→Final→Notice (总册 §228) |
| T11 | E2E 聘期链 | HR07 term→TermCase→AnnualResults→Evaluation→Decision→Handoff (总册 §230) |
| T12 | E2E 异议改档链 | Objection→Review→Reassessment→Result V2→Downstream review (总册 §232) |
| T13 | E2E Provider Failure | Academic unavailable, Research timeout, HR10 unavailable, HR11 not frozen (总册 §233) |
| T14 | Security Tests | Tenant A/B, college 越权, SELF scope, anonymous leak, IDOR, SoD (总册 §218) |
| T15 | Concurrency Tests | 自评双击, Reviewer 重复提交, Calibration+FINALIZE 同时, Quota 并发 (总册 §211) |

---

## 11. S0 清点结论

### 11.1 PMS 现有资产清单（Deep Scan 结果）

| 资产类别 | 数量 | 明细 |
|---|---|---|
| Django 模型 | 17 个 | Period / KeyResult / Objective / EmployeeObjective / Comment / EmployeeKeyResult / QuestionTemplate / Question / QuestionOptions / Feedback / AnonymousFeedback / Answer / KeyResultFeedback / Meetings / MeetingsAnswer / EmployeeBonusPoint / BonusPointSetting |
| URL 路由 | 141 条 | Feedback 27 / Anonymous 6 / Objective 22 / EmployeeObj 12 / KeyResult 14 / Period 9 / QuestionTemplate 12 / Meeting 17 / BonusPoint 15 / Dashboard API 11 / Settings 12 |
| Dashboard API | 11 端点 | KPI / objective-status / kr-status / feedback-status / department / at-risk / performers / okr-overview / meetings / progress-trend / feedback-completion |
| REST API (horilla_api) | ✓ 存在 | `horilla_api/api_views/pms/views.py` — 全量 CRUD API |
| Signals 副作用 | 动态注册 | `pms/signals.py` — BonusPointSetting 运行时动态连接任何已配置模型的 post_save/m2m_changed |
| Scheduler | ✓ 存在 | `pms/scheduler.py` — 后台任务 |
| Report 集成 | ✓ 存在 | `report/views/pms_report.py` |
| 跨模块引用 | 7 处 | horilla_theme / horilla_meet / base/ess_dashboard / base/demo_data / horilla_api / report / payroll |

### 11.2 跨模块信号链（生产风险）

```text
employee.models.Employee
  └─ post_save → BonusPoint.objects.create() ───┐
                                                   │
pms.signals.start_automation()                     │
  └─ BonusPointSetting post_save / post_delete     │
     └─ 动态注册 signal handler (任意已配置模型)   │
        └─ create_employee_bonus() ────────────────┤
                                                   │
pms.models.EmployeeBonusPoint.save()               │
  └─ BonusPoint.points += self.bonus_point ────────┤
                                                   ▼
                                          employee.models.BonusPoint
                                                   │
                                                   ▼
                                   payroll.models.Reimbursement (bonus_encashment)
                                      └─ BonusPoint.objects.get().redeem()
```

**关键发现**：BonusPoint 是 employee → pms → payroll 的唯一跨切数据通道。HR12 施工时必须 cut over 该通道而不是静默保留。

### 11.3 已施工 HR 模块确认

| 模块 | 目录 | 文件数 | 状态 |
|---|---|---|---|
| HR03 (Staff) | `hr_staff/` | 120 | ✅ Active |
| HR06 (Changes) | `hr_changes/` | 102 | ✅ Active |
| HR07 (Contracts) | `hr_contracts/` | 87 | ✅ Active |
| HR09 (Qualifications) | `hr_qualification/` | 37 | ✅ Active |
| HR11 (Time) | `hr_time/` | 57 | ✅ Active |
| HR10 (Development) | `hr_development/` | ❌ 不存在 | 待建（Provider 契约占位） |

```text
HR12 GAP ANALYSIS COMPLETE (PRODUCTION REVIEW — V1.1)
──────────────────────────────────────────────────────
- Aggregates missing:       48+ (CRITICAL)
- Services missing:         20+ (CRITICAL)
- Providers missing:         9  (HIGH)
- API endpoints missing:    30+ (HIGH)
- UI components missing:    28+ (HIGH)
- UI pages missing:         20+ (HIGH)
- Permissions missing:      14  (HIGH)
- Outbox events missing:     6  (MEDIUM)
- Migration tasks:         141 URL routes + 17 models (MEDIUM)
- Test suites missing:      15  (MEDIUM)

Total gaps: 195+
PMS existing:  17 models, 141 URLs, 11 dashboard APIs, 1 REST API layer,
               1 scheduler, 1 report view, 6 cross-module importers
Current state:  0 of 48+ aggregates exist; 0 of 30+ APIs exist; 0 of 20+ services exist
Cross-cutting:  BonusPoint chain (employee→pms→payroll) must be cut over
Baseline:       renshi/pms/ has comprehensive corporate OKR/360 asset —
                all 17 models require ADAPT/REWRITE, none can become HR12 Authority directly
Action:         Proceed to S1-S13 construction per 总册 §246-258
```

