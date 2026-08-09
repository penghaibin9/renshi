# HR05 Gap Matrix（S0 基线复审 · 对照总册终极版）

> 依据：《00_全局架构合同》（§91/§92/§95/§109）、《05_HR05_入职管理_施工总册_终极版》五个三级模块 + H0/A0/HR02/HR03/HR04 硬门。
> 核对对象：`renshi/` 真实代码（onboarding + recruitment + employee + base + horilla_auth + horilla_documents + horilla_audit + notifications + hr_structure + hr_staff + hr_recruitment + hr_control_center）。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`

---

## 0. 顶层裁决

| 层面 | 裁决 | 证据 |
|---|---|---|
| Stage/Task/Kanban/required-task gate 交互骨架 | **ADAPT** | `OnboardingStage/OnboardingTask/CandidateStage/CandidateTask`、`StageChangeForm.clean()`、`KanbanRequiredTaskCheck` 齐全且 gate 逻辑正确 |
| Portal（token 链 + 建号/建员工/银行） | **REWRITE** | `user_creation/employee_creation/employee_bank_details` 直接建 `HorillaUser/Employee/EmployeeWorkInformation/EmployeeBankDetails`；token 明文无过期 |
| 正式生效闸门 | **NEW（依赖 HR03/HR02 Provider）** | 无 `HrOnboardingCase`/Activation 概念；HR03 Employment/Assignment 未建；HR02 reservation 服务已可用 |
| 材料核验 | **NEW** | 仅 `Document`（employee 锚定）；无 requirement/verification/reuse 概念 |
| 协同任务 | **ADAPT + 缺口** | CandidateTask 有骨架但无责任人解析/阻断等级/依赖/自动化 |
| 试用转正 | **REWRITE** | `update_probation_end` 直接写 `Candidate.probation_end` |
| 数据迁移 | **PROJECT** | LegacyOnboardingMapping + DUAL_READ_COMPARE 已列 |

---

## 1. 硬门核对（H0 / A0 / HR04 / HR02 / HR03）

### H0 基础
| 硬门项 | 现状 | 差距 |
|---|---|---|
| Docker / health / ready | `Dockerfile`、`docker-compose*.yml`、`/health/`、`/ready/` 在位 | ✅ 文件在位；S10 实测构建 |
| 迁移可执行 | onboarding 有 0001/0002 migration；hr_structure/hr_staff 各有 0001 | ✅ |
| CI 真实跑迁移/测试 | GitHub Actions 未在本仓库内确认 | ⚠️ S10/S11 前确认 |
| 原 Horilla 测试欠账 | `onboarding/tests.py` 存在（内容未验证）；employee/tests.py 空 | ⚠️ 不能把 legacy 红灯当跃科回归 |

### A0 多学校 fail-closed
| 硬门项 | 现状 | 差距 |
|---|---|---|
| 租户可信上下文解析 | `CompanyMiddleware` + `HorillaCompanyManager` + `hr_control_center.context.resolve_tenant_from_request` 已存在 | ✅ 有可复用范式 |
| 无 tenant 上下文 fail-closed | onboarding 内部 admin 页无显式 403；`hr_control_center/api/views.py` 有 `TENANT_CONTEXT_REQUIRED` 范式 | ⚠️ HR05 必须照做 |
| Portal token 有时效、不入日志 | **❌ 无**：`OnboardingPortal.token` 明文 200 字符、无 expiry/revoke/hash（onboarding/models.py L283） | **HR05-S3 REWRITE**（HrPrehirePortalAccess） |
| 公共 onboarding URL 不可枚举 | token 为 30 hex 随机串（`secrets.token_hex(15)`）难以枚举，但**无速率限制/无失效** | ⚠️ REWRITE 时补 short-lived + purpose + attempt 限流 |
| Portal 与正式员工账号身份体系隔离 | **❌ 混用**：portal 直接建 `HorillaUser`（username=candidate.email）并入员工体系 | **HR05-S3 分离**：Portal 身份 ≠ 员工账号 |
| 上传材料按 tenant+case 隔离 | ❌ `profile` 走 `upload_to="employee/profile"`；无 private storage/签名 URL | HR05-S5 重建 |

### HR04 边界（00 §91）
| 项 | 现状 | 差距 |
|---|---|---|
| `HANDOFF_TO_HR05` 显式幂等 | HR04 已冻结 `ApplicationCanonicalStatus.HANDOFF_TO_HR05` 与 `hr04.handoff_hr05` 权限（S1），**无实现** | HR05 按契约预留消费端；HR04-S8 回填 |
| HR04 Hired ≠ 可入职 | `Candidate.hired`/`start_onboard`/`offer_letter_status` 仍被 onboarding 列表当来源 | HR05 以 `HrOnboardingCase` 为权威，legacy 只投影 |
| Offer 接受和 handoff 幂等 | 无 | 见 RecruitToHireMapping §1.3 |

### HR02 边界（00 §90 / 05 §24）
| 能力 | 真实状态 | 判定 |
|---|---|---|
| `HrOrganization/HrPostCatalog/HrPosition/HrPositionPool/HrStaffingPlan` | `hr_structure` 已注册 INSTALLED_APPS、有 0001 migration、selectors/services/api | ✅ **可用**（优于 HR04 文档 S4 时点判断） |
| `HrPositionReservation` + `PositionService.reserve/commit/release` | 已实现：idempotency_key、`select_for_update`、HELD/COMMITTED/RELEASED/EXPIRED/CANCELLED | ✅ **可用** |
| 可用额度查询接口 | `hr_structure` 有 selectors；无专门 `position-control/availability` API | ⚠️ S4 封装 HR05 Provider（读 + 预占） |
| HR05 须遵守 | 预占未提交不算占岗成功；放弃/No-show 必须 release；reservation 超期 expire | HR05-S4 强制 |

### HR03 边界（00 §92 / 05 §10.5-10.6）
| 能力 | 真实状态 | 判定 |
|---|---|---|
| `HrPerson`/`HrPersonIdentityDocument`/`HrPersonContact` | `hr_staff` S2 已建（tenant-private、fingerprint、掩码） | ✅ |
| `PersonIdentityService.create_person_with_identity` | 已实现 HARD/LIKELY/NO_MATCH 去重；HARD 幂等返回既有 Person；LIKELY 抛 review | ✅ **可调用** |
| `HrStaffMaster` + `StaffMasterService.create_staff` | 已建；`(tenant,staff_no)`/`(tenant,person)` unique | ✅ **可调用** |
| `HrEmploymentRelationship` / `HrStaffAssignment` | **❌ 未建**（hr_staff 计划 S3） | ⚠️ HR05-S4 生效闸门的 Employment/Assignment 依赖未就绪 → Provider mock + 回填 |
| `StaffNumberService` | 存在但实现为“前缀+max 数值+1”+ 5000 行 `select_for_update` 扫描（hr_staff/services/staff_master_service.py L48-71） | ⚠️ 非序号化，00 §24 要求“非 max+1 无并发保护”；HR05 不自行发号，只调用 HR03；此缺口归 HR03 修复，HR05 记录依赖 |
| 激活后事件 | `HR03_EVENT_TYPES` 含 `StaffActivated`，未实现 outbox | HR05-S4 以 outbox 事件契约对齐 |

> **硬门结论：HR04 生产侧 handoff 未实现、HR03 Employment/Assignment 未建 → HR05-S4 Activation Gate 必须以 Provider 契约 mock 先行，完成后再回填，禁止把“报到”直接等于“正式教职工生效”。**

---

## 2. HR05-01 待报到人员

| 需求（总册 §9） | Horilla 现状 | 裁决 | 目标 | 差距 |
|---|---|---|---|---|
| 待报到列表（谁录用但未到校） | `candidates_view`：`Candidate(hired=True, recruitment closed=False)` | PROJECT→NEW | `HrOnboardingCase` 列表 + 统计（待确认/已确认/7天内/延期/风险） | case 模型缺失；统计口径缺失 |
| 入职意愿（确认/延期/放弃） | 无 | NEW | `HrOnboardingCase` 状态机 + `HrReportDelay` + 放弃流程 | 缺失 |
| 延期不覆盖原日期 | `update_joining` 直接改 `joining_date` | REWRITE | `HrReportDelay[]`（old/new/approval） | 缺失 |
| Portal（375 移动优先） | `user_creation/profile_view` 建号链 | REWRITE | `HrPrehirePortalAccess` + `HrPrehireProfile` staging + `GET/PATCH /prehire/me` | token 安全 + 身份隔离 + 不写 HR03 |
| 准备度非虚假百分比 | dashboard `progress = done/total`（dashboard.py L260） | REWRITE | `required_pre_report_tasks_completed/total` + 阻断项展示 | 口径缺失 |
| 风险自动识别 | 无 | NEW | OFFER_EXPIRING/REPORT_DATE_NEAR_NO_CONFIRM/POSITION_RESERVATION_EXPIRING/MISSING_BLOCKING_DOCUMENT 等 | 缺失 |
| 放弃释放 Position Reservation | 无 | NEW | HR02 `release` Provider 调用 | 缺失 |

## 3. HR05-02 报到登记 + Activation Gate

| 需求（总册 §10） | Horilla 现状 | 裁决 | 差距 |
|---|---|---|---|
| 报到≠正式生效（两个动作） | 无 | NEW | `HrReportCheckin`（actual_report_at/location/operator/幂等）+ 独立 `ActivateOnboardingCase` |
| Activation Gate 全项检查 | 无 | NEW | HR04 handoff valid / REPORTED / person match / 材料 / HR02 reservation / 组织岗位 as-of / 用工与人员类别 / 无重复 StaffMaster |
| 正式 Activation 事务（锁 case→HR03→HR02 commit→snapshot→outbox→ACTIVE） | `employee_creation` 直接 `Employee.save()` | REWRITE | 必须走 HR03 Service；Employment/Assignment 未就绪先 mock 后回填 |
| 工号并发保护 | 无（HR03 为 max+1+行锁） | DEPEND_HR03 | HR05 只读 HR03 分配结果；记录依赖 |
| 外部 provisioning 失败不回滚 HR 事实 | 无 | NEW | `HrProvisioningRequest` PARTIAL 状态 + retry/reconciliation |

## 4. HR05-03 入职材料核验

| 需求（总册 §12/§13） | Horilla 现状 | 裁决 | 差距 |
|---|---|---|---|
| 材料要求模板（blocking_phase 分级） | 无 | NEW | `HrOnboardingMaterialRequirement`（PRE_REPORT/REPORT/ACTIVATION/POST_ACTIVATION/PROBATION） |
| 材料状态机 | `Document`（requested/approved/...) | REWRITE | `HrOnboardingMaterial` MISSING/SUBMITTED/UNDER_REVIEW/RETURNED/VERIFIED/REJECTED/EXPIRED/WAIVED |
| 核验记录（谁/何时/依据/证据） | 无 | NEW | `HrMaterialVerification` |
| HR04 材料复用（TRUST_SOURCE/REVERIFY/REQUIRE_ORIGINAL） | `CandidateDocument` 无核验状态 | NEW | `reuse_as_evidence` + 复用策略 |
| 高敏材料受控 | 无（身份证/体检/银行卡明文或不存在） | NEW | 字段加密/裁剪/access audit |
| 人事档案到校 | 无 | NEW | `HrPersonnelFileTransfer` |
| 文件安全（SHA/版本/signed URL） | `Document.clean` 有格式/大小校验；裸存储 | ADAPT+NEW | 沿用校验思路 + private storage + ticket |

## 5. HR05-04 入职协同任务 + Provisioning

| 需求（总册 §14/§15） | Horilla 现状 | 裁决 | 差距 |
|---|---|---|---|
| TaskDefinition（category/responsible_role/due/blocking/prerequisite/automation） | `OnboardingTask`（task_title/stage/candidates/managers/is_required） | ADAPT | 升级为 `HrOnboardingTaskDefinition`；`is_required`→`blocking_level` |
| TaskInstance（assignee/status/时间/payload/failure/version） | `CandidateTask`（candidate/stage/status 5 值/audit） | ADAPT | 9 值权威状态 + 完成证据 + 版本 |
| 责任人解析（角色而非具体 Employee ID） | `employee_id` M2M 直接存员工 | REWRITE | `RESPONSIBLE_HR/COLLEGE_HR/IT_SERVICE/...` 实例化解析 |
| 任务 DAG（prerequisite 防环） | 无 | NEW | prerequisite_task_codes + 防环校验 |
| WAIVED 语义 | 无 | NEW | reason+authority+audit，≠COMPLETED |
| 自动化任务（SSO/邮箱/工资/一卡通） | 无 | NEW | `HrProvisioningRequest` PENDING→RUNNING→SUCCESS/FAILED + retry + reconciliation |
| 协同中心矩阵/我的任务 | `task_report`/`MyOnboardingTaskList` | ADAPT | 换权威数据源 |
| 入职完成定义 | dashboard“进度 100%”误导 | REWRITE | `OnboardingCompletionPolicy`（ACTIVE + BLOCKS_ONBOARDING_COMPLETE 全完 + 无 critical risk） |

## 6. HR05-05 试用与转正

| 需求（总册 §17） | Horilla 现状 | 裁决 | 差距 |
|---|---|---|---|
| `HrProbationCase`（start/planned/actual/policy/status/result） | `Candidate.probation_end` 单日期（update_probation_end 直接写） | REWRITE | 完整试用事实模型 |
| 试用目标/自评/单位评价/HR 审核 | 无 | NEW | `HrProbationGoal` + review flow |
| 延长保留历史 | 无 | NEW | `HrProbationExtension[]`，不覆盖 planned_end_date |
| 转正成功发 `ProbationConfirmed` + HR03 领域服务 | 无 | NEW | 不直接改多表 |
| 转正失败走正式人事事件（HR07/HR16） | 无 | NEW | 不 `Employee.is_active=False` |

---

## 7. Legacy 与投影缺口

| 项 | 现状 | 差距 |
|---|---|---|
| Horilla onboarding 继续运行 | ✅ 现状可跑 | HR05 authority 上线前不删除 |
| Legacy Projection（case→CandidateStage/CandidateTask） | 无 | S8 施工 |
| DUAL_READ_COMPARE 对账 | 无 | S9 施工 |
| `portal_user` 进程内 dict 等脆弱实现 | `portal_user[session_key]=user`（views.py L1128） | REWRITE 消除 |
| `create_initial_stage` post_save signal | Recruitment save 自动造 Stage（models.py L59） | 00 §58 signal 治理；S8 收口 |

---

## 8. 待建 app/目录（S2 起，总册 §32 结构）

```
renshi/hr_onboarding/
    models/{template,case,prehire,material,reporting,activation,task,provisioning,probation}.py
    services/{case,report,material,activation,task,provisioning,probation}_service.py
    integrations/{hr02,hr03,hr04,hr07,hr15,iam,academic}.py
    api/ portal/ policies/ selectors/ projections/ jobs/ tests/
```
