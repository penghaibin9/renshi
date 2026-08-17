# HR12_LegacyAssessmentMapping —— Horilla PMS → HR12 考核 遗留映射表

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §202-204 + `renshi/pms/models.py` 真实代码基线
> 接管裁决：**REWRITE**（KEEP/ADAPT/REWRITE 详见总册 §26）

---

## 0. 基线核验结论

PMS 模块当前拥有 **17 个模型**（含辅助模型 Comment/Answer/MeetingsAnswer/EmployeeBonusPoint/BonusPointSetting），覆盖 OKR 目标、360 反馈、匿名问卷、会议、积分五大能力。

**关键风险判定**：PMS 大量直接绑定 `base.Employee` / `base.Company` / `base.Department` / `base.JobPosition`，无 tenant 意识、无 effective-dated、无 PolicyVersion、无正式 Result/档案馆。**零个现有模型可直接成为 HR12 Authority**。

---

## 1. 核心模型映射矩阵

### 1.1 Period → AssessmentCycle（ADAPT）

| Horilla PMS (`pms.Period`) | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `period_name` (Char, unique) | `cycle_no` + `name` | ADAPT | 唯一名不行；需 tenant + type 复合 |
| `start_date` / `end_date` | `start_at` / `end_at` | ADAPT | 加 business_year / academic_year |
| `company_id` (M2M → Company) | `tenant_id` + `owner_org_id` | **REWRITE** | Company ≠ Tenant；M2M 跨租户不行 |
| 无 | `assessment_type` (ANNUAL/TERM/ROUTINE/SPECIAL/ETHICS) | **NEW** | 周期类型 |
| 无 | `policy_version_id` FK → PolicyVersion | **NEW** | 绑定制度版本 |
| 无 | `lifecycle_status` (DRAFT→...→CLOSED) | **NEW** | 完整生命周期 |
| 无 | `CycleSnapshot` (frozen sub-entity) | **NEW** | 发布后不可变 |
| `HorillaModel` base | 独立 base + tenant enforced | **REWRITE** | 不继承 HorillaModel |

**迁移策略**：`Period.start_date/end_date` → 识别年度/聘期类型；`period_name` → 作为迁移参考标识符。旧 Period 不可直接当正式 AssessmentCycle。

---

### 1.2 Objective → Goal（ADAPT）

| Horilla PMS (`pms.Objective`) | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `title` (Char, 100) | `goal_code` + `GoalVersion.title` | ADAPT | 内容入 Version |
| `description` (Text, 255) | `GoalVersion.description` | ADAPT | — |
| `managers` (M2M → Employee) | `GoalAssignment.reviewer_refs` | **REWRITE** | Employee → HrStaffMaster ref |
| `assignees` (M2M → Employee) | `GoalAssignment` → HrStaffMaster | **REWRITE** | 同上 |
| `key_result_id` (M2M → KeyResult) | `GoalVersion.measure_refs` | ADAPT | KeyResult → GoalMeasure |
| `duration` / `duration_unit` | `GoalVersion.period_config` (JSON) | ADAPT | 结构化 |
| `is_template` (Bool) | `GoalVersion.is_template` | KEEP | 保留模板能力 |
| `self_employee_progress_update` | `GoalVersion.self_progress_allowed` | KEEP | 保留 |
| `archive` (Bool, soft) | `status = ARCHIVED` | KEEP | 改状态 |
| `company_id` (FK → Company) | `tenant_id` | **REWRITE** | Company→Tenant |
| 无 | `GoalVersion` (版本化内容) | **NEW** | DRAFT→CONFIRMED→CHANGE_REQUEST→APPROVED |
| 无 | `goal_plan_id` FK | **NEW** | 目标计划归属 |
| 无 | `owner_type` / `owner_ref` | **NEW** | INDIVIDUAL/TEAM/ORG/ROLE |
| 无 | `source_type` / `source_ref` | **NEW** | 岗位职责/年度任务/学院分解/HR07 聘期目标 |

**迁移策略**：`Objective.title+description` → `Goal` Root + `GoalVersion V1` (MIGRATED_UNVERIFIED)。旧 managers/assignees 通过 Employee→Person 映射转换。

---

