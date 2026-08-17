# HR12_JobClassificationAssessmentMatrix —— 岗位分类与考核评价矩阵

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §11 (高校教师分类评价) + §48 (ClassificationProfile)

---

## 1. 岗位分类 × 考核方式矩阵

| 岗位分类 | 年度考核 | 聘期考核 | 平时考核 | 师德 | 360评价 | 专项 |
|---|---|---|---|---|---|---|
| **TEACHING_FOCUSED** (教学为主型) | ✅ 教学指标为主 | ✅ 聘期目标 | ✅ Check-in | ✅ Gate | 可选 | 可选 |
| **TEACHING_RESEARCH** (教学科研型) | ✅ 教学+科研 | ✅ 聘期目标 | ✅ Check-in | ✅ Gate | 可选 | 可选 |
| **RESEARCH_FOCUSED** (科研为主型) | ✅ 科研指标为主 | ✅ 聘期目标 | ✅ Check-in | ✅ Gate | 可选 | 可选 |
| **STUDENT_AFFAIRS** (辅导员) | ✅ 学生工作指标 | ✅ 聘期目标 | ✅ Check-in | ✅ Gate | 可选 | 专项任务 |
| **LAB_TECHNICAL** (实验技术) | ✅ 实验技术指标 | ✅ 聘期目标 | ✅ Check-in | ✅ Gate | — | 可选 |
| **ADMINISTRATION** (管理岗) | ✅ 管理服务指标 | ✅ 聘期目标 | ✅ Check-in | ✅ Gate | ✅ 推荐 | 可选 |
| **PROFESSIONAL_TECHNICAL_OTHER** (其他专技) | ✅ 专技指标 | ✅ 聘期目标 | ✅ Check-in | ✅ Gate | 可选 | 可选 |
| **WORKER_SKILL** (工勤技能) | ✅ 工作质量指标 | ✅ 聘期目标 | — | ✅ Gate | — | — |
| **EXTERNAL** (外聘/兼职) | ✅ 按约考核 | — | — | ✅ Gate | — | — |
| **OTHER_POLICY** (其他制度) | ✅ | ✅ | 可选 | ✅ Gate | 可选 | 可选 |

---

## 2. 岗位分类 × 指标维度权重参考

| 岗位分类 | 德 | 能 | 勤 | 绩 | 廉 | 教学 | 科研 | 服务 | 发展 |
|---|---|---|---|---|---|---|---|---|---|
| TEACHING_FOCUSED | Gate | 15% | 10% | 75% | Gate | 50% | 10% | 10% | 5% |
| TEACHING_RESEARCH | Gate | 15% | 10% | 75% | Gate | 35% | 25% | 10% | 5% |
| RESEARCH_FOCUSED | Gate | 15% | 10% | 75% | Gate | 15% | 45% | 10% | 5% |
| STUDENT_AFFAIRS | Gate | 15% | 10% | 75% | Gate | — | — | 70% | 5% |
| LAB_TECHNICAL | Gate | 15% | 10% | 75% | Gate | — | — | 70% | 5% |
| ADMINISTRATION | Gate | 15% | 10% | 75% | Gate | — | — | 70% | 5% |

> ⚠️ 权重为参考值，实际由学校 PolicyVersion 配置，不可代码写死。

---

## 3. 岗位分类 × Reviewer 结构

| 岗位分类 | SELF | DIRECT_MANAGER | ORG_HEAD | PEER | SUBORDINATE | SERVICE_RECIPIENT | EXPERT | HR_REVIEWER | COLLECTIVE_BODY |
|---|---|---|---|---|---|---|---|---|---|
| TEACHING_FOCUSED | ✅ | ✅ | ✅ | 可选 | — | ✅ 学生 | 可选 | ✅ | ✅ |
| TEACHING_RESEARCH | ✅ | ✅ | ✅ | 可选 | — | ✅ 学生 | ✅ 同行 | ✅ | ✅ |
| RESEARCH_FOCUSED | ✅ | ✅ | ✅ | ✅ 同行 | — | — | ✅ 同行 | ✅ | ✅ |
| STUDENT_AFFAIRS | ✅ | ✅ | ✅ | ✅ | — | ✅ 学生 | — | ✅ | ✅ |
| LAB_TECHNICAL | ✅ | ✅ | ✅ | 可选 | — | ✅ 教师 | — | ✅ | ✅ |
| ADMINISTRATION | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| PROFESSIONAL_TECHNICAL_OTHER | ✅ | ✅ | ✅ | 可选 | 可选 | ✅ | 可选 | ✅ | ✅ |
| WORKER_SKILL | ✅ | ✅ | ✅ | — | — | ✅ | — | ✅ | ✅ |
| EXTERNAL | ✅ | ✅ | ✅ | — | — | ✅ 合作者 | — | — | 可选 |

