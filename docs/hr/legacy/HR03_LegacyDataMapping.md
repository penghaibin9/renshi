# HR03 LegacyDataMapping（S0 基线复审物化 · 依据真实仓库核对）

> 文档性质：HR03-S0 前置交付；依据 `renshi` 仓库真实模型/字段/路由/方法核对后物化。
> 权威依据：《03_HR03_教职工主档_施工总册_终极版》第 31/32/33 节 + 真实代码基线。
> 核对基线：当前工作树（`F:\高校人事系统\renshi`）；关联文档：《HR01-S0_基线复审报告》《HR02_LegacyDataMapping》
> 物化时间：2026-08-09
> 状态：`DRAFT_V1` —— HR03 权威模型冻结后升级为 `REVIEWED`

---

## 1. 结论先行

- Horilla `Employee / EmployeeWorkInformation / Document / HorillaAuditLog` **不具备**高校"Person & Workforce Fact Core"能力：无 Person/Staff 分层、无 multiple employment、无 effective-dated 任职事实、无主岗/兼岗、无高敏字段分级、`is_active` 过度使用。
- HR03 采用 `REWRITE`：新建 `hr_staff` app 承载权威事实；Horilla 旧模型降级为 **Legacy Projection**（`HrLegacyEmployeeProjectionService` 单向投影），Authority 切换前旧写入口保留、切换后关闭。
- **禁止推断**：不把 `qualification` 字符串当最高学历、不把 `experience` 数字当工作经历、不把 `is_active=False` 一律当离职、不把 `contract_end_date` 当合同权威、不把 Department/JobPosition 名称模糊匹配成权威组织/岗位。
- **HR02 硬门现状（S0 复核更新）**：`hr_structure`（HR02 权威层）**已注册**（INSTALLED_APPS 含 `hr_structure`）、**已有 0001_initial 迁移**，模型全集导出（HrOrganization/HrOrganizationVersion/HrPosition/HrPostCatalog/HrLegacyObjectLink/HrExternalIdentifier…），并已提供 `hr_structure.selectors.effective`（org_version_as_of/children_as_of/build_tree_as_of）与 `OrganizationSelector`。
  结论：HR02 稳定身份与 as-of 查询能力**在代码层已就绪**；HR03 的外键方案直接采用：`HrStaffAssignment.organization_id → hr_structure.HrOrganization`（权威位）+ `legacy_department_id`（只读映射列，走 HrLegacyObjectLink）+ `position_id → hr_structure.HrPosition`。不再需要"纯 legacy 预览兜底"，但仍允许 `LEGACY_CURRENT_SNAPSHOT` 用于 HR02 数据尚未映射前的只读预览，且禁止把 legacy Department/JobPosition 直接固化为权威外键。

---

## 2. 引用盘点（S0 输出）

### 2.1 后端模型引用范围
- `employee/models.py`：Employee / EmployeeTag / EmployeeWorkInformation / EmployeeBankDetails / NoteFiles / EmployeeNote / Policy / BonusPoint / Actiontype / DisciplinaryAction / EmployeeGeneralSetting / ProfileEditFeature
- `horilla_documents/models.py`：Document / DocumentRequest
- `horilla_audit/models.py`：HorillaAuditLog（django-simple-history）/ AccountBlockUnblock / AuditModelConfig
- `base/models.py`：Company / CompanyGroupAssignment / Department / JobPosition / JobRole / WorkType / EmployeeType / EmployeeShift
- 下游读取 EmployeeWorkInformation：`leave/models.py`、`attendance/views`、`payroll/models`、`payroll/views`、`offboarding/dashboard`、`recruitment/dashboard`、`hr_control_center/*`
- HR01 消费：`hr_control_center/providers/workforce.py`、`providers/legacy_employee.py`、`services/alert_service.py`

### 2.2 接管裁决

