# 16_HR16_退休与离校_施工总册（终极冻结版）

> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 前置标准：继承 HR01–HR15 的 A0 多学校 fail-closed、API（`/api/v1/hr`）、权限/数据范围、文件安全、敏感字段、异步任务、审计、可观测性、Excel、幂等、事务、Outbox、规则/模板版本冻结、Legacy 退出和 AI 施工纪律。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、数据库目标（MySQL-only）、事件、权限、Legacy、审计、安全和最终生产 Gate。
> PATCH-08 边界：正式处分导致开除/解除必须消费 PersonnelDecision（HR03），HR16 不自己判处分；档案转递走 ArchiveProvider receipt/reconciliation。

> 产品：跃科高校人事管理与教师发展系统  
> 二级模块：HR16 退休与离校  
> 三级模块数量：6  
> 总体策略：REWRITE（接管 Horilla `offboarding/` 离校 Authority；保留 Resignation、Notice Period、Exit Interview、Work Handover、FnF、Task/Pipeline/Dashboard 等可复用底座；重建高校/事业单位退休、辞职、调出、解除/终止、离校交接、最终结算、档案/关系转移、权限清退和返聘衔接的正式事实链）  
> 版本：V1.0 终极冻结版  
> 适配底座：Horilla HRMS 2.0 / `penghaibin9/renshi`  
> 编写日期：2026-08-08  
> 核心原则：**辞职申请 ≠ 人事关系已终止；合同终止 ≠ 离校完成；退休年龄预测 ≠ 退休资格已核定；退休批准 ≠ 当日立即停权；离校任务完成 ≠ 最终工资已支付；账号停用 ≠ Employment 终止；退休 ≠ 删除员工；返聘 ≠ 撤销退休。**
# 0. 六个三级模块冻结

```text
HR16 退休与离校
├─ HR16-01 离退制度与离校规则
├─ HR16-02 辞职调出与解除离校
├─ HR16-03 退休预审与退休办理
├─ HR16-04 离校交接与权限资产清退
├─ HR16-05 结算证明与关系转移
└─ HR16-06 离退休档案与返聘衔接
```

职责：
- HR16-01：原因、程序、通知期、日期语义、任务模板、Completion Gate、退休政策版本。
- HR16-02：辞职、外部调出、不续聘、解除/终止、开除等正式退出 Case。
- HR16-03：法定/弹性/特殊退休预测、预审、意向、审批、生效、养老待遇办理状态。
- HR16-04：工作、教学、科研、学生、资产、财务、IAM、门禁、图书、数据等交接。
- HR16-05：HR15 最终结算、HR03 生效、HR14/HR02 岗位释放、证明、档案与关系转移、对账。
- HR16-06：ExitFact/RetirementFact、离退历史、退休人员投影、返聘衔接、档案、风险与更正。

# 1. 结论先行

```text
Retirement / Resignation / Transfer-out / Contract End / Formal Personnel Decision
                                   ↓
                                ExitCase
                                   ↓
                         Decision + Date Snapshot
                                   ↓
                          ExitPlanTemplateVersion
                                   ↓
     Work Handover / Teaching / Research / Students / Finance / Assets / IAM
                                   ↓
                            Completion Gate
                                   ↓
           HR07 Contract / HR15 Settlement / HR14 Appointment / IAM
                                   ↓
                            HR03 Exit Effect
                                   ↓
               Employment + Assignment closed as facts
                                   ↓
            HR02 position release / certificates / archive transfer
                                   ↓
                       ExitFact / RetirementFact
                                   ↓
                           HR17 / HR18
```

退休额外链：
`RetirementPolicyVersion → StatutoryDate/FlexibleWindow → Precheck → Intent/Approval → PlannedDate → Offboarding → RetirementEffective → PensionProcessingStatus`。

# 2. 生产级红线

- 不得把 `Employee.is_active=False` 当离校 Authority。
- 不得批准辞职后立即删除 Employee/Staff。
- 不得把 `ResignationLetter.approved` 等同 EmploymentRelationship terminated。
- 不得合同到期自动等于离校完成。
- 不得 HR12 年度不合格自动停账号或触发离校。
- 不得 HR14 岗位终止自动等于人事关系终止。
- 不得把 last working date、employment end、contract end、appointment end、retirement date、access end 混成一个日期。
- 不得用出生年份粗算退休日期。
- 不得只用性别字段推断退休类别。
- 不得写死旧的 60/55/50 退休年龄逻辑作为当前唯一规则。
- 不得忽略 2025-01-01 起渐进式延迟法定退休年龄。
- 不得把弹性提前/延迟退休做成管理员任意改日期。
- 不得退休预警等同退休批准。
- 不得退休批准等同养老待遇已核定。
- 不得返聘通过把 RETIRED 改回 ACTIVE 实现。
- 不得离校任务只用一个 checkbox。
- 不得本人确认财务/资产清缴即算完成。
- 不得 HR 人员伪造 IAM/资产/财务 Provider 回执。
- 不得 Provider unavailable 当 CLEARED。
- 不得账号停用等于 Employment 终止。
- 不得离校后删除合同、考核、职称、岗位聘任、工资历史。
- 不得敏感离职原因扩散给普通任务负责人。
- 不得档案转递用公开下载链接替代正式转递。
- 不得结算请求已创建就标记工资已支付。
- 不得 Future retirement 与 HR07/HR14/HR06 future event 冲突不检查。
- 不得 Excel 批量直接设 RETIRED/TERMINATED。
- 不得 legacy Archived 自动升级成正式 ExitFact。
- 不得 silent legacy fallback。
- 不得 AI 自动批准离职/辞退/退休。
- 不得 AI 自动判定退休类别。
- 不得 AI 自动 waive HARD task。
- 不得为过测试关闭 403。
- 不得只跑 SQLite；最终 MySQL 回归必须通过。
- 不得施工阶段合并 main 或部署生产。

# 3. 事业单位关系终止制度基线

辞职、解除/终止聘用合同、处分开除等需要明确制度依据和程序；系统必须把来源决定、通知、合同事实、人事关系生效分开留痕。

# 4. 2025 渐进式延迟退休基线

从 2025-01-01 起实施渐进式延迟法定退休年龄。HR16 必须以 `RetirementPolicyVersion` + 官方规则/附表为权威，不允许用旧年龄常数继续算。

# 5. 弹性提前退休

必须记录员工自愿意向、可选区间、书面告知、缴费资格来源、审批/程序和选定日期；单位不能替员工选择。

# 6. 弹性延迟退休

必须记录达到法定年龄、员工意向、单位协商同意、批准路径、约定延迟日期和合同/岗位/工资影响。

# 7. 管理人员退休程序

涉及干部人事管理权限和规定程序时，用 AuthorityResolver 决定审批链，不靠岗位名字符串。

# 8. 养老金资格边界

HR16 只消费养老资格/最低缴费年限 Provider，不能自行计算养老金待遇金额。

# 9. 特殊退休边界

特殊工种、病残等如适用，必须独立类型、权威资格、材料、审批和政策版本。

# 10. 人事档案转递

HR16 管转出 Case/目录/渠道/回执，真正档案卷宗归 ArchiveProvider；个人下载文件不等于正式转递。

# 11. Horilla 当前可复用能力

当前 `offboarding/` 已有 Offboarding、OffboardingStage、OffboardingEmployee、ResignationLetter、Task、Notes/files、Pipeline/Dashboard、Notice Period、Exit Interview、Work Handover、FnF、Archive，可复用任务和交互底座。

# 12. Horilla 模型根问题

当前 `OffboardingEmployee.employee_id` 一对一绑定 Employee，默认 Stage 驱动流程；生产级必须改为 `ExitCase` 聚合根，使同一自然人可多次 employment→exit→rehire。

# 13. Horilla Resignation 风险

当前 ResignationLetter 缺政策、审批链、合同影响、日期语义、撤回、生效、下游对账。

# 14. Horilla Stage 风险

默认 Notice/Interview/Handover/FnF/Farewell/Archived 只能作为模板；高校必须用 `ExitPlanTemplateVersion` 生成任务 DAG。

# 15. 总体接管策略

`strategy = REWRITE`；KEEP Task/Pipeline/Dashboard，ADAPT Resignation/Stage，NEW ExitCase/RetirementFact/Provider receipts/Effect/Reconciliation Authority。

# 16. HR02 边界

HR02 管岗位/编制/Position。HR16 生效后经 HR14/HR03 正式关闭任职，再由 HR02 occupancy 事实释放岗位。

# 17. HR03 边界

HR03 管 Person/Staff/EmploymentRelationship/Assignment。HR16 通过 `apply_exit_effect` 请求 HR03 原子关闭事实并保存 receipt。

# 18. HR06 边界

校内调动仍属 HR06；真正离开学校/法人主体的调出才进入 HR16。

# 19. HR07 边界

HR07 管合同解除/终止；HR16 管离校编排。HR07 发 `OffboardingRequired`，HR16 Gate 可要求 Agreement 已结束。

# 20. HR11 边界

HR11 管考勤/休假；HR16 只读离校期间相关事实，不自行扣工资/改余额。

# 21. HR12 边界

HR12 正式考核可作为人事处理证据之一，但不得单独自动触发解除/停权。

# 22. HR14 边界

HR16 ExitEffective 后 HR14 关闭 AppointmentTerm，再由 HR02 释放岗位。

# 23. HR15 边界

HR16 只提供 final dates、exit type、SettlementRequested、任务状态；HR15 算最终工资/税社保公积金/支付。

# 24. HR17 边界

HR17 提供教职工服务入口和退休后日常服务；HR16 保持离退事实 Authority。

# 25. HR18 边界

HR18 只消费 FINAL/EFFECTIVE 离退统计，不读取草稿和私密面谈正文。

# 26. IAM 边界

IAM 负责账号/权限。HR16 编排 planned/effective deprovision，保存 provider receipt。

# 27. 资产边界

资产系统负责设备真值；HR16 请求 outstanding/return receipt，不复制资产台账。

# 28. 教务边界

课程、成绩、监考、学生指导等由教务完成正式交接，HR16 只消费 receipt。

# 29. 科研边界

项目、经费、实验室、数据/IP等由科研 Authority 变更，HR16 只编排。

# 30. 财务边界

财务系统提供借款/报销/项目责任 clearance；本人不可自行确认。

# 31. 档案边界

HR16 管档案转递过程，ArchiveProvider 管人事档案卷宗。

# 32. 离退类型枚举

`RESIGNATION / EXTERNAL_TRANSFER_OUT / CONTRACT_NON_RENEWAL / CONTRACT_TERMINATION / EMPLOYER_TERMINATION / DISMISSAL / DISCIPLINARY_DISMISSAL / STATUTORY_RETIREMENT / FLEXIBLE_EARLY_RETIREMENT / FLEXIBLE_DELAYED_RETIREMENT / SPECIAL_RETIREMENT / DEATH / OTHER`。

# 33. ExitCase 状态

`DRAFT → SUBMITTED/INITIATED_BY_AUTHORITY → UNDER_REVIEW → APPROVED/REJECTED/RETURNED → NOTICE_OR_PREPARATION → OFFBOARDING_IN_PROGRESS → READY_FOR_EFFECT → EFFECT_PENDING → EFFECTIVE → POST_EXIT_COMPLETION → CLOSED → ARCHIVED`。

# 34. 退休 Case 状态

`FORECASTED → PRECHECK → ELIGIBLE/NOT_YET_ELIGIBLE/NEEDS_REVIEW → INTENT_COLLECTED → APPROVAL_IN_PROGRESS → APPROVED → OFFBOARDING → RETIREMENT_EFFECT_PENDING → RETIRED → BENEFIT_PROCESSING → BENEFIT_CONFIRMED/BENEFIT_EXCEPTION → ARCHIVED`。

# 35. Task 状态

`NOT_STARTED / READY / IN_PROGRESS / WAITING_EXTERNAL / BLOCKED / COMPLETED / WAIVED / NOT_APPLICABLE / FAILED / CANCELLED`。

# 36. 阻塞级别

`HARD_BLOCK / SOFT_BLOCK / WARNING / INFO`；HARD waive 需要特权、依据和审批。

# 37. Effect 状态

