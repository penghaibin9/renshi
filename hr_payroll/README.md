# HR15 薪酬福利

> 设计事实源：`docs/15_HR15_薪酬福利_施工总册_终极版.md`

## 这个模块负责什么

HR15 是高校薪酬福利 Authority：薪酬档案、薪资项目与规则版本、月度工资核算、调资与津补贴、社保公积金/职业年金、工资条、支付与财务对账。

## 接管策略

现有 Horilla `payroll/` 不直接删除。先盘点并复用 Payslip、Allowance/Deduction、计算技术、任务调度、报表与 UI；正式高校薪酬事实逐步迁到 `hr_payroll`。只有确认无引用且已被新 Authority 替代的旧实现才删除。

## 固定技术合同

- API：`/api/v1/hr/payroll`
- Permission：`hr.payroll.*`
- 数据库：MySQL-only；金额/比例使用 Decimal。
- Tenant/Scope/Permission：fail-closed。
- Payroll FINAL 不可原地改；追溯调整生成差额事实。
- 岗位/职称/考核/考勤只是输入事实，不能直接等于工资金额。

## 小白看代码顺序

1. `models/`：薪酬档案、规则、期间、计算结果、支付/对账。
2. `services/`：计算、复核、月结、追溯、支付等写操作。
3. `selectors/`：工资期间、个人工资条、差异和历史查询。
4. `integrations/`：财务、银行、税务、社保、公积金 Provider。
5. `api/`：统一 `/api/v1/hr/payroll`。
6. `tests/`：租户、权限、金额精度、月结锁、重算、对账和 MySQL。
