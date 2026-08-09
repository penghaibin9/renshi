# HR12_INTEGRATION_MATRIX —— 考核系统集成矩阵

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §27-37 (与各模块边界) + §193-195 (Outbox/Provider)

---

## 1. 上游依赖矩阵（HR12 消费）

| 源域 | 提供者 | 数据类型 | 消费方式 | 就绪状态 | 失败策略 |
|---|---|---|---|---|---|
| **HR03** | PersonProvider | HrPerson, HrStaffMaster, EmploymentRelationship, Assignment as-of | SubjectSnapshot, Eligibility | ✅ `hr_staff/` 120 files | UNAVAILABLE → Case 无法创建 |
| **HR02** | OrganizationProvider | Organization, Position hierarchy | Population grouping, Reviewer scope | ✅ (`hr_staff/` org resolution) | UNAVAILABLE → Population 无法分组 |
| **HR07** | AgreementProvider | Contract/Agreement, Term, duty snapshot, term goals, review due | TermAssessmentCase | ✅ `hr_contracts/` 87 files | UNAVAILABLE → TERM_CONTEXT_NOT_FOUND |
| **HR09** | QualificationProvider | Credential status, DoubleTeacher facts | Reference only（不决定档次） | ✅ `hr_qualification/` 37 files | UNAVAILABLE → 标记 NOT_APPLICABLE |
| **HR10** | DevelopmentProvider | VERIFIED TrainingCompletion, EnterprisePractice, DevelopmentOutput | EvidenceRef（仅 VERIFIED）| ❌ `hr_development/` 不存在 | UNAVAILABLE（Provider 契约占位） |
| **HR11** | TimeSummaryProvider | Frozen period close: scheduled/worked/absence/late_early/exceptions | MetricSnapshot | ✅ `hr_time/` 57 files | 未月结 → SOURCE_NOT_FROZEN |
| **教务** | AcademicProvider | Teaching assignments, hours, evaluation, quality facts, guidance | EvidenceRef + MetricSnapshot | ⚠️ 外部系统 | UNAVAILABLE → 教学指标不可计算 |
| **科研** | ResearchProvider | Projects, publications, patents, funds, roles | EvidenceRef + MetricSnapshot | ⚠️ 外部系统 | UNAVAILABLE → 科研指标不可计算 |
| **师德** | EthicsFactProvider | Verified formal ethics decisions | EthicsGate | ⚠️ 外部系统 | UNAVAILABLE → Gate REVIEW_REQUIRED |

---

## 2. 下游消费矩阵（HR12 产出）

| 目标域 | 消费事件 | 数据类型 | 消费方式 | 幂等策略 | Revision 影响 |
|---|---|---|---|---|---|
| **HR07** | `TermAssessmentFinalized` | term_id, result_id, grade_code, finalized_at | RenewalPolicy Review → RenewalDecision | consumer_event_id + result_version | `DownstreamAssessmentReviewRequired` |
| **HR13** | `AssessmentResultFinalized` | result_id, grade_code, policy_version, finalized_at | 职称评审 reference | result_version | `DownstreamAssessmentReviewRequired` |
| **HR14** | `AssessmentResultFinalized` | result_id, grade_code, effective_period | 岗位聘任 reference | result_version | `DownstreamAssessmentReviewRequired` |
| **HR15** | `AssessmentResultFinalized` | result_id, grade_code, application_flags | 薪酬规则消费 | result_version | `DownstreamAssessmentReviewRequired` |
| **HR16** | `AssessmentResultFinalized` | result_id, grade_code | 离退/续聘处置 reference | result_version | `DownstreamAssessmentReviewRequired` |
| **HR18** | `AssessmentResultFinalized` + `AssessmentPolicyPublished` | result history, grade distribution, completion status | 报表/上报 | result_version + MetricDefinitionVersion | metric refresh |

---

## 3. Outbox Event 完整清单

