# HR10_GAP_MATRIX — 培训进修与企业实践 基线差距矩阵

> 全局合同：`00_高校人事系统全局架构与Horilla接管合同.md`
> 业务事实源：`10_HR10_培训进修与企业实践_施工总册_终极版.md`
> 代码基线：`penghaibin9/renshi` @ 2026-08-09
> 审计范围：全仓库 (hr_staff/hr_external/hr_time/hr_changes/hr_contracts/hr_onboarding/hr_recruitment/employee/leave/attendance/base)
> 状态：`S0_V1`
> 复审日期：2026-08-09

**严重度定义：**
- **P0**：无此能力则模块不可上线接受验收——无 authority model/无 identity root/无 tenant isolation/无正式事实不可变保护/编号唯一性/并发安全/跨租户隔离
- **P1**：核心业务链路关键但施工可后移（S2-S8）
- **P2**：非阻塞性优化、UI 增强、报表、跨域联动后期集成

---

## 0. 结论先行

```
HR10 总体策略：NEW（绿色新建）。
当前代码中无任何 training/learning/practice/development authority 模型。
总册定义 37+ 新模型，全部需从零施工。

旧代码仅有散落枚举值（HR08 external 模块的 SKILL_TRAINING/PRACTICE_INSTRUCTOR/INDUSTRY_MENTOR
等术语、hr_time 的 TRAINING 工时表条目类型）作为语义占位，不构成可接管 authority。

P0 共计：67 项
P1 共计：54 项
P2 共计：28 项
```

---

## 1. 横向硬契约缺口（全模块通用）

| ID | 能力 | 总册需求 | 当前状态 | 缺口 | 严重度 | 施工阶段 |
|---|---|---|---|---|---|---|
| G-H-01 | A0 tenant fail-closed | 所有模型/API tenant 隔离 | 已就绪（HR03/HR08/HR11 均有 tenant 基础设施） | HR10 新模型需继承 TimeTenantModel 模式 | P0 | S1 |
| G-H-02 | effective-dated | plan/program/project/policy 版本冻结 | HR03/HR11 已实现 effective_from/effective_to | HR10 新模型需实现 PlanVersion/ProgramVersion 快照 | P0 | S2-S3 |
| G-H-03 | Authority ownership | 培训/进修/企业实践事实唯一 Authority | 零 authority | 全部从零构建 | P0 | S2-S8 |
| G-H-04 | State machine separation | RETURNED≠REJECTED, 报名≠完成≠VERIFIED | 无 | 全部需构建 | P0 | S4-S7 |
| G-H-05 | Immutable VERIFIED facts | FINAL/EFFECTIVE 后不可原地改 | 无 | revision 机制 + content_hash | P0 | S5-S7 |
| G-H-06 | Audit trail | 所有写操作审计 | HR03 有 HrStaffAuditEvent; HR08 有 HrExternalAuditEvent | 需 HR10 审计模型 | P0 | S1 |
| G-H-07 | Outbox events | 跨域事件 (DevelopmentFactVerified etc.) | HR03/HR08 有 Outbox 模式 | HR10 事件需 21+ event types | P0 | S9 |
| G-H-08 | Permissions | `hr.development.*` | 当前无 | 需 12+ 权限码 | P0 | S1 |
| G-H-09 | Data scope | SCHOOL/COLLEGE/DEPARTMENT/ASSIGNED/SELF | HR03 有 StaffScopeType | 需适配 HR10 的 PROGRAM_SCOPE/PRACTICE_PROJECT_SCOPE | P0 | S1 |
| G-H-10 | API envelope | `/api/v1/hr/development/*` 统一错误/成功信封（00 §28.1 canonical root） | 无 | 全部从零构建 | P0 | S1 |
| G-H-11 | Excel pipeline | staging→validation→error workbook→confirm→async | HR03 有 complete import pipeline | 可复用模式但需新建 HR10 专用 | P1 | S2-S7 |
| G-H-12 | Provider contracts | 11+ Provider interfaces (HR03/HR08/HR09/HR11/HR15/Academic/Research/Finance/Document/Notification/Agreement) | HR11 已预留 DevelopmentTimeProvider | 全部需实现 | P0 | S9 |
| G-H-13 | Person identity root | 复用 HR03 HrPerson/HrStaffMaster | 已就绪 | 不建第二套人员表 | P0 | S1 |
| G-H-14 | Idempotency | 报名/审批/完成核验/finalize 全部幂等 | HR03 有 pattern | HR10 需实现 | P0 | S4-S7 |

