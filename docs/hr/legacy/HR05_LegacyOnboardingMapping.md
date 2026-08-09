# HR05 LegacyOnboardingMapping（S0 基线复审 · Horilla onboarding → HR05 权威）

> 依据：《00_全局架构与Horilla接管合同》（§109 onboarding→HR05 REWRITE）、《05_HR05_入职管理_施工总册_终极版》（§3.3/§43/§44/§45/§46）。
> 核对对象：`renshi/onboarding/` 真实代码（models.py / views.py / forms.py / urls.py / cbv/* / dashboard.py / sidebar.py）+ 关联 `recruitment` / `employee` / `base` / `horilla_auth` / `horilla_documents` / `horilla_audit` / `notifications`。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1` · 策略沿用 00 §53（KEEP / ADAPT / LEGACY_PROJECTION / REWRITE / DEPRECATE / DROP_AFTER_CUTOVER）

---

## 0. 顶层裁决

| Horilla onboarding 能力 | 裁决 | 一句话理由 |
|---|---|---|
| Stage + Task + CandidateStage/CandidateTask 交互骨架 | **ADAPT** | 有阶段/任务/看板/required-task gate，是 HR05 的现成交互底座 |
| Candidate → Employee 快捷转换（Portal 直接建 User/Employee/BankDetails） | **REWRITE → 移除 authority** | 与 HR05 核心原则“报到≠任职≠账号≠发薪”直接冲突 |
| OnboardingPortal token 模型 | **REWRITE**（安全重做） | 明文 token、无过期/撤销/哈希/限流/会话绑定 |
| Candidate.hired / start_onboard / joining_date / probation_end | **DEPRECATE authority** | 录用真值归 HR04；日期/试用归 HR05 权威模型 |
| Kanban / Dashboard | **KEEP/ADAPT** | 保留交互，数据源切 HR05 权威投影 |
| 邮件/通知 | **KEEP/ADAPT** | 接全局通知体系（模板版本/去重/回执） |

**总原则（00 §109 / 05 §70）：Horilla onboarding 是“阶段+任务+Portal+Kanban”骨架；HR05 把“合法来源、报到事实、材料证据、正式生效事务、岗位占用、权威人员创建、跨部门 provisioning、试用转正”补成高校生产级事实链，旧交互逐步变成新权威模型的工作界面。S0 阶段不删除、不重写任何 legacy 代码。**

---

## 1. 模型映射（Horilla → HR05 Authority）

### 1.1 主模型

| # | Horilla 模型/字段 | HR05 权威模型 | 策略 | 说明（真实代码证据） | Cutover 条件 |
|---|---|---|---|---|---|
| 1 | `OnboardingStage`（stage_title / recruitment_id FK / employee_id M2M / sequence / is_final_stage） | `HrOnboardingTemplate` + `HrOnboardingTemplateVersion` + `HrOnboardingStageDefinition` | **ADAPT + 投影** | 缺陷 A：阶段绑 `recruitment_id`（models.py L32），模板不是独立对象；每新建 Recruitment 由 post_save 自动造 "Initial" 阶段（L59-70），属 00 §58 需治理的 signal 副作用。HR05 模板须独立于 Recruitment，可按人员类别/用工/岗位/组织选择 | 模板版本建模完成 + Stage 投影（legacy→HR05）接通 |
| 2 | `OnboardingTask`（task_title / stage_id FK / candidates M2M / employee_id M2M / is_required bool） | `HrOnboardingTaskDefinition` | **ADAPT** | `is_required` 单布尔 → 总册 §14.3 需升级为 `blocking_level`（INFO/NON_BLOCKING/BLOCKS_ACTIVATION/BLOCKS_ONBOARDING_COMPLETE/BLOCKS_PAYROLL/BLOCKS_WORK_ACCESS）；补 prerequisite、due_offset、available_offset、completion_type、automation_handler | S2 建模 + S6 实例化 |
| 3 | `CandidateStage`（candidate OneToOne / onboarding_stage FK / onboarding_end_date / sequence） | `HrOnboardingCase.current_stage_code` + `HrOnboardingStageTransition[]` | **LEGACY_PROJECTION** | 缺陷 B：OneToOne 只有一个“当前阶段”，适合 Kanban 投影，不是正式阶段历史；`save()` 到 final stage 直接写 `onboarding_end_date=datetime.today()`（L163-166），无审批/无审计 | S3 起 case 为权威，CandidateStage 只读投影 |
| 4 | `CandidateTask`（candidate FK / stage FK / status: todo/scheduled/ongoing/stuck/done / onboarding_task FK） | `HrOnboardingTaskInstance` | **ADAPT + migrate** | 缺陷 C：状态太粗，无完成人/时间/证据/阻断等级/依赖；history 是 HorillaAuditLog（simple-history），非正式业务审计 | S2 建模 + S6 实例化/迁移 |
| 5 | `OnboardingPortal`（candidate OneToOne / token 明文 / used / count / profile ImageField） | `HrPrehirePortalAccess` | **REWRITE（安全）** | 缺陷 D：token 明文存库（models.py L283）、无 expiry/revoke/hash/purpose/rotation/last_used/attempt 限流；`count` 兼作“步骤进度”与“访问次数”，语义混用；profile 走 `/employee/profile` 裸路径 | S3 Portal 重建完成 |
| 6 | `OnboardingCandidate`（Candidate proxy） | HR04 `HrRecruitmentCandidate/HrJobApplication` 来源 | **不再作为 HR05 authority** | Candidate 锚定 Recruitment 是 legacy；HR05 的锚点是 `HrOnboardingCase.source_type + source_id (+ hr04_proposed_hire_id)` | HR05 case 建模完成 |

### 1.2 Portal 路由链（REWRITE 重点）

| # | Horilla 路由（urls.py 证据） | 现状行为 | HR05 裁决 |
|---|---|---|---|
| 1 | `onboarding/user-creation/<str:token>` | 凭明文 token 建 `HorillaUser`（username=candidate.email），并把未保存 user 放进程内 dict `portal_user[session_key]`（views.py L1128/L1186） | **REMOVE authority**：Portal 与员工账号体系隔离；账号属 Provisioning，不由 Portal 建 |
| 2 | `onboarding/profile-view/<str:token>` | 上传头像即改 `candidate.profile` | **REWRITE**：并入 `HrPrehireProfile` staging（可作 non-authority 采集） |
| 3 | `onboarding/employee-creation/<str:token>` | **直接 `Employee.save()` + 建 `EmployeeWorkInformation` + 批量建 `Document`**（views.py L1306-1342）；这是“Portal 直接 Employee.save()”的实锤 | **REMOVE authority**：改走 `ActivateOnboardingCase` 领域命令 → HR03 Activation Service；staging 数据先落 `HrPrehireProfile` |
| 4 | `onboarding/employee-bank-details/<str:token>` | 建 `EmployeeBankDetails`；`candidate.converted_employee_id=employee`；`used=True`（L1397-1418） | **REWRITE**：银行数据进加密 staging，`PayrollProfileRequested` 交 HR15；HR05 不持有正式工资事实 |
| 5 | `onboarding/welcome-aboard/` | 仅静态页 | KEEP（文案/引导交互） |

### 1.3 行为/业务字段映射

| # | Horilla 行为/字段 | HR05 权威 | 策略 | 证据与说明 |
|---|---|---|---|---|
| 1 | `email_send()`：`secrets.token_hex(15)` 生成 token、`Candidate.objects.filter(pk=...).update(start_onboard=True)`、`get_or_create(CandidateStage)` | HR04 `HANDOFF_TO_HR05` → HR05 `OnboardingCaseCreated` + `HrPrehirePortalAccess` 签发 | **REWRITE** | 无幂等键，重复发送反复重置 token；`start_onboard` 用 update() 绕过 save() 校验（views.py L934）；stage 用 `.first()` 无排序保证 |
| 2 | `candidate_creation`：`candidate.hired=True` | 无（HR04 ProposedHire/Offer 才是录用真值） | **DEPRECATE authority** | views.py L446-447 |
| 3 | `candidates_view`：`Candidate.objects.filter(is_active=True, hired=True, recruitment_id__closed=False)` | HR05-01 待报到人员列表（读 `HrOnboardingCase`） | **PROJECT** | “已录用”≠“已进入待报到” |
| 4 | `update_joining`：直接 `candidate.joining_date = date_value` | `HrOnboardingCase.expected_report_date` / `HrReportCheckin.actual_report_at` | **REWRITE** | 无历史；HR05 延期必须走 `HrReportDelay` 保留历史 |
| 5 | `update_probation_end`：直接 `candidate.probation_end` | `HrProbationCase` + `HrProbationExtension[]` | **REWRITE** | 直接写 `Candidate.probation_end` 是明确禁止项（05 §0 清单） |
| 6 | `candidate_stage_update` / `candidate_stage_bulk_update`：直接改 `CandidateStage.onboarding_stage_id` | `HrOnboardingStageTransition` + case 状态机 | **REWRITE** | 拖拽即改正式状态；HR05 必须走 transition service + blocking task 校验 |
| 7 | `StageChangeForm.clean()` / `KanbanRequiredTaskCheck`：`pending_required_tasks` 阻塞前进 | `HrOnboardingTaskInstance` prerequisite/blocking 检查 | **ADAPT**（保留交互） | required task gate 概念正确，保留并升级 |
| 8 | `offer_letter_status`（not_sent/sent/accepted/rejected/joined） | HR04 `HrRecruitmentOffer` 状态（只读投影） | **DEPRECATE authority** | 录用链归 HR04 |
| 9 | `task_report` / `MyOnboardingTaskList` / dashboard | HR05-04 协同中心“我的任务” | **ADAPT** | 保留个人任务视图，换权威数据源 |
| 10 | `onboarding/kanban` / `pipeline`（CandidateStage group） | HR05 Case Stage 工作台 | **KEEP/ADAPT** | 拖拽只能触发 transition，不能绕过 task gate |
| 11 | `send_mail` / `ConfiguredEmailBackend` / `HorillaMailTemplate` | 全局通知体系（templateVersion→recipient→channel→dedupe→status） | **KEEP/ADAPT** | 复用邮件后端与模板概念，升级版本化/回执 |
| 12 | `Document`（horilla_documents）批量建（employee_creation 内） | `HrOnboardingMaterial` + `HrStaffMaterial`（HR03 长期档案） | **REWRITE** | 材料按 tenant+case 隔离；短期签名 URL；SHA-256；核验人 |
| 13 | `OnboardingPortal.count`（0-4 步骤） | `HrPrehirePortalAccess` 状态 + `HrPrehireProfile.submitted_at/verification_status` | **REWRITE** | 步骤进度与 token 安全分离 |

---

## 2. 路由/入口接管清单

| Horilla 入口 | HR05 入口 | 迁移期 | HR05_AUTHORITY 后 |
|---|---|---|---|
| `/onboarding/`（sidebar: Dashboard/Candidates/Onboarding Tasks） | `/hr/onboarding/prehires` `/reporting` `/cases/:id/*` `/collaboration` `/probations` | LEGACY_ONBOARDING_ONLY：新旧并存 | 旧菜单隐藏/重定向只读；新 case 只写 HR05 |
| `/onboarding/user-creation/<token>` 等 4 个 portal 路由 | Portal（public slug + short-lived token，`/portal/prehire/:accessToken`） | 旧 token 失效策略由迁移脚本控制 | 旧路由返回重定向/只读，禁止再建账号 |
| `onboarding/views.py` 的 function/CBV | `hr_onboarding/services|api|portal` | DUAL_READ_COMPARE | legacy 只读投影 |
| `onboarding/dashboard.py` + `view_dashboard` | HR05 工作台（dataBasis=HR05_AUTHORITY） | 新旧口径并列 | 旧 KPI 下线 |

---

## 3. 数据迁移方案（对应 05 §46）

1. **Recruitment/Candidate 对齐 HR04/HR05**：`Candidate` → HR04 `HrRecruitmentCandidate/HrJobApplication`（拆人/申请）；`recruitment_id` → HR04 campaign/position 投影。
2. **创建 `HrOnboardingCase`**：`source_type=LEGACY_MIGRATION`，`source_id`=Candidate.id；绑定 HR04 proposed_hire（如已 handoff）或 legacy link。
3. **映射 current stage**：`CandidateStage.onboarding_stage_id` → case `current_stage_code`（显式 LegacyStageMap，覆盖全部 active stage）。
4. **迁移任务**：`CandidateTask` → `HrOnboardingTaskInstance`（status 5 值 → 9 值权威状态，todo→NOT_STARTED 等显式映射）。
5. **迁移 joining/probation**：`joining_date` → `expected_report_date`；`probation_end` → `HrProbationCase.planned_end_date`（不直接写 Candidate）。
6. **识别已转换 Employee**：`converted_employee_id` → 回填 `hr03_staff_master_id`（HR03 StaffMaster legacy_employee_id 映射），生成 `HrOnboardingActivationSnapshot`（as-of 源版本）。
7. **历史已入职者**：`source_type = LEGACY_MIGRATION`，**不得重新触发账号/岗位/工资副作用**（05 §46）。
8. **对账（DUAL_READ_COMPARE）**：candidate count、current stage、required tasks、task status、joining date、portal status、probation end；discrepancy 必须可见，禁止“新系统空就读旧系统”。

## 4. 迁移期禁止项（05 §68）

- 不直接删除 Horilla onboarding；
- 不把 `CandidateStage` 当权威历史；
- 不自动 fallback legacy（Provider 故障不得读旧系统）；
- 不用 mock 冒充 HR05 业务完成；
- 不在 HR05 建第二份 StaffMaster（一律走 HR03 `StaffMasterService`）。
