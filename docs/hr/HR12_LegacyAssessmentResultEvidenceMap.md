# HR12_LegacyAssessmentResultEvidenceMap —— 遗留考核结果与证据映射

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §202-204 (Legacy Mapping) + `renshi/pms/models.py` 真实代码基线

---

## 1. 遗留数据分类

旧 PMS 中存在的数据类型及其对 HR12 的映射关系：

| 旧数据类型 | 旧表 | 数据量估计 | 映射目标 | 可信度 |
|---|---|---|---|---|
| Period (考核周期) | `pms_period` | ~数十 | Cycle source | MIGRATED_UNVERIFIED |
| Objective (目标定义) | `pms_objective` | ~数百 | Goal source | MIGRATED_UNVERIFIED |
| EmployeeObjective (人员目标) | `pms_employeeobjective` | ~数千 | GoalAssignment source | MIGRATED_UNVERIFIED |
| KeyResult (关键结果定义) | `pms_keyresult` | ~数百 | GoalMeasure source | MIGRATED_UNVERIFIED |
| EmployeeKeyResult (人员关键结果) | `pms_employeekeyresult` | ~数千 | GoalProgressEvent source | MIGRATED_UNVERIFIED |
| Feedback (360 反馈) | `pms_feedback` | ~数百 | MultiRaterSession source | MIGRATED_PARTIAL |
| Answer (反馈回答) | `pms_answer` | ~数千 | MultiRaterAnswer source | MIGRATED_PARTIAL |
| AnonymousFeedback (匿名反馈) | `pms_anonymousfeedback` | ~数百 | restricted MultiRater source | MIGRATED_UNVERIFIED |
| QuestionTemplate (问卷模板) | `pms_questiontemplate` | ~数十 | QuestionnaireVersion source | MIGRATED_UNVERIFIED |
| Question (问题) | `pms_question` | ~数百 | QuestionVersion source | MIGRATED_UNVERIFIED |
| Meetings (1:1 谈话) | `pms_meetings` | ~数百 | GoalCheckIn candidate | MIGRATED_PARTIAL |
| MeetingsAnswer (会议回答) | `pms_meetingsanswer` | ~数百 | CheckIn notes | MIGRATED_PARTIAL |
| Comment (目标评论) | `pms_comment` | ~数千 | CheckIn notes | MIGRATED_PARTIAL |
| EmployeeBonusPoint (积分) | `pms_employeebonuspoint` | ~数百 | **COMPAT_ONLY / DROP** | DROP_AFTER_CUTOVER |
| BonusPointSetting (积分规则) | `pms_bonuspointsetting` | ~数十 | **DROP** | DROP_AFTER_CUTOVER |

---

## 2. 不可迁移项（为什么不能迁移）

| 旧数据 | 不能迁移为正式结果的原因 |
|---|---|
| Old 1~5 feedback score | 无 PolicyVersion、无 Evidence、无 CollectiveDecision、无 Notice |
| Employee.bonus_point 积分 | 是游戏化积分机制，不是事业单位考核 |
| 非正式的 OKR "完成率 %" | 完成率≠年度表现；无师德 Gate、无分类评价、无集体审定 |
| AnonymousFeedback score | 匿名评分不能直接决定正式考核档次 |
| 单一 `qualification` 字段评定 | Employee.qualification text 不能当正式考核结果 |

**策略**：全部标记为 `COMPAT_ONLY` 或 `LEGACY_REFERENCE`，展示在历史标签但不当正式事实消费。

---

## 3. 可迁移的证据映射

### 3.1 Period → Cycle (Reference)

| Legacy Field | HR12 Field | Trust | 说明 |
|---|---|---|---|
| `period_name` | `cycle_legacy_label` | MIGRATED_UNVERIFIED | 保留为参考标识符 |
| `start_date` | `start_at` | MIGRATED_UNVERIFIED | 近似值 |
| `end_date` | `end_at` | MIGRATED_UNVERIFIED | 近似值 |
| `company_id` | `tenant_id` (from Company→Tenant mapping) | MIGRATED_UNVERIFIED | 需要明确的 Tenant 解析 |