`NOT_READY / READY / APPLYING / PARTIAL_EFFECT / EFFECTIVE / RECONCILIATION_REQUIRED / RECONCILED`。

# 38. 档案转递状态

`NOT_REQUIRED / PENDING_DESTINATION / READY_TO_SEND / SENT / IN_TRANSIT / RECEIVED / REJECTED / RETURNED / RECONCILED`。

# 39. 返聘衔接状态

`INTENT / ELIGIBILITY_REVIEW / APPROVED_FOR_REHIRE / HANDOFF_TO_HR05_OR_HR08 / NEW_RELATIONSHIP_PENDING / ACTIVE_REHIRE / CLOSED`。

# 40. HR16-01 离退制度与离校规则｜业务目标

本工作区按本册 Authority 边界实现，禁止退化为通用 CRUD；所有正式结果必须具备版本、来源、权限、审计、有效日期和下游回执。

# 41. HR16-01 离退制度与离校规则｜ExitReasonCatalog

原因 code/category、voluntary/involuntary/retirement、员工可见标签、内部敏感标签、report mapping、certificate exposure、valid period。

# 42. HR16-01 离退制度与离校规则｜ExitPolicyPack/Version

适用人员、原因、通知规则、审批、日期、协议 Gate、任务模板、Completion Gate、证明、档案、effective date，PUBLISHED 后 immutable。

# 43. HR16-01 离退制度与离校规则｜日期语义

request_date、notice_date、planned/approved last_working、contract_end、appointment_end、employment_end、retirement_effective、access_end_at、payroll_cutoff 分字段。

# 44. HR16-01 离退制度与离校规则｜NoticeRule

通知期限、工作日/自然日、HR07 条款来源、waive、特殊例外。

# 45. HR16-01 离退制度与离校规则｜CompletionGate

工作交接、合同、结算、资产、财务、IAM、档案等逐项定义 HARD/SOFT/WARN/INFO。

# 46. HR16-01 离退制度与离校规则｜ExitPlanTemplateVersion

按退出类型/人员类别/组织/岗位生成任务、owner、due、dependency、evidence、waive、SLA。

# 47. HR16-01 离退制度与离校规则｜Task DAG 校验

无环、owner 可解析、Provider 存在、HARD dependency 可达、due offset 合法。

# 48. HR16-01 离退制度与离校规则｜RetirementPolicyVersion

官方来源、生效期、退休类别映射、法定年龄计算、弹性区间、特殊规则、管理审批、缴费资格 Provider。

# 49. HR16-01 离退制度与离校规则｜RetirementCategoryAssignment

不得由 gender 自动推断；保存 category_code/source/evidence/verified_by/effective period。

# 50. HR16-01 离退制度与离校规则｜Retirement Simulator

返回 policy、statutory date、earliest/latest、category、pension status、future event conflicts、warnings；只做预检。

# 51. HR16-01 离退制度与离校规则｜发布 Gate

历史 fixture、出生月边界、2024/2025 边界、弹性区间、特殊类别回归。

# 52. HR16-01 离退制度与离校规则｜UI

`/hr/exits/policies`、`/hr/exits/reasons`、`/hr/exits/task-templates`、`/hr/retirement/policies`、`/hr/retirement/simulator`。

# 53. HR16-02 辞职调出与解除离校｜业务目标

本工作区按本册 Authority 边界实现，禁止退化为通用 CRUD；所有正式结果必须具备版本、来源、权限、审计、有效日期和下游回执。

# 54. HR16-02 辞职调出与解除离校｜ExitCase

case_no/person/staff/relationship/exit_type/reason/source/policy/requested dates/approved dates/authority/status/version/sensitivity。

# 55. HR16-02 辞职调出与解除离校｜本人辞职

SELF token 解析，planned date/reason/statement/contact/ack/attachments，禁止传他人 staff_id。

# 56. HR16-02 辞职调出与解除离校｜辞职撤回

WithdrawalRequest + allowed stage + approval + notice/task impact；EFFECTIVE 后不可撤回。

# 57. HR16-02 辞职调出与解除离校｜外部调出

receiving unit、approval、destination、档案转递、position/payroll/IAM impact；校内调动不走 HR16。

# 58. HR16-02 辞职调出与解除离校｜不续聘

消费 HR07 DO_NOT_RENEW/expiry 决定，不因合同到期自动 terminate。

# 59. HR16-02 辞职调出与解除离校｜组织解除/终止

必须引用正式 HR07/personnel decision、policy/legal basis、notice proof、effective date。

# 60. HR16-02 辞职调出与解除离校｜处分开除

只引用正式处分/人事处理 Authority fact，不复制调查正文。

# 61. HR16-02 辞职调出与解除离校｜死亡特殊 Case

verified death source、urgent IAM、资产/工资/档案、无本人任务、隐私最小化。

# 62. HR16-02 辞职调出与解除离校｜Case 来源

SELF_RESIGNATION / HR07_OFFBOARDING_REQUIRED / HR16_RETIREMENT / AUTHORIZED_PERSONNEL_DECISION / HR06_EXTERNAL_TRANSFER / MIGRATION_VERIFIED。

# 63. HR16-02 辞职调出与解除离校｜Decision Snapshot

原因、authority、policy、approved dates、source docs、contract/assignment/appointment/manager snapshot、hash。

# 64. HR16-02 辞职调出与解除离校｜日期冲突

通知、合同、未来聘任、长期休假、Payroll cutoff、教学任务、Legal Hold 等冲突。

# 65. HR16-02 辞职调出与解除离校｜RETURNED vs REJECTED

退回补正与正式不批准分离。

# 66. HR16-02 辞职调出与解除离校｜Sensitive Reason

普通 task owner 只见执行必要信息，不自动看到处分/医疗/争议细节。

# 67. HR16-02 辞职调出与解除离校｜UI

`/hr/exits/requests`、`/hr/exits/cases`、`/hr/exits/approvals`。

# 68. HR16-03 退休预审与退休办理｜业务目标

本工作区按本册 Authority 边界实现，禁止退化为通用 CRUD；所有正式结果必须具备版本、来源、权限、审计、有效日期和下游回执。

# 69. HR16-03 退休预审与退休办理｜RetirementForecast

staff/statutory date/flexible dates/policy/category/source/warnings/next action/generated_at；forecast 可重算非正式事实。

# 70. HR16-03 退休预审与退休办理｜Watch Window

T-24/T-12/T-6/T-3/T-1 等 tenant 配置，提醒 dedupe。

# 71. HR16-03 退休预审与退休办理｜退休预审

DOB、category、employment、pension provider、contract/appointment、special rule、争议、审批权限、材料。

# 72. HR16-03 退休预审与退休办理｜PensionEligibilityProvider

ELIGIBLE/NOT_ELIGIBLE/PARTIAL/UNAVAILABLE/NEEDS_MANUAL_REVIEW；不算养老金金额。

# 73. HR16-03 退休预审与退休办理｜法定退休

scheduler 只能建预审/待办，不能自动 RETIRED。

# 74. HR16-03 退休预审与退休办理｜弹性提前

本人意向、chosen date、window validation、书面通知、pension eligibility、approval。

# 75. HR16-03 退休预审与退休办理｜弹性延迟

statutory date、employee intent、unit agreement、authority、agreed end date、HR07/14/15 impact。

# 76. HR16-03 退休预审与退休办理｜日期变更

approved date 改动走 RetirementDateChangeCase，旧版本保留。

# 77. HR16-03 退休预审与退休办理｜特殊退休

special eligibility provider、材料、审批、policy ref，禁止 self-certification。

# 78. HR16-03 退休预审与退休办理｜管理人员程序

AuthorityResolver 判定干部人事权限，不能按 JobPosition 名称硬判。

# 79. HR16-03 退休预审与退休办理｜退休材料

notice/application、identity refs、contribution facts、file verification、approval、agency receipt；敏感 ACL。

# 80. HR16-03 退休预审与退休办理｜批准与待遇分离

RetirementDecision APPROVED/EFFECTIVE 与 PensionBenefitProcess 独立。

# 81. HR16-03 退休预审与退休办理｜待遇异常

退休可生效，养老金办理异常进入 post-exit Case，不回滚退休事实。

# 82. HR16-03 退休预审与退休办理｜Events

RetirementApproved / RetirementEffective / ExitEffective / PensionProcessingRequested / RetireeServiceProfileRequested。

# 83. HR16-03 退休预审与退休办理｜UI

`/hr/retirement/forecast`、`/hr/retirement/precheck`、`/hr/retirement/cases`、`/hr/retirement/benefit-status`。

# 84. HR16-04 离校交接与权限资产清退｜业务目标

本工作区按本册 Authority 边界实现，禁止退化为通用 CRUD；所有正式结果必须具备版本、来源、权限、审计、有效日期和下游回执。

# 85. HR16-04 离校交接与权限资产清退｜ExitPlanInstance

case/template version/generated tasks/owner snapshot/due/dependencies/blocking/hash。

# 86. HR16-04 离校交接与权限资产清退｜ExitTask

owner/provider/due/dependency/block/evidence/status/completion source/receipt/version。

# 87. HR16-04 离校交接与权限资产清退｜工作交接

职责、在办事项、文档、共享数据、successor、manager acceptance；禁止交接密码。

# 88. HR16-04 离校交接与权限资产清退｜教学交接

课程、成绩、考试、学生指导、课程资源、教学项目由 AcademicProvider 回执。

# 89. HR16-04 离校交接与权限资产清退｜科研交接

项目、经费、实验室、数据/样品、IP、学生/团队、合作义务由 ResearchProvider 回执。

# 90. HR16-04 离校交接与权限资产清退｜学生工作交接

辅导员/班主任/导师等职责由学工/教务完成正式变更。

# 91. HR16-04 离校交接与权限资产清退｜财务清缴

FinanceProvider 返回 CLEARED/BLOCKED/PARTIAL/UNAVAILABLE。

# 92. HR16-04 离校交接与权限资产清退｜资产归还

AssetProvider item count/high-risk outstanding/receipt；不复制资产台账。

# 93. HR16-04 离校交接与权限资产清退｜图书馆

LibraryProvider 处理借阅/欠费/特殊责任。

# 94. HR16-04 离校交接与权限资产清退｜门禁证卡

CampusAccessProvider 处理工牌、门禁、停车、食堂等。

# 95. HR16-04 离校交接与权限资产清退｜IAM

privileged pre-revoke、normal effective revoke、email/data retention、service account ownership、retiree portal exception。

# 96. HR16-04 离校交接与权限资产清退｜数据归属

共享盘/代码/科研数据唯一 owner 转移，禁止离校账号成为唯一 owner。

# 97. HR16-04 离校交接与权限资产清退｜高风险权限

服务器/数据库/财务/实验室/危化等可设 PRE_EXIT HARD。

# 98. HR16-04 离校交接与权限资产清退｜宿舍/住房

HousingProvider 可选，不强制所有学校。

# 99. HR16-04 离校交接与权限资产清退｜组织关系

仅保存 transfer status/ref，敏感信息不扩散。

# 100. HR16-04 离校交接与权限资产清退｜Completion Evidence

PROVIDER_RECEIPT / AUTHORIZED_CONFIRMATION / SIGNED_DOCUMENT / SYSTEM_FACT。

# 101. HR16-04 离校交接与权限资产清退｜Waiver

ExitTaskWaiverCase + reason + authority + evidence + approval；HARD 更高权限。

# 102. HR16-04 离校交接与权限资产清退｜Reassignment

old/new owner + reason + effective time。

# 103. HR16-04 离校交接与权限资产清退｜SLA

due/overdue/escalation/reminder dedupe。

# 104. HR16-04 离校交接与权限资产清退｜Completion Gate

所有 HARD completed/authorized waived + required downstream readiness 才 READY_FOR_EFFECT。

# 105. HR16-04 离校交接与权限资产清退｜UI

`/hr/exits/workbench`、`/hr/exits/cases/{id}/plan`、`/hr/exits/tasks`、`/hr/exits/provider-status`。

# 106. HR16-05 结算证明与关系转移｜业务目标

本工作区按本册 Authority 边界实现，禁止退化为通用 CRUD；所有正式结果必须具备版本、来源、权限、审计、有效日期和下游回执。

# 107. HR16-05 结算证明与关系转移｜Settlement Request

