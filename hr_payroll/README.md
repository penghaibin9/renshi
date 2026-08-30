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

## 支付 Provider 边界

- 系统不内置“自动成功”银行。部署必须通过 `HR15_PAYMENT_PROVIDERS` 将
  `provider_code` 映射到可信适配器导入路径；未配置时支付保持 `CREATED` 并明确失败。
- 适配器实现 `dispatch(request)` 和 `verify_receipt(payload)`。前者必须返回与
  tenant、指令、金额、币种和幂等键完全一致的发送回执；后者负责验签/鉴权后返回
  规范化银行回执。
- 业务 HTTP API 只能发起发送，不能自行提交 `SENT/ACCEPTED`。回执由受信 worker
  调用 `PayrollPaymentService.ingest_provider_receipt`，并再次执行归属、金额、币种、
  幂等和终态校验。

## 工资输入事实 Provider 边界

- `period inputs` 业务 API 只接受 `staffId` 这类业务选择；客户端提交
  `sourceVersions`、`variables` 或 `currencyCode` 会被拒绝，不能自行声明权威金额。
- 部署通过 `HR15_PAYROLL_INPUT_PROVIDERS` 显式映射 HR03、HR11、HR12、HR14
  及其他实际薪资输入 Authority。每个适配器实现 `collect(request)`，返回与
  tenant、period、staff 完全一致的版本化证据、来源快照及它拥有的变量。
- 可选内置适配器位于 `hr_payroll.services.input_fact_providers`，复用 HR03 人员、
  HR11 月结考勤、HR12 正式考核和 HR14 已封印聘任事实。HR14 合同不输出金额；
  `approvedMonthlySalary` 等实际钱数仍须由学校配置的正式薪酬审批 Provider 提供。
- 四个内置类依次为 `Hr03PayrollInputProvider`、`Hr11PayrollInputProvider`、
  `Hr12PayrollInputProvider`、`Hr14PayrollInputProvider`；可另加如 `COMPENSATION`
  的学校适配器提供正式审批后的金额，registry 会同时封存它的来源证据。
- 缺任一必需 Provider、必需变量、跨租户身份或来源证据时冻结失败。服务端保存
  provider 版本、evidence id/hash、不可变来源快照、变量和总内容哈希；计算重放及
  工资单发布都会重新校验这条证据链。

## 小白看代码顺序

1. `models.py` / `calculation_models.py` / `statutory_models.py`：薪酬档案、规则、期间、计算结果、法定缴费、支付/对账。
2. `services/`：计算、复核、月结、追溯、法定缴费、支付等写操作。
3. `selectors.py`：工资期间、个人工资条、法定缴费、差异和历史查询。
4. `api.py` / `api_urls.py`：统一 `/api/v1/hr/payroll`。
5. `tests/`：租户、权限、金额精度、月结锁、重算、对账和 MySQL。