| Horilla 对象 | HR03 决策 | 终局用途 |
|---|---|---|
| `Employee` | LEGACY PROJECTION | 兼容旧模块；authority 由 HrPerson→HrStaffMaster 替代 |
| `Employee.email` (unique) | REMOVE AS PERSON IDENTITY | PersonContact/AccountLink；解除跨租户唯一 |
| `EmployeeWorkInformation` | LEGACY PROJECTION | 不再承载新权威事实 |
| `EmployeeWorkInformation.department/job_position/job_role` | PROJECT | 经 `HrLegacyObjectLink` 映射，不固化 FK |
| `Employee.is_active` | migration hint | 不得等于新人员状态（ACTIVE/DEPARTED/RETIRED…） |
| `badge_id` | ADAPT | `HrStaffMaster.staff_no` 候选（冲突/格式校验后迁移） |
| `Document / DocumentRequest` | ADAPT 底层 + REWRITE 证据层 | `HrStaffMaterial/HrStaffMaterialVersion` legacy link |
| `HorillaAuditLog` | KEEP 技术历史辅助 | `HrStaffAuditEvent` + `HrSensitiveAccessLog` 为正式审计 |
| `Employee.save()` 自动建 User/WorkInfo | REMOVE FROM AUTHORITY FLOW | 新模型禁止自动建密码账号 |
| Excel import/export | REWRITE | 异步 staging 体系（HrImportJob/Row/Issue） |
| `HorillaCompanyManager` | HARDEN 复用 | A0 fail-closed tenant scope（HR03 权威表自带 tenant_id） |

---

## 3. 字段级映射：`Employee` → HR03

| Horilla 字段 | 新权威落点 | 映射方式 | 说明 |
|---|---|---|---|
| `Employee.id` | `HrStaffMaster.legacy_employee_id` | 直迁 | 只作映射，不是 authority key |
| `Employee.badge_id` | `HrStaffMaster.staff_no` | 冲突/格式校验后迁移 | 候选源；`unique_badge_id` 约束已全局唯一，需先按 tenant 检查 |
| `employee_first_name` + `employee_last_name` | `HrPerson.legal_name` | 中文拼接规则确认 | 迁移前必须确认"姓+名/全名"语义 |
| `email` | `HrPersonContact` / `HrAccountLink` | 拆散，不再 person unique | **解除跨租户唯一**（硬合同 32.5） |
| `phone` | `HrPersonContact` | 敏感策略 | RESTRICTED_HR |
| `address/country/state/city/zip` | `HrPersonContact`（地址实体） | 可迁 | RESTRICTED_HR |
| `dob` | `HrPerson.birth_date` | 数据质量校验 | SENSITIVE；受控列+掩码+严格权限 |
| `gender` | `HrPerson.gender_code` | 字典映射 | male/female/other → M/F/O/UNSPECIFIED 需确认 |
| `marital_status` | 背景事实（SENSITIVE） | 可迁但谨慎 | 默认不入 API |
| `children` | 背景事实 | 谨慎 | 无业务必要不迁 |
| `emergency_contact*` | `HrEmergencyContact`（受限字段） | 独立模型 | SENSITIVE |
| `qualification` | **不迁为权威学历** | exception queue | 只能 legacy reference；最高学历需人工/规则确认 |
| `experience` (int) | **不迁为工作经历** | exception queue | 只能 legacy reference |
| `is_active` | migration hint | 对账输入 | **不得当历史真值**；ACTIVE 判定走关系+任职段 |
| `additional_info` | 逐字段评估 | REMOVE 作为核心容器 | 不进权威表；已识别字段拆出 |
| `is_from_onboarding / is_directly_converted` | 溯源标记参考 | 可映射到 `HrStaffMaster.source` | onboarding 直转人员可标记 HR05_ONBOARDING |
| `employee_profile` | `HrPerson.avatar`（非权威事实） | 直迁 | 展示用，非人事事实 |
| `employee_user_id` | `HrAccountLink` | 映射 | 账号与身份解耦，1:0..n |

## 4. 字段级映射：`EmployeeWorkInformation` → HR03

| Horilla 字段 | 新权威落点 | 映射方式 | 说明 |
|---|---|---|---|
| `company_id` | A0 tenant_id / `HrStaffMaster.tenant_id` | 必须 A0 校验 | 无 company 的孤儿行进 exception queue |
| `department_id` | `HrStaffAssignment.organization_id`（可空权威位） | 经 HR02 legacy mapping | **硬门**：先存 `legacy_department_id` 映射，不固化 FK |
| `job_position_id` | `HrStaffAssignment.position_id/post_catalog_id` | 经 HR02 mapping | 同上，不固化 FK |
| `job_role_id` | assignment_role_code 候选 | 逐校规则核验 | 绝不自动映射为高校岗位等级 |
| `employee_type_id` | `HrStaffMaster.staff_category_code` / `relationship.employment_type` | 字典映射 | EmployeeType → 高校人员类别需学校规则 |
| `reporting_manager_id` | `HrStaffAssignment.reporting_staff_id` | legacy→staff 映射 | 需双向对账 |
| `shift_id / work_type_id` | **不进入 HR03 V1 权威模型** | legacy reference | 考勤/排班域数据，HR03 不复制 |
| `location` | `HrStaffAssignment.location_ref`（文本） | 直迁 | 非权威 |
| `email`（work email） | `HrPersonContact.work_email` | 直迁 | RESTRICTED_HR |
| `mobile`（work phone） | `HrPersonContact.work_phone` | 直迁 | RESTRICTED_HR |
| `date_joining` | `HrEmploymentRelationship.effective_from` | **需对账** | 多次入职/返聘时只有一条当前值 → 缺历史，作为第一段 effective_from 候选 |
| `contract_end_date` | **HR07 投影**（HrContractFactReference） | 不作为 HR03 合同权威 | 仅迁移提示/到期预警参考 |
| `basic_salary / salary_hour` | HR15 migration reference | 不迁 | HR03 不接管工资权威 |
| `additional_info` | 逐字段评估 | REMOVE 核心容器 | 不进权威模型 |
| `experience` (float) | 不迁 | exception | 由 date_joining 推导或弃用 |
| `history` (HorillaAuditLog) | 技术历史参考 | 保留只读 | 正式业务审计走 HrStaffAuditEvent |