HR16→HR15：relationship、exit type、final working/employment date、recovery refs、deadline；返回 SettlementCase status。

# 108. HR16-05 结算证明与关系转移｜Settlement Gate

REQUESTED/CALCULATED/APPROVED/PAID 哪级 HARD 由 policy 配置，不能全局写死。

# 109. HR16-05 结算证明与关系转移｜HR07 Gate

需结束的 Agreement 全部有 EFFECTIVE/ENDED receipt；Legal Hold 单独处理。

# 110. HR16-05 结算证明与关系转移｜HR14 Gate

exit 后关闭 appointment；失败进入 reconciliation。

# 111. HR16-05 结算证明与关系转移｜HR03 Effect

apply_exit_effect(staff, relationship, dates, type, case, decision_ref)，幂等。

# 112. HR16-05 结算证明与关系转移｜HR03 Receipt

closed assignments、relationship status、staff projection、event id、effect time/conflicts。

# 113. HR16-05 结算证明与关系转移｜IAM 时序

高权限可提前撤，普通权限按 effective cutoff，退休门户例外。

# 114. HR16-05 结算证明与关系转移｜离职证明

template/version/visible fields/reason policy/verification code/hash/issuer；敏感原因默认不放。

# 115. HR16-05 结算证明与关系转移｜退休证明

引用 RetirementDecision/Fact，不从 current status 反推。

# 116. HR16-05 结算证明与关系转移｜档案转递 Case

destination、basis、manifest、channel、tracking、sent/received/reject/return receipt。

# 117. HR16-05 结算证明与关系转移｜社保公积金

只显示 HR15 statutory stop/transfer status/ref。

# 118. HR16-05 结算证明与关系转移｜组织关系

Provider 状态，不自建完整党务系统。

# 119. HR16-05 结算证明与关系转移｜证明验证

公开 endpoint 返回最小真伪信息。

# 120. HR16-05 结算证明与关系转移｜EFFECTIVE vs CLOSED

EFFECTIVE=人事退出已生效；CLOSED=post-exit 必要任务/对账完成。

# 121. HR16-05 结算证明与关系转移｜Post-exit Outstanding

外部支付/档案/回执继续 owner/SLA 跟踪。

# 122. HR16-05 结算证明与关系转移｜最终对账

Exit vs HR03 closed vs HR14 closed vs HR02 released vs HR15 settlement vs IAM revoke vs asset clearance。

# 123. HR16-05 结算证明与关系转移｜UI

`/hr/exits/effect-workbench`、`/hr/exits/settlements`、`/hr/exits/certificates`、`/hr/exits/archive-transfer`、`/hr/exits/reconciliation`。

# 124. HR16-06 离退休档案与返聘衔接｜业务目标

本工作区按本册 Authority 边界实现，禁止退化为通用 CRUD；所有正式结果必须具备版本、来源、权限、审计、有效日期和下游回执。

# 125. HR16-06 离退休档案与返聘衔接｜ExitFact

case/person/staff/relationship/type/final working/employment end/decision/policy/effective/revision/hash；EFFECTIVE immutable。

# 126. HR16-06 离退休档案与返聘衔接｜RetirementFact

relationship/type/statutory/chosen/effective/policy/approval/pension status/revision/hash。

# 127. HR16-06 离退休档案与返聘衔接｜退休投影

HR03/HR17 展示 retired/date/former org/position snapshot/service category；不复制 Person。

# 128. HR16-06 离退休档案与返聘衔接｜退休后服务

慰问、活动、服务门户归 HR17，HR16 仅提供 facts。

# 129. HR16-06 离退休档案与返聘衔接｜返聘原则

RetirementFact 永久保留，返聘走新 relationship/engagement。

# 130. HR16-06 离退休档案与返聘衔接｜返聘政策

allowed categories/qualifications/approval/relationship type/contract/pay/tax/social/term 等 versioned。

# 131. HR16-06 离退休档案与返聘衔接｜RehireReferral

HR16 发起 referral，HR05/HR08/HR03 执行新关系，不复活旧 relationship。

# 132. HR16-06 离退休档案与返聘衔接｜多次生命周期

employment1→exit→rehire employment2→exit2，各段独立。

# 133. HR16-06 离退休档案与返聘衔接｜历史更正

CorrectionCase + FactRevision，不原地改 EFFECTIVE。

# 134. HR16-06 离退休档案与返聘衔接｜决定撤销

未 effect 可 cancel/supersede；已 effect 后走新的恢复/重新聘用程序。

# 135. HR16-06 离退休档案与返聘衔接｜证明重发

CertificateVersion V2，原 issue/hash 保留；旧验证显示 superseded。

# 136. HR16-06 离退休档案与返聘衔接｜政策变化

只影响未来/未 final Case，不改已退休事实。

# 137. HR16-06 离退休档案与返聘衔接｜ArchivePackage

decision/tasks/receipts/certificate/transfer/hash manifest。

# 138. HR16-06 离退休档案与返聘衔接｜Risk Center

category unknown、effect mismatch、IAM active、position not released、settlement/file transfer failed、rehire overlap、legacy drift。

# 139. HR16-06 离退休档案与返聘衔接｜UI

`/hr/exits/history`、`/hr/retirement/retirees`、`/hr/retirement/rehire-referrals`、`/hr/exits/archive`、`/hr/exits/risk`。

# 140. 核心模型关系说明

权威聚合分为四层：
1. Policy：为什么、什么条件、哪些任务；
2. Case：某个人这一轮离退的业务过程；
3. Effect：正式生效与各下游实际结果；
4. Fact：不可变的最终退出/退休事实。

Task/Pipeline 绝不能反过来成为最终 Fact Authority。

# 141. HrExitReason

字段至少：
`tenant_id / code / category / employee_label / internal_label / reporting_code / sensitivity / certificate_visibility / valid_from / valid_to / version`。

原因字典必须 effective-dated。

# 142. HrExitPolicyPack

按人员类别/关系/退出类型分组。
一个学校可同时存在：
- 在编人员；
- 合同制；
- 外聘；
- 管理岗位；
- 专技岗位；
- 特殊人员
不同离校 Policy。

# 143. HrExitPolicyVersion

发布后 immutable。
包含：
- notice；
- approval；
- date semantics；
- task templates；
- gate；
- documents；
- certificate wording rules；
- archive transfer；
- post-exit；
- downstream effect timing。

# 144. HrExitPlanTemplate

模板 Root 只负责身份与版本引用，不直接保存当前可变任务。

# 145. HrExitPlanTemplateVersion

每版冻结：
- task DAG；
- owner resolver；
- due offsets；
- blocking level；
- completion source；
- evidence rule；
- waiver rule；
- provider contract；
- applicable case types。

# 146. HrExitTaskDefinition

任务定义有稳定 task_code。
不得用标题作为程序判断。
标题可本地化，业务代码只能识别 task_code/type。

# 147. HrExitCompletionGateRule

Gate 用显式 predicate：
- TASK_STATUS；
- PROVIDER_STATUS；
- AGREEMENT_STATUS；
- SETTLEMENT_STATUS；
- EFFECT_STATUS；
- DOCUMENT_STATUS；
- CUSTOM_TYPED_RULE。

禁止任意 Python eval。

# 148. HrExitCase

Case 是离退流程聚合根。
一个 Staff 可历史多个 Case，但同一 EmploymentRelationship 同时最多一个互斥 active exit case，除非明确 linked/superseding。

# 149. HrExitDecision

决定与申请分离。
员工“想离职”不是决定；
组织“拟解除”不是已生效；
正式 Decision 保存 authority/source/policy/effective semantics。

# 150. HrExitDecisionVersion

任何退回补正、决定变更、日期变化形成新 Version，旧决定不可覆盖。

# 151. HrExitSubjectSnapshot

进入正式审核/离校时冻结：
- org；
- assignment；
- appointment；
- active agreements；
- manager；
- personnel category；
- access criticality；
- provider versions。

不复制无关家庭/医疗等 PII。

# 152. HrExitDateSnapshot

把所有关键日期显式快照：
request/notice/last_working/employment_end/contract_end/appointment_end/access_end/payroll_cutoff/retirement。

# 153. HrExitPlanInstance

Case 生成的具体 Plan，绑定 template_version + owner_snapshot + generated_at + plan_hash。

# 154. HrExitTask

任务实例不可因模板后来修改而变化；模板变更只影响新 Case 或正式 rebase。

# 155. HrExitTaskEvidence

证据可为：
- ProviderReceipt；
- DocumentRef；
- SystemFactRef；
- AuthorizedConfirmation。
保存 hash/source/status，不保存不必要原文。

# 156. HrExitTaskWaiverCase

Waive 是正式 Case，不是直接把 task.status=WAIVED。

# 157. HrExitTaskReassignment

负责人变化保留 from/to/reason/effective_at/audit。

# 158. HrExitProviderReceipt

统一：
`provider_type / request_id / provider_ref / business_status / received_at / raw_hash / normalized_status / verified / version`。

# 159. HrExitEffect

正式 effect 编排对象：
HR03 effect、HR14 close、HR02 release observed、IAM、HR15 settlement、archive transfer 等。
允许 PARTIAL_EFFECT，但必须 risk/reconciliation。

# 160. HrExitDownstreamEffect

每个下游单独状态，不允许一个 `all_done=True`。

# 161. HrExitReconciliation

保存 expected/observed/difference/owner/SLA/resolution，不静默修数。

# 162. HrRetirementPolicyPack

退休政策按人员类别/主管权限/地区等分包。

# 163. HrRetirementPolicyVersion

官方算法、弹性规则、特殊规则、审批、Provider requirements 全部版本化。

# 164. HrRetirementCategoryAssignment

确定适用退休年龄类别的正式事实，包含 source/evidence/authority/effective period。

# 165. HrRetirementForecast

可重算预测对象；不得被下游当正式退休事实。

# 166. HrRetirementPrecheck

预审结果保存逐项 Gate + source status + policy version。

# 167. HrRetirementCase

正式退休业务 Case，可由 forecast 创建但独立生命周期。

# 168. HrRetirementIntent

本人弹性退休意愿/书面告知的版本化事实。

# 169. HrRetirementDateAgreement

弹性延迟等涉及双方协商日期的正式事实，独立于 HR07 文书。

# 170. HrRetirementApproval

批准 Authority / decision / effective date / document ref / hash。

# 171. HrPensionEligibilitySnapshot

只缓存养老资格 Provider 的受控快照，不是养老金待遇金额 Authority。

# 172. HrPensionProcessingCase

办理状态可晚于 RetirementEffective，不能阻止历史退休事实保存。

# 173. HrRetirementFact

正式退休事实 immutable；更正使用 revision chain。

# 174. HrExitSettlementLink

只关联 HR15 SettlementCase/receipt/status，不复制 payroll 金额。

# 175. HrExitCertificate

证明 root，绑定 ExitFact/RetirementFact。

# 176. HrExitCertificateVersion

模板、可见字段、签发者、文档 hash、verification token、supersedes。

# 177. HrPersonnelFileTransferCase

人事档案转递流程 root。

# 178. HrPersonnelFileTransferReceipt

接收/退回/异常回执独立记录。

# 179. HrRelationshipTransferCase

党团/其他组织关系仅保存最小流程状态/ref，正文在专门 Provider。

# 180. HrExitFact

正式退出事实 immutable，是 HR18/HR17/历史查询消费对象。

# 181. HrRetireeServiceProjection

面向 HR17 的最小退休服务投影，不复制 HR03 主档。

# 182. HrRetireeRehireReferral

返聘衔接引用 RetirementFact，handoff 到 HR05/HR08/HR03。

# 183. HrExitCorrectionCase

用于迁移错误/日期录错/证明元数据等事实更正，不用于撤销真实业务决定。

# 184. HrExitArchivePackage

把 Decision、Plan、Task evidence、Effect receipts、certificate、transfer 等做 manifest/hash。

# 185. HrExitRiskCase

所有 unresolved blocker/drift/provider failures 统一风险对象。

# 186. A0｜Tenant Context

所有 HR16 Authority 表 `tenant_id NOT NULL`。
请求没有 tenant context：
`TENANT_CONTEXT_REQUIRED`。
后台任务、scheduler、Provider callback 必须显式 tenant。

# 187. A0｜跨租户 FK