**特别注意**：旧 Period 的 `unique` 约束是全局 period_name 唯一；新 Cycle 是 tenant+type 复合。

### 3.2 Objective → Goal (Reference)

| Legacy Field | HR12 Field | Trust |
|---|---|---|
| `title` | `goal_code` + GoalVersion.title(V1) | MIGRATED_UNVERIFIED |
| `description` | GoalVersion.description(V1) | MIGRATED_UNVERIFIED |
| `managers` (Employee M2M) | GoalAssignment.reviewer_refs | MIGRATED_UNVERIFIED |
| `assignees` (Employee M2M) | GoalAssignment → HrStaffMaster | MIGRATED_UNVERIFIED |
| `key_result_id` M2M | GoalVersion.measure_refs(V1) | MIGRATED_UNVERIFIED |

### 3.3 EmployeeObjective → GoalAssignment

| Legacy Field | HR12 Field | Trust |
|---|---|---|
| `employee_id` | `staff_id` (via Employee→Person mapping) | MIGRATED_UNVERIFIED |
| `status` (On Track/Behind/...) | GoalProgressEvent.status_claim | MIGRATED_UNVERIFIED |
| `progress_percentage` | GoalProgressEvent.self_claimed_progress | MIGRATED_UNVERIFIED |
| `start_date/end_date` | `effective_period` | MIGRATED_UNVERIFIED |

### 3.4 EmployeeKeyResult → ProgressEvent

| Legacy Field | HR12 Field | Trust |
|---|---|---|
| `start_value/current_value/target_value` | GoalProgressEvent (self_claimed) | MIGRATED_UNVERIFIED |
| `progress_percentage` | calculated_progress (with trust flag) | MIGRATED_UNVERIFIED |

### 3.5 Feedback → MultiRaterSession

| Legacy Field | HR12 Field | Trust |
|---|---|---|
| `review_cycle` | `session_name` | MIGRATED_PARTIAL |
| `manager_id` / `employee_id` / `colleague_id` / `subordinate_id` | ReviewerAssignment[] | MIGRATED_PARTIAL |
| `question_template_id` | questionnaire_version_id (V1 snapshot) | MIGRATED_PARTIAL |
| `status` | session_status | MIGRATED_PARTIAL |

### 3.6 Answer → MultiRaterAnswer

| Legacy Field | HR12 Field | Trust |
|---|---|---|
| `answer` (JSONField) | `answer_value` | MIGRATED_PARTIAL |
| `question_id` → Question | question_version_id (V1) | MIGRATED_PARTIAL |
| `employee_id` | reviewer_staff_id (via mapping) | MIGRATED_PARTIAL |

---

## 4. Employee → HrStaffMaster 映射策略

```text
Legacy: employee.Employee.id + badge_id + employee_work_info
Target: HrStaffMaster.id (UUID) + HrPerson.id

Mapping table:
  legacy_employee_id → hr_staff_master_id
  legacy_employee_badge → hr_person_display_id

Resolution rules:
  1. badge_id unique per company → resolve via HR03
  2. If employee exists in HR03 → map
  3. If not found → MIGRATION_BLOCKED (orphan employee)
  4. If ambiguous (multiple matches) → MIGRATION_BLOCKED
```

---

## 5. Company → Tenant 映射策略

```text
Legacy: base.Company.id + company_name
Target: tenant_id (UUID)

Resolution:
  1. Company with single tenant → direct map
  2. Company shared across tenants → MIGRATION_BLOCKED
  3. Period with M2M company → resolve all companies; if >1 → MIGRATION_BLOCKED
  4. Employee.current company → verify consistency

Blockers:
  - Multi-company Period (M2M)
  - Employee with null company_id
  - Cross-company Feedback (employee and reviewer different companies)
  - AnonymousFeedback: objects = models.Manager() (not CompanyManager)
```