---

## 2. HR10-01 教师发展计划 缺口

| ID | 能力 | 总册模型 | 当前 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-01-01 | Plan aggregate | HrDevelopmentPlan | 无 | 全模型+状态机+版本 | P0 | S2 |
| G-01-02 | Plan version freeze | HrDevelopmentPlanVersion | 无 | DRAFT→FROZEN→PUBLISHED 状态机 | P0 | S2 |
| G-01-03 | Development need catalog | HrDevelopmentNeed | 无 | source_type 7种 + competency 映射 | P1 | S2 |
| G-01-04 | Development target | HrDevelopmentTarget | 无 | metric_definition 引用 | P1 | S2 |
| G-01-05 | Budget plan | HrDevelopmentBudgetPlan | 无（全代码库 "budget" 零匹配） | 全模型 + 预留/承诺/实际投影 | P0 | S2 |
| G-01-06 | Plan submission/approval | ApprovalSnapshot based | 无 | workflow policy version 化 | P0 | S2 |
| G-01-07 | Plan metrics | MetricDefinition | HR18 未建 | 暂用 HR10 内置 metric；后续迁 HR18 | P1 | S2 |
| G-01-08 | Plan UI | 10 tabs dashboard | 无 | 全部从零 (计划/需求/目标/项目组合/人员覆盖/预算/审批/版本/执行/风险/审计) | P1 | S2 |

---

## 3. HR10-02 培训项目 缺口

| ID | 能力 | 总册模型 | 当前 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-02-01 | Program aggregate | HrLearningProgram | 无 | 全模型+编码唯一性 | P0 | S3 |
| G-02-02 | Program version | HrLearningProgramVersion | 无 | objectives/curriculum/completion_rule JSON | P0 | S3 |
| G-02-03 | Offering/班次 | HrLearningOffering | 无 | capacity/waitlist/delivery_mode/session | P0 | S3 |
| G-02-04 | Provider org registry | HrDevelopmentProviderOrganization | HR08 有组织引用但无 training provider 专用模型 | 全新 | P0 | S3 |
| G-02-05 | Provider verification | verification_status/risk_status | 无 | 核验→有效期→历史快照→黑名单 | P1 | S3 |
| G-02-06 | Capacity control (并发) | 数据库级名额锁定 | 无 | SELECT FOR UPDATE / optimistic lock | P0 | S3 |
| G-02-07 | Waitlist management | waitlist_capacity + 转正逻辑 | 无 | 候补→转正并发保护 | P0 | S4 |
| G-02-08 | Session/schedule | HrLearningSession | 无 | 多 session + 学时计算 | P1 | S3 |
| G-02-09 | Instructor refs | ProgramInstructorRef | HR08 有 external teacher profile | 可引用 HR03/HR08/外部讲师 | P1 | S3 |
| G-02-10 | Completion rules versioned | completion_rule_json | 无 | 与 program version 绑定 | P0 | S3 |
| G-02-11 | Program UI | catalog + management | 无 | 项目/班次/成员/师资/费用管理 | P1 | S3 |

---

## 4. HR10-03 培训报名与审批 缺口