数据库/服务双层阻断：
- case.staff；
- task.owner；
- policy；
- document；
- receipt；
- relationship；
- archive destination。
禁止跨 tenant 引用。

# 188. A0｜Case ACL

对 Dismissal/Disciplinary/Medical/SpecialRetirement/Death 等高敏 Case：
- participant ACL；
- role ACL；
- field ACL；
- document ACL；
- access log。

普通 SCHOOL scope 也不能自动读取全部敏感正文。

# 189. A0｜SELF 解析

本人 API 必须从 access token → identity → staff/relationship，禁止客户端裸传任意 staff_id。

# 190. A0｜Assigned Task Scope

资产/财务/IAM/教学等负责人只看分配给自己的任务和最小必要 SubjectSnapshot。

# 191. A0｜Break-glass

紧急敏感 Case 访问需 reason、时限、审批/授权策略、完整审计。

# 192. A0｜File Security

所有正式决定、退休材料、证明源文件、档案转递资料 private object storage；签名 URL 短 TTL。

# 193. A0｜PII Masking

列表默认遮罩身份证/联系方式/档案编号；只有业务必要角色可查看完整字段。

# 194. A0｜Audit

每个关键动作记录：
tenant / actor / role / action / object / before-after / reason / request_id / source policy / timestamp。
Provider receipt 和敏感查看也审计。

# 195. A0｜Request Correlation

Case、Task、Effect、ProviderRequest、Outbox event 全部可从 request_id/correlation_id 串起来。

# 196. A0｜Version Contract

Case/Decision/Task/Effect/Policy 使用 version + optimistic locking；客户端 stale write 返回 409。

# 197. A0｜Idempotency-Key Contract

所有 create/effect/callback/receipt/import 类写操作支持稳定幂等键和结果重放。

# 198. A0｜Outbox Atomicity

状态变化与 Outbox event 同事务，禁止先 commit 业务再 best-effort 发事件。

# 199. A0｜Inbox De-dup

Provider webhook/event 的 provider_event_id tenant-scoped unique，重复事件不重复完任务/停权。

# 200. A0｜Provider Typed Contract

Provider 返回 typed payload + normalized status + sourceUpdatedAt + sourceVersion；禁止靠字符串备注判断完成。

# 201. A0｜Provider Fail-closed

`UNAVAILABLE/STALE/ERROR` 不得归一为 CLEARED/COMPLETED。

# 202. A0｜Provider Retry

指数退避、最大尝试、dead-letter/quarantine、人工重放；每次 attempt 记录。

# 203. A0｜Provider Reconciliation

对所有具有外部状态的 Provider 定期 pull/query，对 callback 丢失进行补偿。

# 204. A0｜Job State

`PENDING → RUNNING → SUCCESS/PARTIAL_FAILED/FAILED/CANCELLED`；批量 forecast/export/provider refresh 使用 Job。

# 205. A0｜Scheduler Idempotency

退休 forecast、提醒、到期 effect、post-exit followup 调度器按 natural key 去重。

# 206. A0｜Notification

通知模板版本化、recipient scope、去重键、retry、delivery status；敏感原因不进普通短信/邮件标题。

# 207. A0｜Error Envelope

统一：
```json
{
  "data": null,
  "meta": {"requestId":"..."},
  "error": {"code":"HARD_TASK_INCOMPLETE","message":"...","details":{}}
}
```

# 208. A0｜API Compatibility

v1 additive-only；enum 未知值前端 fallback；breaking change 使用 v2。

# 209. A0｜Data Freshness

Forecast/dashboard 可以缓存；Final Effect、IAM revoke、资产/财务 clearance 必须实时/强一致或明确 source status。

# 210. A0｜Data Provenance

所有决定日期、退休日期、任务完成、证明字段必须能追到 authority/source/provider/version。

# 211. A0｜No Silent Fallback

新 Authority 读失败时不能自动读 legacy offboarding/employee.active 并伪装正常。

# 212. A0｜Reason Code Registry

业务 reason_code 稳定；展示文本/本地化可以变化，统计只用 code + versioned mapping。

# 213. A0｜Sensitivity Classification

`PUBLIC_INTERNAL / HR_CONFIDENTIAL / HIGHLY_RESTRICTED / LEGAL_HOLD` 等分类驱动 field/document policy。

# 214. A0｜Retention Class

不同 task/evidence/interview/legal/retirement docs 有 retention class；禁止一刀切永久保存自由文本。

# 215. A0｜Legal Hold

Case 被仲裁/诉讼/审计 hold 后禁止 purge，直到正式 release。

# 216. A0｜Time Zone

日期/时间统一 tenant timezone；政策日期用 date，操作事件用 timezone-aware datetime。

# 217. A0｜Calendar

notice/task due 可用工作日或自然日，CalendarProvider/HR11 日历版本必须冻结。

# 218. A0｜Public Verification

证明验证 token 不可枚举；只展示最小字段；revoked/superseded 状态可见。

# 219. A0｜Sensitive Export

高敏导出需专门 permission + reason + short-lived artifact + watermark + audit。

# 220. A0｜Bulk Safety

批量创建 Case/Forecast 先 preview；每人独立 row result；部分失败不回滚成功行但必须可追踪。

# 221. A0｜No Delete of Facts

EFFECTIVE ExitFact/RetirementFact/Certificate issue history 不 hard delete。

# 222. A0｜Correction Semantics

数据更正与业务撤销/恢复分离；Correction 只产生 revision chain。

# 223. A0｜Event Ordering

消费者使用 aggregate_version；旧事件晚到不能覆盖新状态。

# 224. A0｜Impact Analysis

离退日期/决定变更前必须计算 HR07/14/15/IAM/教学/科研影响，不允许直接改日期。

# 225. A0｜Transition Reservation

未来 ExitEffect 可登记 relationship transition reservation，阻止后续不兼容 Future Appointment/Transfer。

# 226. A0｜Transition Conflict Types

`HARD_OVERLAP / REBASE_REQUIRED / DEPENDENCY_CONFLICT / INFORMATIONAL`。

# 227. A0｜Effect Orchestration

不要分布式大事务；使用 durable saga/orchestration + idempotent participants + reconciliation。

# 228. A0｜Effect Criticality

HR03 人事 effect 是核心事实；IAM/HR14/HR02/settlement/档案可按策略同步硬门或 post-effect 跟踪。

# 229. A0｜Partial Effect

发生部分 effect 必须明确记录已发生的外部不可逆事实，禁止自动数据库 rollback 假装没发生。

# 230. A0｜Compensation Action

任何涉及金额的处理只传 source refs 和 date 给 HR15，HR16 不保存自行计算金额。

# 231. A0｜Access Action

任何账号权限只发 intent 给 IAM，HR16 不保存密码/权限表复制。

# 232. A0｜Asset Action

任何资产只保存 provider ref/status，不复制资产账面价值/全字段。

# 233. A0｜Academic Action

离校教学交接由 Academic provider 完成业务变更，HR16 不 UPDATE 课程/学生指导表。

# 234. A0｜Research Action

科研负责人/经费/设备/知识产权变化由 Research Authority 执行，HR16 保存 receipt。

# 235. A0｜Archive Action

人事档案正文由 ArchiveProvider；HR16 仅 transfer case/manifest/receipt。

# 236. A0｜Observability Trace

一次 ExitEffect 从 HR16 → HR03/HR14/IAM/HR15 都保留 trace/correlation id。

# 237. A0｜Health Metrics

Provider latency/error/status、scheduler lag、outbox lag、reconciliation backlog 都进 metrics。

# 238. A0｜Alert Severity

P0：人事已离退但高权限仍 active/岗位未释放；P1：settlement/archive overdue；P2：非关键通知失败。

# 239. A0｜Audit Immutable Storage

高风险决定、权限清退和 provider receipts 建议进入防篡改/长期审计存储策略。

# 240. API｜政策列表与版本

`GET/POST /api/v1/hr/exits/policies`；`GET/POST /policies/{id}/versions`。

# 241. API｜政策发布

`POST /policies/{id}/versions/{v}/validate`；`POST .../publish`；发布失败返回逐项 rule errors。

# 242. API｜离退原因

`GET/POST /api/v1/hr/exits/reasons`；删除已引用 reason 禁止，改为 retire。

# 243. API｜任务模板

`GET/POST /api/v1/hr/exits/task-templates` + version/validate/publish。

# 244. API｜本人辞职

`POST /api/v1/hr/exits/me/resignations`；`GET /me/exit-cases`；`POST /me/exit-cases/{id}/withdraw`。

# 245. API｜Exit Case 后台

`GET/POST /api/v1/hr/exits/cases`；detail/timeline/documents/effects。

# 246. API｜Exit Decision

`POST /cases/{id}/submit|return|reject|approve|suspend|resume`，每个 action 有独立 permission。

# 247. API｜Plan

`POST /cases/{id}/plans/generate`；`POST /plans/{id}/rebase-preview`；`POST .../rebase`。

# 248. API｜Tasks

`GET /tasks`；`POST /tasks/{id}/complete|reopen|waive|reassign`。

# 249. API｜Provider Refresh

`POST /cases/{id}/providers/{type}/refresh`，异步返回 job。

# 250. API｜退休 Forecast

`GET /api/v1/hr/retirement/forecast`；`POST /forecast/run`。

# 251. API｜退休 Simulator

`POST /api/v1/hr/retirement/simulate` 返回逐项解释，不写 Authority。

# 252. API｜退休 Case

`GET/POST /api/v1/hr/retirement/cases`；precheck/intent/approve/change-date/start-offboarding。

# 253. API｜养老办理状态

`GET /retirement/cases/{id}/pension-processing`；Provider callback 走专门 secured endpoint。

# 254. API｜Settlement

`POST /exits/cases/{id}/settlement-request`；`GET .../settlement-status`。

# 255. API｜Apply Effect

`POST /exits/cases/{id}/effects/apply` 必须 If-Match + Idempotency-Key。

# 256. API｜Effect Query

`GET /exits/cases/{id}/effects` 展示 participant state 和 reconciliation。

# 257. API｜Certificates

`POST /cases/{id}/certificates`；`GET /me/certificates`；public verify 使用 token route。

# 258. API｜档案转递

`POST /cases/{id}/file-transfers`；receipt import/callback；状态查询。

# 259. API｜Rehire Referral

`POST /retirement/retirees/{id}/rehire-referrals`，仅创建 handoff，不新建关系。

# 260. 字段｜ExitPolicyVersion

核心字段：
`id tenant_id pack_id version_no effective_from effective_to source_refs reason_rules notice_rules approval_route task_template_refs gate_rules date_rules certificate_rules archive_rules published_at published_by status content_hash supersedes_id`。

# 261. 字段｜ExitCase

`id tenant_id case_no person_id staff_id employment_relationship_id exit_type reason_code policy_version_id source_type source_ref request_date notice_date planned_last_working_date approved_last_working_date planned_employment_end_date approved_employment_end_date status decision_version plan_version sensitivity version`。

# 262. 字段｜ExitDecision

`case_id decision_version decision_code authority_ref source_document_refs approved_last_working_date approved_employment_end_date reason decided_by decided_at content_hash supersedes_id`。

# 263. 字段｜ExitSubjectSnapshot

`case_id snapshot_at org_ref assignment_refs appointment_refs agreement_refs manager_ref personnel_category source_versions payload_hash`。

# 264. 字段｜ExitPlanInstance

`case_id template_version_id plan_version generated_at owner_snapshot task_count hard_task_count plan_hash status`。

# 265. 字段｜ExitTask

`case_id plan_id task_code owner_type owner_ref provider_type due_at blocking_level dependencies status completion_source provider_receipt_id evidence_required completed_at version`。

# 266. 字段｜TaskEvidence

`task_id evidence_type document_ref system_fact_ref provider_receipt_ref verified_by verified_at hash sensitivity`。

# 267. 字段｜TaskWaiver

`task_id requested_by reason authority_requirement approved_by approved_at conditions document_ref status version`。

# 268. 字段｜ProviderReceipt

`tenant_id provider_type provider_event_id request_id case_id task_id provider_ref normalized_status business_time received_at verified_at raw_hash version`。

# 269. 字段｜RetirementPolicyVersion

`pack/version/source/effective dates/category schema/statutory algorithm/flexible early/flexible late/special rules/management authority/pension provider/hash/status`。

