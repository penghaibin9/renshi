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
- 社保和住房公积金规则按学校、属地、险种和版本发布；工资输入提供缴费基数，系统按上下限截断后分别计算个人扣款与单位缴费。
- 法定缴费事实复用同一条“计算 → 复核 → 封板 → 支付”工资权威链；封板后只能在新工资期间追加调整，不能改历史。
- 每条法定缴费事实保存规则哈希、输入哈希、计算证据哈希与复核证据哈希，便于审计复算。

## 小白看代码顺序

1. `models.py` / `calculation_models.py` / `statutory_models.py`：薪酬档案、规则、期间、计算结果、法定缴费、支付/对账。
2. `services/`：计算、复核、月结、追溯、法定缴费、支付等写操作。
3. `selectors.py`：工资期间、个人工资条、法定缴费、差异和历史查询。
4. `api.py` / `api_urls.py`：统一 `/api/v1/hr/payroll`。
5. `tests/`：租户、权限、金额精度、月结锁、重算、对账和 MySQL。
