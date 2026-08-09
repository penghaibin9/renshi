# HR07 Payroll Contract Dependency Map（S0 物化 · 解耦门输入）

> 目的：完整列出 payroll/leave/employee 对旧 `Contract` 的依赖，逐个裁决归属（HR07 / HR15 / HR11 / 兼容投影）。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`
> 归属图例：**[HR15]**=薪酬域；**[HR11]**=考勤/请假域；**[HR07]**=合同域；**[LEGACY]**=旧页兼容/投影。

---

## 1. 创建/编辑 Contract 入口

| # | 入口 | 位置 | 归属 | 处理 |
|---|---|---|---|---|
| E1 | `contract_create`（POST，payroll.add_contract） | payroll/views/views.py:78 | [LEGACY] | authority 后 redirect → HR07 signing case |
| E2 | `contract_update`（POST，payroll.change_contract） | payroll/views/views.py:114 | [LEGACY] | 禁改已签署；redirect |
| E3 | `contract_status_update` | payroll/views/views.py:164 | [LEGACY] | 状态机接管 |
| E4 | `bulk_contract_status_update` | payroll/views/views.py:217 | [LEGACY] | 状态机接管 |
| E5 | `update_contract_filing_status` | payroll/views/views.py:255 | [HR15] | tax 归属 HR15 |
| E6 | `contract_delete` / `contract_bulk_delete` | payroll/views/views.py:280/1400 | [LEGACY] | 仅 DRAFT 无引用可删 |
| E7 | signal `employeeworkinformation_pre_save` 自动建 active Contract | payroll/signals.py:12-40 | [HR07] | 冻结；改 HR05→HR07 显式契约 |
| E8 | `create_contracts_in_thread`（Excel 导入 bulk） | employee/methods/methods.py:730-754 | [HR07] | HR07 Excel 导入流程替代 |

## 2. 读取 Contract.wage 入口（薪资解耦门 §126）

| # | 入口 | 位置 | 归属 |
|---|---|---|---|
| W1 | `payroll_calculation` → basic_pay | payroll/views/component_views.py:294-295 | [HR15] |
| W2 | `compute_salary_on_period` | payroll/methods/methods.py:606-626 | [HR15] |
| W3 | `salary_computation` 系列（L270/304/499/541） | payroll/methods/methods.py | [HR15] |
| W4 | allowance 详情 basic_pay 上下文 | payroll/cbv/allowance_deduction.py:125-129 | [HR15] |
| W5 | payslip `contract_wage`（生成/存储） | payroll/cbv/payslip.py:348；payroll/views/views.py:937/1072 | [HR15] |
| W6 | 展示模板 `{{ contract.wage }}` | payroll/templates/contract/*、payslip 摘要 | [LEGACY] 展示层 |
| W7 | 旧表单 JS `$("#id_wage").val(data.wage)` | payroll/templates/common/form*.html | [LEGACY] |

## 3. Contract save 副作用

| # | 副作用 | 位置 | 裁决 |
|---|---|---|---|
| S1 | 自动补 department/position/role/shift/work_type | models.py:441-458 | 改 `signing_context_snapshot`（[HR07]） |
| S2 | end<today → status=expired | models.py:459-460 | 状态机接管（[HR07]） |
| S3 | 单 active/单 draft 约束 | models.py:461-485 + clean | `AgreementFamily` 参数化（[HR07]） |
| S4 | wage → `EmployeeWorkInformation.basic_salary` 回写 | models.py:487-503 | 移除（[HR15]） |
| S5 | unique_together(employee,start,end) | models.py:510 | legacy 保留 |

## 4. 到期 scheduler

| # | 入口 | 位置 | 裁决 |
|---|---|---|---|
| D1 | `expire_contract()`（每 4h `update(status="expired")`） | payroll/scheduler.py:20-27 | `AgreementLifecycleScheduler` 幂等接管（[HR07]） |
| D2 | `contract_ending`（dashboard 到期列表） | payroll/views/views.py:900 | 风险中心接管（[HR07]） |

## 5. payroll/leave 对 Contract 的状态/薪资依赖

| # | 依赖 | 位置 | 裁决 |
|---|---|---|---|
| P1 | 仅 active contract 员工生成 payslip | payroll/scheduler.py:49-68 | [HR15] 以 HR15 薪酬档案为准；HR07 主合同有效区间作输入 |
| P2 | `get_active_employees`（is_active + contract_set 非空 + payslip） | payroll/context_processors.py:52 | [HR15/HR03] 改由 HR03 关系 + HR15 档案 |
| P3 | payslip 自动生成按 contract active 过滤 | payroll/forms/component_forms.py:467-468 | [HR15] |
| P4 | allowance/deduction 条件 `contract_set__*` | payroll/models/models.py:806-808 | [HR15] 条件字段迁移 |
| P5 | 员工页展示 contract_set（active contract 摘要） | employee/views.py:398/431 | [HR07] 改为 HR07 台账摘要（只读 provider） |
| P6 | `EmployeeWorkInformation.contract_end_date`（独立快照字段） | employee/models.py:901；employee/forms.py | [LEGACY] 只读快照；HR07 不写入 |
| P7 | 员工 Excel 导入读取 Contract End Date → work_info.contract_end_date | employee/methods/methods.py:313-320/882-934 | [LEGACY] 停止导入为快照；HR07 导入接管 |
| P8 | 离职时 contract 清理 | 无（offboarding 未接入） | HR07-S7 终止事件 + HR16 联动 |

## 6. 解耦门结论

```text
切 HR07_AUTHORITY 前必须完成：
A) W1-W5 全部改读 HR15 provider（或 HR07 只读提供 compensation_reference，不参与计算）；
B) S4 回写冻结；
C) D1 由 HR07 lifecycle 接管并停止 payroll scheduler 自动改状态；
D) E7/E8 隐式建 Contract 冻结；
E) P1-P4 依赖逐一迁移；
否则拒绝切换（HR07 §126）。
```
