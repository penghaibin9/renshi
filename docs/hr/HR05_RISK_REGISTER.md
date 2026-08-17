# HR05 Risk Register（S0 基线复审 · P0 数据/权限/状态机/事务/并发）

> 依据：《05_HR05_入职管理_施工总册_终极版》第 0 节禁止清单 + 第 47/52/54 节 + 真实代码审计。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`
> 风险分级：P0（封板阻断，施工期必须解决）/ P1（验收前必须解决）/ P2（后续迭代）

---

## 1. P0 风险（封板阻断）

| ID | 类别 | 风险 | 真实代码证据 | 缓解/对策 | 负责阶段 |
|---|---|---|---|---|---|
| R-001 | 边界 | Portal 直接 `Employee.save()` + 建 WorkInfo + 批量建 Document，绕过 HR03 | `onboarding/views.py employee_creation()` L1306-1342（EmployeeCreationForm.save → EmployeeWorkInformation.update_or_create → Document.bulk_create） | Portal 只写 `HrPrehireProfile` staging；正式生效走 `ActivateOnboardingCase` → HR03 Activation Service；旧路由 S8 降级只读 | S2/S4/S8 |
| R-002 | 安全 | Portal 与员工账号体系混用：token 链直接建 `HorillaUser` | `user_creation()` L1150 `HorillaUser.objects.filter(username=candidate.email)`；`portal_user[session_key]=user` 进程内 dict L1128 | Portal 身份 = `HrPrehirePortalAccess`；账号属 Provisioning；S8 移除 legacy 建号入口 | S3/S8 |
| R-003 | 安全 | Portal token 明文、永久有效、无撤销/哈希/限流/会话绑定 | `OnboardingPortal.token=CharField(200)`（models.py L283）；`secrets.token_hex(15)` 明文存库；无 expiry | `HrPrehirePortalAccess`（token_hash + purpose + expires_at + revoked_at + last_used_at + failed_attempts + status）；明文只签发一次、不入日志/URL analytics | S2/S3 |
| R-004 | 状态机 | 报到登记、正式任职、账号开通、发薪起算全部混成一个动作 | `employee_bank_details_save` 一次完成 Employee+BankDetails+converted_employee_id+used=True（views.py L1397-1418）；`Candidate.hired=True` 即进列表 | 拆分 `HrReportCheckin`（REPORTED）、`HrOnboardingCase`（ACTIVE）、`HrProvisioningRequest`（账号）、HR15 PayrollProfileRequested；一个“已完成”必须能解释欠账环节 | S2/S4/S6 |
| R-005 | 数据 | 直接写 `Candidate.joining_date`/`probation_end`，无历史、非权威 | `update_joining()`（L1729-1760）；`update_probation_end()`（L1938-1961） | `expected_report_date` + `HrReportDelay[]` 保留历史；`HrProbationCase` 权威；legacy 字段只读投影 | S3/S7 |
| R-006 | 并发 | 同一 HR04 ProposedHire 重复建两份 onboarding case | 无 handoff、无 unique(source_type,source_id)；HR04 handoff 未实现 | `UNIQUE(tenant,source_type,source_id)` + 幂等消费；重复调用返回同一 case | S2/S3 |
| R-007 | 并发 | 岗位预占并发超卖/预占未提交就算占岗成功 | legacy 无 reservation；HR02 `PositionService.reserve/commit/release` 已就绪（含 `select_for_update` + idempotency_key） | HR05 一律经 `Hr02PositionProvider`；Activation 才 `HELD→COMMITTED`；放弃/No-show 必须 `RELEASED`；失败补偿作业 | S4 |
| R-008 | 数据 | 工号“当前最大值+1”无并发保护 | HR03 `StaffNumberService.next_staff_no`（staff_master_service.py L48-71）：max+1 + 5000 行 select_for_update 扫描，非序号化 | HR05 **不自建工号**，只调 HR03；记录依赖由 HR03 修复为 `HrStaffNumberSequence`（00 §24）；并发测试覆盖 | S4/依赖HR03 |
| R-009 | 安全 | 公开 onboarding URL 可枚举/无失效/无限流 | portal 4 路由 `/onboarding/user-creation/<token>` 等；token 30 hex 但永久有效、count 仅步进 | short-lived token + purpose + attempt/rate limit + session binding；公共 URL 不可枚举（00 §134） | S3 |
| R-010 | 安全 | 跨学校通过手机号/身份证自动识别同一人 | legacy `Candidate` 无 tenant-scope 去重；HR03 `find_duplicate` 已 tenant-private（person_identity_service.py L49-82） | 一律复用 HR03 去重（先 tenant）；LIKELY_MATCH 进人工队列；禁止自动合并 | S4 |
| R-011 | 隐私 | 高敏材料（身份证/银行卡/体检/无犯罪/档案）明文/裸 URL 暴露 | `OnboardingPortal.profile` upload_to="employee/profile"；无 SHA/版本/ticket；`employee_bank_details` 明文 | private storage + 签名 URL ticket + 高敏裁剪 + 字段加密 + 访问审计；材料按 tenant+case 隔离 | S3/S5 |
| R-012 | 事务 | 激活成功但外部 provisioning 失败 → 误显示“入职完成” | 无 provisioning 概念；legacy dashboard `progress=done/total` 100% 误导（dashboard.py L260） | `HrProvisioningRequest` PARTIAL + retry/reconciliation；`OnboardingCompletionPolicy` 区分正式生效/协同进度/阻断项/后续事项 | S4/S6 |
| R-013 | 边界 | 材料“Day1 前必须”与“可事后补齐”不分，流程僵死或失控 | 无 requirement/blocking_phase 概念 | `HrOnboardingMaterialRequirement.blocking_phase`（PRE_REPORT/REPORT/ACTIVATION/POST_ACTIVATION/PROBATION）+ 可配置 | S5 |
| R-014 | 状态机 | 转正失败直接 `Employee.is_active=False`，无正式人事事件 | 无试用模型（仅 `probation_end` 单日期） | `ProbationFailed` 事件 → HR07/HR16 处理合同/离开；HR05 不删除/禁用员工 | S7 |
| R-015 | 数据 | 延期报到直接覆盖原预计日期，不留历史 | `update_joining` 直接赋值 | `HrReportDelay[]`（old/new/reason/approval）+ audit | S3 |
| R-016 | 状态机 | 多部门协同失败静默跳过；账号失败但显示完成 | legacy task 仅状态 5 值、无阻断等级、无负责人截止 | blocking_level + assignee/due_at + FAILED 显式 + 协同中心可见 | S6 |

## 2. P1 风险（验收前解决）

| ID | 类别 | 风险 | 对策 | 负责阶段 |
|---|---|---|---|---|
| R-101 | 依赖 | HR03 `HrEmploymentRelationship/HrStaffAssignment` 未建，Activation 无法创建正式任职 | S4 用 `Hr03ActivationProvider` 契约 + `mode=MOCK` 仅测试；HR03-S3 就绪后回填真实现，回填前不宣称生产 | S4 |
| R-102 | 依赖 | HR04 `handoff-to-hr05` 未实现 | HR05 按 RecruitToHireMapping 预留幂等消费端 + mock；HR04-S8 联调 | S3 |
| R-103 | 数据 | 已转 Employee 的历史 Candidate 迁移回填不准确 | `converted_employee_id` → HR03 StaffMaster legacy_employee_id 映射 + activation snapshot；对账 | S9 |
| R-104 | 状态机 | `CandidateStage` 被当权威阶段历史（OneToOne 无历史） | `HrOnboardingStageTransition[]` 权威；CandidateStage 仅投影 | S2/S8 |
| R-105 | 权限 | stage/task manager 权限仅按 M2M Employee 判断，无 data scope | `all_manager_can_enter` 等（decorators.py）按 Employee 关系判断；HR05 用 `Hr05RequestContext` tenant+scope 重做 | S1/S3 |
| R-106 | 安全 | IT/财务等任务执行人可见不必要 PII（体检/薪资/简历） | 字段级权限 + 服务端裁剪；IT 只看“为工号 X 开通邮箱” | S1/S5/S6 |
| R-107 | 并发 | Portal 重复提交（网络重试）造成双材料/双申请 | Idempotency-Key + task/material unique + 提交事务 | S3/S5 |
| R-108 | 并发 | 两 HR 同时 Activate 同一 case | `select_for_update` case + version；409 VERSION_CONFLICT；重复激活返回原结果 | S4 |
| R-109 | 数据 | 模板变更污染历史 case | case 绑定 `HrOnboardingTemplateVersion`（snapshot 冻结）；后续改模板不影响旧 case | S2 |
| R-110 | 数据 | 材料 HR04 已验证状态被无条件继承 | `reuse_policy`：TRUST_SOURCE/REVERIFY/REQUIRE_ORIGINAL；不自动继承 | S5 |
| R-111 | 数据 | 完成定义模糊导致“100% 完成”误导 | `OnboardingCompletionPolicy`（ACTIVE + BLOCKS_ONBOARDING_COMPLETE 全完/waived + 无 critical risk）；UI 分离 | S6 |
| R-112 | 安全 | 旧 portal 路由在 authority 切换后仍可建号 | S8 legacy 路由 readonly/redirect；禁止再写 Employee/User | S8 |
| R-113 | 数据 | 试用期结束日期仍被写 Candidate.probation_end | 迁移后禁止 legacy 写入口；`HrProbationCase` 唯一权威 | S7/S9 |
| R-114 | 可观测 | 无 HR05 专项 metrics / PII 日志风险 | metrics（05 §49）+ 结构化日志无高敏 payload | S1/S10 |

## 3. P2 风险（后续迭代）

| ID | 类别 | 风险 | 对策 |
|---|---|---|---|
| R-201 | 集成 | IAM/邮箱/一卡通/教务等外部系统未接入 | `HrProvisioningRequest` 抽象 + integration registry（00 §144）；先内部成功态 + 外部 mock 标记 |
| R-202 | 集成 | 工资档案（HR15）未就绪导致“已完成入职”误判 | 完成策略按学校配置；PayrollProfileRequested 事件契约预留 |
| R-203 | 数据 | `OnboardingPortal.count`（0-4 步进）与 token 安全耦合 | 已重做为 `HrPrehirePortalAccess` 状态 + `HrPrehireProfile` 进度 |
| R-204 | 分析 | 待报到统计/风险从 legacy 字段反推 | 全部基于 `HrOnboardingCase` 权威字段/事件 |

## 4. 硬门追踪（封板依据）

- [ ] H0：Docker/health/ready/CI 实测迁移测试（S10/S11）
- [ ] A0：tenant fail-closed 全绿；Portal token 有时效不入日志；公共 URL 不可枚举；Portal 与员工账号隔离（S3）
- [ ] HR04：handoff 幂等 + 重复 case=0（S3 + HR04-S8）
- [ ] HR02：reservation HELD→COMMITTED 只发生在 Activation；放弃/No-show 释放（S4）
- [ ] HR03：Person match tenant-private、Employment/Assignment 就绪或显式 mock+回填标记（S4）
- [ ] 材料：Day1 硬阻断与事后补齐分级；附件 tenant+case 隔离、无裸 URL（S5）
- [ ] 协同：任务失败不静默跳过；账号失败不显示“完成”（S6）
- [ ] 试用：转正失败走正式事件；延长保留历史（S7）