| ID | 能力 | 总册模型 | 当前 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-03-01 | Training request | HrTrainingRequest | 无 | 内部/外部/进修/团队四种类型 | P0 | S4 |
| G-03-02 | Request state machine | 25+ states | 无 | RETURNED≠REJECTED, 多步审批可配置 | P0 | S4 |
| G-03-03 | Approval snapshot | HrDevelopmentApprovalSnapshot | HR06 有 ChangeApprovalSnapshot 可参考 | 全新模型 | P0 | S4 |
| G-03-04 | Enrollment | HrLearningEnrollment | 无 | 名额并发 + staff/offering unique active | P0 | S4 |
| G-03-05 | Schedule conflict check | TimeConflictProvider (HR11) | HR11 有 abstract Provider interface | Provider 未实现 | P1 | S9 |
| G-03-06 | Self-approval prohibition | SoD enforcement | 无 | 需实现 applicant==approver 检测 | P0 | S4 |
| G-03-07 | Budget reservation | 预留/承诺与 HR15 联动 | 无（"budget" 全代码库零匹配） | Provider contract + 预留接口 | P1 | S9 |
| G-03-08 | Withdraw/cancel/no-show | 不同语义分离 | 无 | ORG_CANCEL/PROVIDER_CANCEL/NO_SHOW 等 | P1 | S4 |
| G-03-09 | Teacher portal | self-service 申请/报名/历史 | 无 | `/me/development/*` 端点 | P1 | S4 |
| G-03-10 | Supervisor team view | 学院/主管审批视图 | 无 | 数据范围 + 待审批/覆盖/预算摘要 | P2 | S4 |

---

## 5. HR10-04 企业实践项目 缺口

| ID | 能力 | 总册模型 | 当前 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-04-01 | Practice project aggregate | HrEnterprisePracticeProject | 无 | 全模型+project_no 唯一 | P0 | S6 |
| G-04-02 | Project version freeze | HrEnterprisePracticeProjectVersion | 无 | 目标/场景/模块/导师/评价/安全要求 JSON | P0 | S6 |
| G-04-03 | Position/scene definition | HrPracticePositionScene | 无 | 真实岗位/生产线/服务场景 | P0 | S6 |
| G-04-04 | Placement/batch | HrEnterprisePracticePlacement | 无 | batch/start/end/capacity/导师/联系人 | P0 | S6 |
| G-04-05 | Assignment | HrEnterprisePracticeAssignment | 无 | staff↔placement↔scene+mentor mapping | P0 | S6 |
| G-04-06 | Mentor management | HrEnterprisePracticeMentor | HR08 有 INDUSTRY_MENTOR 枚举占位 | 全新模型（person_display/credential/access） | P0 | S6 |
| G-04-07 | Practice plan | HrEnterprisePracticePlan | 无 | 双方确认 + content_hash | P0 | S6 |
| G-04-08 | Prerequisite gate | safety/confidentiality/IP agreement | 无 | 前置检查→READY_TO_START 控制 | P0 | S6 |
| G-04-09 | Project status machine | 15 states | 无 | MATCHING→READY_TO_START→ACTIVE→COMPLETION_REVIEW | P0 | S6 |
| G-04-10 | Practice base management | provider_org + practice_base_level | 无 | 国家级/省级/校级的级别+有效期+核验 | P1 | S6 |

---

## 6. HR10-05 实践过程与成果 缺口

| ID | 能力 | 总册模型 | 当前 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-05-01 | Activity recording | HrEnterprisePracticeActivity | 无 | 13 activity types + DRAFT→VERIFIED chain | P0 | S7 |
| G-05-02 | Attendance fact | HrEnterprisePracticeAttendanceFact | HR11 有 attendance 但非企业实践 | 4 source types + trust_level | P0 | S7 |
| G-05-03 | Evidence management | HrEnterprisePracticeEvidence | HR03 有 Material 但非实践专用 | evidence_type + verification workflow | P0 | S7 |
| G-05-04 | Mentor feedback | HrEnterpriseMentorFeedback | 无 | rubric + rating + revision chain | P0 | S7 |
| G-05-05 | School evaluation | HrPracticeSchoolEvaluation | 无 | rubric + evidence package + revision | P0 | S7 |
| G-05-06 | Final evaluation | HrEnterprisePracticeEvaluation | 无 | enterprise+school combined + immutable_hash | P0 | S7 |
| G-05-07 | Duration ledger | verified activity segments → ledger | 无 | 去重+排除+转换 version | P0 | S7 |
| G-05-08 | Development output | HrDevelopmentOutput | 无 | 30+ output types + duplicate detection | P1 | S7 |
| G-05-09 | Teaching transformation | output→academic ref | 无 | 教务 Provider contract | P2 | S9 |
| G-05-10 | Suspicious evidence detection | RiskCase automation | 无 | hash duplicate/time overlap/future time | P1 | S7 |
| G-05-11 | Mentor portal | scoped access to assignment only | 无 | short-lived identity/magic-link/token+assignment scope | P1 | S7 |
| G-05-12 | Suspend/resume/transfer | PracticeTransferEvent | 无 | 企业变更/岗位变更事件 + old/new snapshot | P1 | S7 |

