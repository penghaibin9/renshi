# HR10_INTEGRATION_MATRIX — 跨域集成联动矩阵

> 全局合同：`00_高校人事系统全局架构与旧系统接管合同.md`
> 业务事实源：总册 §15–22 + §145
> 版本：`S0_V1`
> 日期：2026-08-09

---

## 0. 集成总览图

```text
                        ┌─────────────┐
                        │   HR03      │ (Person/Staff/Education)
                        │   Identity  │ ← Person/Staff read + Education writeback
                        └──────┬──────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
  ┌─────▼─────┐        ┌──────▼──────┐        ┌──────▼──────┐
  │   HR08    │        │   HR09      │        │   HR12      │
  │ External  │        │Qualification│        │ Assessment  │
  │ reference │        │  Evidence ← │        │  Facts →    │
  └───────────┘        │  (consumer) │        │ (consumer)  │
                       └─────────────┘        └─────────────┘
        │
  ┌─────▼─────┐        ┌─────────────┐        ┌─────────────┐
  │   HR11    │        │   HR15      │        │  Academic   │
  │Schedule   │        │  Finance    │        │  Provider   │
  │Conflict ↔ │        │ Budget ←→   │        │ output ref↔ │
  │TimeWindow→│        │(projection) │        │             │
  └───────────┘        └─────────────┘        └─────────────┘
        │
  ┌─────▼─────┐        ┌─────────────┐        ┌─────────────┐
  │   HR07    │        │  Documents  │        │  Research   │
  │ Agreement │        │  Provider   │        │  Provider   │
  │   ref     │        │ file upload │        │ output ref↔ │
  └───────────┘        └─────────────┘        └─────────────┘
```

---

## 1. Provider 契约清单

| # | Provider | 方向 | 数据流向 | 状态 | 施工阶段 |
|---|---|---|---|---|---|
| 1 | PersonProvider (HR03) | HR10→HR03 | HrPerson / HrStaffMaster / EmploymentRelationship / Assignment / EducationHistory | 已就绪（HR03 模型可直接引用） | S1 |
| 2 | ExternalTeacherProvider (HR08) | HR10→HR08 | HrExternalEngagement (allow_external_teacher, allowed_activity_types) | 已就绪（HR08 已施工） | S9 |
| 3 | QualificationEvidenceProvider (HR09) | HR10→HR09 | VERIFIED DevelopmentFact (as-of) → 双师证据 | 待施工（HR09 未建） | S9 |
| 4 | TimeConflictProvider (HR11) | HR10→HR11 | Schedule conflict: PASS/WARNING/BLOCKED/SOURCE_UNAVAILABLE | 已预留接口 | S9 |
| 5 | DevelopmentTimeProvider (HR10→HR11) | HR10→HR11 | Training/practice time windows → schedule exceptions | 已预留接口 | S9 |
| 6 | AssessmentFactsConsumer (HR12) | HR10→HR12 | Verified completion/practice facts + plan completion rates | 待施工（HR12 未建） | S9 |
| 7 | FinanceBudgetProvider (HR15) | HR10→HR15 | planned_budget / reserved / committed → budget status read | 待施工（HR15 未建） | S9 |
| 8 | PayrollTimeConsumer (HR15) | HR10→HR15 | (边界：不传输 HR10 数据；仅通过 HR11 传递时间事实) | N/A | — |
| 9 | AcademicProvider (教务) | HR10↔教务 | teaching calendar → schedule conflict; output → teaching transformation ref | 无对接（PENDING_EXTERNAL_LINK） | S9 |
| 10 | ResearchProvider (科研) | HR10↔科研 | output → technical/research ref (patent/standard/R&D) | 无对接（PENDING_EXTERNAL_LINK） | S9 |
| 11 | AgreementProvider (HR07) | HR10→HR07 | Practice agreement / confidentiality / IP | 已就绪（HR07 Agreement 模型） | S9 |
| 12 | DocumentProvider | HR10→horilla_documents | Evidence file upload + download ticket + security | 已就绪 | S1 |
| 13 | NotificationProvider | HR10→notifications | All state transitions → notify | 已就绪 | S4+ |

---