## 5. 字段级映射：`Document` / `EmployeeBankDetails` → HR03

| Horilla | 新权威 | 说明 |
|---|---|---|
| `Document.id` | `HrStaffMaterialVersion.legacy_document_id` | 分类需人工/规则映射 |
| `Document.document` | `HrStaffMaterialVersion.storage_file_id` | 迁移时重新入库 + SHA-256 |
| `Document.issue_date/expiry_date/status` | material version 相应字段 | status requested/approved/rejected 是流程态，非证据核验态 |
| `Document.document_request_id` | `HrMaterialRequest` 参考 | 保留"索要材料"思想，升级模型 |
| `EmployeeBankDetails.account_number` | **不进入 HR03** | HR15 薪酬域 + HIGH_SENSITIVE 独立治理 |
| `EmployeeBankDetails.bank_name/…` | 不进入 HR03 | 同上 |

---

## 6. S0 全入口清单（写入即风险面）

### 6.1 直接写 `EmployeeWorkInformation` 受管字段的入口

| # | 入口 | 文件/路由 | 写哪些受管字段 |
|---|---|---|---|
| 1 | `employee_create_update_personal_info` | `employee/views.py` + `employee-create-personal-info` / `employee-update-personal-info` | Employee 个人字段（badge_id/email/phone/…），**会触发 `Employee.save()` 自动建 work_info** |
| 2 | `employee_update_work_info` | `employee/views.py` + `employee-create-work-info` / `employee-update-work-info` | department/job_position/job_role/work_type/employee_type/shift/reporting_manager/company/location/email/mobile/date_joining/contract_end_date/basic_salary/salary_hour |
| 3 | `employee_view_update`（work tab） | `employee/views.py` + `employee-view-update/<obj_id>` | 同上（EmployeeWorkInformationUpdateForm） |
| 4 | `employee_work_info_view_update` | `employee/views.py` + `employee-work-info-view-update/<obj_id>` | 同上（含 tags） |
| 5 | `employee_view_update` 跨校重挂 | `employee/views.py` 1656-1666 | `work.company_id = cmpny; work.save()` —— **跨学校改归属的隐性入口** |
| 6 | `employee_update`（旧 POST 处理） | `employee/views.py` | Employee 个人字段 |
| 7 | `save_employee_bulk_update` | `employee/views.py` + `save-employee-bulk-update` | 批量改 work_info 受管字段 |
| 8 | `work_info_import` + `methods.process_employee_records` | `employee/views.py` + `employee/methods/methods.py` | bulk_create/bulk_update 全部受管字段（同步逐行+批量混合，非 staging） |
| 9 | `Employee.save()` 自动 `get_or_create(EmployeeWorkInformation)` | `employee/models.py` 755-767 | 任何 Employee 保存（含归档回弹）都可能触发 |
| 10 | 入职/候选人转换 | `onboarding/views.py:1320` `update_or_create`；`recruitment/views/views.py:2127` `new_employee.save()` | work_info 与 Employee 当前字段 |
| 11 | payroll 同步 | `payroll/signals.py:12` pre_save EmployeeWorkInformation；`payroll/models/models.py:442` | 工资字段回写（salary_hour 等） |
| 12 | `employee_work_information_delete` | `employee/views.py` + `employee-work-information-delete/<obj_id>` | 删除整行（注意级联面） |
| 13 | 归档/换岗 | `offboarding/views.py:525/593`；`replace_employee`（reporting_manager_id 批量 update） | is_active / reporting_manager_id |

