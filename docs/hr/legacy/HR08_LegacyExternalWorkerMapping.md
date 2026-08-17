# HR08 LegacyExternalWorkerMapping（初版 · 依据真实仓库核对）

> 文档性质：HR08-S0 前置交付；依据 `renshi` 仓库真实模型/字段核对后物化。
> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md`（§111 Legacy Mapping / §112-117）
> 对接边界：HR03 `HrPerson` 为唯一自然人身份根；HR07 为协议/合同生命周期权威（未交付，采用 Provider 契约占位）；HR15 结算权威；教务课程权威。
> 物化时间：2026-08-09
> 状态：`DRAFT_V1` —— HR08 编码期以最终模型核对后升级

---

## 1. 结论先行

- Horilla 的 `Employee / EmployeeWorkInformation / EmployeeType / Contract / Candidate / OnboardingPortal / Document` **不具备**高校外聘教师权威能力：
  - `Employee` 强绑定 HorillaUser（save 自动建账号）、email 全局 unique、`is_active` 粗状态、无 effective-dated 多关系；
  - `EmployeeWorkInformation` 是"当前快照"，只能表达一个 department/position/type；
  - `EmployeeType` 只是一个 CharField 字典，不能表达「荣誉称号≠受聘、多 Engagement、类别策略」；
  - `payroll.Contract` 承载 wage/leave 配置，与正式协议生命周期无关。
- HR08 采用 **REWRITE**：新建 `hr_external` app 承载 External Workforce Authority；Horilla 旧模型降级为**单向投影（projection）**，Authority 切换后旧外聘写入口关闭。
- **HR03 边界（§6.1/§6.3）**：身份根复用 `hr_staff.HrPerson`（tenant-private），**禁止**自建 `ExternalPerson` 第二自然人表；外聘教师目录投影若需 Staff ID，通过 HR03 受控服务建立 `HrStaffMaster`（source 受控）并保留 HR08 侧 `worker_kind=EXTERNAL` 标记，`regular_employee/benefits_eligible/payroll_regular/attendance_regular` 全部默认 false。
- **HR07 边界（§7）**：`agreement_id/agreement_status` 只引用 HR07；HR07 未交付期间用 Provider 契约占位（`agreement_type_code + agreement_status` 文本语义 + 解析函数），不建第二套协议表。
- **禁止推断**：不根据 EmployeeType 文本猜外聘类别、不把 `is_active=False` 一律当退出、不按姓名自动合并重复人。

## 2. 引用盘点（S0 输出）

### Employee / EmployeeType / WorkInformation / Contract / Candidate 被引用范围

- **后端模型**：`employee/models.py`（Employee/EmployeeWorkInformation/EmployeeBankDetails）、`base/models.py`（EmployeeType/Company/Department/JobPosition/JobRole/WorkType/EmployeeShift）、`payroll/models/models.py`（Contract）、`recruitment/models.py`（Candidate/Recruitment）、`onboarding/models.py`（OnboardingStage/OnboardingTask/CandidateStage/OnboardingPortal）、`horilla_documents/models.py`（Document/DocumentRequest）、`horilla_audit/models.py`（HorillaAuditLog）、`notifications/models.py`。
- **账号创建**：`employee/models.py::Employee.save()`（无 user 时 `HorillaUser.objects.create_user(username=email, password=phone, is_new_employee=True)` + 默认 `change_ownprofile/view_ownprofile` 权限 + `EmployeeWorkInformation` 自动创建）。
- **统计/工作台**：`employee/dashboard.py`、`hr_control_center/providers/workforce.py`、`hr_control_center/providers/legacy_employee.py`、`hr_control_center/services/alert_service.py`。
- **报表**：`report/views/{employee,payroll,leave,attendance}_report.py`（大量 `employee_work_info__employee_type_id__employee_type`）。
- **请假/考勤依赖**：`leave/services.py`、`leave/views.py`、`leave/filters.py`、`leave/cbv/*`、`attendance/*`、`base/ess_dashboard.py`、`employee/not_in_out_dashboard.py`。
- **Payroll 依赖**：`payroll/scheduler.py`（generate_payslip 按 company 全量 Employee + active Contract）、`payroll/methods/*`（active Contract wage）、`payroll/signals.py`（Contract 写回）、`payroll/forms/component_forms.py`（`Employee.objects.filter(is_active=True)` 组件适用范围）。
- **招聘/入职**：`recruitment/models.py::Candidate`、`recruitment/cbv/*`、`onboarding/models.py`、`onboarding/threadings/portal_send.py`。
- **HR04 现状**：`hr_recruitment` 已有 constants/api/policies/projections 骨架，**权威模型尚未交付**（`hr_recruitment` 无 models 目录）。HR08 与 HR04 的边界（§9：HR04 可作 `EXTERNAL_RECRUITMENT` 来源之一）以 Provider/Event 契约对接，不直接写 HR04。

### 接管裁决

| Horilla 对象 | HR08 决策 | 终局用途 |
|---|---|---|
| `Employee` | **PROJECT** | 仅作 legacy 当前目录投影（HR08-S9）；不是 HR08 权威身份根 |
| `Employee.email` | **PROJECT/evidence** | 联系方式 + 身份证据，不再作为 person 唯一标识 |
| `Employee.is_active` | **PROJECT hint** | 只是当前投影，不代表 Engagement 状态、不代表退出 |
| `Employee.save()` 自动建账号 | **DO NOT REUSE** | 外聘账号走 HR08 AccessGrant + IAM provisioning（S6），严禁复用该入口 |
| `EmployeeType` | **ADAPT → projection** | 外聘类别权威在 `HrExternalCategory`；EmployeeType 仅用于 legacy 报表兼容投影 |
| `EmployeeWorkInformation.department` | **PROJECT** | `HrExternalEngagementAssignment.organization_id`（HR02 HrOrganization）权威 |
| `EmployeeWorkInformation.job_position` | **PROJECT** | `post_catalog_id`/`service_role` 权威（HR08 §8） |
| `EmployeeWorkInformation.contract_end_date` | **PROJECT** | Engagement.end_at 权威 |
| `payroll.Contract` | **DEPRECATE + PROJECT** | 归 HR07/HR15；HR08 不重建 |
| `recruitment.Candidate` | **possible source** | 映射 `source_type=EXTERNAL_RECRUITMENT`；不是权威 |
| `onboarding.OnboardingPortal` | **UX reference only** | 外聘本人门户交互参考；不直接复用 Employee 创建 |
| `horilla_documents.Document` | **KEEP/ADAPT** | 证据/材料文件底层（MIME/大小校验）；HR08 增加版本/敏感/票据 |
| `horilla_audit.HorillaAuditLog` | **KEEP + NEW** | 技术历史辅助；HR08 正式业务审计 `HrExternalAuditEvent` |
| `notifications` | **KEEP/ADAPT** | 事件驱动通知（模板版本/去重/回执） |

## 3. 字段级映射

### `Employee` → HR03 HrPerson / HR08 Profile
```
Employee.id                        → HrStaffMaster.legacy_employee_id（仅映射）+ HrLegacyProjectionState
Employee.employee_first/last_name  → HrPerson.legal_name（中文姓名拼接规则迁移前确认）
Employee.email                     → HrPersonContact(PERSONAL_EMAIL/WORK_EMAIL) 证据；禁止 person unique
Employee.phone                     → HrPersonContact(PERSONAL_MOBILE)（SENSITIVE 掩码）
Employee.dob/gender                → HrPerson.birth_date/gender_code（数据质量校验）
Employee.qualification/experience  → 不迁为外聘资格事实；只能作为 legacy reference
Employee.emergency_contact         → HrEmergencyContact（受限字段）
Employee.is_active                 → migration hint，不能直接等于 Engagement status
Employee.employee_user_id          → IAM 账号生命周期由 HR08 AccessGrant 管辖；不反向从 legacy 建账号
Employee.badge_id                  → HR08 external_teacher_no（独立 tenant-scoped 序列，不复用正式工号序列）
```

### `EmployeeWorkInformation` → Engagement/Assignment 投影
```
EmployeeWorkInformation.company_id      → tenant 归属校验（A0）；映射 HrExternalCategory/Engagement tenant
department_id                          → EngagementAssignment.organization_id（HR02 HrOrganization stable id）
job_position_id                        → post_catalog_id / service_role（HR08 §8 岗位边界）
job_role_id                            → 不自动映射外聘角色；按校规核验
employee_type_id                       → HrExternalCategory 候选映射（dict 映射，不进 authority 前必须人工确认）
reporting_manager_id                   → 外聘不建 reporting_manager；改用 reviewer_id/主办部门
shift_id/work_type_id                  → 外聘默认不落入 HR11 常规考勤规则（attendance_regular=false）
date_joining                           → Engagement.start_at 候选（需对账）
contract_end_date                      → Engagement.end_at 候选（需对账）
basic_salary/salary_hour               → HR15 结算参考；HR08 不存"工资"
```

### `EmployeeType` → HrExternalCategory（映射候选）
```
employee_type 文本                     → HrExternalCategory.code/name 候选映射
                                        （e.g. "外聘教师/兼职教师/产业教授/技能大师/客座教授/荣誉教授"）
```
**禁止自动硬迁**：无映射规则时进入 exception queue 人工确认。

### `payroll.Contract` → HR07（Provider 占位）
```
Contract.employee_id        → HR03 staff/employment ref（重映射）
Contract.contract_name      → HR07 Agreement title/type 参考
Contract.contract_start/end → HR07 agreement dates 参考
Contract.contract_status    → HR07 lifecycle status（映射前校验）
Contract.wage/pay_frequency → HR15 结算（移出 HR08 权威）
Contract.contract_document  → HR07 AgreementDocument（迁移候选）
Contract.notice_period      → HR07 AgreementTerm 候选
```
> HR08 不在本域重建 Contract；`HrExternalEngagement.agreement_id/agreement_status` 通过 HR07 Provider 解析（未交付 → `NOT_AVAILABLE` + 状态占位）。

## 4. 无法迁移的事实（MANUAL_IMPORT_REQUIRED）
- 历史聘用的真实起止、审批链、师德/冲突审查记录；
- 课程/教学任务正式事实（权威在教务，HR08 只保存 reference）；
- 结算金额、税、支付结果（HR15/财务权威）；
- 账号/门禁/教务身份历史（IAM 权威）；
- EmployeeType → HrExternalCategory 无规则映射的模糊项。

以上必须 `UNAVAILABLE / MANUAL_IMPORT_REQUIRED`，禁止根据当前 Employee 状态"补历史"。

## 5. 迁移阶段（总册 §116-117）
```
M0 只盘点（CLEAR_EXTERNAL / POSSIBLE_EXTERNAL / REGULAR_EMPLOYEE / AMBIGUOUS 分类）
→ M1 建 HrPerson + HrExternalTeacherProfile 骨架（identity evidence）
→ M2 建 HrExternalCategory 配置（tenant 默认集）
→ M3 Engagement/Assignment 历史（按对账，不自动猜）
→ M4 重复人识别（identity evidence + 人工 review，禁止姓名自动 merge）
→ M5 Dual Read Compare（person/category/host org/dates/status/academic identity/access/agreement）
→ M6 Authority Cutover
```

## 6. 退出合同（总册 §114）
```
LEGACY_EMPLOYEE_TAG_ONLY → DUAL_READ_COMPARE → HR08_AUTHORITY
```
- Authority 后：新外聘只写 HR08；`Employee` 是投影；旧 employee 创建外聘路径 redirect HR08；禁止 fallback。
- Legacy Projection 副作用禁令（§113）：不得因为投影自动进入正式 payroll/leave/attendance/编制人数/普通 manager/regular benefits。
- Cutover 硬门：person 映射 100%、外聘类别 mapping 100%、无重复人未决、downstream（HR01 报表/IAM/教务）provider 可切换、回归全绿。

## 7. 现状缺口（S0 清点摘要）
| 清点项 | 现状 | HR08 目标 |
|---|---|---|
| EmployeeType 使用点 | base/employee/dashboard/report/leave/HR01 provider 等 60+ 处 | 外聘类别权威 `HrExternalCategory`；EmployeeType 仅 legacy 报表投影 |
| employee.is_active 使用点 | dashboard/HR01 provider/alert/leave/payroll forms 等 30+ 处 | 外聘状态权威 `Engagement.status`；is_active 仅当前投影 |
| 默认"Employee=正式员工" | `Employee.save()` 自动建账号+WorkInformation；Contract 写回 wage；leave 全量分配 | HR08 域外聘绝不走该入口 |
| 自动进 Payroll/Leave/Attendance | payroll scheduler 全量生成 payslip；component forms `is_active=True`；leave 分配 | worker_kind=EXTERNAL 投影标记 + access policy 隔离 |
| 账号创建入口 | `Employee.save()` create_user；onboarding Candidate→Employee 路径 | HR08 AccessGrant + IAM provisioning（S6），scoped grants 不重复账号 |
| 教务教师身份入口 | **无**（未发现 academic/teaching_identity 模块） | HR08-S6 `HrExternalAcademicIdentity` + Provider/Event |

> 状态：`DRAFT_V1`。HR08 编码期必须以此文件为基线再次核对最终模型，升级到 `REVIEWED`。