| Event | Owner | Consumer(s) | Payload Key Fields | Idempotency | PII Classification |
|---|---|---|---|---|---|
| `AssessmentPolicyPublished` | HR12 | HR18 (awareness) | policy_pack_id, version_no | eventId | INTERNAL |
| `AssessmentCycleOpened` | HR12 | HR18 | cycle_id, assessment_type | eventId | INTERNAL |
| `AssessmentPopulationFrozen` | HR12 | — | cycle_id, count | eventId | INTERNAL |
| `AssessmentGoalConfirmed` | HR12 | — | goal_id, goal_version_id | eventId | INTERNAL |
| `AssessmentGoalRevised` | HR12 | — | goal_id, old_version, new_version | eventId | INTERNAL |
| `AssessmentSelfReviewSubmitted` | HR12 | — | case_id, submitted_at | eventId | RESTRICTED |
| `AssessmentEvaluationSubmitted` | HR12 | — | case_id, reviewer_role, submitted_at | eventId | RESTRICTED |
| `AssessmentEvidenceUnavailable` | HR12 | HR01 (alert) | case_id, provider, indicator | eventId | INTERNAL |
| `AssessmentCalibrationChanged` | HR12 | — | case_id, before/after | eventId | RESTRICTED |
| `AssessmentGradeProposed` | HR12 | — | case_id, proposed_grade | eventId | RESTRICTED |
| `AssessmentPublicityStarted` | HR12 | HR18 | publicity_case_id, scope | eventId | INTERNAL |
| `AssessmentPublicityCompleted` | HR12 | — | publicity_case_id, completed_at | eventId | INTERNAL |
| **`AssessmentResultFinalized`** | HR12 | HR13/14/15/16/18 | result_id, case_id, grade_code, policy_version_id, finalized_at, content_hash | result_id + result_version_no | **FORMAL_RESULT** |
| `AssessmentResultNotified` | HR12 | HR17 (ESS) | result_id, delivery_status | eventId | PERSONAL |
| `AssessmentResultAcknowledged` | HR12 | — | result_id, opinion | eventId | PERSONAL |
| `AssessmentObjectionSubmitted` | HR12 | — | result_id, objection_id | eventId | RESTRICTED |
| `AssessmentObjectionDecided` | HR12 | — | result_id, objection_id, conclusion | eventId | RESTRICTED |
| `AssessmentResultRevised` | HR12 | HR07/13/14/15/16/18 | result_id, old_version, new_version, revision_type | result_id + new_version_no | **FORMAL_RESULT** |
| **`TermAssessmentFinalized`** | HR12 | HR07 | tenant_id, staff_id, term_id, result_id, result_version, grade_code, finalized_at | result_id + result_version_no | **FORMAL_RESULT** |
| `DownstreamAssessmentReviewRequired` | HR12 | HR07/13/14/15 | consumer_domain, result_id, new_version, previous_version | correlation_id | FORMAL_RESULT |
| `AssessmentArchived` | HR12 | HR18 | result_id, archive_package_id | eventId | INTERNAL |

---

## 4. 关键跨域边界规则

### HR12 → HR07 聘期 Handoff

```text
HR12 TermAssessmentFinalized
  → HR07 Consumer Ack (consumer_event_id + result_id + version)
  → HR07 RenewalPolicy Review
  → HR07 RenewalDecision

HR12 不签合同、不自动续聘、不自动解除
HR12 只发结果和需要下游复核的事件
```

### HR12 → HR13/HR14/HR15 结果引用

```text
HR13/HR14/HR15 可读取:
  - FinalAssessmentResult
  - AnnualResultHistory
  - TermResult
  - VerifiedPerformanceEvidence refs
  
但不能:
  - 修改 HR12
  - 因"准备申报职称"自动提高评分
  - 将职称/岗位聘任结果覆盖历史考核
```

### HR12 → HR16 离退引用

```text
HR16 可引用 HR12 结果作为事实依据之一
但必须同时满足: HR07 合同关系 + 正式决定 + 适用制度 + 人事程序
禁止: Annual UNQUALIFIED → disable account
```

---

## 5. 未就绪 Provider 契约

```python
# HR10 未就绪时的 Provider 契约
{
    "provider": "DevelopmentProvider",
    "status": "UNAVAILABLE",
    "reason": "HR10 not yet integrated; contract placeholder for S6",
    "impact": ["professional_development_indicator", "enterprise_practice_evidence"],
    "mitigation": "evidence_requirement.fallback_mode = FAIL_CLOSED → reviewer_verification",
    "target_readiness": "HR10 S6"
}

# 教务/科研未就绪时的 Provider 契约
{
    "provider": "AcademicProvider",
    "status": "UNAVAILABLE",
    "reason": "External academic system not yet integrated",
    "impact": ["teaching_load", "teaching_quality", "curriculum_work"],
    "mitigation": "manual_review with self_reported evidence + reviewer_verification",
    "target_readiness": "TBD"
}
```

---

## 6. Provider Contract Template

每个 Provider 契约包含：