---

## 6. 迁移执行步骤

```text
Step 1: Tenant Resolution
  - Build Company→Tenant mapping table
  - Validate: all companies have unique tenant

Step 2: Employee Resolution
  - Build Employee→HrStaffMaster mapping
  - Handle orphans (log, skip, manual)

Step 3: Period → Cycle (Reference)
  - Create Cycle records with ASSESSMENT_MIGRATION type
  - Link to resolved tenant

Step 4: Objective → Goal (Reference)
  - Create Goal Root + GoalVersion V1
  - Map assignees to HrStaffMaster

Step 5: EmployeeObjective → GoalAssignment
  - Map each EmployeeObjective to GoalAssignment

Step 6: KeyResult → GoalMeasure
  - Create GoalMeasure records

Step 7: EmployeeKeyResult → GoalProgressEvent
  - Map progress data

Step 8: Feedback → MultiRaterSession
  - Map each Feedback to MultiRaterSession
  - Create ReviewerAssignments

Step 9: Answer → MultiRaterAnswer
  - Map answers (JSON)

Step 10: QuestionTemplate → QuestionnaireVersion
  - Create QuestionnaireVersion V1 snapshot

Step 11: Comment/Meetings → CheckIn
  - Map as GoalCheckIn / RoutineAssessmentEntry

Step 12: DUAL_READ_COMPARE
  - Compare Legacy vs Migrated counts
  - Generate migration report

Step 13: Legacy Write Freeze
  - Block /pms/* create/update endpoints
  - Enable compat redirect

Step 14: Cleanup
  - EmployeeBonusPoint → DROP
  - BonusPointSetting → DROP
  - KeyResultFeedback → DROP_AFTER_CUTOVER
```

---

## 7. 迁移验收标准

| 检查项 | 标准 |
|---|---|
| 所有 Period 有对应 Cycle | 100% mapped or explained |
| 所有 Objective 有对应 Goal | 100% mapped or explained |
| 所有 EmployeeObjective 有对应 GoalAssignment | 100% mapped or explained (cross-verify count) |
| 所有 EmployeeKeyResult 有对应 ProgressEvent | 100% mapped |
| 所有 Feedback 有对应 MultiRaterSession | 100% mapped |
| 所有 Answer 有对应 MultiRaterAnswer | 100% mapped |
| 所有映射中 Employee→Staff 匹配 | No orphan; no ambiguous |
| 所有映射中 Company→Tenant 匹配 | No multi-company; no ambiguous tenant |
| Trust level 正确标记 | MIGRATED_UNVERIFIED/MIGRATED_PARTIAL/COMPAT_ONLY |
| DUAL_READ_COMPARE pass | Counts match within acceptable drift |
| Legacy write endpoints blocked | /pms/* POST/PUT/DELETE → 405/redirect |
| 零个旧数据被标记为 FINAL Result | No legacy data with FINALIZED status |

---

## 8. 结论

```text
LEGACY ASSESSMENT RESULT EVIDENCE MAP COMPLETE
───────────────────────────────────────────────
Migratable models:    12 (Period/Objective/EmployeeObjective/KeyResult/EmployeeKeyResult/
                          Feedback/Answer/QuestionTemplate/Question/Comment/Meetings/MeetingsAnswer)
Non-migratable:        3 (EmployeeBonusPoint/BonusPointSetting/KeyResultFeedback)
Trust level:           ALL MIGRATED_UNVERIFIED or MIGRATED_PARTIAL
                       NONE qualifies as FinalAssessmentResult
Migration complexity:  HIGH — requires Employee→Staff + Company→Tenant resolution
Risk:                  Multiple MIGRATION_BLOCKED conditions (multi-company, orphan employee)
```
