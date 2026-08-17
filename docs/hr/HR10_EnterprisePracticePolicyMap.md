# HR10_EnterprisePracticePolicyMap — 企业实践政策映射矩阵

> 国家依据：教育部等七部门《职业学校教师企业实践规定》（2016）、教育部办公厅《全国职业教育教师企业实践基地管理办法（试行）》（2023）、2025-12《职业教育教师企业实践项目开发与实施指南》
> 业务事实源：总册 §3–6 + §69–108
> 版本：`S0_V1`
> 日期：2026-08-09

---

## 0. 核心原则

**政策不是 Python 硬编码**。
HR10 把制度能力抽象为 Policy Template → Tenant Rule Pack → Effective-dated Rule Version → Project snapshot → Historical fact immutable 五层。

---

## 1. 国家制度能力清单

| # | 制度需求 | 总册能力 | 施工模型 |
|---|---|---|---|
| P-01 | 专业课教师/实习指导教师应每 5 年累计不少于 6 个月到企业或生产服务一线实践 | HrDevelopmentComplianceRule (population + window + minimum) | S8 |
| P-02 | 公共基础课教师应定期到企业考察、调研和学习 | HrDevelopmentComplianceRule (different minimum/population) | S8 |
| P-03 | 新任教师入职前应安排企业实践 | HrDevelopmentNeed + prerequisite check (READY_TO_START gate) | S2/S6 |
| P-04 | 企业实践的形式包括到企业考察观摩、接受企业组织技能培训、在企业的生产或服务岗位上操作演练、参与企业的产品开发和技术改造等 | HrPracticeActivity (13 types: OBSERVATION/POSITION_WORK/TECHNICAL_TRAINING/R_AND_D/TECHNICAL_IMPROVEMENT) | S7 |
| P-05 | 企业实践应有明确的实践活动记录、工作成果和评估意见 | HrPracticeEvidence + HrEnterpriseMentorFeedback + HrPracticeSchoolEvaluation + HrEnterprisePracticeEvaluation | S7 |
| P-06 | 学校应与企业签订协议，明确各方权利义务与责任 | HrEnterprisePracticePlan (approved_by_enterprise + approved_by_school) + AgreementProvider (HR07 引用) | S6/S9 |
| P-07 | 强化企业实践基地建设 | HrDevelopmentProviderOrganization (practice_base_level + official_reference + specialty_scope) | S3 |
| P-08 | 企业实践基地应提供真实岗位/场景 | HrPracticePositionScene (real_position_name + production_or_service_scene + core_tasks) | S6 |
| P-09 | 企业实践应转化为教学成果 | HrDevelopmentOutput (30+ types + teaching_transformation mapping) | S7 |
| P-10 | 保障教师在实践期间的法律权利、安全和费用 | Prerequisite gate (safety/agreement/confidentiality/IP) + 费用映射到 HR15 | S6/S9 |

---

## 2. 2025 企业实践指南核心要素对照

| 指南要求 | HR10 模型 | 施工阶段 |
|---|---|---|
| 实践项目化（不是简单活动） | HrEnterprisePracticeProject + ProjectVersion | S6 |
| 真实岗位/场景 | HrPracticePositionScene (scene_code + real_position_name + production_or_service_scene) | S6 |
| 模块化内容 | ProjectVersion.module_task_json | S6 |
| 实施计划 | HrEnterprisePracticePlan (task_snapshot + schedule_json) | S6 |
| 多元评价 | Mentor Feedback + School Evaluation + Final Evaluation (rubric + composite) | S7 |
| 成果转化 | HrDevelopmentOutput → Academic/Research Provider | S7/S9 |
| 过程证据 | HrEnterprisePracticeActivity + AttendanceFact + Evidence | S7 |
| 导师配备 | HrEnterprisePracticeMentor (enterprise side) | S6 |

---

## 3. 教师分类 × 企业实践规则模板

系统内置可配置规则包（非硬编码永久常量）：