---

## 4. 岗位分类 × Evidence Source

| 证据类型 | TEACHING | TR | RESEARCH | STUDENT | LAB | ADMIN | OTHER_TECH | WORKER | EXTERNAL |
|---|---|---|---|---|---|---|---|---|---|
| 教学工作量 | ✅ Auth | ✅ Auth | — | — | — | — | — | — | — |
| 教学评价 | ✅ Auth | ✅ Auth | — | — | — | — | — | — | — |
| 课程建设 | ✅ Self+Review | ✅ Self+Review | — | — | — | — | — | — | — |
| 科研项目 | — | ✅ Auth | ✅ Auth | — | — | — | 可选 | — | — |
| 论文/成果 | — | ✅ Auth | ✅ Auth | — | — | — | 可选 | — | — |
| 学生工作 | — | — | — | ✅ Auth | — | — | — | — | — |
| 实验管理 | — | — | — | — | ✅ Self+Review | — | — | — | — |
| 管理服务 | — | — | — | — | — | ✅ MultiRater | ✅ MultiRater | — | — |
| 培训/发展 | ✅ HR10 | ✅ HR10 | ✅ HR10 | ✅ HR10 | ✅ HR10 | ✅ HR10 | ✅ HR10 | 可选 | — |
| 考勤 | ✅ HR11 | ✅ HR11 | ✅ HR11 | ✅ HR11 | ✅ HR11 | ✅ HR11 | ✅ HR11 | ✅ HR11 | — |

---

## 5. 岗位分类 × 优秀比例策略

| 岗位分类 | 默认优秀比例 | 是否可倾斜 | 倾斜条件 |
|---|---|---|---|
| TEACHING_FOCUSED | ≤20% of eligible | 是 (学校政策) | 突出教学实绩 |
| TEACHING_RESEARCH | ≤20% | 是 | 突出综合表现 |
| RESEARCH_FOCUSED | ≤20% | 是 | 重大科研突破 |
| STUDENT_AFFAIRS | ≤20% | 是 | 突出学生工作成效 |
| LAB_TECHNICAL | ≤20% | 是 | 技术服务突出 |
| ADMINISTRATION | ≤20% | 是 | 管理创新/服务成效 |
| PROFESSIONAL_TECHNICAL_OTHER | ≤20% | 是 | 按制度 |
| WORKER_SKILL | ≤20% | 是 | 按制度 |
| EXTERNAL | — | — | 不适用 |
| OTHER_POLICY | ≤20% | 是 | 按制度 |

> ⚠️ 比例策略由 PolicyVersion.ExcellentQuotaPolicy 配置，不可代码写死 `top 20% by score`。

---

## 6. 岗位分类 × Special Population 处理

| 特殊群体 | TEACHING | TR | RESEARCH | STUDENT | LAB | ADMIN | OTHER | WORKER | EXTERNAL |
|---|---|---|---|---|---|---|---|---|---|
| NEW_JOINER (<6月) | NO_RATING | NO_RATING | NO_RATING | NO_RATING | NO_RATING | NO_RATING | NO_RATING | NO_RATING | — |
| TRANSFERRED (中途调岗) | KEEP_ORIGINAL or SPLIT | 同左 | 同左 | 同左 | 同左 | TRANSFER | 同左 | — | — |
| LONG_LEAVE (长期假期) | NO_RATING or DEFERRED | 同左 | 同左 | 同左 | 同左 | 同左 | 同左 | 同左 | — |
| RETIRED_DURING | 按 Policy | 按 Policy | 按 Policy | 按 Policy | 按 Policy | 按 Policy | 按 Policy | — | — |
| MULTI_ASSIGNMENT | 主岗参评 | 主岗参评 | 主岗参评 | 主岗参评 | 主岗参评 | 主岗参评 | 主岗参评 | — | — |

---

## 7. 禁止行为

- ❌ 前端手选"我是教学科研型"成为正式分类
- ❌ 今日调岗导致去年考核模板变化
- ❌ 多 Assignment 人员只取第一条
- ❌ 所有岗位一套指标、一套权重
- ❌ 强制正态分布或强制末位淘汰
- ❌ NO_RATING 被统计口径排除而指标失真