> Authority 切换后：以上 legacy 写入口关闭或投影化（`HR03_LEGACY_WRITE_DISABLED`），正式事实只能走 HR03 service/domain event。

### 6.2 读 `is_active` 反推人事状态的入口

| # | 入口 | 位置 | 用途 |
|---|---|---|---|
| 1 | `LegacyWorkforceProvider.active_employee_qs` | `hr_control_center/providers/workforce.py` | 在岗人数/分布（dataBasis=LEGACY_CURRENT_SNAPSHOT） |
| 2 | `LegacyEmployeeProvider` | `hr_control_center/providers/legacy_employee.py` | 本年新进/在岗；**本年离退已正确返回 UNAVAILABLE**（is_active=False 无离退日期） |
| 3 | `alert_service.py` | `hr_control_center/services/alert_service.py` | 生日/合同到期等预警 |
| 4 | `employee/dashboard.py` | 多处 `filter(is_active=True)`、`employee_id__is_active=True` | 部门/性别/类型/在职趋势 |
| 5 | `base/dashboard.py`、`ess_dashboard.py` | base | ESS 首页口径 |
| 6 | `leave/views.py`、`offboarding/dashboard.py`、`payroll/dashboard.py`、`attendance/*` | 各模块 | 可请假人、在岗名单、薪酬资格 |
| 7 | `employee/views.py` `employee_filter_view`、`EmployeeFilter.is_active` | employee | 名册"在职/离职"筛选 —— **HR03 名册的 legacy 对照** |
| 8 | `birthday()` | `employee/views.py:3010` | 生日提醒（is_active=True + dob） |
| 9 | `get_archive_condition` | `employee/models.py:412` | 归档资格判定（is_active + 业务关联回弹） |
| 10 | `HorillaCompanyManager.all()` | `base/horilla_company_manager.py` | 默认 is_active 过滤 —— **所有 legacy 查询隐性依赖** |

### 6.3 email 当自然人唯一标识的入口

| # | 入口 | 位置 | 说明 |
|---|---|---|---|
| 1 | `Employee.email = EmailField(unique=True)` + `unique_together(first,last,email)` | `employee/models.py` | **跨租户全局唯一，多学校/多关系阻断点** |
| 2 | `EmployeeForm.clean()` | `employee/forms.py` | `Employee.objects.entire().filter(email=...)` 全局查重 |
| 3 | `Employee.save()` 自动建 `HorillaUser(username=email, password=phone)` | `employee/models.py:733-753` | 账号生命周期与身份强耦合 |
| 4 | `employee_import` | `employee/views.py:2662` | 以 email 作 username / 判重 |
| 5 | onboarding 候选人转换 | `onboarding/views.py:1150/1256/1269` | `HorillaUser.objects.filter(username=candidate.email)`；`Employee.objects.filter(email=user_email)` |
| 6 | recruitment 候选人→员工 | `recruitment/views/views.py:2111` | `HorillaUser.objects.filter(username=candidate_obj.email)` |
| 7 | `import_ldap_users` | `employee/management/commands`、`horilla_ldap/…` | `Q(username=email)|Q(username=user_id)|Q(email=email)` |
| 8 | `base/views.py`、`demo_roles.py`、`createhorillauser.py` | base | 以 email 找用户/建用户 |

---

## 7. 迁移波次映射（总册 33 节）

```
Wave 0 只盘点    → Employee 数量、WorkInfo 完整度、tenant 缺失、badge 冲突、
                   email 冲突、company/department/job position 无映射、
                   active/inactive 分布、document 分类、孤儿数据。不写 authority。
Wave 1 骨架      → HrPerson + HrStaffMaster + HrPersonIdentityDocument + HrLegacyObjectLink
Wave 2 关系/任职 → HrEmploymentRelationship + HrStaffAssignment（HR02 映射就绪后）
Wave 3 背景/材料 → 教育/经历/证书结构化 + Document→Material staging
Wave 4 对账      → DUAL_READ_COMPARE 全量 + 兼岗样本 + as_of 样本
Wave 5 切换      → 按 tenant 切 AUTHORITY；记录 cutover 证据；禁止 fallback
```

## 8. 状态与升级路径

- `DRAFT_V1`（当前）：以本文件为准施工 Wave 0/1；
- `REVIEWED`：HR03 权威模型冻结 + 字段核对完成后升级；
- 每次字段级变更必须回更本文件并注明变更记录。

---

## 变更记录
| 日期 | 版本 | 说明 |
|---|---|---|
| 2026-08-09 | DRAFT_V1 | S0 基线复审物化；依据真实代码核对 Employee/WorkInformation/Document/写入口/读入口/email 入口 |