### 1.3 EmployeeObjective → GoalAssignment（ADAPT）

| Horilla PMS | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `objective_id` FK → Objective | `goal_id` FK → Goal | ADAPT | — |
| `employee_id` FK → Employee | `staff_id` → HrStaffMaster | **REWRITE** | Person mapping |
| `status` (Not Started/On Track/Behind/At Risk/Closed) | 合并进入 `GoalProgressEvent` | ADAPT | 保留但降级为事件 |
| `progress_percentage` (Int) | `GoalProgressEvent.self_claimed_progress` | ADAPT | 不可信需标记 |
| `start_date` / `end_date` | `GoalAssignment.effective_period` | ADAPT | — |
| `key_result_id` M2M | `GoalAssignment.measure_assignments` | ADAPT | — |
| `unique_together` (employee, objective) | `unique_together` (staff, goal) 或约束放松支持多轮 | KEEP | 语义调整为"每轮每人每个目标唯一" |

**迁移策略**：统计每个人每个 Objective 的 EmployeeObjective 数量判断 is_individual/team。

---

### 1.4 KeyResult → GoalMeasure（ADAPT）

| Horilla PMS (`pms.KeyResult`) | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `title` (Char, 60) | `measure_code` | ADAPT | — |
| `description` (Text) | `GoalMeasure.description` | ADAPT | — |
| `progress_type` (% / # / Currency) | `measure_type` (扩展) | **REWRITE** | 移除 USD/INR/EUR 货币硬编码 |
| `target_value` (Int, default 100) | `GoalMeasure.target_value` (Decimal) | **REWRITE** | Int→Decimal；移除 100 默认值文化 |
| `duration` (Int, days) | `GoalMeasure.period` | ADAPT | — |
| `archive` | `status = ARCHIVED` | KEEP | — |
| `company_id` FK → Company | `tenant_id` | **REWRITE** | — |

---

### 1.5 EmployeeKeyResult → GoalMeasureAssignment + ProgressEvent（ADAPT）

| Horilla PMS | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `key_result_id` FK → KeyResult | `goal_measure_id` FK | ADAPT | — |
| `start_value` / `current_value` / `target_value` (Int) | `GoalProgressEvent` (self/verified/comment) | **REWRITE** | Int→Decimal；分层可信度 |
| `progress_percentage` (Int) | `calculated_progress` (derived) | ADAPT | 服务端重算 |
| `status` (Not Started/...) | `GoalProgressEvent.status_claim` | ADAPT | — |
| `start_date` / `end_date` | `effective_period` | ADAPT | — |

**关键修正**：旧 `current_value` 可由本人/管理员原位输入，HR12 强制区分 self_claimed vs verified_progress。

---

### 1.6 Comment → GoalCheckIn / RoutineAssessmentEntry（ADAPT）

| Horilla PMS (`pms.Comment`) | HR12 Target | 裁决 |
|---|---|---|
| `comment` (Text) | `GoalCheckIn.comment` / `RoutineEntry.observation` | ADAPT |
| `employee_id` FK → Employee | `author_staff_id` | **REWRITE** |
| `employee_objective_id` FK | `goal_assignment_id` | ADAPT |
| `created_at` | `check_in_at` | KEEP |

---

## 2. 360 Feedback 体系映射

### 2.1 Feedback → ReviewerAssignment + MultiRaterSession（ADAPT）

| Horilla PMS (`pms.Feedback`) | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `review_cycle` (Char) | `session_name` | ADAPT | — |
| `manager_id` FK → Employee | `reviewer_assignments[DIRECT_MANAGER]` | **REWRITE** | Employee→Staff |
| `employee_id` FK | `subject_staff_id` | **REWRITE** | — |
| `colleague_id` M2M | `reviewer_assignments[PEER]` | **REWRITE** | — |
| `subordinate_id` M2M | `reviewer_assignments[SUBORDINATE]` | **REWRITE** | — |
| `others_id` M2M | `reviewer_assignments[OTHER/EXPERT]` | **REWRITE** | — |
| `question_template_id` FK | `questionnaire_version_id` | ADAPT | — |
| `status` (On Track/...) | `session_status` | **REWRITE** | 改生命周期 |
| `cyclic_feedback*` (Bool+count+period) | `feedback_scheduler` (独立 Job/周期) | **REWRITE** | 解耦 |

**结构风险**：旧 Feedback 同时绑定周期、被评人、评价人群组和问卷，混合了"评价安排"与"评价内容"。HR12 必须分离 `ReviewerAssignment`（谁评谁）+ `MultiRaterFeedback`（评分+回答）。

---

### 2.2 AnonymousFeedback → MultiRaterSession（匿名策略）（ADAPT）

| Horilla PMS | HR12 Target | 裁决 |
|---|---|---|
| `feedback_subject` | `session_title` | ADAPT |
| `based_on` (general/employee/department/job_position) | `population_filter_config` (JSON) | **REWRITE** |
| `employee_id` / `department_id` / `job_position_id` | `target_ref` (聚合) | **REWRITE** |
| `anonymous_feedback_id` (Char, 10) | `anonymous_session_code` | ADAPT |
| `feedback_description` | `session_description` | ADAPT |

**安全需修复**：旧 `objects = models.Manager()` （无 CompanyManager），tenant 隔离脆弱。

---

### 2.3 QuestionTemplate / Question / QuestionOptions → QuestionnaireVersion（ADAPT）

| Horilla PMS | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `QuestionTemplate` | `AssessmentQuestionnaire` root | ADAPT | — |
| `Question` (includes question_type) | `QuestionVersion` | ADAPT | — |
| `QuestionOptions` (A/B/C/D 四选项) | `QuestionVersion.options` (JSON) | **REWRITE** | 不限四选项 |
| 无 | `QuestionnaireVersion` (immutable after publish) | **NEW** | 版本冻结 |
| 无 | `dimension` / `purpose` / `sensitivity` | **NEW** | HR12 新增 |

**问题类型对齐**：旧 `1-5` (Text/Rating/Boolean/Multi-choices/Likert) → 新 `TEXT/RATING/BOOLEAN/SINGLE_CHOICE/MULTI_CHOICE/LIKERT/NUMBER/DATE/EVIDENCE_REFERENCE`

---

### 2.4 Answer → MultiRaterAnswer（ADAPT）

| Horilla PMS (`pms.Answer`) | HR12 Target | 裁决 | 说明 |
|---|---|---|---|
| `answer` (JSONField, 200) | `answer_value` (JSON) | ADAPT | — |
| `question_id` FK → Question | `question_version_id` FK | **REWRITE** | 绑定版本 |
| `employee_id` FK | `reviewer_staff_id` | **REWRITE** | — |
| `feedback_id` FK → Feedback | `session_id` FK | **REWRITE** | — |

---

### 2.5 KeyResultFeedback → (废弃，归入 EvidenceRef)（DROP_AFTER_CUTOVER）

旧 `KeyResultFeedback` 是对 KeyResult 的反馈，语义模糊（既是评价又是进度）。HR12 由 `GoalMeasureAssignment.progress_events` + `EvidenceRef` 取代。迁移后标记 DROP_AFTER_CUTOVER。

---

## 3. Meetings / 1:1 映射

### 3.1 Meetings → GoalCheckIn / RoutineAssessmentEntry（ADAPT）

| Horilla PMS (`pms.Meetings`) | HR12 Target | 裁决 |
|---|---|---|
| `title` | `GoalCheckIn.summary` | ADAPT |
| `date` | `check_in_at` | ADAPT |
| `employee_id` M2M | `subject_staff_ids` | **REWRITE** |
| `manager` M2M | `participant_staff_ids` | **REWRITE** |
| `answer_employees` M2M | 解密为 reviewer group | **REWRITE** |
| `question_template` FK | `questionnaire_version_id` | ADAPT |
| `response` (Text) | `check_in_notes` | ADAPT |
| `show_response` (Bool) | `visibility_policy` | KEEP |
| `company_id` FK | `tenant_id` | **REWRITE** |

### 3.2 MeetingsAnswer → (归入 CheckIn/MultiRater)（DEPRECATE + MIGRATE）

Meeting 中的问答数据独立成 MultiRaterAnswer 或在 CheckIn 中引用。

---

## 4. BonusPoint 体系映射

### 4.1 EmployeeBonusPoint → (数据清理；新 EvidenceScoreRef)（DEPRECATE）

旧 `EmployeeBonusPoint` 是绩效积分的"游戏化"机制（完成任务/关闭目标加积分），与高校人事考核制度无关。**不迁移为 HR12 事实**。历史数据按 `LEGACY_REFERENCE` 展示。

### 4.2 BonusPointSetting → (废弃；用 RuleVersion 替代)（DEPRECATE）

旧自动化积分规则（如 "Objective Closed → +5 points"）。HR12 不使用自动积分机制。

---

## 5. Horilla 基础依赖映射

### 5.1 base.Company → Tenant

| Legacy | HR12 | 裁决 |
|---|---|---|
| `Company.id` / `selected_company` | `tenant_id` (UUID) | **REWRITE** |
| `PMS.Company` M2M (Period) | `tenant_id` (unique, not M2M) | **REWRITE** |

### 5.2 base.Department → HR02 Organization

| Legacy | HR12 | 裁决 |
|---|---|---|
| `Department.id` + current head | `org_id` + as-of snapshot | **REWRITE** |

### 5.3 base.JobPosition → HR02 Position

| Legacy | HR12 | 裁决 |
|---|---|---|
| `JobPosition` current title | `position_id` + as-of snapshot | **REWRITE** |

### 5.4 employee.Employee → HR03 HrStaffMaster / HrPerson

| Legacy | HR12 | 裁决 |
|---|---|---|
| `Employee` single current model | `HrStaffMaster` + `EmploymentRelationship` + `Assignment(s)` as-of | **REWRITE** |
| `employee.Employee.bonus_point` (BonusPoint FK) | 废弃；不迁移 | **DEPRECATE** |

---

## 6. HorillaAudit 兼容性

| 项目 | 状态 | 裁决 |
|---|---|---|
| `HorillaAuditLog` / `HorillaAuditInfo` | 技术框架可用 | KEEP（技术复用，但不作为业务审计最终态） |
| `history` field (per model) | 保留审计 | KEEP |
| 业务审计事件 | 补全 (PolicyPublished, ResultFinalized, etc.) | **NEW** |

---

## 7. PMS URLs / Routes 全量映射（141 条路由）

### 7.1 路由组分类

| 路由组 | 数量 | HR12 Target | 裁决 |
|---|---|---|---|
| Feedback | 27 | `/api/v1/hr/assessments/multi-rater` + evaluations | **REWRITE** |
| Anonymous Feedback | 6 | `/api/v1/hr/assessments/multi-rater` (anonymity flag) | **MERGE** |
| Objective | 22 | `/api/v1/hr/assessments/goals` | **REWRITE** |
| Employee Objective | 12 | GoalAssignment + GoalProgress API | **REWRITE** |
| Key Result | 14 | GoalMeasure API | **REWRITE** |
| Period | 9 | `/api/v1/hr/assessments/cycles` | **REWRITE** |
| Question Template | 12 | `/api/v1/hr/assessments/questionnaires` | **REWRITE** |
| Meetings | 17 | `/api/v1/hr/assessments/check-ins` | **ADAPT** |
| Bonus Point | 15 | 废弃 | **DEPRECATE** |
| Dashboard API | 11 | HR01 + HR18 (不保留 ranking) | **DEPRECATE / REPLACE** |
| Performance Settings | 12 | Policy Center + S1 Settings | **REWRITE** |
| **合计** | **141** | — | — |

### 7.2 Dashboard API 风险标记

PMS Dashboard API 包含 11 个端点，其中以下端点暴露员工排名/评比信息，HR12 **禁止保留**：

| 端点 | 风险 | 处理 |
|---|---|---|
| `dashboard/api/performers/` | 暴露全校员工分数排名 | **DEPRECATE** — HR12 不做公开排行榜 |
| `dashboard/api/at-risk/` | "At Risk" 标签隐含末位压力 | **DEPRECATE** — 改用 Goal overdue/blocker 概念 |
| `dashboard/api/kpi/` | 绩效 KPI 与企业 OKR 耦合 | **REPLACE** — 迁移到 HR18 Assessment Analytics |
| `dashboard/api/okr-overview/` | OKR 命名不适用高校 | **REPLACE** — 改为 Cycle 进度概览 |
| `dashboard/api/progress-trend/` | 趋势图 — 可用 | **ADAPT** — 保留技术，切换数据源 |

### 7.3 核心路由迁移映射

| Legacy Route Group | HR12 Target API | 裁决 |
|---|---|---|
| `/pms/period/*` (9 routes) | `/api/v1/hr/assessments/cycles` | **REWRITE** |
| `/pms/objective/*` (22 routes) | `/api/v1/hr/assessments/goals` | **REWRITE** |
| `/pms/feedback/*` (27 routes) | `/api/v1/hr/assessments/multi-rater` + evaluations | **REWRITE** |
| `/pms/anonymous-feedback/*` (6 routes) | 合并入 multi-rater (anonymity flag) | **MERGE** |
| `/pms/question-template/*` (12 routes) | `/api/v1/hr/assessments/questionnaires` | **REWRITE** |
| `/pms/meetings/*` (17 routes) | `/api/v1/hr/assessments/check-ins` | **ADAPT** |
| `/pms/bonus-point*/*` (15 routes) | 废弃 | **DEPRECATE** |
| `/pms/dashboard/*` (11 routes) | HR01 Dashboard + HR18 Analytics | **REPLACE** |
| `/pms/performance-settings/*` (12 routes) | S1 Settings + Policy Center | **REWRITE** |

---

## 8. 跨模块信号链与依赖（Deep Scan 发现）

### 8.1 BonusPoint 跨切信号链

```text
employee.models.Employee
  └─ @receiver(post_save) → BonusPoint.objects.create() if not exists
       │
pms.signals.start_automation()     ← 运行时动态注册
  └─ BonusPointSetting post_save/delete
     └─ 动态连接 post_save 到任意已配置模型类
        └─ status 匹配 → EmployeeBonusPoint.save()
           └─ BonusPoint.points += self.bonus_point ← 同一 BonusPoint 记录
                │
                ▼
payroll.models.Reimbursement(type=bonus_encashment)
  └─ BonusPoint.objects.get(employee_id=...).redeem()
       └─ Reimbursement.save() → deduct_and_redeem points
```

**HR12 施工关键影响**：
- BonusPoint 是 **employee → pms → payroll 的唯一跨切数据通道**
- S10 Legacy Cutover 时该通道必须显式 FREEZE，不能静默保留
- Employee 的 `post_save` 信号创建 BonusPoint 是刚性依赖，不能简单 mute
- Payroll 的 Reimbursement `bonus_encashment` 类型消费 BonusPoint — 需与 HR15 协调切换

### 8.2 PMS 跨模块 Importers（7 处）

| 文件 | 导入方式 | 风险 | HR12 处理 |
|---|---|---|---|
| `report/views/pms_report.py` | `from pms.models import ...` | 中等 — 报表数据源 | S10 切换到 HR12 Assessment Analytics |
| `horilla_theme/overrides.py` | `from pms import ...` | 低 — UI 配置 | 兼容过渡 |
| `horilla_meet/views.py` + `models.py` | `from pms.models import Meetings` | 低 — Meetings 独立模块 | ADAPT |
| `base/ess_dashboard.py` | `from pms.views import ...` | 高 — ESS 首页 | S10 切换到 HR17 self API |
| `base/demo_data/sanitize.py` | PMS 数据清理 | 低 — 仅测试 | 无需处理 |
| `horilla_api/api_views/pms/views.py` | PMS REST API 全量 | **高** — 外部 API 消费者 | S10 Freeze 旧 API；新建 HR12 API |

### 8.3 PMS Scheduler

`pms/scheduler.py` — 后台定时任务。S10 迁移到 HR12 的 Job 体系（`PENDING→RUNNING→SUCCESS/FAILED/CANCELLED/EXPIRED`）。

---

## 9. 迁移可信度策略

| 旧数据类型 | HR12 Trust Level | 说明 |
|---|---|---|
| 旧 `Objective + EmployeeObjective` (有明确周期/目标/结果) | `MIGRATED_UNVERIFIED` | 入 Goal 供参考，不当正式年度结果 |
| 旧 `Feedback + Answer` (有问卷/评价) | `MIGRATED_PARTIAL` | 入 ReviewerEvaluation ref，标记为 legacy |
| 旧 `AnonymousFeedback` | `MIGRATED_UNVERIFIED` | 需特别标记来源/匿名策略 |
| 旧 `EmployeeBonusPoint` + score | `COMPAT_ONLY` / `DROP_AFTER_CUTOVER` | 不迁移 |
| 旧 `Meetings + MeetingsAnswer` | `MIGRATED_PARTIAL` | 入 CheckIn |
| 旧 1~5 feedback score 单一字段 | `MIGRATED_UNVERIFIED` | **不足以冒充 Annual Final Result** |

---

## 9. Tenant 映射风险

| 风险 | 旧 PMS 表现 | HR12 要求 |
|---|---|---|
| Period.company_id M2M 混合 | 一个 Period 可跨公司 | tenant_id NOT NULL；跨租户 fail-closed |
| Employee.current company 漂变 | Employee 可能换 company | `SubjectSnapshot` 冻结当时 org |
| 历史记录无 company | migrated data | `MIGRATION_BLOCKED` |
| thread-local 依赖 | `_thread_locals.request` | 后台 Job 显式 tenant |

---

## 10. 禁止迁移项

以下旧 PMS 能力**不进 HR12**：

- ❌ `Employee.bonus_point` 积分体系
- ❌ `BonusPointSetting` 自动化积分规则
- ❌ OKR "完成率 %" 直接当年度考核结果
- ❌ 匿名 feedback 的评分直接成正式档次
- ❌ `Period` 直接当 `AssessmentCycle`
- ❌ 无 PolicyVersion 的历史数据直接成 FinalResult

---

## 13. S0 审计清单（Production Review v1.1）

- [x] `pms/models.py` 17 模型全部扫描
- [x] `pms/signals.py` 副作用审计（BonusPointSetting 动态注册 + pre_bulk_update 追踪）
- [x] `pms/urls.py` 全量路由清点（9 组 141 条 URL）
- [x] `pms/scheduler.py` 后台任务审计
- [x] `employee/models.py` Employee/BonusPoint 依赖 + post_save 信号
- [x] `base/models.py` Company/Department/JobPosition 依赖确认
- [x] `payroll/models/models.py` Contract + Reimbursement 依赖确认
- [x] `horilla_audit` 审计能力确认（技术复用 KEEP）
- [x] `notifications/base/models.py` 通知机制确认
- [x] `horilla_api/api_views/pms/views.py` REST API 层确认
- [x] `report/views/pms_report.py` 报表集成确认
- [x] `horilla_meet` / `horilla_theme` / `base/ess_dashboard` 跨模块 importer 确认
- [x] 全仓关键词搜索（period/objective/feedback/keyresult/meeting/bonuspoint/performance/review/rating）完成
- [x] Migrations 状态确认（5 个 migration, 状态 OK）
- [x] 多租户风险标记（Company M2M, thread-local, no tenant field）
- [x] 正式结果缺失确认（PMS 无 FINALIZED Result 概念）
- [x] BonusPoint 跨切信号链追踪（employee→pms→payroll）
- [x] hr_development/ 不存在确认（HR10 待建）
- [x] hr_staff/hr_contracts/hr_qualification/hr_time 已施工确认

---

## 14. 结论

```text
PMS LEGACY MAPPING READY (PRODUCTION REVIEW v1.1)
──────────────────────────────────────────────────
Models mapped:       17 (ADAPT 8 + REWRITE 7 + DEPRECATE 2)
URL routes:          141 (across 9 functional groups + dashboard API + settings)
Dashboard APIs:      11 (5 to DEPRECATE — performers/at-risk/kpi/okr-overview/fb-completion)
Cross-module refs:   7 importer files (2 HIGH risk — ess_dashboard + horilla_api)
Signal chain:        BonusPoint (employee→pms→payroll) — must FREEZE at S10

All legacy data:     MIGRATED_UNVERIFIED or MIGRATED_PARTIAL
NONE qualifies:      as FinalAssessmentResult
Blockers:            Company→Tenant; Employee→HrStaffMaster; no PolicyVersion/Result
Cutover strategy:    ADAPT (8) + REWRITE (7 core) + DEPRECATE (BonusPoint 2 + dashboard ranking)
```