## 2. 跨域事件清单

| 事件 | 发布者 | 消费者 | payload 核心字段 |
|---|---|---|---|
| `DevelopmentPlanPublished` | HR10 | HR01/HR18 | plan_id, version_id, tenant_id, population_snapshot |
| `DevelopmentNeedCreated` | HR10 | HR01 | need_id, plan_version_id, staff_ids[], priority |
| `LearningProgramPublished` | HR10 | HR01/HR17 | program_id, version_id, offering_ids[] |
| `LearningOfferingOpened` | HR10 | HR17 | offering_id, capacity, enrollment_open_at |
| `TrainingRequestSubmitted` | HR10 | approvers | request_id, staff_id, program_id, estimated_cost |
| `TrainingRequestApproved` | HR10 | HR15/HR11 | request_id, budget_reservation_ref, leave_required |
| `LearningEnrollmentCreated` | HR10 | HR11/HR17 | enrollment_id, offering_id, staff_id, date_range |
| `LearningWaitlisted` | HR10 | HR17 | enrollment_id, position |
| `LearningStarted` | HR10 | HR11 | enrollment_id, start_at |
| `LearningCompletionSubmitted` | HR10 | verifiers | completion_id, enrollment_id, submitted_evidence_hash |
| `LearningCompletionVerified` | HR10 | HR09/HR12 | completion_id, verified_hours, trust_level |
| `FurtherStudyStarted` | HR10 | HR03/HR11 | case_id, staff_id, study_type, host_org |
| `FurtherStudyMilestoneVerified` | HR10 | HR03 | case_id, milestone_type, verified_at |
| `PracticeProjectPublished` | HR10 | HR01 | project_id, version_id, enterprise_id |
| `PracticeAssignmentCreated` | HR10 | HR11/mentor | assignment_id, staff_id, placement_id, mentor_id |
| `PracticeAssignmentStarted` | HR10 | HR11 | assignment_id, started_at |
| `PracticeEvidenceSubmitted` | HR10 | evaluators | assignment_id, evidence_id, evidence_type |
| `PracticeEvaluationFinalized` | HR10 | HR09/HR12/HR15 | assignment_id, verified_hours, verified_days, output_refs |
| `DevelopmentOutputVerified` | HR10 | Academic/Research | output_id, output_type, external_authority_ref |
| `DevelopmentFactCreated` | HR10 | HR09/HR12/HR06 | fact_id, fact_type, staff_id, verified_hours/days |
| `DevelopmentRiskOpened` | HR10 | HR01/manager | risk_id, risk_type, severity, staff_id |

> **00 §28.3 全局事件注册表规定：** 跨域正式事件使用 `DevelopmentFactVerified`（过去式），`DevelopmentFactCreated` 为模块内部事件。HR09/HR12 消费 `DevelopmentFactVerified`。

---

## 3. 关键跨域边界详细合同

### 3.1 HR10→HR09（双师证据提供）

```text
Provider: QualificationEvidenceProvider
Interface: GET /internal/hr/development/evidence/staff/{staffId}
Parameters: ?asOf=&types=ENTERPRISE_PRACTICE,TRAINING_COMPLETION,DEVELOPMENT_OUTPUT
Response: {
  "data": [{
    "sourceFactId": "uuid",
    "factType": "ENTERPRISE_PRACTICE",
    "verifiedStatus": "VERIFIED",
    "period": {"from": "2024-03-01", "to": "2024-08-31"},
    "provider": {"name": "XX集团", "kind": "ENTERPRISE"},
    "positionScene": "智能制造工程师",
    "verifiedDuration": {"hours": 960, "days": 120},
    "evaluationSummary": {"status": "PASS", "enterpriseRating": {...}},
    "outputRefs": [...],
    "evidencePackageHash": "sha256:...",
    "sourceUpdatedAt": "2026-08-09T21:50:00+08"
  }],
  "meta": {"requestId", "sourceUpdatedAt", "calculatedAt", "dataFreshness"}
}
Contracts:
- 只返回 VERIFIED facts (status = VERIFIED)
- 返回数据带 as-of 语义
- dataFreshness: FRESH / STALE / SOURCE_UNAVAILABLE
- HR09 不能反向修改 HR10 fact
- Canonical event: DevelopmentFactVerified (00 §28.3)
```

