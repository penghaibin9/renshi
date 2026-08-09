# HR09_TASK_TREE —— 教师资格与双师型施工任务树

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §161-174

---

## 施工阶段总览

```text
S0  →  基线复审  [已完成]
S1  →  基础层    [待施工]
S2  →  Credential Authority  [待施工]
S3  →  教师资格台账  (HR09-01)  [待施工]
S4  →  双师认定标准  (HR09-02)  [待施工]
S5  →  Provider 层   [待施工]
S6  →  双师申报 + HR10 集成  (HR09-03)  [待施工]
S7  →  认定与评审  (HR09-04)  [待施工]
S8  →  复核与资格台账  (HR09-05)  [待施工]
S9  →  Legacy Projection  [待施工]
S10 →  Legacy Migration + DUAL_READ_COMPARE  [待施工]
S11 →  Security / Concurrency / Performance / E2E  [待施工]
S12 →  Authority 切换  [待施工]
S13 →  最终封板  [待施工]
```

---

## S0 基线复审 ✅

| # | 任务 | 状态 | 产出 |
|---|---|---|---|
| S0.1 | 读取总册 + 00 合同 | DONE | — |
| S0.2 | 扫描 employee/models.py | DONE | 定位 `qualification` 字段 line 108 |
| S0.3 | 扫描 horilla_documents | DONE | Document/DocumentRequest 模型 |
| S0.4 | 扫描 horilla_audit | DONE | HorillaAuditLog 技术审计 |
| S0.5 | 全仓搜索关键词 | DONE | 8 关键词 × 全仓 |
| S0.6 | 核验法律法规 | DONE | 教师厅〔2022〕2号 / 教师资格条例 |
| S0.7 | 读取 HR03/HR08 权威模型 | DONE | HrCredential/HrPerson/Hengagerment |
| S0.8 | 物化 LegacyQualificationMapping | DONE | docs/hr/legacy/HR09_LegacyQualificationMapping.md |
| S0.9 | 物化 GAP_MATRIX | DONE | docs/hr/HR09_GAP_MATRIX.md |
| S0.10 | 物化 TASK_TREE | DONE | 本文档 |
| S0.11 | 物化 RISK_REGISTER | DONE | docs/hr/HR09_RISK_REGISTER.md |
| S0.12 | 物化 CredentialCategoryMatrix | DONE | docs/hr/HR09_CredentialCategoryMatrix.md |
| S0.13 | 物化 DoubleTeacherNationalBaselineMap | DONE | docs/hr/HR09_DoubleTeacherNationalBaselineMap.md |
| S0.14 | 物化 EvidenceProviderMatrix | DONE | docs/hr/HR09_EvidenceProviderMatrix.md |

---

