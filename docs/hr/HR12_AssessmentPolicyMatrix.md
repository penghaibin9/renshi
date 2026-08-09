# HR12_AssessmentPolicyMatrix —— 考核制度与指标体系矩阵

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §39-60 (PolicyPack/Version 完整模型)

---

## 1. PolicyPack 结构

| 字段 | 类型 | 说明 | 约束 |
|---|---|---|---|
| `id` | UUID PK | — | — |
| `tenant_id` | UUID NOT NULL | 学校租户 | FK → tenant |
| `code` | VARCHAR(50) | 政策编码 | tenant 唯一 |
| `name` | VARCHAR(200) | 政策名称 | NOT NULL |
| `assessment_domain` | VARCHAR(50) | ANNUAL/TERM/ROUTINE/SPECIAL/ETHICS | NOT NULL |
| `owner_org_id` | UUID | 归属组织 | FK → organization |
| `status` | VARCHAR(20) | DRAFT/PUBLISHED/RETIRED | NOT NULL |
| `current_published_version_id` | UUID | 当前发布版本 | FK → PolicyVersion |
| `source_policy_refs` | JSON | 来源制度引用 | nullable |
| `created_at` | TIMESTAMP | — | auto |

**学校示例**：一所学校可有多个 PolicyPack（如：专任教师、辅导员、管理岗、实验技术、工勤）。

---

## 2. PolicyVersion 结构

| 字段 | 类型 | 说明 | 约束 |
|---|---|---|---|
| `id` | UUID PK | — | — |
| `policy_pack_id` | UUID FK | — | NOT NULL |
| `version_no` | INT | 版本号 | 递增 |
| `effective_from` | DATE | 生效日期 | NOT NULL |
| `effective_to` | DATE | 失效日期 | nullable (NULL=无固定结束) |
| `assessment_types` | JSON | 适用考核类型 [ANNUAL, TERM, ...] | NOT NULL |
| `eligibility_rule_json` | JSON | 适用对象规则 | NOT NULL |
| `cycle_rule_json` | JSON | 周期规则（自然年/学年） | NOT NULL |
| `rating_scale_version_id` | UUID FK | 评分尺度版本 | NOT NULL |
| `indicator_set_version_id` | UUID FK | 指标集版本 | NOT NULL |
| `workflow_version_id` | UUID FK | 工作流版本 | NOT NULL |
| `excellent_quota_policy_id` | UUID FK | 优秀比例政策 | nullable |
| `ethics_gate_policy_id` | UUID FK | 师德门槛政策 | nullable |
| `evidence_policy_id` | UUID FK | 证据政策 | nullable |
| `result_rule_version_id` | UUID FK | 结果规则版本 | nullable |
| `content_hash` | VARCHAR(64) | 内容哈希 | immutable after PUBLISHED |
| `status` | VARCHAR(20) | DRAFT/PUBLISHED/RETIRED | immutable after PUBLISHED |

**状态机**：`DRAFT → [PUBLISHED] → [RETIRED]`。PUBLISHED 后所有字段冻结。

---

## 3. AssessmentType Catalog（内置稳定枚举）

```text
ANNUAL    — 年度考核
TERM      — 聘期考核
ROUTINE   — 平时考核
SPECIAL   — 专项考核
ETHICS    — 师德评价
MULTI_RATER — 360/多主体评价
```

学校通过 `AssessmentSubType` 扩展，不把"教师年度考核2026版"直接作为 enum type。

---

## 4. ClassificationProfileVersion

| 分类 | 适用岗位 | 核心指标维度 |
|---|---|---|
| `TEACHING_FOCUSED` | 教学为主型 | TEACHING_LOAD/QUALITY/CURRICULUM_DEVELOPMENT |
| `TEACHING_RESEARCH` | 教学科研型 | TEACHING + RESEARCH + SOCIAL_SERVICE |
| `RESEARCH_FOCUSED` | 科研为主型 | RESEARCH_CONTRIBUTION/PROJECT/PATENT/TRANSFORMATION |
| `STUDENT_AFFAIRS` | 辅导员/学生工作 | STUDENT_GUIDANCE/AFFAIRS_MANAGEMENT/SPECIAL_TASKS |
| `LAB_TECHNICAL` | 实验技术 | LAB_MANAGEMENT/TECHNICAL_SUPPORT/SAFETY |
| `ADMINISTRATION` | 管理岗 | MANAGEMENT_EFFECTIVENESS/SERVICE_QUALITY |
| `PROFESSIONAL_TECHNICAL_OTHER` | 其他专技 | PROFESSIONAL_OUTPUT/TECHNICAL_SERVICE |
| `WORKER_SKILL` | 工勤技能 | WORK_QUALITY/SAFETY_COMPLIANCE |
| `EXTERNAL` | 外聘/兼职 | ENGAGEMENT_OUTPUT/SERVICE_DELIVERY |
| `OTHER_POLICY` | 其他制度规定 | 按制度配置 |

---

## 5. RatingScaleVersion