```text
Rule Pack: VOC_TEACHER_ENTERPRISE_PRACTICE
├─ Population 1: PROFESSIONAL_COURSE_TEACHER
│  ├─ window: ROLLING_5_YEAR
│  ├─ minimum_duration: tenant_policy_value (默认 6 months ≈ 180 days)
│  ├─ eligible_activity_types: ENTERPRISE_PRACTICE, PRACTICE_BASE_TRAINING, SHADOWING, POSITION_WORK
│  ├─ verification_required: true
│  └─ minimum_trust_level: PROVIDER_VERIFIED
├─ Population 2: PRACTICE_INSTRUCTOR
│  ├─ window: ROLLING_5_YEAR
│  ├─ minimum_duration: tenant_policy_value (默认 6 months)
│  └─ (同上)
├─ Population 3: PUBLIC_BASIC_COURSE_TEACHER
│  ├─ window: tenant_policy (默认 ANNUAL)
│  ├─ minimum_duration: tenant_policy_value (默认较短，侧重考察/调研)
│  ├─ eligible_activity_types: SCHOOL_VISIT, RESEARCH_VISIT, INDUSTRY_TECH_TRAINING, ENTERPRISE_VISIT
│  └─ verification_required: true
└─ Population 4: NEW_TEACHER (入职不满1年)
   ├─ prerequisite: ENTERPRISE_PRACTICE_BEFORE_ONBOARDING
   └─ minimum_duration: tenant_policy_value
```

**Tenant 可覆盖**：
- 最小月数/天数
- 是否允许跨多企业累计
- 是否区分连续 vs 累计
- 是否允许线上/混合形式计入
- 起步时间、完成 deadline

---

## 4. 政策计算模式

| 计算方式 | 示例 | 实现 |
|---|---|---|
| `ROLLING_5_YEAR` | 从今天往回 5 年累计 | ComplianceRule.window = ROLLING_5_YEAR; as-of evaluation |
| `FIXED_ACADEMIC_CYCLE` | 2023-2028 一个完整周期 | ComplianceRule.window = FIXED_CYCLE; start/end dates |
| `CALENDAR_YEAR` | 每年至少 X 天 | ComplianceRule.window = CALENDAR_YEAR |
| `BEFORE_ONBOARDING` | 入职前完成 | Prerequisite check in HrEnterprisePracticePlan |
| `BEFORE_PROMOTION` | 晋升前满足 | Linked to HR14 appointment eligibility (HR14 consumer) |

---

## 5. 有效实践时长计算规则

```text
Raw Activity Segments
│
├── Source 1: Verified EnterprisePracticeActivity (status=VERIFIED)
│   └── excludes: OBSERVATION (less weight), MEETING (optional)
├── Source 2: Verified EnterprisePracticeAttendanceFact (status=VERIFIED)
│   ├── trust_level >= policy_required
│   └── source: ENTERPRISE_SYSTEM > MENTOR > SCHOOL_CHECK > SELF_WITH_EVIDENCE > IMPORT
├── Source 3: Mentor Feedback → confirmed duration
│
▼
Deduplication
│   └── same time window + overlapping segments → take max trust, min overlap
│
▼
Eligible Duration (raw hours → days via policy conversion factor)
│
▼
Compliance Window → check minimum
│
▼
HrDevelopmentMetricLedger: raw_hours + raw_days + normalized_days + conversion_rule_version
```

---

## 6. 政策不可变保障

- ComplianceRule 发布后 PUBLISHED→immutable（类 RuleVersion）
- 新 as-of evaluation 使用规则有效日期的版本
- 已完成历史评估不受新规则影响
- 变更创建 NEW version 并标记 supracession
- 旧评估引用 frozen rule_version_id

---

## 7. 与总账边界

HR10 不是政策解读权威。以下不进入 HR10：
- 双师认定为"初级/中级/高级"的判定标准 → HR09
- 教师企业实践与职称评审挂钩 → HR13 消费
- 企业实践与岗位聘任竞聘条件 → HR14 消费
- 企业实践补贴/薪酬调整 → HR15 根据实践事实重新核定

---

**文档状态：S0_V1 — 政策映射完成。10 项国家制度能力 + 2025 指南 8 项要素 + 4 类教师规则模板 + 5 种计算模式。**
