# HR06 LegacyChangeMapping（S0 基线复审 · Legacy→新权威映射 + 直接修改入口清点）

> 依据：《06_HR06_人事异动_施工总册_终极版》§55/§56/§57 + 《00_全局架构合同》§106 + 当前 `renshi` 仓库真实代码（2026-08-09 复审）。
> 权威边界：HR06 是"请求改变"的 Case Authority；HR03（hr_staff）负责"按有效日期写事实"；HR02（hr_structure）负责岗位占用/预占。Legacy `EmployeeWorkInformation` 仅作投影。
> 本文档是 S9（Legacy Projection + 入口封堵）与 S10（Dual write/compare）的事实依据。

---

## 1. 受管字段定义（HR06 将来接管范围）

依据总册 §57，以下 `EmployeeWorkInformation` 字段在 Authority 切换后，旧编辑页不得直接写：

| Legacy 字段 | 新权威 | 策略 | 说明 |
|---|---|---|---|
| `department_id` | HrStaffAssignment.organization_id | **PROJECT** | HR03 任职段组织 → 投影；禁止旧页直改 |
| `job_position_id` | HrStaffAssignment.position_id | **PROJECT** | HR03 任职段岗位 → 投影 |
| `job_role_id` | HrStaffAssignment.assignment_role_code | **ADAPT** | 角色码投影，V1 仅展示 |
| `reporting_manager_id` | HrStaffAssignment.reporting_staff_id | **PROJECT** | HR06 调动按 policy 推导/显式选择（§22） |
| `employee_type_id` | HrEmploymentRelationship.relationship_type / employment_type | **PROJECT** | 用工性质属 HR03 关系层 |
| `work_type_id` | HR11 时间制度 | **DOWNSTREAM** | 考勤规则随组织/人员类别变化，HR06 发 `AttendanceRuleReevaluationRequested` |
| `shift_id` | HR11 时间制度 | **DOWNSTREAM** | 同上 |
| `location` | HrStaffAssignment.location（V1 未建模则保留 legacy 映射列） | **PROJECT/ADAPT** | 工作地点 |
| `company_id` | tenant_id（A0 合同 §8/§9） | **A0_AUTHORITY** | 只作 Legacy 兼容；映射 Tenant↔Company |
| `date_joining` | HrEmploymentRelationship.effective_from | **PROJECT** | 入校生效日 |
| `contract_end_date` | HR07 合同 | **NO_HR06_AUTHORITY** | 禁止 HR06 写 |
| `basic_salary` / `salary_hour` | HR15 薪酬 | **NO_HR06_AUTHORITY** | 禁止 HR06 写 |
| `experience` | 派生字段 | **READONLY** | 由 join date 派生 |
| `additional_info` | JSON 补充 | **ADAPT** | 非受管，保留 |
| `HorillaAuditLog`（simple-history） | HrStaffAuditEvent / HrChangeTransition | **KEEP+NEW** | 技术审计，不是业务台账（§55） |

---

## 2. Legacy 直接修改入口清点（S0 必做物化）

以下全部为"直接修改受管字段"的入口，Authority 切换后逐一封堵。策略取值：
`KEEP`=保留但改语义；`REDIRECT_TO_HR06`=转 HR06 Case；`READONLY`=只读投影；`REMOVE_LATER`=切换后删除；`AUDIT_ONLY`=只审计。

| # | 入口（文件:行） | 修改方式 | 涉及受管字段 | 策略 | 封堵阶段 |
|---|---|---|---|---|---|
| L-01 | `employee/views.py:2520 employee_work_info_view_create` | `EmployeeWorkInformationUpdateForm(request.POST).save()` | 全部 | REDIRECT_TO_HR06 | S9 |
| L-02 | `employee/views.py:2556 employee_work_info_view_update` | `EmployeeWorkInformationUpdateForm(request.POST, instance=...).save()` | 全部 | REDIRECT_TO_HR06 | S9 |
| L-03 | `employee/views.py:2642 employee_work_information_delete` | `.delete()`（硬删） | 全部 | REMOVE_LATER（禁硬删；总册 §81） | S9 |
| L-04 | `employee/views.py:1511 save_employee_bulk_update` | `EmployeeWorkInformation.objects.filter(...).update(**{field: value})` 批量 UPDATE | department/job_position/job_role/shift/work_type/reporting_manager/employee_type/company/location 等 | REDIRECT_TO_HR06（批量异动走 Bulk，§38/§39） | S9 |
| L-05 | `employee/views.py:1600 employee_view_new` | 新建员工时 `EmployeeWorkInformationForm` 一并保存 | 全部（入职场景） | KEEP（入职首建走 HR05/HR03；受管字段禁直接改） | S8 |
| L-06 | `employee/views.py:1618 employee_view_update` | POST form=work 时 `EmployeeWorkInformationUpdateForm.save()` | 全部 | REDIRECT_TO_HR06 | S9 |
| L-07 | `employee/views.py:~1884 employee_individual_update` | `EmployeeWorkInformationForm(...).save()` | 全部 | REDIRECT_TO_HR06 | S9 |
| L-08 | `employee/views.py:~1933 employee_work_info_view` | `EmployeeWorkInformationForm(...).save()` | 全部 | REDIRECT_TO_HR06 | S9 |
| L-09 | `employee/views.py:~2139 employee_update_work_info` | `EmployeeWorkInformationUpdateForm(...)` | 全部 | REDIRECT_TO_HR06 | S9 |
| L-10 | `employee/views.py:3920/4020 employee_work_info_form` | ModelForm save | 全部 | REDIRECT_TO_HR06 | S9 |
| L-11 | `employee/methods/methods.py:~896 bulk_create_work_info` | `EmployeeWorkInformation(...)` 批量建/改 | department/job_position/job_role/work_type/employee_type/shift/reporting_manager/company/location | REDIRECT_TO_HR06（Excel 只是输入渠道，§40） | S9 |
| L-12 | `employee/models.py:756 Employee.save()` | `get_or_create(employee_id=self)` 自动建 WorkInfo | 仅建空投影行 | KEEP（投影占位；不再携带受管字段语义） | S9 |
| L-13 | `employee/forms.py:347 EmployeeWorkInformationForm` | ModelForm `fields="__all__"` | 全部 | REDIRECT_TO_HR06（表单字段 readonly 或跳 HR06） | S9 |
| L-14 | `employee/forms.py:434 EmployeeWorkInformationUpdateForm` | ModelForm `fields="__all__"` | 全部 | REDIRECT_TO_HR06 | S9 |
| L-15 | `employee/cbv/employees.py`（列表/详情/导出） | 读为主；导出含受管字段 | 只读/导出 | KEEP（读路径）+ 导出 scope 收紧 | S9 |
| L-16 | `employee/cbv/employee_profile.py` | WorkAndShiftTabView（shift/work_type tab 编辑） | shift_id / work_type_id | REDIRECT_TO_HR06/HR11 | S9 |
| L-17 | `employee/cbv/allocations.py:374 work_info_post_save` signal | `post_save` 副作用 | 全部（触发后处理） | AUDIT_ONLY（不恢复受管字段写权） | S9 |
| L-18 | `employee/cbv/allocations.py:108` | `model.objects.filter(pk=...).update(...)` | 依调用方 | AUDIT_ONLY（如涉及受管字段则 REDIRECT） | S9 |
| L-19 | `employee/scheduler.py:14` | 只读查询 | — | KEEP | — |
| L-20 | `employee/dashboard.py` | 只读统计 | — | KEEP | — |