---

## 7. HR10-06 教师发展档案 缺口

| ID | 能力 | 总册模型 | 当前 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-06-01 | DevelopmentFact aggregate | HrDevelopmentFact | 无 | 4 fact types + immutable_hash | P0 | S8 |
| G-06-02 | Fact generation rules | only VERIFIED source→fact | 无 | 禁止 DRAFT/SELF_REPORTED 生成 fact | P0 | S8 |
| G-06-03 | Metric ledger | HrDevelopmentMetricLedger | 无 | hours/credits/days 分账 | P0 | S8 |
| G-06-04 | Compliance engine | HrDevelopmentComplianceRule | 无 | policy_version + time_window + minimum_value | P1 | S8 |
| G-06-05 | Risk center | HrDevelopmentRiskCase | HR11 有 HrTimeRiskCase 参考 | 12 risk types | P1 | S8 |
| G-06-06 | Development dashboard | 13 KPIs + as-of | 无 | 全部新建 | P2 | S8 |
| G-06-07 | HR09 evidence Provider | `/internal/hr/development/evidence/staff/{id}` | 无 | 仅返回 VERIFIED facts | P0 | S9 |
| G-06-08 | HR12 assessment Provider | 引用发展事实+计划完成率 | 无 | Provider contract | P2 | S9 |
| G-06-09 | Degree writeback to HR03 | FurtherStudy→EducationHistory | HR03 有 HrEducationExperience | 核验后提交→HR03 写回 | P1 | S9 |
| G-06-10 | as-of query | 历史时间点事实复现 | HR03 有 effective_dated_query_service | 需要 HR10 实现的 as-of query | P1 | S8 |

---

## 8. 跨域 Provider/Event 契约缺口

| ID | 方向 | 契约 | 当前 | 缺口 | 严重度 |
|---|---|---|---|---|---|
| G-X-01 | HR10→HR03 | Person read Provider | 已就绪 | 直接引用 HrPerson/HrStaffMaster 模型 | P0 |
| G-X-02 | HR10→HR03 | Education writeback | 无 | 核验后通过 Provider contract 提交 HR03 | P1 |
| G-X-03 | HR10→HR08 | External teacher reference | 已就绪 | 引用 external_engagement_id | P0 |
| G-X-04 | HR10→HR09 | Evidence Provider | 无 | VERIFIED facts→HR09 双师证据 | P0 |
| G-X-05 | HR10→HR11 | Time/conflict Provider | HR11 有 DevelopmentTimeProvider 抽象接口 | 需实现 | P1 |
| G-X-06 | HR10→HR12 | Assessment Provider | 无 | 发展事实→考核引用 | P2 |
| G-X-07 | HR10→HR15 | Finance budget/payment Provider | 无（"budget" 零匹配） | Provider contract + 预留字段 | P2 |
| G-X-08 | HR10→教务 | Academic Provider | 无 | 教学成果认证→教务引用 | P2 |
| G-X-09 | HR10→科研 | Research Provider | 无 | 科研产出认证→科研引用 | P2 |
| G-X-10 | HR10→HR07 | Agreement Provider | HR07 有 Agreement 模型 | 实践协议引用 | P2 |
| G-X-11 | HR10→Documents | File security Provider | horilla_documents 已有文件基础设施 | 复用+增加 HR10 evidence scope | P0 |

---

## 9. 旧代码接管缺口

| ID | 能力 | 缺口 | 严重度 |
|---|---|---|---|
| G-L-01 | Employee.qualification 接管 | 自由文本→Staging 迁移→不可直接 Authority | P1 |
| G-L-02 | EmployeeNote 培训备注 | 解析→staging→MIGRATED_FREE_TEXT | P2 |
| G-L-03 | Document 培训证书 | 关联→evidence staging→不自动 VERIFIED | P2 |
| G-L-04 | HrTimeSheetEntry.TRAINING | 改为引用 HR10 participation→不重复计算工时 | P2 |
| G-L-05 | HrScheduleException training/practice | 改为引用 HR10 assignment→schedule conflict gate | P2 |

