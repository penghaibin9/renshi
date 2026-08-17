# HR10_DevelopmentActivityTaxonomy — 发展活动分类体系认证

> 来源：总册 §24 + §7 + §88
> 版本：`S0_V1`
> 日期：2026-08-09

---

## 0. 分类体系总览

HR10 发展活动采用可扩展 Catalog 设计（非单一 Enum 终结学校差异）。

系统内置 18 个建议类型，每个类型定义 10 项行为特征（can_generate_learning_hours / can_generate_practice_hours 分别独立，不可混用）。

---

## 1. 内置活动类型清单

| 代码 | 中文名 | 英文名 | 类别归属 |
|---|---|---|---|
| `INTERNAL_TRAINING` | 校内培训 | Internal Training | 培训 |
| `EXTERNAL_TRAINING` | 校外培训 | External Training | 培训 |
| `ONLINE_LEARNING` | 线上学习 | Online Learning | 学习 |
| `BLENDED_LEARNING` | 混合研修 | Blended Learning | 学习 |
| `TEACHING_WORKSHOP` | 教学研讨会 | Teaching Workshop | 研讨 |
| `DIGITAL_SKILL_TRAINING` | 数字化能力培训 | Digital Skill Training | 培训 |
| `INDUSTRY_TECH_TRAINING` | 产业技术培训 | Industry Tech Training | 培训 |
| `SCHOOL_VISIT` | 校际参观 | School Visit | 参观 |
| `VISITING_STUDY` | 访学研修 | Visiting Study | 进修 |
| `SHADOWING` | 跟岗研修 | Shadowing | 进修 |
| `FURTHER_STUDY` | 继续教育 | Further Study | 进修 |
| `DEGREE_STUDY_PROCESS` | 学历提升 | Degree Study Process | 进修 |
| `CERTIFICATION_PREPARATION` | 证书备考 | Certification Preparation | 学习 |
| `ENTERPRISE_PRACTICE` | 企业实践 | Enterprise Practice | 企业实践 |
| `PRACTICE_BASE_TRAINING` | 实践基地培训 | Practice Base Training | 企业实践 |
| `RESEARCH_VISIT` | 科研访学 | Research Visit | 进修 |
| `INTERNATIONAL_EXCHANGE` | 国际交流 | International Exchange | 进修 |
| `OTHER` | 其他 | Other | 其他 |

---

## 2. 行为特征定义

每种活动类型在 Catalog 中定义 8 个行为特征（可被 Tenant Policy 覆盖）：

| 特征 | 含义 | 值 |
|---|---|---|
| `requires_program` | 是否必须有正式培训项目 | `true`/`false` |
| `requires_approval` | 是否需要审批 | `true`/`false` |
| `requires_budget` | 是否需要预算控制 | `true`/`false` |
| `requires_leave_check` | 是否需要请假/时间冲突检查 | `true`/`false` |
| `requires_completion_evidence` | 是否需要完成证据 | `true`/`false` |
| `requires_provider_verification` | 是否需要外部 Provider 核验 | `true`/`false` |
| `can_generate_learning_hours` | 是否产生培训学时 | `true`/`false` |
| `can_generate_practice_hours` | 是否产生实践时长 | `true`/`false` |
| `can_feed_hr09` | 是否可作 HR09 双师证据 | `true`/`false` |
| `result_authority` | 结果权威域 | `HR10`（过程）、`HR03`（学历）、`HR09`（资格） |

---

## 3. 类型 × 行为矩阵