### 3.2 HR10→HR11（时间冲突与窗口）

```
Provider: TimeConflictProvider
Interface: check_conflict(staff_master_id, start_at, end_at) → {PASS, WARNING, BLOCKED, SOURCE_UNAVAILABLE}
Sources: teaching_schedule, approved_leave, attendance_schedule, other_enrollment, enterprise_practice
Conflict: when start/end overlaps with existing commitments

Provider: DevelopmentTimeProvider (HR10→HR11)
Interface: get_development_time_windows(staff_master_id, period_start, period_end) → [{type, start, end}]
Purpose: HR11 creates schedule exceptions (AUTHORIZED_TRAINING / ENTERPRISE_PRACTICE) 
         for attendance processing
```

### 3.3 HR10→HR03（学历写回）

```
Provider: EducationWritebackProvider (HR10→HR03)
Process:
  FurtherStudyCase milestone: GRADUATED (verified)
  → HR10 submits to HR03: HrEducationExperience create/verify request
  → HR03 authoritative EducationHistory record created
  → HR10 milestone: marks external_authority_ref with HR03 education fact ID
Contract:
  - HR10 只发起请求，不创建 HR03 记录
  - HR03 EducationHistory 是最终权威
  - 写回失败 → FurtherStudyMilestone stays in VERIFIED but external_authority_ref = PENDING
```

---

## 4. Integration 可用性状态

| Provider | 当前可用性 | Fallback 行为 |
|---|---|---|
| HR03 Person/Staff | AVAILABLE | NO FALLBACK (person identity required) |
| HR08 External Teacher | AVAILABLE | 外聘教师标记为 EXTERNAL_REF_UNAVAILABLE |
| HR09 Evidence Consumer | UNAVAILABLE (HR09 未建) | HR10 正常生成 fact; dataFreshness: SOURCE_UNAVAILABLE; consumer 未来回填 |
| HR11 Time Conflict | PARTIAL (HR11 S0 基线) | conflict check 返回 SOURCE_UNAVAILABLE; WARNING not BLOCKED |
| HR12 Assessment Consumer | UNAVAILABLE (HR12 未建) | 正常记录; HR12 读取时通过 Provider 追溯 |
| HR15 Finance | UNAVAILABLE (HR15 未建) | recorded as PLANNED_BUDGET_ONLY; payment_status = UNKNOWN |
| Academic | UNAVAILABLE | output ref = PENDING_EXTERNAL_LINK |
| Research | UNAVAILABLE | same as above |
| HR07 Agreement | PARTIAL (HR07 有 Agreement 模型但非通用协议) | practice agreement 通过 HR07 创建或存为 HR10 document |
| Document | AVAILABLE | 正常使用 |
| Notification | AVAILABLE | 正常使用 |

---

## 5. Integration 故障模式

| 故障 | HR10 行为 | 不做什么 |
|---|---|---|
| HR03 Person read timeout | 返回 503: PERSON_PROVIDER_UNAVAILABLE | 不 fallback to Employee 旧表 |
| HR11 schedule conflict timeout | conflict = SOURCE_UNAVAILABLE; approval continues with WARNING | 不自动标 Pass |
| HR09 evidence index rebuild fail | dataFreshness = STALE; 不影响 HR10 内部 fact 存在 | 不删除 fact |
| HR15 finance API fail | payment_status = UNKNOWN; budget reservation 继续（HR10 内部账） | 不替代 HR15 支付 |
| Academic/Research API fail | output external_authority_ref = PENDING_EXTERNAL_LINK | 不伪造 ref |
| Outbox event dispatch fail | PENDING → RETRY (3x) → FAILED → DEAD letter | 不丢事件 |

---

**文档状态：S0_V1 — 集成矩阵完成。13 Provider 契约 + 21 事件（DevelopmentFactVerified 对齐 00 §28.3）+ 4 关键边界合同 + 可用性矩阵 + 故障模式。**
**API Root：** `/api/v1/hr/development/*`（00 §28.1 canonical root "development" 一级资源）。
