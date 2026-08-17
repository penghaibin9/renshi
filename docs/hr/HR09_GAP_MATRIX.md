# HR09_GAP_MATRIX —— 教师资格与双师型缺口矩阵（S0 基线复审）

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §161 + 真实代码基线扫描

---

## 1. 总览

| 缺口类别 | 数量 | 严重度 |
|---|---|---|
| 模型缺失 | 13 | CRITICAL |
| 服务缺失 | 10 | HIGH |
| 前端缺失 | 28+ | HIGH |
| 集成缺失 | 6 | HIGH |
| 治理缺失 | 8 | MEDIUM |
| **合计** | **65+** | — |

---

## 2. 模型缺口（CRITICAL）

| ID | 缺口 | 总册节号 | 说明 |
|---|---|---|---|
| M01 | `HrCredentialCatalogItem` | §18 | 资格目录表。HR03 仅有 `HrCredential` 的四选一 type，无目录系统 |
| M02 | `HrPersonCredential` (HR09) | §20 | 完整人员持证模型（证号加密+hash、有效期、snapshot、source、version）。HR03 的 HrCredential 缺 catalog_item_id/credential_name_snapshot |
| M03 | `HrCredentialVerification` | §22 | 核验历史多记录（支持第三方 provider 引用）。HR03 只有单 verified_by/verified_at 字段 |
| M04 | `HrCredentialDocument` | §26 | 证书附件（document_type/sensitivity/checksum）。horilla_documents 未区分类型 |
| M05 | `HrCredentialStatusEvent` | §133 | 状态变更历史链 |
| M06 | `HrCredentialRequirement` | §29 | 岗位/认定资格需求 |
| M07 | `HrCredentialRenewal` | §28 | 证书续期代际（不覆盖原记录） |
| M08 | `HrDoubleTeacherRulePack` + `HrDoubleTeacherRulePackVersion` | §36 | 四层规则体系（国家/省/学校/批次） |
| M09 | `HrDoubleTeacherRule` | §37 | 结构化规则条目 |
| M10 | `HrDoubleTeacherEvidenceRequirement` | §39 | 证据要求 |
| M11 | `HrDoubleTeacherRecognitionBatch` | §52 | 认定批次 |
| M12 | `HrDoubleTeacherApplication` + `HrDoubleTeacherEvidencePackage` | §54/57 | 申报+证据包 |
| M13 | `HrDoubleTeacherReviewPanel` + `HrDoubleTeacherScoreSheet` + `HrDoubleTeacherPanelDecision` + `HrDoubleTeacherFinalDecision` | §70-80 | 评审全链 |

| ID | 缺口 | 总册节号 | 说明 |
|---|---|---|---|
| M14 | `HrDoubleTeacherRecognition` | §84 | 认定结果实体 |
| M15 | `HrDoubleTeacherRecheckCase` | §87 | 复核案例 |
| M16 | `HrQualificationRiskCase` | §92 | 资格风险案例 |
| M17 | `HrEvidenceUsage` | §131 | 证据反向引用图 |
| M18 | `HrCredentialVerificationProvider` | §24 | 第三方核验 Provider 抽象 |

---

## 3. 服务缺口（HIGH）

| ID | 缺口 | 说明 |
|---|---|---|
| S01 | Credential Service | CRUD + submit_verification/verify/renew/suspend/revoke |
| S02 | Verification Service | 多类型核验编排 + Provider 调度 |
| S03 | Credential Requirement Service | Requirement Match 引擎 |
| S04 | Rule Service | RulePack 四层继承、diff、publish |
| S05 | Evidence Service | 多源证据聚合 + 快照冻结 |
| S06 | Precheck Service | 基于 Frozen RuleVersion 的自动预检 |
| S07 | Application Service | 申报状态机 (DRAFT→SUBMITTED→FORMAL_REVIEW→...→RECOGNIZED) |
| S08 | Review Service | Formal Review + Panel + Score + Vote + Final |
| S09 | Recognition Service | 认定结果管理（effective/upgrade/revoke） |
| S10 | Recheck Service | 复核编排（触发→证据快照→决策） |
| S11 | Risk Service | 风险检测/去重/跟踪/影响图遍历 |

---

## 4. Provider 缺口（HIGH）

| ID | 缺口 | 源域 | 说明 |
|---|---|---|---|
| P01 | HR03_EDUCATION Provider | hr_staff | HrEducationExperience/HrDegreeRecord/HrWorkExperience |
| P02 | HR08_ENGAGEMENT Provider | hr_external | 外聘教师 eligibility |
| P03 | HR10_PRACTICE Provider | hr_development | 企业实践/培训（HR10 未就绪时返回 UNAVAILABLE） |
| P04 | HR12_ASSESSMENT Provider | hr_assessment | 考核结果（HR12 未就绪时返回 UNAVAILABLE） |
| P05 | ACADEMIC_TEACHING Provider | academic | 教务教学任务/竞赛/成果（外部系统） |
| P06 | CREDENTIAL_VERIFICATION Provider | internal | 第三方证书核验接口抽象 |