| 类型代码 | requires_program | requires_approval | requires_budget | requires_leave_check | completion_evidence | provider_verification | learning_hours | practice_hours | feed_hr09 | result_authority |
|---|---|---|---|---|---|---|---|---|---|---|
| INTERNAL_TRAINING | Y | Y | — | — | Y | — | Y | — | Y | HR10 |
| EXTERNAL_TRAINING | Y | Y | Y | Y | Y | Y | Y | — | Y | HR10 |
| ONLINE_LEARNING | Y | — | — | — | Y | Y | Y | — | — | HR10 |
| BLENDED_LEARNING | Y | Y | Y | Y | Y | Y | Y | — | Y | HR10 |
| TEACHING_WORKSHOP | Y | — | — | — | Y | — | Y | — | Y | HR10 |
| DIGITAL_SKILL_TRAINING | Y | Y | Y | — | Y | Y | Y | — | Y | HR10 |
| INDUSTRY_TECH_TRAINING | Y | Y | Y | Y | Y | Y | Y | Y | Y | HR10 |
| SCHOOL_VISIT | — | Y | Y | Y | Y | — | — | — | — | HR10 |
| VISITING_STUDY | Y | Y | Y | Y | Y | Y | Y | — | Y | HR10 |
| SHADOWING | Y | Y | Y | Y | Y | Y | Y | Y | Y | HR10 |
| FURTHER_STUDY | Y | Y | Y | Y | Y | Y | Y | — | — | HR10 |
| DEGREE_STUDY_PROCESS | N/A | Y | Y | Y | N/A | Y | — | — | — | HR03 (学历最终) |
| CERTIFICATION_PREPARATION | Y | — | — | — | Y | Y | Y | — | — | HR09 (证书最终) |
| ENTERPRISE_PRACTICE | Y | Y | Y | Y | Y | Y | — | Y | Y | HR10 |
| PRACTICE_BASE_TRAINING | Y | Y | Y | Y | Y | Y | — | Y | Y | HR10 |
| RESEARCH_VISIT | Y | Y | Y | Y | Y | Y | — | — | — | HR10 |
| INTERNATIONAL_EXCHANGE | Y | Y | Y | Y | Y | Y | Y | — | — | HR10 |
| OTHER | — | — | — | — | — | — | — | — | — | 由 Tenant Policy 决定 |

---

## 4. 与现有代码对齐

| 类型代码 | 旧代码参考 | 对齐 |
|---|---|---|
| `INTERNAL_TRAINING` | 无直接对应 | 全新 |
| `EXTERNAL_TRAINING` | `hr_time.models.attendance.TRAINING` | 工时表条目类型保留，引入 HR10 participation 引用 |
| `DIGITAL_SKILL_TRAINING` | `hr_external.constants.SKILL_TRAINING` | HR08 分配类型，HR10 引用 engagement |
| `ENTERPRISE_PRACTICE` | `hr_external.constants.PRACTICE_INSTRUCTOR`, `PRACTICE_GUIDANCE` | HR08 人员/分配类型，HR10 自有 authority |
| `INDUSTRY_TECH_TRAINING` | `hr_external.constants.FACULTY_TRAINING` | HR08 贡献类型 |
| `TEACHING_WORKSHOP` | `hr_external.constants.SKILL_MASTER_WORKSHOP`, `INDUSTRY_TEACHING_WORKSHOP` | HR08 workspace 类型 |
| `SHADOWING` | `hr_external.constants.PRACTICE_GUIDANCE` | HR08 分配类型 |

---

## 5. Tenant 可扩展性

学校可按以下方式自定义：
- 增加 Tenant 级 Catalog 条目（非系统内置）
- 覆盖内置类型的行为特征值（如某校要求所有培训都需要预算审批）
- 禁用某些类型（如某校不允许 DEGREE_STUDY_PROCESS 走 HR10 流程）

**Catalog 版本化**：租户覆盖保存为 `DevelopmentActivityTypeCatalogVersion`，修改后新申请用新版本，历史记录不变。

---

## 6. 与 Delivery Mode 的关系

Activity Type ≠ Delivery Mode。
一个活动类型可以有多种交付方式：

| 交付方式 | 典型活动类型 |
|---|---|
| `ONSITE` | INTERNAL_TRAINING, TEACHING_WORKSHOP, INDUSTRY_TECH_TRAINING |
| `ONLINE_LIVE` | ONLINE_LEARNING, BLENDED_LEARNING |
| `ONLINE_ASYNC` | ONLINE_LEARNING |
| `BLENDED` | BLENDED_LEARNING, DIGITAL_SKILL_TRAINING |
| `SHADOWING` | SHADOWING |
| `VISITING` | SCHOOL_VISIT, VISITING_STUDY, RESEARCH_VISIT |
| `FIELD_PRACTICE` | ENTERPRISE_PRACTICE, PRACTICE_BASE_TRAINING |
| `ENTERPRISE_PRACTICE` | ENTERPRISE_PRACTICE |
| `SELF_DIRECTED_WITH_VERIFICATION` | CERTIFICATION_PREPARATION, OTHER |

---

**文档状态：S0_V1 — 分类体系认证完成。18 内置类型 + 10 行为特征 + Tenant 可扩展。**