```text
owner_domain:   "hr_assessment"
consumer:       "assessment_evidence_service"
tenant:         UUID
ids:            [staff_ids]
as_of:          ISO datetime
source_version: "v1"
freshness:      {maxStaleSeconds: 3600, hardExpireSeconds: 86400}
timeout:        5000ms
sensitivity:    INTERNAL / RESTRICTED / HIGHLY_RESTRICTED
authorization:  service_principal
errors:         [UNAVAILABLE, STALE, PARTIAL, CONFLICT]
cache_policy:   NO_CACHE (for FINALIZE) / TTL_300 (for read)
```

---

## 7. Handoff 幂等协议

```text
HR12 emits: TermAssessmentFinalized(eventId, result_id, result_version, ...)

HR07 consumer:
  1. Check consumer_event_id dedup table → already processed? → ACK
  2. Query HR12 GET /api/v1/hr/assessments/results/{result_id} → verify version
  3. Create RenewalCase (only if not exists)
  4. Write ConsumerAck (consumer_event_id, result_id, version, renewal_case_ref)
  5. Return ACK

HR12 records: delivery_status = HR07_RECEIVED
Retry: exponential backoff; max 10 attempts
Duplicate: same outcome, no duplicate renewal case
```

---

## 8. Result Revision 跨域影响

```text
Result V1 FINALIZED
  → HR07 consumed V1 for renewal
  → HR13 consumed V1 for title review

Result V2 (Revision) FINALIZED
  → HR12 emits: AssessmentResultRevised
  → HR12 emits: DownstreamAssessmentReviewRequired(consumer=HR07, result_id, V2)
  → HR12 emits: DownstreamAssessmentReviewRequired(consumer=HR13, result_id, V2)

HR07 receives → creates RenewalDecisionReviewRequired
HR13 receives → creates TitleReviewCheck

HR12 不能静默回写: 已签合同 / 已完成职称 / 已发工资 / 已完成岗位聘任
```

---

## 9. 集成就绪检查清单（Production Review v1.1）

| 检查项 | 状态 | 说明 |
|---|---|---|
| HR03 PersonProvider | ✅ `hr_staff/` 120 files | Staff identity + as-of assignment |
| HR07 AgreementProvider | ✅ `hr_contracts/` 87 files | Contract term + duty snapshot |
| HR09 QualificationProvider | ✅ `hr_qualification/` 37 files | Reference data |
| HR10 DevelopmentProvider | ❌ `hr_development/` 不存在 | 待建 — Provider 契约占位（返回 UNAVAILABLE） |
| HR11 TimeSummaryProvider | ✅ `hr_time/` 57 files | Frozen period close |
| AcademicProvider | ⚠️ 外部系统 | 教务系统未接入 |
| ResearchProvider | ⚠️ 外部系统 | 科研系统未接入 |
| EthicsFactProvider | ⚠️ 外部系统 | 正式师德事实源未接入 |
| HR13/14/15/16/18 Consumer | TBD | 按各自施工状态 |
| Outbox 基础设施 | TBD | 共用 Outbox 平台 |
| PMS REST API (horilla_api) | ✅ 存在 — `horilla_api/api_views/pms/views.py` | 需 S10 新建 HR12 API 层后 freeze |
| PMS Dashboard API (11 endpoints) | ✅ 存在 — 5 个 ranking 端点需 DEPRECATE | `performers/` `at-risk/` `kpi/` `okr-overview/` `fb-completion/` |
| BonusPoint 信号链 | ⚠️ employee→pms→payroll 活跃 | S10 FREEZE 后切断 |

---

## 10. HR10 依赖缓解策略（Provider 契约占位）

在 HR10 S6 集成完成前：

```text
DevelopmentProvider:
  status: UNAVAILABLE
  年度考核中培训/发展指标: 标记 UNAVAILABLE
  处理方式: 按 Policy 决定
    - 对于不要求培训指标的岗位: NOT_APPLICABLE（不参与计算）
    - 对于要求培训指标的岗位: REVIEW_REQUIRED（需人工提供替代证据）
    - 禁止: 默认 0 分 / 默认满分 / self-report 自动充填
```

同样，HR11 未月结时的考勤指标：
```text
TimeSummaryProvider:
  status: SOURCE_NOT_FROZEN
  考勤指标: 标记 SOURCE_NOT_FROZEN
  处理方式:
    - 如果是 FINALIZE 前检查: blocker → 等待月结完成
    - 如果是平时查看: stale indicator, display "待月结"
```