---

## 5. 前端缺口（HIGH）

| ID | 组件 | 总册节号 |
|---|---|---|
| U01 | HrCredentialStatusBadge | §97 |
| U02 | HrCredentialVerificationBadge | §97 |
| U03 | HrCredentialCard | §97 |
| U04 | HrCredentialRequirementMatch | §97 |
| U05 | HrCredentialExpiryBadge | §97 |
| U06 | HrVerificationTimeline | §97 |
| U07 | HrDoubleTeacherLevelBadge | §97 |
| U08 | HrRulePackVersionBadge | §97 |
| U09 | HrRuleInheritanceTree | §97 |
| U10 | HrRuleDiff | §97 |
| U11 | HrRecognitionBatchHeader | §97 |
| U12 | HrRecognitionProgress | §97 |
| U13 | HrEvidenceMatrix | §97 |
| U14 | HrEvidenceSourceBadge | §97 |
| U15 | HrEvidenceVerificationBadge | §97 |
| U16 | HrPrecheckPanel | §97 |
| U17 | HrRuleExplainPanel | §97 |
| U18 | HrQualificationGap | §97 |
| U19 | HrPanelConflictBadge | §97 |
| U20 | HrReviewRubric | §97 |
| U21 | HrScoreLockBadge | §97 |
| U22 | HrRecognitionTimeline | §97 |
| U23 | HrRecheckStatusBadge | §97 |
| U24 | HrQualificationRiskCard | §97 |

页面级缺口：

| ID | 页面 | 路由 |
|---|---|---|
| U25 | 教师资格台账 | /hr/qualifications |
| U26 | Credential Detail | /hr/qualifications/:id |
| U27 | 双师规则中心 | /hr/double-teacher/rules |
| U28 | Rule Diff 页 | /hr/double-teacher/rules/:id/diff |
| U29 | 认定批次管理 | /hr/double-teacher/batches |
| U30 | 双师申报页 | /hr/double-teacher/applications |
| U31 | 形式审查工作台 | /hr/double-teacher/reviews |
| U32 | Panel 评审页 | /hr/double-teacher/reviews/panel |
| U33 | 认定结果台账 | /hr/double-teacher/recognitions |
| U34 | 复核中心 | /hr/double-teacher/rechecks |
| U35 | 风险中心 | /hr/double-teacher/risks |

---

## 6. 治理缺口（MEDIUM）

| ID | 缺口 | 说明 |
|---|---|---|
| G01 | Permissions (hr09.credential.*, hr09.rule.*, hr09.review.*, hr09.recognition.*) | 总册 §125 |
| G02 | Data Scope (SCHOOL/COLLEGE/BATCH/PANEL_ASSIGNED/SELF) | 总册 §126 |
| G03 | Outbox Events (12 个事件类型) | 总册 §119 |
| G04 | Error Codes (16 个业务错误码) | 总册 §112 |
| G05 | Security Tests (17 项安全验收) | 总册 §144 |
| G06 | Reconciliation (LegacyQ→HR09) | 总册 §139 |
| G07 | Data Quality Checks (11 个规则) | 总册 §157 |
| G08 | Metric Registry (dual_teacher_ratio 等) | 总册 §94-96 |

---

## 7. P0 风险标注

| ID | 风险 | 影响 |
|---|---|---|
| P0-01 | 教师资格与双师混淆 | 一个 free-text 字段无法区分法定资格与职业认定 |
| P0-02 | 规则版本污染历史 | 无 RuleVersion → 修改规则后旧认定语义被污染 |
| P0-03 | 证据伪造风险 | 无 EvidenceUsage 反向图 → 证据撤销不影响双师资格 |
| P0-04 | Provider 失败假 0 | 教务/HR10 不可用时无 UNAVAILABLE → 误判 FAIL |
| P0-05 | 证书撤销无影响链 | 证书 REVOKED 后双师资格不进入风险审查 |
| P0-06 | 专家越权 | 无 Panel 成员冲突检测 → 利益冲突专家参与评审 |
| P0-07 | 跨租户泄露 | 无 tenant fail-closed → A校看到B校证书 |
| P0-08 | Legacy free-text 当权威 | Employee.qualification 字符串被视为正式资格 |

---

**文件状态：S0_BASELINE 冻结。**