# 270. 字段｜RetirementCategoryAssignment

`staff_id relationship_id category_code source_type source_ref evidence_ref verified_by verified_at effective_from effective_to status version`。

# 271. 字段｜RetirementForecast

`staff_id relationship_id policy_version_id category_assignment_id statutory_date flexible_earliest flexible_latest pension_status conflicts warnings generated_at source_hash`。

# 272. 字段｜RetirementCase

`case_no staff relationship retirement_type policy_version forecast_ref statutory_date chosen_date approval_route precheck_status status version`。

# 273. 字段｜RetirementApproval

`case_id authority_ref decision effective_date decision_document_id approved_by approved_at content_hash version`。

# 274. 字段｜ExitEffect

`case_id effect_version idempotency_key requested_at status hr03_status hr03_receipt hr14_status iam_status settlement_status archive_status applied_at reconciled_at version`。

# 275. 字段｜ExitFact

`fact_no case_id person_id staff_id relationship_id exit_type final_working_date employment_end_date policy_version decision_ref effective_at revision_no supersedes_id status content_hash`。

# 276. 字段｜RetirementFact

`fact_no exit_fact_id staff_id retirement_type statutory_date chosen_date effective_date policy_version approval_ref pension_processing_ref revision_no supersedes_id status content_hash`。

# 277. 字段｜CertificateVersion

`certificate_id fact_ref template_version visible_field_snapshot issue_no issued_at issuer document_id document_hash verification_token status supersedes_id`。

# 278. 字段｜FileTransferCase

`case_id destination_type destination_ref destination_name manifest_ref dispatch_channel tracking_no sent_at status receipt_ref legal_hold version`。

# 279. 字段｜ArchivePackage

`case_id package_version manifest_json object_hashes aggregate_hash retention_class legal_hold generated_job generated_at verification_status`。

# 280. 字段｜RiskCase

`case_id risk_code severity source_type source_ref opened_at owner due_at status remediation resolved_at resolution_evidence`。

# 281. DB｜唯一性

同一 employment_relationship 只能有一个互斥 active ExitCase；同一 effective fact revision 链唯一；provider_event_id tenant+provider 唯一。

# 282. DB｜日期约束

approved_last_working <= employment_end（如 policy 定义），retirement chosen date 必须在批准窗口；不要依赖前端。

# 283. DB｜跨租户约束

业务服务写入前校验所有 refs tenant 一致，并对关键 FK 建 tenant-aware constraints/guards。

# 284. DB｜不可变约束

Policy published、Decision finalized、ExitFact、RetirementFact、Certificate issued version、Archive hash 均禁止原地修改。

# 285. DB｜索引

`(tenant,status,effective_date)`、`(tenant,staff,status)`、`(relationship,status)`、`(task_owner,status,due)`、`(retirement_date,status)`、`(case,risk,status)`。

# 286. 测试｜政策版本

- published immutable
- effective overlap blocked
- old case uses old version
- new version no history pollution
- retired policy cannot new case

# 287. 测试｜Reason Catalog

- sensitive reason hidden
- reporting mapping
- certificate visibility
- retired reason still historical
- unknown reason fail

# 288. 测试｜Notice Rule

- 30-day contract rule source
- waiver
- working/calendar days
- short notice blocker
- employee/authority initiated differences

# 289. 测试｜Date Semantics

- last working vs end
- contract end mismatch
- appointment end
- access end
- payroll cutoff
- future date
- same-day date

# 290. 测试｜Transition Lock

- HR06 vs HR16
- HR14 vs HR16
- HR07 renewal vs HR16
- two exit cases
- effect retry
- future transition reservation

# 291. 测试｜SELF Resignation

- own only
- no arbitrary staff
- draft
- submit
- withdraw
- rejected immutable
- resubmit new case where policy

# 292. 测试｜Authority Initiated Exit

- source decision mandatory
- sensitive ACL
- notice proof
- approval authority
- no employee self approval

# 293. 测试｜Non-renewal

- HR07 source
- contract expiry alone not auto exit
- notice
- future contract conflict
- HR12 only evidence

# 294. 测试｜Dismissal

- formal source required
- restricted documents
- urgent IAM plan
- legal hold
- certificate reason policy
- no AI decision

# 295. 测试｜Death

- verified source
- no self tasks
- urgent revoke
- settlement
- privacy
- beneficiary data minimization
- archive

# 296. 测试｜Retirement Forecast

- statutory date
- flexible earliest/latest
- source category
- policy version
- warnings
- repeat run idempotent

# 297. 测试｜Retirement Boundary DOB

- month first day
- month last day
- leap day
- policy effective date
- old-age category
- official fixture table

# 298. 测试｜Retirement Category Unknown

- no guessed date
- manual verify task
- provider unavailable
- wrong category correction
- reforecast

# 299. 测试｜Flexible Early

- employee intent
- within window
- minimum contribution status
- notice requirement
- cancel/change
- no employer forced

# 300. 测试｜Flexible Delayed

- employee+unit agreement
- max window
- management authority
- agreement timing
- future contract impact
- date change

# 301. 测试｜Special Retirement

- special category source
- medical/provider if applicable
- approval
- restricted data
- no boolean bypass

# 302. 测试｜Pension Eligibility

- ELIGIBLE
- NOT_ELIGIBLE
- PARTIAL
- UNAVAILABLE
- NEEDS_REVIEW
- no pension amount calculation

# 303. 测试｜Retirement Approval

- precheck
- authority
- document hash
- effective date
- future effect
- immutable after final

# 304. 测试｜Pension Processing

- retirement can effective
- benefit pending
- provider reject
- resubmit
- receipt
- does not rollback retirement

# 305. 测试｜Plan Generation

- correct template
- person category
- exit type
- task DAG
- owner resolve
- frozen template
- rebase explicit

# 306. 测试｜Task Dependency

- cycle blocked at publish
- upstream incomplete
- parallel tasks
- NOT_APPLICABLE
- external waiting
- reopen

# 307. 测试｜Task Evidence

- provider receipt
- authorized confirmation
- document hash
- evidence required
- self confirmation denied for hard task

# 308. 测试｜Task Waiver

- soft waiver
- hard waiver privilege
- reason required
- approval
- audit
- waived gate semantics

# 309. 测试｜Task Reassign

- manager leaves
- new owner
- history
- due unchanged/recalc by policy
- permission

# 310. 测试｜Teaching Provider

- active teaching blocks
- grade pending
- no obligations
- provider unavailable
- receipt version
- cross-tenant

# 311. 测试｜Research Provider

- PI project
- fund authority
- lab
- IP
- no active research
- unavailable
- receipt

# 312. 测试｜Asset Provider

- zero assets verified
- high-value outstanding
- damaged/lost
- return receipt
- provider unavailable
- waiver policy

# 313. 测试｜Finance Provider

- cleared
- outstanding
- partial
- unavailable
- employee self cannot clear
- receipt duplicate

# 314. 测试｜IAM Provider

- privileged pre-revoke
- normal at effect
- retiree portal exception
- mail retention
- failed callback
- duplicate callback
- reconcile

# 315. 测试｜Data Ownership

- shared drive
- repo owner
- service account
- API key rotation
- password not captured
- provider receipt

# 316. 测试｜Completion Gate

- all hard complete
- soft incomplete allowed per policy
- unavailable hard blocks
- waived hard authorized
- post-exit task separation

# 317. 测试｜Settlement

- request once
- status mapping
- not paid != paid
- recovery pending
- policy gate threshold
- HR16 no money

# 318. 测试｜HR03 Effect

- close assignments
- close relationship
- idempotent
- network timeout unknown
- query receipt
- partial failure
- no duplicate history

# 319. 测试｜HR14/HR02 Effect

- appointment close
- position release
- already closed
- provider fail
- event duplicate
- drift detected

# 320. 测试｜Effect Partial Failure

- HR03 success IAM fail
- HR03 fail no false effective
- HR14 fail
- asset post-effect
- risk generated
- reconcile

# 321. 测试｜Certificate

- minimal fields
- sensitive reason exclusion
- template version
- verify token
- superseded
- download scope
- hash

# 322. 测试｜File Transfer

- destination
- manifest
- send
- receive
- return
- re-send
- legal hold
- no self download substitute

# 323. 测试｜Post-exit Tasks

- effect already final
- settlement pending
- archive pending
- owner/SLA
- close only after policy conditions

# 324. 测试｜Rehire Referral

- retirement stays
- new employment handoff
- no reopen old relationship
- duplicate referral
- HR05 vs HR08 route
- overlap

# 325. 测试｜History

- multiple employments
- exit1
- rehire
- exit2
- as-of
- correct current projection

# 326. 测试｜Correction

- wrong date
- wrong reason mapping
- old fact preserved
- certificate supersede
- downstream re-evaluate
- no direct update

# 327. 测试｜Tenant IDOR

- case
- task
- retirement
- certificate
- archive
- provider receipt
- file
- export
- public verify minimal

# 328. 测试｜Sensitive ACL

- disciplinary
- medical/special retirement
- death
- exit interview
- legal hold
- break-glass

# 329. 测试｜Concurrency

- approve+withdraw
- retirement date change+effect
- task complete+waive
- effect double click
- provider duplicate
- rehire+post-exit close

# 330. 测试｜Outbox/Inbox

- atomic event
- consumer retry
- duplicate
- out-of-order
- dead letter
- replay

# 331. 测试｜Excel

- template
- tenant
- date parsing
- staging
- error workbook
- preview
- partial rows
- no direct effective

# 332. 测试｜Migration

- inactive no evidence
- archived no effect
- approved resignation with actual end
- retired historical evidence
- duplicate relationships
- trust

# 333. 测试｜Performance

- 1万 forecast
- 10万 history
- task list pagination
- provider refresh async
- dashboard no N+1
- archive async

# 334. 测试｜MySQL Transaction

- row lock
- unique active case
- deadlock retry
- effect idempotency
- provider event unique
- migration rollback

# 335. 测试｜Observability

- metrics
- trace
- structured log
- no sensitive body
- alert thresholds
- scheduler lag
- outbox lag

# 336. 测试｜Accessibility

- keyboard
- focus
- labels
- task table
- status text
- error association
- mobile self flows

# 337. 测试｜Visual Regression

- policy
- self resignation
- case detail
- retirement forecast
- precheck
- task matrix
- effect
- certificate
- history
- risk
- 375/768/1280/1440

# 338. E2E｜普通辞职

SELF request → policy/notice → manager/org review → HR approve → HR07 termination/expiry coordination
→ plan/tasks → settlement requested → hard gates → HR03 effect → HR14 close → HR02 vacancy
→ IAM revoke → certificate → archive transfer/post-exit → reconcile → CLOSED。

# 339. E2E｜辞职撤回

SUBMITTED → withdrawal request → policy allows → cancel pending plan/tasks → no HR03/IAM effects → audit/history remains。

# 340. E2E｜不续聘

HR07 DO_NOT_RENEW → OffboardingRequired → HR16 Case → notice/tasks → agreement expires → ExitEffect → no contract/history delete。

# 341. E2E｜合同到期但未决定离校

HR07 EXPIRED → no OffboardingRequired/formal decision → HR16 must not auto terminate employment。

# 342. E2E｜HR12 不合格负向

HR12 UNQUALIFIED → downstream review requested → no HR07/formal decision → HR16 no exit → IAM untouched。

# 343. E2E｜外部调出

HR06 resolves EXTERNAL_TRANSFER_OUT → HR16 → receiving unit/file transfer → tasks → effect → current relationship closes。

# 344. E2E｜校内调动负向

HR06 INTERNAL_TRANSFER → HR16 not created → HR03 assignment changes only。

# 345. E2E｜法定退休

Forecast → Precheck → verified category → approval → future plan → tasks → retirement/exit effect → pension processing → retiree projection。

# 346. E2E｜弹性提前退休

employee intent → within legal/policy window → contribution/provider ready → written notice → approval → planned date → offboarding/effect。

# 347. E2E｜弹性延迟退休

statutory date → employee intent + unit agreement + authority route → delayed date → current relationship remains active until date → effect。

# 348. E2E｜退休日期类别争议

Forecast UNKNOWN/CONFLICT → Dispute/verification → corrected category version → reforecast → no auto approval during dispute。

