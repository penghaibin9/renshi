# HR09_DoubleTeacherNationalBaselineMap —— 国家基本标准映射表

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：教育部教师厅〔2022〕2号 + 总册 §5/§41-45

---

## 1. 国家标准权威来源

- **文件名**：《职业教育"双师型"教师基本标准（试行）》
- **文号**：教师厅〔2022〕2号
- **发布日**：2022年10月25日
- **执行日**：自发布之日起
- **最新状态**：2026年8月确认仍为现行标准（无 2025/2026 修订版）
- **层级**：初/中/高级 三个层次
- **适用范围**：职业学校专业课教师（含实习指导教师）；公共课教师、校外兼职教师等可参照
- **复核周期**：不超过5年一轮

---

## 2. 通用基线条件（所有层级）

| 维度码 | 中文 | 评价方式 | 证据来源 | Hard/Soft |
|---|---|---|---|---|
| ETHICS_AND_CONDUCT | 师德师风 | 人工评议（严禁 AI 判断） | HR12_ASSESSMENT / 师德考核 | HARD |
| TEACHING_ABILITY | 理论与实践教学能力 | 举证+评议 | ACADEMIC_TEACHING / 教学任务/评价 | HARD |
| ENTERPRISE_EXPERIENCE | 企业相关工作经历或实践 | 可量化 | HR10_ENTERPRISE_PRACTICE / HR03_WORK_HISTORY | HARD |
| INDUSTRY_PRACTICE | 深入企业/生产服务一线岗位实践 | 可量化 | HR10_ENTERPRISE_PRACTICE | HARD |
| INDUSTRY_AWARENESS | 行业认知与产教融合意识 | 举证+评议 | HR10 + 专业建设成果 | SOFT |

---

## 3. 初级（DOUBLE_TEACHER_JUNIOR）特殊条件

| 维度码 | 要求 | 证据来源 | 规则类型 |
|---|---|---|---|
| PROFESSIONAL_KNOWLEDGE | 掌握专业知识技能 | HR03_EDUCATION + 教学经历 | LEVEL_AT_LEAST |
| TEACHING_PRACTICE | 具备理论与实践教学能力 | ACADEMIC_TEACHING | BOOLEAN_FACT |
| TEACHING_RESEARCH | 参与教育教学研究 | ACADEMIC_TEACHING + 教改项目 | COUNT(min=1) |
| ENTERPRISE_OR_PRACTICE | 企业工作经历或深入一线实践 | HR03_WORK_HISTORY / HR10 | ONE_OF |
| VOCATIONAL_CERTIFICATE_OR_EQUIV | 职业资格/技能等级/非教师职称或等效能力 | HR09_CREDENTIAL + EQUIVALENCY_ROUTE | ANY_OF |
| REPRESENTATIVE_OUTPUT | 代表性成果 | MANUAL + ACADEMIC | COUNT(min=1) |

---

## 4. 中级（DOUBLE_TEACHER_INTERMEDIATE）特殊条件

| 维度码 | 要求 | 强化级别 | 证据来源 | 规则类型 |
|---|---|---|---|---|
| TEACHING_PERFORMANCE | 教学业绩良好 | 比初级更强 | ACADEMIC_TEACHING + HR12_ASSESSMENT | LEVEL_AT_LEAST |
| TEACHING_FEATURE | 具有教学特色 | — | ACADEMIC_TEACHING | MANUAL_COMMITTEE |
| RESEARCH_AND_DEVELOPMENT | 较强研究/专业建设能力 | — | ACADEMIC_COURSE_DEVELOPMENT | COUNT(min=2) |
| RICH_ENTERPRISE_PRACTICE | 较丰富的企业实践 | 比初级多 | HR10_ENTERPRISE_PRACTICE | DURATION(min=X days) |
| COOPERATION_OUTPUT | 较突出校企合作成果 | — | MANUAL + ACADEMIC | COUNT(min=1) |
| INTERMEDIATE_SKILL_OR_EQUIV | 中级及以上技能/职业/非教师职称或等效 | 比初级高 | HR09_CREDENTIAL + EQUIVALENCY_ROUTE | LEVEL_AT_LEAST(INTERMEDIATE) |
| HIGHER_OUTPUT | 较高水平成果 | — | MANUAL + ACADEMIC | COUNT(min=1) |
| COMPETITION_OR_AWARD | 竞赛/教学/科技成果或指导学生获奖 | — | ACADEMIC_COMPETITION | COUNT(min=1) |