## S1 基础层

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S1.1 | 创建 `hr_qualification` Django app | — | INSTALLED_APPS + AppConfig |
| S1.2 | 定义 enums（constants.py） | — | CredentialCategory/CredentialStatus/VerificationStatus/RecognitionLevel 等 |
| S1.3 | 注册 permissions | S1.1 | hr09.credential.* / hr09.rule.* / hr09.review.* / hr09.recognition.* |
| S1.4 | 创建 Credential Catalog 模型 | S1.2 | HrCredentialCatalogItem |
| S1.5 | 设置 API envelope | S1.1 | /api/v1/hr/qualifications/* 路由 + 响应格式 |
| S1.6 | 创建基础 UI 组件 | S1.1 | StatusBadge / VerificationBadge / CredentialCard 等 |

---

## S2 Credential Authority

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S2.1 | HrPersonCredential 模型 + migration | S1.2 | credential.py（证号加密/hash、catalog_item FK、status 状态机） |
| S2.2 | HrCredentialVerification 模型 + migration | S1.2 | verification.py（多记录审计链） |
| S2.3 | HrCredentialDocument 模型 + migration | S1.2 | document.py（sensitivity/checksum/version） |
| S2.4 | HrCredentialStatusEvent 模型 + migration | S1.2 | status_event.py（from→to/reason/actor/evidence） |
| S2.5 | HrCredentialRequirement 模型 + migration | S1.2 | requirement.py（target/credential_category/level/hard_or_soft） |
| S2.6 | HrQualificationRiskCase 模型 + migration | S1.2 | risk.py |
| S2.7 | HrCredentialRenewal 模型 + migration | S1.2 | renewal.py（代际链） |
| S2.8 | Credential Service | S2.1-2.6 | CRUD + status 流转 |
| S2.9 | Verification Service | S2.2 | 多类型核验编排 |
| S2.10 | Requirement Service | S2.5 | Person vs Requirement 对比 |
| S2.11 | 单元测试 | S2.1-2.10 | test_credential.py |

---

## S3 HR09-01 教师资格台账

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S3.1 | 台账 API（列表/筛选/分页） | S2.1 | GET /api/v1/hr/qualifications/credentials |
| S3.2 | Credential Detail API | S2.1 | GET /api/v1/hr/qualifications/credentials/{id} |
| S3.3 | 核验操作 API | S2.2 | POST .../{id}/verify |
| S3.4 | 续证/挂起/撤销 API | S2.8 | POST .../{id}/renew/suspend/revoke |
| S3.5 | Exact Match 证号搜索 | S2.1 | POST .../exact-match |
| S3.6 | Requirement Match API | S2.10 | GET .../requirement-match |
| S3.7 | Risk Case API | S2.6 | GET/POST /api/v1/hr/qualifications/risks |
| S3.8 | Excel 导入/导出 | S2.1 | template→staging→validation→audit |
| S3.9 | 台账前端页面 | S1.6 | /hr/qualifications |
| S3.10 | Credential Detail 前端 | S1.6 | /hr/qualifications/:id |
| S3.11 | 集成测试 | S3.1-3.10 | test_hr09_01.py |

---

## S4 HR09-02 双师认定标准

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S4.1 | HrDoubleTeacherRulePack 模型 + migration | S1.2 | rule_pack.py（四层 jurisdiction_level） |
| S4.2 | HrDoubleTeacherRulePackVersion 模型 + migration | S1.2 | DRAFT→UNDER_REVIEW→ACTIVE→RETIRED 状态机 |
| S4.3 | HrDoubleTeacherRule 模型 + migration | S1.2 | rule.py（结构化维度/rule_type/operator/expected_value） |
| S4.4 | HrDoubleTeacherEvidenceRequirement 模型 | S1.2 | 证据类型/来源/数量/验证要求 |
| S4.5 | HrDoubleTeacherExceptionRoute 模型 | S1.2 | 破格条件 |
| S4.6 | Rule Pack Service | S4.1-4.5 | 四层继承校验、diff、publish |
| S4.7 | Rule Inheritance Validation | S4.6 | 学校规则不得弱化国家 HARD Rule |
| S4.8 | Rule API | S4.6 | GET/POST rule-packs/versions/validate/publish/diff |
| S4.9 | 规则中心前端（继承树/Diff） | S1.6 | /hr/double-teacher/rules |
| S4.10 | 种子数据：国家基本标准 | S4.1-4.3 | 教师厅〔2022〕2号 → 结构化规则 |
| S4.11 | 集成测试 | S4.1-4.10 | test_hr09_02.py |

---

## S5 Provider 层

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S5.1 | Provider 基类抽象 | — | providers/base.py（ProviderStatus 枚举 + 契约） |
| S5.2 | HR03 Education Provider | S1.2 | providers/hr03.py（教育/学位/工作经历） |
| S5.3 | HR08 Engagement Provider | S1.2 | providers/hr08.py（外聘教师 eligibility） |
| S5.4 | HR10 Practice Provider（占位） | S1.2 | providers/hr10.py（返回 UNAVAILABLE 直到 HR10 READY） |
| S5.5 | HR12 Assessment Provider（占位） | S1.2 | providers/hr12.py（返回 UNAVAILABLE 直到 HR12 READY） |
| S5.6 | Academic Teaching Provider（占位） | S1.2 | providers/academic.py（接口契约；默认 UNAVAILABLE） |
| S5.7 | Provider 单元测试 | S5.1-5.6 | test_providers.py（含 UNAVAILABLE≠0 测试） |

---

## S6 HR09-03 双师申报 + HR10 集成

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S6.1 | HrDoubleTeacherRecognitionBatch 模型 + migration | S4.2 | batch.py（DRAFT→PUBLISHED→APPLICATION_OPEN→...→CLOSED） |
| S6.2 | HrDoubleTeacherApplication 模型 + migration | S6.1 | application.py（DRAFT→PRECHECKING→...→RECOGNIZED） |
| S6.3 | HrDoubleTeacherEvidencePackage 模型 + migration | S6.2 | evidence.py（快照+checksum+冻结） |
| S6.4 | HrDoubleTeacherEvidenceItem 模型 | S6.3 | evidence_item.py |
| S6.5 | Application Service | S6.2 | 状态机 + submit freeze |
| S6.6 | Evidence Aggregation Service | S6.3-6.4 | 多源拉取 → EvidencePackage 快照 |
| S6.7 | Precheck Service | S4.3 + S6.3 | 规则引擎（PASS/FAIL_HARD/MISSING/MANUAL/SOURCE_UNAVAILABLE） |
| S6.8 | Batch/Application API | S6.1-6.7 | GET/POST batches/applications/precheck/submit/withdraw |
| S6.9 | 申报前端页面 | S1.6 | 三栏 Evidence Matrix + Gap View |
| S6.10 | 集成测试 | S6.1-6.9 | test_hr09_03.py |

---

## S7 HR09-04 认定与评审

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S7.1 | HrDoubleTeacherReviewPanel 模型 + migration | S6.1 | review.py（panel/discipline_scope/members/recusal） |
| S7.2 | HrDoubleTeacherPanelMember 模型 + conflict | S7.1 | conflict.py（CLEAR/DECLARED/DETECTED/RECUSED/OVERRIDDEN） |
| S7.3 | HrDoubleTeacherReviewRubricVersion 模型 | S7.1 | rubric.py（dimensions/score_scale/decision_rule/locked） |
| S7.4 | HrDoubleTeacherScoreSheet 模型 | S7.3 | score_sheet.py（DRAFT→SUBMITTED→LOCKED→VOID） |
| S7.5 | HrDoubleTeacherPanelDecision 模型 | S7.1 | panel_decision.py |
| S7.6 | HrDoubleTeacherFinalDecision 模型 | S7.5 | final_decision.py（effective_from/to/authority/meeting_ref） |
| S7.7 | HrDoubleTeacherResultPublication 模型 | S7.6 | publication.py（公示） |
| S7.8 | HrDoubleTeacherObjection 模型 | S7.6 | objection.py（异议） |
| S7.9 | Review Service | S7.1-7.8 | Formal Review + Panel + Score + Vote + Final |
| S7.10 | Review API | S7.9 | formal-review/return/mark-eligible/score-sheets/panel-decisions/final-decisions |
| S7.11 | 评审前端（三栏 workbench） | S1.6 | /hr/double-teacher/reviews |
| S7.12 | 集成测试 | S7.1-7.11 | test_hr09_04.py |

---

## S8 HR09-05 复核与资格台账

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S8.1 | HrDoubleTeacherRecognition 模型 + migration | S7.6 | recognition.py（level/effective_from/to/status） |
| S8.2 | HrRecognitionStatusEvent 模型 | S8.1 | status_event.py（from→to/reason/actor） |
| S8.3 | HrDoubleTeacherRecheckCase 模型 | S8.1 | recheck.py（trigger/due_at/rule_version/decision） |
| S8.4 | HrEvidenceUsage 模型 | S6.4 + S8.1 | evidence_usage.py（反向引用图） |
| S8.5 | Recognition Service | S8.1 | 认定结果管理（effective/upgrade/supersede/revoke） |
| S8.6 | Recheck Service | S8.3 | 触发→证据快照→决策（KEEP/UPGRADE/DOWNGRADE/SUSPEND/REVOKE） |
| S8.7 | Evidence Invalidated → RecheckCase | S8.4 + S8.6 | 证据失效 graph traversal → 开复核 |
| S8.8 | Recognition/Recheck API | S8.5-8.7 | GET/POST recognitions/rechecks/decide |
| S8.9 | 台账+复核前端 | S1.6 | /hr/double-teacher/recognitions /rechecks /risks |
| S8.10 | 集成测试 | S8.1-8.9 | test_hr09_05.py |

---

## S9 Legacy Projection

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S9.1 | HrQualificationProjectionService | S8.1 | HR09→Employee.qualification 单向投影 |
| S9.2 | 旧写入口封堵 | S9.1 | qualification 字段 readonly + audit |
| S9.3 | Legacy 写尝试 metric | S9.2 | legacy_write_attempts_total 计数 |

---

## S10 Legacy Migration + DUAL_READ_COMPARE

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S10.1 | Excel 迁移模板 + staging | S8.1 | 教师资格+双师历史数据迁移 |
| S10.2 | DUAL_READ_COMPARE Job | S9.1 | qualification text ↔ HR09 current summary |
| S10.3 | HR09_LEGACY_DRIFT 发现 | S10.2 | DataQualityFinding 记录差异 |

---

## S11 Security / Concurrency / Performance

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S11.1 | 安全测试（17 项，见总册 §144） | S8.5 | test_security.py |
| S11.2 | 并发测试（8 场景，见总册 §143） | S8.5 | test_concurrency.py |
| S11.3 | 性能测试（p95 < 阈值，见总册 §153） | S8.5 | test_performance.py |
| S11.4 | E2E 测试（25 步主链，见总册 §150） | S11.1-11.3 | test_e2e_main.py |
| S11.5 | E2E 异常链（13 场景，见总册 §151） | S11.4 | test_e2e_exception.py |
| S11.6 | Visual Regression（16 页 × 4 视口） | S8.9 | 截图验证 |
| S11.7 | Accessibility 测试 | S8.9 | a11y 检查 |

---

## S12 Authority 切换

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S12.1 | LEGACY_QUALIFICATION_TEXT → DUAL_READ_COMPARE | S10.3 | flag 切换 |
| S12.2 | DUAL_READ_COMPARE → HR09_AUTHORITY | S12.1 | 全量对账全绿 |
| S12.3 | Legacy 写入口 CLOSE | S12.2 | Employee.qualification 写入禁止 |

---

## S13 最终封板

| # | 任务 | 依赖 | 产出物 |
|---|---|---|---|
| S13.1 | 全模块验收（总册 §145-149） | S11-S12 | 5 个三级模块闭环 |
| S13.2 | 数据完整性验收 | S12.2 | no hard delete / history preserved |
| S13.3 | 安全验收（总册 §127-128） | S11.1 | tenant/scope/panel ✅ |
| S13.4 | 前端验收（总册 §152） | S11.6-11.7 | 多视口/A11y ✅ |
| S13.5 | 封板报告 | S13.1-13.4 | HR09 READY FOR ACCEPTANCE |

---

**文件状态：S0_BASELINE 冻结。**