# 349. E2E｜特殊退休

special authority/evidence → protected ACL → approval → offboarding → effect；普通 HR 仅见必要 status。

# 350. E2E｜退休待遇晚办

RetirementEffective → PensionProcessing=NEEDS_INFO → retired fact remains → service case → provider accepted → archive。

# 351. E2E｜资产 HARD Block

Case approved → asset provider outstanding → task BLOCKED → apply effect 409 HARD_TASK_INCOMPLETE → return receipt → ready。

# 352. E2E｜IAM 部分失败

HR03 effect success → IAM timeout → ExitFact effective + Effect PARTIAL → P0 risk → IAM reconcile/retry → effect reconciled。

# 353. E2E｜HR14 关闭失败

ExitEffective → appointment close provider fails → relationship remains correctly ended → risk + retry → appointment closed → HR02 released。

# 354. E2E｜最终结算未支付

policy requires SettlementRequested only → exit effect → HR15 payment pending in POST_EXIT → later payment success → Case CLOSED。

# 355. E2E｜最终结算为 HARD Paid

tenant policy requires paid before effect → Settlement PAYMENT_PENDING blocks → payment success receipt → effect allowed。

# 356. E2E｜教学未交接

teacher has active course/grades → Academic task HARD → successor/grade handoff → provider receipt → effect allowed。

# 357. E2E｜科研项目负责人

PI active → Research task → formal PI change/agency receipt → no copy of project data in HR16。

# 358. E2E｜紧急解除

authorized high-risk decision → EmergencyPlan → privileged IAM early revoke → HR03 effect at approved date → remaining finance/archive post-exit。

# 359. E2E｜死亡特殊流程

verified death → authority-init case → no self tasks → urgent IAM/access → settlement/asset/archive → HR03 effect → fact。

# 360. E2E｜档案被接收方退回

FileTransfer SENT → REJECTED/RETURNED → post-exit Case remains open → correct destination/manifest → resend → RECEIVED。

# 361. E2E｜离职证明事实更正

ExitFact date correction approved → Fact V2 → old certificate superseded → new certificate V2 → public verify old=SUPERSEDED。

# 362. E2E｜退休后返聘

RetirementFact immutable → RehireReferral → HR05/HR08 → new relationship/contract/assignment/payroll profile → old retirement preserved。

# 363. E2E｜返聘再次离校

new relationship has new HR16 Case → ExitFact2 → history shows retirement/rehire/exit2 timeline。

# 364. E2E｜Provider 全部不可用

Case detail shows UNAVAILABLE blockers → no fake clearance → provider restore → refresh → receipts → continue。

# 365. E2E｜网络超时 after HR03 commit

apply_exit_effect timeout → HR16 status UNKNOWN/PARTIAL → query by idempotency key → receive existing HR03 receipt → no duplicate close。

# 366. E2E｜Future Retirement 与 Future Appointment

HR16 future transition reservation → HR14 detects DEPENDENCY_CONFLICT → appointment cannot silently extend beyond exit。

# 367. E2E｜Future Exit 日期变更

approved future exit V1 → date change case → impact analysis → Decision V2 → Plan due dates rebase → old V1 retained。

# 368. E2E｜Legacy inactive 但仍在职

legacy is_active=false due technical issue → no formal source → migration marks CONFLICTED → no ExitFact created。

# 369. E2E｜Legacy archived with formal proof

legacy offboarding archived + HR03 historical end + agreement end/document → staging trust high → migrated ExitFact → no fake task receipts。

# 370. Legacy｜审计范围

必须逐目录搜索：
`offboarding/* / employee/* / payroll/* / contract legacy / notifications / reports / custom fields / migrations`。
列出所有直接改变 employee active/status 的入口。

# 371. Legacy｜Offboarding Mapping

`Offboarding` → template/process evidence；不直接映成 ExitPolicy Authority。

# 372. Legacy｜Stage Mapping

Notice/Interview/Handover/FnF/Archive → Task candidates；保留 historical timestamps/source。

# 373. Legacy｜OffboardingEmployee Mapping

一对一 Employee 旧对象 → historical process participant，不继续作为新聚合根。

# 374. Legacy｜ResignationLetter Mapping

requested/approved/rejected → request evidence；与 HR03 historical relationship end 联合确认真实退出。

# 375. Legacy｜Employee is_active Mapping

`is_active=false` 仅 technical projection，不能单独判定离职/退休。

# 376. Legacy｜Legacy Contract End

旧 contract status/end date 只是佐证，不能代替 ExitFact。

# 377. Legacy｜Legacy Payroll FnF

旧 FnF/payroll record 作为 settlement evidence，金额 Authority 迁 HR15。

# 378. Legacy｜Retirement Historical Data

退休日期/类型若来自正式文书/档案则 MIGRATED_VERIFIED；只有备注则 UNVERIFIED。

# 379. Legacy｜Trust Matrix

```text
FORMAL_DECISION_SUPPORTED
ARCHIVE_DOCUMENT_SUPPORTED
HR03_HISTORY_SUPPORTED
CONTRACT_SUPPORTED
PAYROLL_SUPPORTED
MANUAL_CONFIRMED
MIGRATED_UNVERIFIED
CONFLICTED
```

# 380. Legacy｜Staging

所有候选进入 HrExitMigrationStaging；person/relationship/date/type/source/trust/conflict 校验后人工确认。

# 381. Legacy｜No Fake Process

历史只有最终离职日期时，只迁 ExitFact；不得伪造当年 Task/Provider Receipt/IAM callback。

# 382. Legacy｜Projection

新 HR16 → legacy offboarding/status 只读 projection；旧 archive/unarchive endpoint 在 cutover 后 blocked。

# 383. Legacy｜Dual Read Compare

current active/exit date/retirement/relationship/assignment/appointment/settlement/status 做逐人和汇总对账。

# 384. Legacy｜Cutover Gate

差异分类：EXPECTED_MODEL_CHANGE / LEGACY_BAD_DATA / MIGRATION_BUG / SOURCE_UNAVAILABLE；未解释 P0 不切换。

# 385. Legacy｜Rollback

入口切回不删除 HR16 facts；外部已执行 IAM/HR03/档案等必须按真实补偿流程。

# 386. AI｜允许能力

材料分类、任务缺口摘要、Provider 异常摘要、政策条款定位、退休日期解释辅助、风险排序、面谈主题去标识化汇总。

# 387. AI｜禁止退休决定

AI 不得基于年龄/性别/职位直接产生 APPROVED/RETIRED。

# 388. AI｜禁止解除决定

AI 不得根据考核、考勤、投诉自动决定解除/辞退/开除。

# 389. AI｜禁止假证据

AI 不得生成不存在的辞职信、回执、证明、档案目录、资产归还单。

# 390. AI｜禁止敏感推断

AI 不得从非授权信息推断疾病、家庭情况、政治身份等离退依据。

# 391. AI｜建议可追溯

任何 AI 建议必须标 advisory、source refs、model/time，不可直接写 FINAL Fact。

# 392. 施工纪律｜Repo First

每阶段先确认目标分支真实模型/路由/测试，不按文档假设文件一定存在。

# 393. 施工纪律｜No Big Bang

S1–S10 分阶段迁移，保留旧 UI adapter，禁止一次性删除 offboarding。

# 394. 施工纪律｜No git add -A

只 stage 当前阶段明确文件。

# 395. 施工纪律｜No Push/Merge

未经用户明确授权不 push、不 merge main、不 deploy。

# 396. 施工纪律｜Regression

每阶段跑新增专项 + offboarding/employee/contracts/payroll 相关旧回归。

# 397. 施工纪律｜Fail Closed

任何为了“跑通流程”而把 Provider UNAVAILABLE 当 complete 均视为 P0。

# 398. S0 输出物

必须生成：
```text
HR16_GAP_MATRIX.md
LegacyExitMapping.md
LegacyExitTrustMatrix.md
ExitAuthorityBoundary.md
ExitReasonPolicyMatrix.md
ExitDateSemanticMatrix.md
ExitTaskTemplateMatrix.md
ExitCompletionGateMatrix.md
RetirementPolicyMatrix.md
RetirementCategoryMatrix.md
RetirementProviderMatrix.md
ExitProviderMatrix.md
ExitSensitiveDataMatrix.md
HR16_PERMISSION_MATRIX.md
HR16_INTEGRATION_MATRIX.md
HR16_TASK_TREE.md
HR16_RISK_REGISTER.md
HR16_MIGRATION_PLAN.md
```

# 399. HR16-S0 基线复审

- 读 offboarding 全目录与 migrations
- 搜索 employee active/archive/termination/retirement 副作用
- 读 HR03/06/07/11/12/14/15 contracts
- 审计 IAM/asset/finance/academic/research/archive integration
- 核验退休政策与目标学校制度
- 只审计/矩阵，不大改业务

# 400. HR16-S1 A0 与公共合同

- tenant
- permissions/Case ACL/SoD
- enums
- API envelope/errors
- files
- audit
- idempotency
- outbox/inbox
- jobs
- provider base

# 401. HR16-S2 离退制度与任务模板

- ReasonCatalog
- ExitPolicyPack/Version
- date semantics
- notice
- TaskTemplateVersion
- DAG
- CompletionGate
- UI

# 402. HR16-S3 退休政策与预测

- RetirementPolicyVersion
- category assignment
- official fixtures
- forecast
- simulator
- flexible windows
- special rules
- alerts

# 403. HR16-S4 辞职/调出/解除 Case

- ExitCase
- SELF request
- authority initiated
- decision
- withdraw
- RETURNED/REJECTED
- date conflicts
- sensitive ACL
- HR07/HR06 linkage

# 404. HR16-S5 退休正式办理

- precheck
- pension provider
- intent
- elastic early/delay
- approval authority
- date agreement
- special retirement
- pension processing
- UI

# 405. HR16-S6 离校 Plan 与多域 Task

- plan generator
- owner resolver
- task evidence
- teaching
- research
- student
- finance
- asset
- library
- housing optional
- waive
- SLA

# 406. HR16-S7 IAM 与数据所有权

- privileged revoke
- normal deprovision
- mail/data retention
- repo/shared ownership
- service accounts
- retiree portal
- provider receipts
- security E2E

# 407. HR16-S8 Completion Gate 与生效

- settlement link
- HR07 gate
- hard blockers
- transition lock
- HR03 effect
- HR14 close
- HR02 release
- partial effect
- reconciliation

# 408. HR16-S9 证明/档案/关系转移

- certificate version
- public verify
- personnel file transfer
- receipts
- statutory status
- post-exit outstanding
- archive package
- UI

# 409. HR16-S10 离退休历史与返聘

- ExitFact
- RetirementFact
- retiree projection
- history/as-of
- correction
- rehire referral
- HR05/HR08 handoff
- risk

# 410. HR16-S11 Legacy + 全量质量

- staging
- trust
- DUAL compare
- security
- concurrency
- provider failure
- MySQL
- performance
- E2E
- A11y
- visual
- observability
- data quality

# 411. HR16-S12 Authority Cutover

- shadow new cases
- retirement forecast compare
- freeze legacy formal writes
- HR03 effect rehearsal
- IAM/asset/finance dry-run
- archive dry-run
- rollback rehearsal
- no fallback

# 412. HR16-S13 最终封板

- six workspaces green
- retirement rules green
- exit decisions green
- tasks/gates green
- effects/reconcile green
- archive/certificate green
- rehire green
- security/migration/MySQL/E2E/observability/A11y/visual green

# 413. 附录｜退休预审字段

- DOB verified source
- retirement category
- employment relationship
- statutory date
- flexible window
- pension eligibility
- special rule
- authority route
- conflicts

# 414. 附录｜退休 Forecast 提醒去重

natural key=`staff+forecast_version+threshold_date+alert_type`，防止每天重复提醒。

# 415. 附录｜退休日期计算版本

保存 algorithm_version + official_source_ref；算法修复后可 reforecast，但已批准 Case 不静默变更。

# 416. 附录｜出生日期更正影响

HR03 DOB Correction → RetirementForecastRebuildRequested → 未批准 Case recheck；已批准 Case 创建 ImpactReview。

# 417. 附录｜人员类别更正影响

RetirementCategoryAssignment Revision → future forecast/case review；历史退休事实保持。