---

## 10. P0 阻件清单

以下 67 项 P0 必须全部施工完成才能进入验收：

1. A0 tenant fail-closed（所有模型+API）
2. effective-dated 版本冻结（PlanVersion/ProgramVersion/ProjectVersion/PolicyVersion）
3. Person identity root 复用 HR03（不建第二套人员表）
4. API envelope + 错误码体系 (40+ error codes)
5. Permissions (12+ `hr.development.*`)
6. Data scope (PROGRAM_SCOPE/PRACTICE_PROJECT_SCOPE/SELF)
7. Audit trail 模型
8. Outbox events (21+ event types)
9. All 37+ NEW models (所有总册 §14 清单中的模型)
10. HrDevelopmentPlan + state machine (15 states)
11. HrDevelopmentPlanVersion (DRAFT→FROZEN 不可变)
12. HrDevelopmentBudgetPlan（全新，"budget" 零代码匹配）
13. HrLearningProgram (program_code unique)
14. HrLearningProgramVersion (completion_rule JSON)
15. HrLearningOffering + capacity concurrent control
16. HrDevelopmentProviderOrganization
17. HrTrainingRequest + state machine (25+ states)
18. HrDevelopmentApprovalSnapshot
19. HrLearningEnrollment + staff/offering unique active constraint
20. Self-approval prohibition
21. Waitlist 转正并发安全
22. HrEnterprisePracticeProject + 15 states
23. HrEnterprisePracticeProjectVersion
24. HrPracticePositionScene
25. HrEnterprisePracticePlacement
26. HrEnterprisePracticeAssignment
27. HrEnterprisePracticeMentor
28. HrEnterprisePracticePlan
29. Prerequisite gate (safety/confidentiality/IP)
30. HrEnterprisePracticeActivity
31. HrEnterprisePracticeAttendanceFact
32. HrEnterprisePracticeEvidence
33. HrEnterpriseMentorFeedback
34. HrPracticeSchoolEvaluation
35. HrEnterprisePracticeEvaluation (immutable_hash)
36. Duration ledger (verified segments→ledger)
37. HrDevelopmentFact (4 types + immutable_hash)
38. Fact generation rules (only VERIFIED→fact)
39. HrDevelopmentMetricLedger
40. HR09 Evidence Provider
41. Document Provider integration
42. HR03 Person/Staff reference
43. HR08 External teacher reference
44. 所有写操作幂等 (Idempotency-Key)
45. 所有并发写乐观锁 (If-Match/object version)
46. Tenant isolation at DB/FK level
47. File security (private storage/signed URL/permission before download)
48. 文件 MIME/extension/size 校验
49. 敏感数据最小化（不泄露身份证/薪酬给企业导师）
50. 教师 self-only (改 staffId 即 403)
51. 企业导师 scoped access (assignment-link+expiry+field policy)
52. 跨租户访问 fail-closed
53. RETURNED≠REJECTED 语义分离
54. 报名≠完成 语义分离
55. 完成≠VERIFIED 语义分离
56. 培训证书≠职业资格 边界
57. 进修学历→HR03 EducationHistory 写回（非 HR10 重建）
58. 企业实践天数≠企业实践质量
59. VERIFIED 后不可原地修改（revision 机制）
60. Program/Project 发布后不可静默修改内容
61. 名额后端数据库并发控制
62. Provider 不可用≠成功（UNAVAILABLE 显式状态）
63. Completion rule version 绑定 program version
64. 所有审批 snapshot 带 hash 校验
65. Excel 导入管线（staging→validation→error workbook→confirm→async）
66. UI 中文化（所有模板/JS 中文，camelCase + xxxLabel 成对）
67. 不创建第二套 Person/StaffMaster/EducationHistory/请假/考勤/报销系统

---

## 11. 自纠错对照（总册 §178 的 30 问）