| 尺度类型 | 示例 | HR12 支持 |
|---|---|---|
| `SCORE` | 0-100 分 | ✅ min/max/rounding |
| `LEVEL` | 1-5 级 | ✅ levels[] / display_labels |
| `DESCRIPTIVE` | 优秀/合格/基本合格/不合格 | ✅ levels[] + description |
| `NO_NUMERIC_TOTAL` | 定性评价，不产生总分 | ✅ scale_type=DESCRIPTIVE + no normalization |

最终年度/聘期档次是另一个独立对象（`FinalAssessmentResult.grade_code`），不绑定 RatingScale。

---

## 6. IndicatorDimension 维度

| 维度 | 代码 | 说明 |
|---|---|---|
| 德 | `MORALITY` | 政治表现、师德师风、职业道德 |
| 能 | `CAPABILITY` | 业务能力、专业水平、管理能力 |
| 勤 | `DILIGENCE` | 工作态度、出勤情况、敬业精神 |
| 绩 | `PERFORMANCE` | 完成任务、工作质量、实际贡献 |
| 廉 | `INTEGRITY` | 廉洁自律、遵纪守法 |

---

## 7. IndicatorSource Provider 矩阵

| 指标 | Source Provider | 量化/人工 | 信任级别要求 |
|---|---|---|---|
| `TEACHING_LOAD` | AcademicProvider | 量化 | AUTHORITATIVE_VERIFIED |
| `TEACHING_QUALITY` | AcademicProvider + Reviewer | 量化+人工 | SYSTEM_VERIFIED |
| `CURRICULUM_DEVELOPMENT` | AcademicProvider + Self | 质化为主 | REVIEWER_VERIFIED |
| `RESEARCH_CONTRIBUTION` | ResearchProvider | 量化 | AUTHORITATIVE_VERIFIED |
| `STUDENT_GUIDANCE` | Academic/StudentAffairs | 量化+人工 | SYSTEM_VERIFIED |
| `SOCIAL_SERVICE` | Self + Reviewer | 质化 | REVIEWER_VERIFIED |
| `MANAGEMENT_EFFECTIVENESS` | MultiRater | 质化 | SYSTEM_VERIFIED |
| `PROFESSIONAL_DEVELOPMENT` | HR10 (VERIFIED only) | 量化 | HR10_VERIFIED |
| `ATTENDANCE_SUMMARY` | HR11 (Frozen only) | 量化 | SYSTEM_VERIFIED |
| `ETHICS_GATE` | EthicsFactProvider | Gate | AUTHORITATIVE_VERIFIED |

---

## 8. EvidenceRequirement 矩阵

| 指标 | 接受的 Provider 类型 | 最低信任级别 | 必需时期 | 需要文件 | 需要人工核实 |
|---|---|---|---|---|---|
| TEACHING_LOAD | AcademicProvider | AUTHORITATIVE_VERIFIED | WITHIN_CYCLE | NO | NO |
| TEACHING_QUALITY | AcademicProvider + MultiRater | SYSTEM_VERIFIED | WITHIN_CYCLE | NO | YES |
| RESEARCH_CONTRIBUTION | ResearchProvider | AUTHORITATIVE_VERIFIED | WITHIN_TERM | NO | NO |
| PROFESSIONAL_DEVELOPMENT | DevelopmentProvider | HR10_VERIFIED | WITHIN_CYCLE | YES | YES |
| ETHICS_GATE | EthicsFactProvider | AUTHORITATIVE_VERIFIED | AS_OF_DATE | YES | YES |
| MANAGEMENT_EFFECTIVENESS | MultiRater | SYSTEM_VERIFIED | WITHIN_CYCLE | NO | YES |

---

## 9. ResultRule 核心映射

| 输入 | 输出 | 规则类型 |
|---|---|---|
| calculated_score + gate | grade_recommendation | `SCORE_TO_GRADE_MAPPING` |
| ethics_gate BLOCKED | final_grade override | `HARD_GATE_EFFECT` |
| proposed_excellent > quota | OVER_QUOTA_BLOCKER | `QUOTA_RULE` |
| new_joiner / long_leave / ... | NO_RATING | `SPECIAL_POPULATION_RULE` |
| term goal completion | QUALIFIED/UNQUALIFIED | `TERM_QUALIFICATION_CONDITION` |
| collective override | final_grade with reason | `COLLECTIVE_OVERRIDE_PERMISSION` |

---

## 10. Workflow Step 完整清单

```text
GOAL_CONFIRM        → 目标确认
SELF_SUMMARY        → 个人总结/述职
MANAGER_REVIEW      → 主管评价
ORG_REVIEW          → 组织评议
MULTI_RATER         → 多主体评价
EVIDENCE_VERIFY     → 证据核实
CALIBRATION         → 校准
COLLECTIVE_DELIBERATION → 集体审定
PUBLICITY           → 公示
RESULT_NOTICE       → 结果告知
ACKNOWLEDGEMENT     → 本人意见确认
OBJECTION_WINDOW    → 异议期
ARCHIVE             → 归档
```

不同考核类型可裁剪步骤。FINALIZE 前强制步骤冻结在 CycleSnapshot。