# 418. 附录｜养老资格不可用

Pension Provider UNAVAILABLE 时预审显示灰色阻塞，不得根据工龄猜缴费年限。

# 419. 附录｜弹性提前通知期限

以现行政策版本配置至少提前通知要求；不同未来政策可新 Version，不写死 UI。

# 420. 附录｜弹性延迟协商

协商结果保存双方确认时间/文书/日期；未达成一致不能默认延迟。

# 421. 附录｜延迟退休到期

agreed delayed date 到期前自动进入 HR16 plan，不通过延长合同暗中再延。

# 422. 附录｜退休审批职责

学校/主管部门/干部人事权限通过 AuthorityResolver；技术管理员绝不能审批。

# 423. 附录｜退休批次视图

批次仅是工作组织视图，每人独立 Forecast/Case/Approval/Fact。

# 424. 附录｜退休人员联系信息

退休后联系偏好由 HR17/HR03 管；HR16 不创建第二份通讯录。

# 425. 附录｜离职申请联系方式

post-exit contact 仅为证明/结算必要时使用，单独敏感分类和保留期。

# 426. 附录｜离职原因二级分类

员工可见 reason 与 HR 内部 reporting reason 分离，避免敏感处分信息扩散。

# 427. 附录｜主动/非主动离退

voluntary/involuntary/retirement/transfer 分类用于流程与统计，不代替法律原因。

# 428. 附录｜离职申请评论

自由文本长度/敏感提示/访问控制；禁止把未核实指控自动进入人员主档。

# 429. 附录｜Exit Interview

模板版本、参与者、保密级别、是否匿名汇总、保留期；原文不进入普通 manager report。

# 430. 附录｜面谈分析

仅聚合组织改善主题，低样本抑制，禁止生成个人风险评分。

# 431. 附录｜Notice Period 工作安排

HR11/Academic 继续各自 Authority；HR16 只呈现计划和冲突。

# 432. 附录｜Garden Leave/免岗等特殊安排

若学校制度存在，作为 Policy/HR07/HR11 协同对象，不在 HR16 自创工资规则。

# 433. 附录｜离校设备损坏

资产系统认定损坏/赔偿；HR16 保存 AssetCase ref，金额处理由财务/HR15 appropriate provider。

# 434. 附录｜工牌/门禁卡

实体卡归还与数字权限撤销分别有 provider receipt，不以“卡已还”推断账号已停。

# 435. 附录｜VPN/远程访问

高风险权限可 PRE_EFFECT revoke，任务完成由 IAM Provider 证明。

# 436. 附录｜代码仓库 Ownership

GitHub/GitLab 等通过 IT Provider 转移 team/repo ownership；HR16 不保存 access token。

# 437. 附录｜数据库账号

DB account revoke/ownership transfer 仅由 IAM/DBA provider，HR16 只存 receipt。

# 438. 附录｜科研数据保留

数据归属/留存由科研/法务 policy；HR16 不允许个人任意删除组织数据。

# 439. 附录｜个人隐私数据删除

离校不等于删除全部个人数据；按法定档案/工资/合同/审计 retention 分类处理。

# 440. 附录｜Email Auto Reply

可作为 IT task，内容模板和时限由学校策略；不影响 ExitFact。

# 441. 附录｜Service Account

必须迁移 owner/rotate secret；无明确 owner 的高权限 service account 是 P0 blocker。

# 442. 附录｜教学成绩截止

成绩未 final 时 AcademicProvider 可 HARD BLOCK；不允许 HR 代录成绩。

# 443. 附录｜在研项目审批

科研项目交接可能需主管部门/资助方批准，HR16 显示 WAITING_EXTERNAL。

# 444. 附录｜科研经费权限

Finance/Research 双 Provider 可分别确认业务负责人和财务授权解除。

# 445. 附录｜实验室安全

危险化学品/生物安全/辐射等权限清退可以独立 HARD task。

# 446. 附录｜学生指导

导师变更需 Academic/Graduate provider 完成后给 receipt；不能只发邮件算完成。

# 447. 附录｜辅导员 Case

学生重点关怀/处分/资助等进行中 Case 交接由学工 Provider，HR16 只看 completion。

# 448. 附录｜个人借款

Finance Provider 的 CLEARANCE 可有 outstanding amount，但普通 HR 仅看 blocked/cleared。

# 449. 附录｜工资 Recovery

HR15 RecoveryPlan 可 post-exit 继续，HR16 不得自行从证明/档案中扣留金额。

# 450. 附录｜最终工资条

HR15 正式生成，HR16/HR17 只提供入口/状态。

# 451. 附录｜社保停保

申报时间与 employment end 可能不同；HR15 statutory provider 管 status，HR16不猜。

# 452. 附录｜公积金封存/转移

同样由 HR15/Provider，HR16只跟踪服务完成状态。

# 453. 附录｜养老金待遇核定

RetirementEffective 后可能长期 processing；HR16保持服务 Case，不把退休状态回滚为 ACTIVE。

# 454. 附录｜退休证件/证明

是否需要、模板、签发主体由地方/学校 policy，系统不全国硬编码。

# 455. 附录｜档案调档函

DocumentProvider 版本化模板，目标机构/编号/签章证据和发送回执。

# 456. 附录｜档案材料缺失

TransferCase BLOCKED/NEEDS_REVIEW；不能伪造完整 manifest。

# 457. 附录｜档案接收机构校验

destination provider/人工核验；不允许把普通个人邮箱作为正式接收地址。

# 458. 附录｜组织关系敏感性

仅特定角色看到详细状态；普通离校 Task 显示“需办理/已办理”即可。

# 459. 附录｜证明英文版

可作为 TemplateVersion；内容仍引用同一 ExitFact，不重新手输日期。

# 460. 附录｜证明二维码

verification token 短而不可猜，支持撤销/更正后的状态提示。

# 461. 附录｜证明下载次数

可记录 audit，不应把下载次数作为员工行为评价。

# 462. 附录｜离校日后账号例外

retiree/alumni/research handover temporary access 必须 ExceptionAccessCase + expiry，不修改 Employment fact。

# 463. 附录｜临时访问自动到期

IAM Provider 返回 exception id/expiry；scheduler 监控未按期撤销。

# 464. 附录｜Legal Hold 与邮箱

诉讼/调查需要数据保全时，IAM/Archive retention 延长；权限仍可撤销。

# 465. 附录｜离校后知识产权

权利归属由科研/法务 Authority，HR16不自动转让。

# 466. 附录｜返聘入口

退休人员可在 HR17 发起意向，HR16生成 Referral，HR05/HR08完成新聘。

# 467. 附录｜返聘审批

不能因为原来是教授自动批准；当前岗位/资格/年龄/政策均重新审查。

# 468. 附录｜返聘期限

新合同/engagement term独立；退休前合同不延长复活。

# 469. 附录｜返聘 IAM

创建新 access policy/identity link，禁止简单 unarchive old account 全权限恢复。

# 470. 附录｜返聘工资

新 HR15 PayrollProfile，历史工资和退休事实只读。

# 471. 附录｜重复离退 Case

同一 relationship active case unique；不同 source case 要 link/merge/supersede 而非重复并行。

# 472. 附录｜Case Merge

误重复 Case 可 merge metadata 但不删除 audit；保留 source refs 和 canonical_case_id。

# 473. 附录｜Case Cancel

生效前取消需 authority/reason；已产生外部预撤权等要补偿/恢复任务。

# 474. 附录｜Rebase Plan

Decision/date/organization变化导致 Plan owner/due变化时先 preview diff，再正式新 PlanVersion。

# 475. 附录｜任务负责人缺失

OwnerResolver 无人时 task=BLOCKED + risk，禁止自动分给超级管理员。

# 476. 附录｜任务超期

提醒、升级、SLA、escalation recipient 版本化；同一天不重复创建无穷消息。

# 477. 附录｜任务批量完成

只允许同 Provider/同 evidence 语义的批量确认，逐人/逐任务结果保留。

# 478. 附录｜Provider Cache

清单可缓存，apply effect 前 HARD provider 必须按最大 stale 阈值刷新。

# 479. 附录｜Provider Scope Token

调用下游时使用服务身份 + tenant + subject/case scope，不转发可伪造前端 tenant。

# 480. 附录｜Webhook Security

signature、timestamp、nonce/replay protection、provider event id、payload hash。

# 481. 附录｜Effect 顺序

具体 participant 顺序由 OrchestrationPolicyVersion；HR03/IAM/HR14不可假设永远同步成功。

# 482. 附录｜Emergency Effect

安全事件可先 IAM revoke 后人事生效，但必须 formal source/authority 和后续 reconciliation。

# 483. 附录｜Effect 补偿

只对可逆外部动作做 compensating action；人事已正式生效后不靠技术 rollback 撤销事实。

# 484. 附录｜P0 Drift

- ExitFact effective but HR03 active
- privileged IAM active
- appointment active and position occupied
- wrong tenant access
- duplicate employment closure

# 485. 附录｜P1 Drift

- settlement overdue
- archive receipt missing
- retiree portal not provisioned
- nonprivileged mailbox retention pending
- certificate issue failure

# 486. 附录｜Metric Definition

Turnover/retirement rates必须定义 numerator/denominator/asOf/personnel scope/reason mapping/version。

# 487. 附录｜小样本隐私

离职原因/退休特殊类型统计低于阈值时抑制/合并，避免反推个人。

# 488. 附录｜Dashboard Freshness

每个卡片带 sourceUpdatedAt/calculatedAt/status，不把 stale provider 数据当实时。

# 489. 附录｜Runbook｜IAM 未撤权

P0：隔离账号→人工确认→provider重试→审计→复盘，不回滚 ExitFact。

# 490. 附录｜Runbook｜HR03 Effect 卡死

查询幂等状态→transition lock→repair/retry→确认 assignment/relationship→下游重放。

# 491. 附录｜Runbook｜档案丢件

冻结 transfer case→核对 manifest/hash/tracking→通知责任人→重新封装/发送→保留原异常。

# 492. 附录｜Runbook｜退休日期争议

停止自动 effect→锁定 Case→核验证据/政策→Correction/DateChange→重新影响分析。

# 493. 附录｜Runbook｜批量退休算法缺陷

停止 Forecast scheduler→标记 affected forecasts→发布 corrected policy/algorithm→reforecast；已批准 Case人工复审。

# 494. 附录｜Runbook｜Provider 大面积不可用

业务页面显示 degraded/blocked，禁止 mass waive；恢复后批量 refresh/reconcile。

# 495. 附录｜Runbook｜数据库恢复

先恢复 Authority→暂停 scheduler→核对 Outbox/Inbox→查询外部 receipts→reconcile→再恢复自动任务。

# 496. 附录｜监控｜未来90天退休

只作为计划指标，不自动创建 approved case；支持人员类别/学院 drilldown。

# 497. 附录｜监控｜未来30天离校

突出 HARD blockers、IAM plan、replacement/teaching/research risk。

# 498. 附录｜监控｜离校后未结事项

按 settlement/archive/IAM/certificate/provider owner 分组，避免 case“关了就看不见”。

# 499. 验收矩阵｜辞职申请页面

- 本人身份不可切换
- 计划日期解释
- notice rule提示
- 原因敏感提示
- 保存草稿
- 提交确认
- 撤回入口

# 500. 验收矩阵｜人事 Case 首页

- exit type
- source decision
- 关键日期
- current stage
- hard blockers
- downstream effects
- next actions

# 501. 验收矩阵｜退休 Forecast 页面

- statutory date
- flexible window
- policy version
- category source
- pension status
- conflicts
- reforecast time

# 502. 验收矩阵｜退休预审页面

- 逐项 Gate
- evidence source
- UNAVAILABLE显示
- manual review
- employee intent
- authority route
- no auto approval

# 503. 验收矩阵｜退休批准页面

- decision snapshot
- chosen date
- statutory date
- written docs
- authority
- effect date
- impact summary

# 504. 验收矩阵｜Task Matrix 页面

- department grouping
- owner
- due
- blocking
- provider status
- evidence
- dependency
- waiver

# 505. 验收矩阵｜IAM Task

- account scope
- privileged flag
- planned revoke
- actual receipt
- exceptions
- expiry
- no credentials

# 506. 验收矩阵｜资产 Task