| # | 问题 | 状态 |
|---|---|---|
| 1 | 培训、进修、企业实践三个概念是否被错误合并？ | ✅ 总册已分离为 HrLearningProgram / HrFurtherStudyCase / HrEnterprisePracticeProject |
| 2 | 报名是否被误当完成？ | ✅ DESIGN ENFORCED：Enrollment ≠ Completion ≠ DevelopmentFact |
| 3 | 培训证书是否被误当职业资格？ | ✅ COMPLETION_CERTIFICATE→HR10; PROFESSIONAL_CREDENTIAL→HR09 |
| 4 | 进修学位是否在 HR10 重复建权威？ | ✅ FurtherStudy 只管过程；学位通过 Provider 写 HR03 EducationHistory |
| 5 | 企业实践是否只剩天数？ | ✅ PositionScene/Activity/Evidence/Evaluation/Output 完整 |
| 6 | 真实岗位/场景是否结构化？ | ✅ HrPracticePositionScene 模型 |
| 7 | 企业导师与外聘教师身份是否混淆？ | ✅ Mentor≠ExternalTeacher; 仅当有正式 engagement 时引用 HR08 |
| 8 | 安全/保密/IP 是否有前置？ | ✅ Prerequisite gate 控制 READY_TO_START |
| 9 | 实践时长是否从 verified ledger 计算？ | ✅ Duration ledger 模型 |
| 10 | 线上培训是否被签到模型卡死？ | ✅ Delivery mode ONLINE_ASYNC→provider progress evidence |
| 11 | 外部学习补录是否区分自报/核验？ | ✅ source/trust 分离 |
| 12 | 名额是否有数据库并发保护？ | ✅ DESIGN ENFORCED |
| 13 | 预算是否只是前端数字？ | ✅ DB constraint + reservation ledger |
| 14 | RETURNED/REJECTED 是否分离？ | ✅ DESIGN ENFORCED |
| 15 | 取消/撤回/no-show/fail 是否分离？ | ✅ DESIGN ENFORCED |
| 16 | Provider 不可用是否被当 0/Pass？ | ✅ SOURCE_UNAVAILABLE 显式状态 |
| 17 | 已完成历史是否受最新项目版本污染？ | ✅ Version frozen + snapshot |
| 18 | HR09 是否只读 verified HR10 facts？ | ✅ DESIGN ENFORCED |
| 19 | 企业导师是否存在越权读取 PII？ | ✅ scoped access + field policy |
| 20 | GPS 是否被错误设为强制真实性证明？ | ✅ 默认不强制 GPS |
| 21 | Excel 是否绕过核验直接生成事实？ | ✅ staging→validation→confirm 管线 |
| 22 | Legacy free-text 是否被直接当 authoritative？ | ✅ MIGRATED_FREE_TEXT trust level |
| 23 | as-of 合规是否可复现？ | ✅ DESIGN ENFORCED |
| 24 | 培训学时/学分/实践天数是否错误混账？ | ✅ MetricLedger 分账 |
| 25 | 成果是否重复计数？ | ✅ duplicate_group_id + content_hash |
| 26 | 教务/科研/财务下游是否被 HR10 复制？ | ✅ 只存 ref，不复制 |
| 27 | 外聘教师参与是否有 policy scope？ | ✅ Policy check: allow_external_teacher |
| 28 | 历史 correction 是否保留 revision？ | ✅ revision_no + supersedes_id |
| 29 | 文件 URL 是否安全？ | ✅ short signed URL + 下载前再鉴权 |
| 30 | 关键写操作是否幂等/事务/Outbox？ | ✅ DESIGN ENFORCED |

全部 30 问在设计层面已覆盖，施工时逐项落地。

---

**文档状态：S0_V1 — 基线复审完成。P0=67（横向 13 + 子模块 40 + 跨域 4 + P0 清单展开），P1=54，P2=28。施工按总册 §179 顺序执行。**
**交叉引用：** `HR10_TASK_TREE.md`（施工计划）、`HR10_RISK_REGISTER.md`（风险登记）、`legacy/HR10_LegacyDevelopmentMapping.md`（旧代码接管）、`HR10_INTEGRATION_MATRIX.md`（跨域集成）、`HR10_DevelopmentActivityTaxonomy.md`（活动分类）、`HR10_TrainingProviderMatrix.md`（机构矩阵）、`HR10_EnterprisePracticePolicyMap.md`（政策映射）、`HR10_PracticeEvidenceMatrix.md`（证据矩阵）。