> 备注：L-04 是唯一存在"批量 SQL UPDATE WorkInformation"的入口（总册 §81 明令禁止），S9 必须最先封堵。

---

## 3. Legacy WorkInfo 投影规则（Authority 切换后唯一合法写入路径）

```text
HR06 Case（请求改变）
  → APPROVED_WAITING_EFFECTIVE（含未来生效）
  → Apply Service（S8）
      → HR03 AssignmentService.switch_primary / create_assignment / close_assignment（写 HrStaffAssignment 段）
      → HR02 PositionService reserve/commit/release（岗位占用）
      → HrChangeEffectiveSnapshot（不可变快照）
      → Outbox（PersonnelChangeEffective）
      → Legacy Projection：
          EmployeeWorkInformation.department_id     ← HrAssignment 当前主岗.organization
          EmployeeWorkInformation.job_position_id   ← HrAssignment 当前主岗.position
          EmployeeWorkInformation.reporting_manager_id ← HrAssignment 当前主岗.reporting_staff
          EmployeeWorkInformation.employee_type_id  ← 关系层 employment_type 投影（映射 legacy EmployeeType）
          ...
```

**禁止**：反向把 Legacy current state 当权威覆盖 HR03；不 fallback；`LEGACY_DIRECT_EDIT → DUAL_WRITE_COMPARE → HR06_AUTHORITY` 三阶段推进（§56）。

---

## 4. Dual Write Compare 核对维度（S10）

| 核对项 | 权威源 | 投影源 | 不一致时 |
|---|---|---|---|
| 当前组织 | HrStaffAssignment（as-of today PRIMARY） | WorkInformation.department_id | `HR06_PROJECTION_DRIFT` 记录 DataQualityFinding，不得静默修复 |
| 当前岗位 | HrStaffAssignment.position_id | WorkInformation.job_position_id | 同上 |
| 人员类别 | HrStaffMaster.staff_category_code | （legacy employee_type 映射） | 同上 |
| 直属上级 | reporting_staff_id | reporting_manager_id | 同上 |
| 主岗唯一性 | 开放 PRIMARY 条件唯一约束 | — | `PRIMARY_ASSIGNMENT_CONFLICT` |
| 生效区间 | `[effective_from, effective_to)` | 无历史 | as-of 查询禁止读 current |

---

## 5. Legacy↔HR03 双向标识（S10 迁移）

- `HrStaffMaster.legacy_employee_id`（已有，db_index）→ legacy Employee.id；
- `HrStaffAssignment.legacy_department_id / legacy_job_position_id`（已有）→ 未映射数据 LEGACY_CURRENT_SNAPSHOT 预览；
- `hr_structure.HrLegacyObjectLink`（已有）→ Department/JobPosition ↔ HrOrganization/HrPosition 映射；
- 迁移策略：先建立映射 → HR03 事实段 → 投影校验 → 冻结 legacy 正式写。

---

## 6. S9 封堵清单（落地顺序）

1. `save_employee_bulk_update`（L-04）：受管字段选择项移除 + 已存在表单字段置 readonly 提示"该字段已由人事异动管理，请发起异动"（§57）。
2. `employee_work_info_view_create/update`（L-01/L-02）：受管字段字段级 disabled + 提示走 HR06。
3. `EmployeeWorkInformationForm/UpdateForm`（L-13/L-14）：`fields_to_remove` 逻辑已存在于 bulk form（forms.py:604），把受管字段并入。
4. `employee_work_information_delete`（L-03）：S9 仅审计拦截，REMOVE_LATER 等 Authority 切换完成。
5. `bulk_create_work_info`（L-11）：Excel 导入模板移除受管字段列。
6. WorkAndShiftTabView（L-16）：shift/work_type 跳 HR11。
7. 导出（L-15）：默认不含受管字段当前快照作为"事实"，仅投影标注。

---

**文档状态：S0 复审物化，随 S9/S10 施工同步更新。**