- provider count
- high risk items
- return status
- receipt
- unavailable
- waiver rules
- no duplicated ledger

# 507. 验收矩阵｜教学 Task

- course/exam/student roles
- source provider
- handover target
- completion receipt
- blocking
- no direct edit

# 508. 验收矩阵｜科研 Task

- projects
- PI responsibility
- fund/lab/IP
- handover target
- receipt
- external wait
- restricted data

# 509. 验收矩阵｜Settlement 页面

- request id
- HR15 status
- final date inputs
- outstanding recovery
- payment state
- no editable amount
- post-exit flag

# 510. 验收矩阵｜Effect Workbench

- HR03
- HR14
- HR02 observed
- IAM
- settlement
- archive
- partial effect
- reconcile action

# 511. 验收矩阵｜证明页面

- fact version
- template
- visible fields
- hash
- verify token
- status
- reissue history

# 512. 验收矩阵｜档案转递

- destination
- manifest
- dispatch
- tracking
- receipt
- return
- legal hold
- owner

# 513. 验收矩阵｜退休人员台账

- retirement date
- type
- former org/position snapshot
- pension status
- retiree service link
- rehire status
- as-of

# 514. 验收矩阵｜返聘 Referral

- retirement fact
- intent
- target route
- policy
- handoff case
- new relationship status
- no unretire

# 515. 验收矩阵｜风险中心

- severity
- risk code
- object
- owner
- due
- evidence
- remediation
- resolved

# 516. 验收矩阵｜历史时间线

- employment segments
- assignments
- exit decisions
- retirement
- rehire
- certificates
- corrections
- as-of

# 517. 验收矩阵｜搜索与过滤

- org
- exit type
- status
- effective date
- retirement window
- blocker
- provider status
- risk

# 518. 验收矩阵｜批量操作

- preview
- eligible rows
- ineligible rows
- partial failures
- async job
- error workbook
- audit
- no mass effective

# 519. 验收矩阵｜Excel 历史迁移

- template version
- source key
- trust
- person match
- relationship match
- date validation
- conflict
- confirm

# 520. 验收矩阵｜导出

- async
- scope
- field permission
- sensitive exclusion
- watermark
- expiry
- audit
- row count

# 521. 验收矩阵｜通知

- template version
- recipient
- sensitive-safe wording
- dedupe
- delivery status
- retry
- opt-in where applicable

# 522. 验收矩阵｜移动端本人

- next step
- deadline
- task progress
- retirement date
- certificate
- help
- no admin tables

# 523. 验收矩阵｜375px

- no horizontal critical flow
- buttons reachable
- date readable
- status text
- document link
- task detail
- error states

# 524. 验收矩阵｜768px

- task table adaptation
- timeline
- filters
- detail panels
- sticky action
- no clipping

# 525. 验收矩阵｜1280px

- workbench density
- matrix
- drilldown
- risk rail
- filter bar
- full-page detail

# 526. 验收矩阵｜1440px

- information hierarchy
- max content width
- no giant empty cards
- clear blockers
- side context

# 527. 验收矩阵｜Loading

所有 provider/task/dashboard loading 显示具体来源，不把 loading 当“无事项”。

# 528. 验收矩阵｜Empty

空态解释业务含义，例如“当前无未来12个月退休预审对象”，不是空白页。

# 529. 验收矩阵｜403

无权限明确显示权限不足；不得返回空列表伪装无数据。

# 530. 验收矩阵｜Provider Unavailable

显示来源不可用、上次更新时间、retry/owner；不得显示“已清缴”。

# 531. 验收矩阵｜Stale

超过 hardExpire 的 HARD provider 数据不能用于 Effect Gate。

# 532. 验收矩阵｜Conflict

Future event/date/policy conflict 展示双方事实和处理入口。

# 533. 验收矩阵｜Immutable

EFFECTIVE fact 页面只允许 correction/reissue/review actions，不显示普通编辑。

# 534. 验收矩阵｜Audit

关键对象能查看授权的业务审计摘要；敏感审计详情独立权限。

# 535. 验收矩阵｜Accessibility 自动化

axe/等效规则 + keyboard smoke；重点表单和矩阵不得只有鼠标拖拽。

# 536. 验收矩阵｜可观测性

每个 P0 event 有 metric + log + trace + alert owner + runbook。

# 537. 验收矩阵｜灾备恢复

恢复演练需证明不会重复 HR03 effect、重复停权、重复档案转递或重复 settlement request。

# 538. 验收矩阵｜商业演示真实度

任何展示给学校的 Case 必须走真实 state/provider contract，不使用写死成功状态。

# 539. 外部依据｜事业单位人事管理条例

正式依据：国务院令第652号《事业单位人事管理条例》。

产品约束：
- 人事管理分级分类；
- 聘用关系解除/终止必须有正式制度事实；
- 不能用账号 active 状态替代人事关系；
- 不能把考核单一结果直接升级为技术停权动作。

官方法规库：
https://xzfg.moj.gov.cn/front/law/detail?LawID=414

# 540. 外部依据｜渐进式延迟法定退休年龄

2024-09-13 全国人大常委会决定，自 2025-01-01 起施行渐进式延迟法定退休年龄。

产品约束：
- RetirementPolicyVersion；
- 不再使用旧固定年龄作为现行硬编码；
- 15年渐进调整需官方算法/附表 fixtures；
- 分类推进、弹性实施；
- 历史政策版本保持。

S0 必须以全国人大/中国政府网正式文本和附表再次核验。

# 541. 外部依据｜弹性退休制度

人社部发〔2024〕94号《实施弹性退休制度暂行办法》，自 2025-01-01 起施行。

产品约束：
- 自愿、弹性；
- 弹性提前需要书面告知和资格条件；
- 弹性延迟需要本人意愿、单位协商及适用程序；
- 国有企事业单位工作人员按干部人事管理权限和规定程序办理；
- 不能给所有人员一个无差别“延迟退休”按钮。

官方：
https://www.mohrss.gov.cn/wap/zc/zcwj/202501/t20250101_533701.html

# 542. 外部依据｜人事档案转递

《流动人员人事档案管理服务规定》等要求由授权档案管理服务机构规范接收、转递，按规定形成目录、包封、转递与接收流程。

产品约束：
- HR16 只管理 Transfer Case；
- ArchiveProvider 管档案正文；
- SENT ≠ RECEIVED；
- 个人下载电子副本 ≠ 正式档案转递；
- manifest/receipt/异常必须留痕。

# 543. 成熟产品对标｜SAP Offboarding 1H 2026

SAP SuccessFactors 1H 2026 Offboarding 当前覆盖：
- termination-related information；
- time-sensitive activities；
- knowledge transfer；
- asset tracking；
- paperwork；
- HR/admin/employee review；
- employee exit。

官方：
https://help.sap.com/docs/successfactors-onboarding/implementing-onboarding/offboarding

本册只吸收成熟流程思想，不复制其数据模型。

# 544. 政策落地原则

任何全国规则都只进入“国家基线”。
最终生产需再叠加：
- 目标省/市；
- 主管部门；
- 学校；
- 人员类别；
- 干部人事管理权限；
- 特殊退休政策
形成 Tenant PolicyVersion。

开发 AI 禁止从本文直接推断所有学校具体退休批准路线。

# 545. 最终架构冻结图

```text
SOURCE DECISION / RETIREMENT POLICY
               │
               ▼
            ExitCase
               │
      Decision / Date Snapshot
               │
               ▼
       ExitPlanTemplateVersion
               │
        Task DAG / Providers
               │
               ▼
         Completion Gate
               │
               ▼
           ExitEffect
   ┌───────────┼──────────┬───────────┐
   ▼           ▼          ▼           ▼
  HR03        HR14       HR15         IAM
Relation      Term     Settlement   Deprovision
   │           │
   ▼           ▼
 History      HR02
             Vacancy
   │
   └─────────────┬─────────────┐
                 ▼             ▼
           Certificate      Archive
                 │             │
                 └──────┬──────┘
                        ▼
               ExitFact/RetirementFact
                        │
                  HR17 / HR18

Retirement:
Policy → Forecast → Precheck → Intent/Approval
→ ExitCase → RetirementFact → Pension Processing

Rehire:
RetirementFact remains → Referral → HR05/HR08
→ New Employment/Engagement
```

# 546. 最终封板业务条件

- 六个三级模块全闭环
- 2025退休政策与弹性退休可配置/可解释
- 辞职/调出/不续聘/解除/退休/死亡差异化流程
- 跨教学科研资产财务IAM任务真实Provider闭环
- HR03/HR14/HR02/HR15 effects可对账
- 档案/证明/退休历史/返聘衔接完整
- 历史 as-of 正确

# 547. 最终封板技术条件

- A0 tenant fail-closed
- Case ACL
- idempotency
- transition lock
- Outbox/Inbox
- partial-effect reconciliation
- file security
- MySQL concurrency
- Legacy cutover/rollback
- E2E/performance/observability/accessibility/visual regression

# 548. 编码 AI 首条执行指令

```text
你现在施工 HR16 退休与离校。

唯一权威事实源：
16_HR16_退休与离校_施工总册_终极版.md

先执行 HR16-S0，不要先改页面。

必须：
1. 读取 penghaibin9/renshi 目标分支真实 offboarding/employee/contracts/payroll/base 代码；
2. 找出所有 Offboarding/OffboardingEmployee/ResignationLetter/employee.is_active/archive/termination/retirement 的读写入口和副作用；
3. 读取 HR03/HR06/HR07/HR11/HR12/HR14/HR15/HR17/HR18 已冻结 Authority 合同；
4. 审计 IAM、资产、财务、教务、科研、档案 Provider；没有真实 Provider 时定义 Contract + UNAVAILABLE，不用 mock 冒充完成；
5. 物化：
   HR16_GAP_MATRIX.md
   LegacyExitMapping.md
   LegacyExitTrustMatrix.md
   ExitAuthorityBoundary.md
   ExitReasonPolicyMatrix.md
   ExitDateSemanticMatrix.md
   ExitTaskTemplateMatrix.md
   ExitCompletionGateMatrix.md
   RetirementPolicyMatrix.md
   RetirementCategoryMatrix.md
   RetirementProviderMatrix.md
   ExitProviderMatrix.md
   ExitSensitiveDataMatrix.md
   HR16_PERMISSION_MATRIX.md
   HR16_INTEGRATION_MATRIX.md
   HR16_TASK_TREE.md
   HR16_RISK_REGISTER.md
   HR16_MIGRATION_PLAN.md
6. 核验 2025 起渐进式延迟退休、弹性退休及目标学校/主管部门现行实施规则；
7. S0 只审计和落计划；
8. 后续严格 S1→S13；
9. 保留 Horilla Task/Pipeline/Dashboard 可复用技术，但 ExitCase/ExitFact/RetirementFact 为新 Authority；
10. 不用 employee.is_active、legacy archived、合同到期、考核不合格作为自动离退事实；
11. 不根据性别+年龄粗算退休，不绕过 RetirementCategoryAssignment/PolicyVersion；
12. Provider UNAVAILABLE 绝不等于 CLEARED；
13. HR15 SettlementRequested 绝不等于 PAID；
14. IAM request 绝不等于 account revoked；
15. HR03 effect 网络超时必须按幂等键查询/reconcile，禁止重复关闭；
16. 返聘必须新关系，绝不“取消退休”；
17. 不关闭 403 修测试；
18. MySQL 全量回归必须绿；
19. 不使用 git add -A；
20. 未经授权不 push、不 merge main、不部署生产。

只有六模块、退休规则、离退业务、跨系统任务、Effect/Reconciliation、敏感安全、档案证明、返聘、迁移、MySQL、E2E、性能、可观测性、Accessibility、Visual Regression 全部绿色时，才输出：

HR16 READY FOR ACCEPTANCE
```

# 549. 最终封板口径

只有全部 Gate 通过，唯一允许输出：

```text
HR16 READY FOR ACCEPTANCE
```

存在任何 P0/P1：

```text
HR16 NOT READY
blocking:
- <精确缺口>
```

禁止：
- “人已经走了所以算完成”
- “账号之后再关”
- “退休年龄大概没问题”
- “档案以后再转”
- “工资后面再结”
- “Provider 暂时不可用先勾已完成”