---

## 5. 高级（DOUBLE_TEACHER_SENIOR）特殊条件

| 维度码 | 要求 | 强化级别 | 证据来源 | 规则类型 |
|---|---|---|---|---|
| DEEP_THEORY | 深度专业理论 | 最高级 | HR03_EDUCATION + 教学经历 | LEVEL_AT_LEAST |
| EXQUISITE_SKILL | 精湛技能 | — | ACADEMIC_TEACHING + 技能竞赛 | MANUAL_COMMITTEE |
| TEACHING_DEMONSTRATION | 教学示范 | — | ACADEMIC_TEACHING | BOOLEAN_FACT |
| TEAM_KEY_ROLE | 团队关键作用 | — | TEAM_LEADERSHIP | ROLE_REQUIRED(LEADER/KEY) |
| MAJOR_PROJECT_LEAD | 主持重要项目 | — | ACADEMIC_COURSE_DEVELOPMENT | PROJECT_ROLE(LEAD) |
| REFORM_OUTPUT | 专业/课程/实践教学改革显著成果 | — | ACADEMIC + 成果证明 | COUNT(min=2) |
| EXTENSIVE_ENTERPRISE_PRACTICE | 丰富企业实践 | 比中级多 | HR10_ENTERPRISE_PRACTICE | DURATION(min=2Y) |
| TECHNICAL_INNOVATION | 突出技术革新/成果转化 | — | MANUAL + RESULT_TRANSFORMATION | COUNT(min=1) |
| SENIOR_SKILL_OR_EQUIV | 高级技能/职业/非教师职称或等效 | 最高级别 | HR09_CREDENTIAL + EQUIVALENCY_ROUTE | LEVEL_AT_LEAST(SENIOR) |
| HIGH_LEVEL_COMPETITION | 高水平竞赛/教学/科技成果 | — | ACADEMIC_COMPETITION | AWARD_LEVEL(min=PROVINCIAL) |
| MENTOR_TEACHERS | 指导培养教师 | — | TEACHER_DEVELOPMENT_CONTRIBUTION | COUNT(min=1) |
| INDUSTRY_IMPACT | 行业影响力 | — | MANUAL_COMMITTEE | MANUAL_COMMITTEE |

---

## 6. Rule Pack 四层结构初始化

```text
NATIONAL_BASELINE (jurisdiction_code=CN, jurisdiction_level=NATIONAL)
  │ 教师厅〔2022〕2号 → 通用 + 初/中/高级 规则集
  │
  ├── PROVINCIAL (jurisdiction_code=XX, parent=national)
  │   │ 目标省认定标准 → 不低于国家 + 本地化补充
  │   │
  │   └── SCHOOL (jurisdiction_code=SCH-001, parent=provincial)
  │       │ 学校实施细则 → 不低于省级 + 破格/等效路线
  │       │
  │       └── BATCH_OVERRIDE (batch=2026-Autumn)
  │           本次认定批次 → 冻结学校规则 + 批次特殊政策
```

---

## 7. 等效路线（EQUIVALENCY_ROUTE）

标准中"或具有相应能力水平"的处置：

| 路线 | 触发条件 | 审批流程 | 证据要求 |
|---|---|---|---|
| EQUIV-WORK | 工作年限 ≥ X 年 + 岗位匹配 | 专家评议 + 委员会 | 工作经历 + 业绩证明 |
| EQUIV-ACHIEVE | 突出贡献/重大成果 | 专家评议 + 委员会 + 学校核准 | 成果证明 + 第三方评价 |
| EQUIV-CERT | 国际等效认证 | 专家评议 | 认证证书 + 翻译件 |
| EQUIV-TEACH | 教学卓越 | 专家评议 + 委员会 | 教学成果 + 学生评价 + 同行评议 |

禁止：`if seniority > 10: equivalent = True`（无证据、无人工评议的代码自动判定）。

---

## 8. 破格条件（ExceptionRoute）

| 路线码 | 说明 | 最小约束 |
|---|---|---|
| EXC-NATL-TALENT | 国家/省级人才计划入选者 | committee_required=True |
| EXC-AWARD | 国家级教学/科技奖励获得者 | committee_required=True；specific_awards JSON |
| EXC-INDUSTRY | 行业公认技术专家 | committee_required=True；external_reference 2+ |
| EXC-SKILL | 世界/国家级技能大赛获奖 | committee_required=True；level ≥ NATIONAL |

---

**文件状态：S0_BASELINE 冻结。**
