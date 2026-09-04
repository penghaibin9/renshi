# 15_HR15_薪酬福利_施工总册（终极冻结版）

> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、API（`/api/v1/hr`）、数据库目标（MySQL-only）、事件、权限、Legacy、审计、安全和最终生产 Gate。
> PATCH-10 补充：HR15-05 含职业年金/补充福利计划（OccupationalAnnuityAccount/BenefitPlan/ProviderReceipt/Reconciliation）。

> 产品：跃科高校人事管理与教师发展系统  
> 二级模块：HR15 薪酬福利  
> 三级模块数量：6  
> 总体策略：REWRITE（接管 Horilla `payroll/` 的薪酬 Authority；保留可复用的 Payslip、Allowance/Deduction、Payroll UI、任务调度、报表与部分计算技术能力；重建中国高校/事业单位薪酬事实、规则版本、月结、社保公积金、个税、支付与财务对账）  
> 版本：V1.0 终极冻结版  
> 文档性质：HR15 唯一权威施工事实源；可直接整份交给编码 AI 执行“真实仓库 payroll 基线复审 → 薪酬档案 → 薪资项目与规则版本 → 月度工资输入快照 → 计算/复核/月结 → 调资/津补贴/绩效 → 追溯重算 → 社保公积金 → 个税 → 工资条 → 支付批次 → 银行/财务/税务/社保公积金接口 → 对账 → Legacy Projection → 双读比较 → 安全/并发/E2E → Authority 切换”的生产级施工。  
> 适配底座：Horilla HRMS 2.0（当前 `penghaibin9/renshi` 基线；S0 必须以目标分支真实代码再次核验）  
> 前置标准：继承《01_HR01》至《14_HR14》终极版的 A0 多学校 fail-closed、API 版本化、统一错误信封、公共 UI、权限/数据范围、文件安全、敏感字段、异步任务、审计、可观测性、Excel、幂等、事务、Outbox、规则/模板版本冻结、Legacy 退出和 AI 施工纪律。  
> 强依赖：HR03 提供 Person/Staff/EmploymentRelationship/Assignment；HR05 只采集并核验银行卡等入职基础资料，HR15 建正式 PayrollProfile；HR07 提供合同有效事实但合同工资条款不是工资计算 Authority；HR11 提供已月结考勤/请假/加班基础；HR12 提供正式年度/聘期考核结果及应用标记；HR14 提供已 EFFECTIVE 岗位聘任/岗位等级/生效日期；HR16 提供离职/退休/终止生效日及结算请求；HR18 消费正式工资统计与上报口径；财务、银行、税务、社保、公积金系统均通过 Provider/Adapter 集成。  
> 编写日期：2026-08-08  
> 核心原则：**合同工资条款 ≠ 月度工资真值；岗位/职称/考核结果 ≠ 工资金额；考勤原始打卡 ≠ 扣款金额；工资计算结果 ≠ 已支付；工资条 ≠ 财务凭证；社保公积金政策 ≠ 全国固定比例；个税规则 ≠ 一个固定税率；月结工资不可原地改；追溯调整必须生成差额事实而不是重写历史。**
# 0. 六个三级模块冻结

```text
HR15 薪酬福利
├─ HR15-01 薪酬档案
├─ HR15-02 薪资项目与规则
├─ HR15-03 月度工资核算
├─ HR15-04 调资与津补贴
├─ HR15-05 社保与公积金
└─ HR15-06 工资条与财务对接
```

职责严格分离：

- **HR15-01 薪酬档案**：个人薪酬身份、发薪组织、工资制度、岗位/薪级、支付账户、税务身份、社保公积金参保配置、effective-dated 历史。
- **HR15-02 薪资项目与规则**：岗位工资、薪级工资、绩效工资、津贴补贴、奖金、扣款、税前税后、计税计保属性、公式、适用人群、规则版本与模拟器。
- **HR15-03 月度工资核算**：工资期间、输入冻结、批量计算、异常、复核、审批、月结、追溯重算、差额单、会计期间锁。
- **HR15-04 调资与津补贴**：岗位/薪级变化、考核绩效、政策性调资、津贴补贴、一次性奖金、补发/追扣、专项奖励、有效期和审批。
- **HR15-05 社保与公积金**：参保账户、险种、缴费基数、单位/个人比例、上下限、地方规则版本、变更申报、差额、对账、个人权益信息。
- **HR15-06 工资条与财务对接**：工资条、支付批次、银行代发、财务凭证/ERP、个税扣缴数据、社保/公积金申报数据、回执、对账、失败重试与归档。

# 1. 结论先行

真正生产级 HR15 必须形成：

```text
HR03 Staff / Employment / Assignment
             │
HR14 Effective Appointment
             │
HR12 Final Assessment
             │
HR11 Closed Time Facts
             │
HR05 Bank Basic Data / HR07 Contract Facts / HR16 Exit
             │
             ▼
       Payroll Profile
             │
             ▼
 Compensation Policy / Pay Item / Rule Version
             │
             ▼
       Payroll Period Open
             │
             ▼
      Input Snapshot Freeze
             │
      ┌──────┼──────────┐
      ▼      ▼          ▼
   Fixed   Variable   Statutory
   Pay     Inputs     Inputs
      └──────┼──────────┘
             ▼
       Calculation Run
             │
             ▼
   Validation / Variance / Review
             │
             ▼
       Payroll Finalization
             │
       ┌─────┼─────────┬──────────┐
       ▼     ▼         ▼          ▼
    Payslip  Tax   Social/HF   Finance
       │     │         │          │
       └─────┼─────────┴──────────┘
             ▼
        Payment Batch
             │
             ▼
       Bank / Treasury
             │
             ▼
      Reconciliation / Receipt

Retroactive change:
Source Event → Impact Analysis → Retro Run → Delta Payroll → New Payment/Recovery
```

系统必须能回答：
- 这笔钱为什么有？
- 用的是哪一版规则？
- 哪个岗位/薪级/考核/考勤事实触发？
- 计税、计社保、计公积金口径是什么？
- 当时政策参数是什么？
- 月结前后是否有人改过输入？
- 补发/追扣为什么产生？
- 工资条和实际银行支付是否一致？
- 财务凭证是否已入账？
- 税务/社保/公积金申报是否收到正式回执？

# 2. 生产级红线

- 不得继续用 `EmployeeWorkInformation.basic_salary` 作为 HR15 权威。
- 不得继续用 Horilla payroll.Contract.wage 作为高校正式薪酬真值。
- 不得把 HR07 合同里的工资条款直接当本月工资金额。
- 不得把 HR14 岗位等级直接硬编码成工资金额。
- 不得把 HR13 职称等级直接硬编码成工资金额。
- 不得把 HR12 考核档次直接等于某固定绩效金额，必须经过 HR15 版本化规则。
- 不得读取 HR11 raw punch 直接扣工资。
- 不得把缺卡自动等于旷工扣款。
- 不得把病假/事假天数直接用一个全国统一公式扣款。
- 不得把社保比例、公积金比例、缴费基数上下限写死为全国常数。
- 不得把湖南某地当前参数当全国 SaaS 默认真值。
- 不得把个税做成固定百分比。
- 不得把中国个税套用 Horilla FilingStatus/美式 filing-status 语义。
- 不得允许任意 `python_code` 作为生产薪资公式直接执行。
- 不得使用 FloatField 存正式金额。
- 不得二进制浮点参与工资、税、社保、公积金计算。
- 不得使用前端 JavaScript 作为权威工资计算器。
- 不得在工资月结后原地 UPDATE payslip 金额。
- 不得删除已发放工资记录。
- 不得追溯变动后重写历史工资条。
- 不得把“本月计算成功”等同“已支付”。
- 不得把银行文件生成成功等同银行代发成功。
- 不得支付失败后自动标记已发。
- 不得财务凭证生成成功等同已过账。
- 不得税务申报文件生成成功等同申报成功。
- 不得社保/公积金导出成功等同申报成功。
- 不得一个 Excel 直接改 FINALIZED 工资。
- 不得批量手工调资绕审批和 effective date。
- 不得普通 HR 查看完整银行卡。
- 不得普通学院管理员查看教师工资金额。
- 不得 SaaS 平台运营默认查看任意学校工资数据。
- 不得工资条永久公开 URL。
- 不得工资条 API 通过猜 staff_id 越权。
- 不得导出完整身份证/银行卡而无专门权限。
- 不得日志打印银行卡、税号、完整工资条、专项附加扣除明细。
- 不得使用 untrusted formula eval。
- 不得月度批处理出现半成功后无独立行级状态。
- 不得多人同时 finalize 同一 payroll period。
- 不得同一人同一期间生成两个 active final payslip。
- 不得 PayrollProfile 跨 tenant 关联人员。
- 不得 Provider unavailable 时把缺失输入当 0。
- 不得 HR14/HR12/HR11 provider 失败时静默 fallback legacy。
- 不得用 mock payroll provider 冒充生产成功。
- 不得 AI 自动批准工资调整。
- 不得 AI 自己决定教师该发多少绩效。
- 不得 AI 自动推断社保缴费身份。
- 不得为修测试关闭 403 或弱化敏感数据权限。
- 不得只在 SQLite 跑 payroll 并发与 Decimal 测试。
- 不得施工阶段直接合并 main 或部署生产。

# 3. 事业单位工资制度产品基线

事业单位工资体系必须能表达：
- 基本工资；
- 绩效工资；
- 津贴补贴；
- 其他依法依规收入。

其中基本工资需要进一步支持“岗位工资 + 薪级工资”等政策映射。
具体金额标准会调整，必须用 `PayStandardVersion` 管理，绝不能写死在代码。

# 4. 高校薪酬校正

高校作为事业单位时，HR15 必须支持岗位绩效工资框架，同时允许学校在核定/授权范围内形成版本化绩效分配规则。

产品不能简单把企业 SaaS 的：
`basic salary + bonus - deduction`
原样当高校薪酬模型。

# 5. 多用工关系

同一学校可能同时存在：
- 事业编制工作人员；
- 员额/备案制；
- 合同制；
- 劳务派遣；
- 项目聘用；
- 兼职/外聘教师；
- 返聘；
- 其他依法配置人员。

每类可对应不同 CompensationProfile/Tax/SocialInsurance/HousingFund/PayFrequency。
不得所有人套一套事业单位工资规则。

# 6. 社会保险制度边界

国家层面社会保险包含基本养老、基本医疗、工伤、失业、生育等制度。
具体缴费基数、比例、上下限、险种合并/经办口径具有地方和年度变化，HR15 必须：
- RegionPolicyVersion；
- effective date；
- employer/employee rates；
- base lower/upper；
- rounding；
- eligibility；
- provider receipt。

# 7. 住房公积金制度边界

住房公积金适用于事业单位及在职职工等主体。
系统必须支持当地缴存基数上下限和比例版本。
全国法规给出基本框架，但地方具体口径必须租户/地区版本化。

# 8. 个税累计预扣

居民个人工资薪金预扣需支持累计预扣法：
累计收入、累计免税收入、累计减除费用、累计专项扣除、累计专项附加扣除、其他扣除、累计已预扣税额等均进入年度累计状态。

不能每个月独立按当月收入乘固定税率。

# 9. 新入职个税特殊口径

对符合规定的年度中间首次取得工资薪金的居民个人，累计减除费用存在特殊计算规则。
必须由 TaxRuleVersion 表达适用条件，不能让工资员手算。

# 10. 专项附加扣除

专项附加扣除属于个人敏感税务信息。
系统只保存工资扣缴所需最小数据或税务 Provider 引用：
- item type；
- monthly eligible deduction；
- effective months；
- source/status。

三岁以下婴幼儿照护、子女教育、赡养老人等标准曾在 2023 调整，因此必须版本化，不能永久硬编码。

# 11. 全年一次性奖金

截至本册编写时，居民个人符合条件的全年一次性奖金可在政策有效期内按规定选择单独计税或并入综合所得。
HR15 必须把：
- eligibility；
- employee choice/authorized mode；
- tax rule version；
- calculation snapshot
独立建模。

不能永远假设一种计税方式。

# 12. Horilla payroll 当前可复用能力

当前仓库已经有：
- `payroll/` 独立模块；
- Contract/wage；
- Allowance；
- Deduction；
- FilingStatus/TaxBracket；
- Payslip；
- payroll dashboard；
- scheduler；
- auto payslip；
- payroll reports/forms；
- company scope；
- audit 基础。

因此 HR15 不应 NEW 重造所有页面和计算技术，而是 REWRITE Authority + ADAPT engine/UI。

# 13. Horilla 当前 Contract/wage 风险

当前 `payroll.Contract` 同时保存：
- employee；
- contract dates/status；
- wage type；
- pay frequency；
- wage；
- filing status；
- department/job position/work type/shift；
- leave deduction；
- contract document。

并且 active 合同保存时会尝试把 wage 写回 `EmployeeWorkInformation.basic_salary`。

这与已冻结 HR07/HR03 Authority 冲突。
HR15 必须把“工资档案”从旧 Contract 中拆出。

# 14. Horilla 金额精度风险

当前旧模型大量金额/比例使用 `FloatField`。
正式工资、税、社保、公积金、补发追扣必须迁移到 Decimal：
- currency；
- scale；
- rounding mode；
- calculation precision；
- display precision。

旧 Float 只作为 Legacy Source。

# 15. Horilla Tax 风险

当前 `FilingStatus` / `TaxBracket` 更接近通用/美国 payroll tax 结构，并允许 `use_py/python_code`。

中国高校 HR15 必须重建：
- China resident/nonresident tax profile；
- cumulative withholding ledger；
- deduction policy；
- bonus tax mode；
- tax filing output；
- tax receipt/reconciliation。

不得让 arbitrary Python formula 进入生产工资规则。

# 16. Horilla Allowance/Deduction 可保留点

可复用：
- allowance/deduction UI；
- employee targeting；
- fixed/percentage concept；
- one-time concept；
- max limit；
- condition UI；
- payslip presentation。

但正式 Rule 必须：
- typed expression DSL；
- versioned；
- deterministic；
- sandboxed；
- no arbitrary Python；
- source facts explicit；
- Decimal。

# 17. Horilla Payslip 可保留点

可保留工资单生成/查看/列表/通知思路。
需要重构为：
`PayrollResult + PayrollResultLine + PayslipDocumentVersion`。

工资条是最终工资结果的“展示投影”，不能成为 calculation authority。

# 18. HR03 边界

HR03 提供：
- staff/person；
- employment relationship；
- assignment；
- personnel category；
- organization；
- effective dates；
- status。

HR15 不复制人员真值。
PayrollProfile 引用 stable staff/employment IDs。

# 19. HR05 边界

HR05 只负责入职时：
- 采集银行卡；
- 基础核验；
- 发 `PayrollProfileRequested`。

HR15 才建立正式：
- payment account；
- pay group；
- tax profile；
- social insurance profile；
- housing fund profile；
- compensation profile。

银行卡敏感权限在 HR15 统一治理。

# 20. HR07 边界

HR07 合同可能包含工资条款/参考金额。
HR15 可引用：
- contract status；
- compensation clause snapshot；
- effective date。

但正式工资计算由 HR15 RuleVersion 决定。
合同修订触发 `CompensationReviewRequired`，不直接改 final payroll。

# 21. HR08 边界

兼职/外聘教师的报酬方式可与正式员工不同。
HR08 提供：
- engagement；
- workload/service facts；
- payment eligibility；
- contract refs。

HR15 负责依法依规的金额、税、支付。
不得把外聘教师硬套正式事业编工资结构。

# 22. HR11 边界

HR11 只向 HR15 提供**已冻结/月结的时间基础**：
- scheduled/worked or authorized；
- approved absence；
- approved overtime；
- compensatory facts；
- close period/version。

HR15 绝不读取 raw punch 直接扣工资。

# 23. HR12 边界

HR12 输出正式考核结果、档次、有效期、policy version、application flags。
HR15 根据自己的 `PerformancePayRuleVersion` 计算是否产生绩效工资、薪级/奖励影响。

HR12 不算钱；HR15 不改考核。

# 24. HR13 边界

职称结果可作为薪酬规则输入，但不得：
`副教授 → 固定金额`
硬编码。

必须经：
HR13 Result → HR14 Appointment（若制度要求）/HR15 EligibilityRule → PayStandardVersion。

# 25. HR14 边界

HR14 EFFECTIVE 才向 HR15 发送：
- position；
- appointment level；
- term；
- effective date；
- change reason；
- source policy。

HR15 决定岗位工资、薪级、津贴、绩效、追溯差额和实际金额。

# 26. HR16 边界

HR16 提供：
- final working/employment date；
- retirement/resignation/termination type；
- settlement requested；
- leave/asset/etc completion refs。

HR15 负责：
- final payroll；
- arrears；
- deduction/recovery；
- tax/social/housing end-period；
- payment statement。

HR15 不执行离校账号停用/资产回收。

# 27. HR18 边界

HR18 只消费 FINAL/CLOSED 的薪酬事实、人工成本指标、社保公积金统计和正式上报口径。
不得读取 DRAFT payroll、工资员模拟值或未批准调资。

# 28. 财务边界

HR15 是工资核算与应付工资明细 Authority。
财务系统负责：
- 会计科目；
- 总账；
- 预算/资金；
- 凭证过账；
- 实际银行付款/国库支付（按学校体系）。

HR15 输出可追溯 PayrollPostingPackage，接收回执。

# 29. 金额类型

统一 `Money`：
- amount Decimal；
- currency CNY default；
- scale；
- rounding mode。

数据库禁止 Float。

# 30. Payroll Profile 状态

```text
DRAFT
READY
ACTIVE
SUSPENDED
CLOSED
SUPERSEDED
```

# 31. 工资期间状态

```text
DRAFT
OPEN
INPUT_FREEZE
CALCULATING
REVIEW
APPROVAL
FINALIZING
CLOSED
PAYMENT_PENDING
PAID
RECONCILED
ARCHIVED
```

# 32. 工资结果状态

```text
DRAFT
CALCULATED
VALIDATED
REVIEWED
APPROVED
FINAL
PAYMENT_PENDING
PAID
PARTIALLY_PAID
PAYMENT_FAILED
SUPERSEDED
REVERSED
```

# 33. 调资状态

```text
DRAFT
SUBMITTED
REVIEW
APPROVED
PENDING_EFFECTIVE
EFFECTIVE
REJECTED
CANCELLED
SUPERSEDED
```

# 34. 社保公积金申报状态

```text
DRAFT
CALCULATED
REVIEWED
SUBMITTED
ACCEPTED
PARTIALLY_ACCEPTED
REJECTED
RECONCILED
```

# 35. 支付批次状态

```text
DRAFT
READY
APPROVED
EXPORTED
SUBMITTED
PROCESSING
PARTIALLY_SUCCESS
SUCCESS
FAILED
RECONCILED
CANCELLED
```

# 36. 追溯状态

```text
IMPACT_DETECTED
ANALYZING
CALCULATED
REVIEW
APPROVED
POSTED
PAID_OR_RECOVERED
CLOSED
```

# 37. HR15-01 业务目标

回答“这个人在某个时点属于哪套工资制度、从哪个组织发薪、岗位/薪级是什么、发到哪个账户、税/社保/公积金身份是什么”。

# 38. PayrollProfile

`HrPayrollProfile`：
- tenant；
- staff/person；
- employment relationship；
- pay_group；
- payroll organization；
- compensation scheme；
- tax profile；
- social insurance profile；
- housing fund profile；
- payment account ref；
- effective_from/to；
- status/version。

# 39. PayGroup

支持：
- monthly staff；
- external teacher；
- project personnel；
- retiree rehired；
- other lawful groups。

字段：
calendar、pay day rule、cutoff、currency、calculation policy、payment channel。

# 40. 薪酬制度身份

`CompensationSchemeAssignment`：
-事业单位岗位绩效；
-学校自主协议；
-外聘课酬；
-项目制；
-其他。

使用 SchemeVersion + effective date。

# 41. 岗位工资档案

引用 HR14 EFFECTIVE Appointment，形成 `PayBasisRef`：
- appointment result；
- category；
- appointment level；
- effective date。

不复制 HR14 decision。

# 42. 薪级工资档案

`SalaryStepAssignment`：
- salary scale version；
- step；
- effective_from/to；
- reason；
- source decision；
- previous step；
- status/version。

薪级不是自由文本数字。

# 43. 支付账户

`PayrollPaymentAccount`：
- account holder；
- bank；
- account token/encrypted value；
- account type；
- verified status；
- effective period；
- primary flag。

列表只显示 mask。

# 44. 银行卡更换

必须：
- employee request；
- identity verification；
- review；
- old/new masked comparison；
- effective date；
- cutoff impact；
- audit。

月结后改卡不回写已提交支付批次。

# 45. 税务身份

`TaxProfile`：
- resident status；
- taxpayer id encrypted/tokenized；
- first-employment flags where applicable；
- cumulative ledger anchor；
- deduction authorization；
- bonus tax option；
- valid period。

# 46. 社保档案

`SocialInsuranceProfile`：
- jurisdiction；
- enrollment status；
- plan/set；
- employee category；
- base source；
- start/end；
- provider account ref；
- version。

# 47. 公积金档案

`HousingFundProfile`：
- jurisdiction；
- account status；
- base；
- employer/employee ratio rule refs；
- start/end；
- provider account ref。

# 48. Payroll Readiness Gate

发薪前检查：
- active employment；
- pay group；
- scheme；
- payment account；
- tax status；
- social/housing configuration；
- source provider readiness。

返回 READY/WARN/BLOCK。

# 49. HR15-01 UI

```text
/hr/payroll/profiles
/hr/payroll/profiles/{staffId}
/hr/payroll/profiles/{staffId}/history
/hr/payroll/readiness
```

个人页显示 mask，不显示无关敏感税务详情。

# 50. HR15-02 业务目标

建立稳定、版本化、可解释、可模拟且禁止任意代码执行的薪资规则引擎。

# 51. PayItemCatalog

类型：
```text
BASE_PAY
POSITION_PAY
SALARY_STEP_PAY
PERFORMANCE_PAY
ALLOWANCE
SUBSIDY
BONUS
OVERTIME_PAY
ADJUSTMENT
ARREARS
RECOVERY
EMPLOYEE_SOCIAL
EMPLOYER_SOCIAL
EMPLOYEE_HOUSING_FUND
EMPLOYER_HOUSING_FUND
TAX
OTHER_DEDUCTION
OTHER_EARNING
```

# 52. PayItem 属性

每项：
- earning/deduction/employer contribution；
- taxable；
- social-insurance-base-includable；
- housing-fund-base-includable；
- pension/reporting classification；
- cost center behavior；
- display order；
- rounding；
- GL mapping ref；
- active period。

# 53. PayStandardVersion

用于国家/地方/学校岗位工资、薪级工资、标准津贴：
- version；
- source；
- effective_from/to；
- matrix；
- category/level mapping；
- currency；
- published_at；
- hash。

新标准发布创建新版本。

# 54. Rule DSL

仅允许白名单表达式：
- arithmetic；
- min/max；
- round；
- conditional；
- lookup versioned table；
- period proration；
- days/minutes based on approved facts；
- cumulative tax functions；
- caps/floors。

禁止 Python eval/exec。

# 55. Rule 输入类型

显式：
- HR03 attribute snapshot；
- HR14 appointment；
- HR12 assessment result；
- HR11 closed time；
- PayrollProfile；
- policy tables；
- manual approved input；
- prior payroll cumulative ledger。

未知输入不得默认为 0。

# 56. 规则输出

每条 RuleEvaluation：
- pay item；
- amount；
- formula version；
- inputs；
- source refs；
- rounding；
- explanation；
- warnings；
- hash。

# 57. 规则优先级

RuleSet 显式：
- base；
- tenant override；
- employee exception；
- one-time change；
- retro delta。

冲突必须 error，不靠“最后保存覆盖”。

# 58. 条件适用

按：
- pay group；
- personnel category；
- organization；
- appointment category/level；
- employment type；
- region；
- effective date；
- staff-specific exception。

所有 targeting 服务端求值。

# 59. 税前/税后语义

不能只 `is_pretax=True/False`。
需区分：
- PIT taxable；
- PIT exempt；
- social base；
- housing base；
- post-tax deduction；
- employer-only cost；
- non-cash informational。

# 60. 绩效工资规则

读取 HR12 Final Result 或其他 VERIFIED performance facts。
支持：
- total pool；
- fixed portion；
- variable portion；
- coefficient；
- department allocation；
- individual allocation；
- cap/floor；
- rounding residual。

总量控制与个人分配都需版本/审计。

# 61. 津贴补贴规则

支持：
-岗位；
-地区；
-人才；
-教学；
-班主任/辅导员；
-艰苦；
-夜班/值班；
-通讯/交通；
-临时专项；
-其他合法项目。

项目开关 + RuleVersion，不硬编码。

# 62. 一次性奖金规则

RuleVersion 包含：
- bonus eligibility；
- gross amount；
- tax mode options；
- employee election/authorization；
- policy expiry；
- payroll period；
- tax calculation snapshot。

# 63. Rule Simulator

输入 staff + period + hypothetical source changes。
输出：
- gross；
- deductions；
- tax；
- employer contributions；
- net；
- delta；
- rule explanations。

Simulator 不写正式工资。

# 64. RuleVersion 发布

DRAFT → VALIDATED → PUBLISHED → SUPERSEDED。
PUBLISHED immutable。

# 65. HR15-02 UI

```text
/hr/payroll/items
/hr/payroll/rules
/hr/payroll/rules/{id}/versions
/hr/payroll/standards
/hr/payroll/simulator
```

# 66. HR15-03 业务目标

做到真正可重跑、可复核、可月结、可追溯、可差额的月度工资核算。

# 67. PayrollPeriod

`HrPayrollPeriod`：
- pay_group；
- period start/end；
- cutoff；
- pay date；
- tax year/month；
- status；
- version；
- opened/closed by/at。

# 68. PopulationSnapshot

Period OPEN 时根据 HR03/PayGroup 生成：
- staff list；
- employment refs；
- payroll profiles；
- exclusions；
- source versions。

后续入离职通过 delta population case，不能静默改变。

# 69. InputSnapshot

INPUT_FREEZE 固化：
- HR03 assignment；
- HR14 appointment；
- HR12 result；
- HR11 close；
- fixed pay；
- variable inputs；
- tax cumulative state；
- social/housing rules；
- manual approved adjustments；
- source hashes。

# 70. 固定工资输入

包括岗位工资、薪级工资、固定津贴等。
全部从 effective-dated profile/rule 解析，不手抄。

# 71. 变动工资输入

来源：
- HR12 performance；
- teaching/workload Provider；
- approved overtime；
- approved allowance；
- bonus；
- one-time adjustments；
- external-teacher workload。

必须有 source status。

# 72. 考勤扣款输入

只消费 HR11 closed absence/time basis。
HR15 通过 LeavePayRuleVersion 计算金额。
不读打卡明细。

# 73. 计算 Run

`PayrollCalculationRun`：
- run_no；
- period；
- population version；
- rule set versions；
- input hash；
- status；
- started/completed；
- worker version；
- retry count。

# 74. 个人 Calculation

每人：
- result header；
- result lines；
- employer contribution lines；
- tax ledger delta；
- validation；
- warnings；
- source refs；
- calculation hash。

# 75. Gross / Net

明确：
```text
gross earnings
- employee statutory deductions
- tax
- other deductions
± adjustments
= net payable
```

同时保留 employer cost，不混进 net pay。

# 76. Validation Engine

至少：
- negative net；
- huge variance；
- missing bank；
- source unavailable；
- duplicate pay item；
- invalid tax state；
- social/housing base out of bounds；
- terminated staff paid beyond date；
- new hire proration；
- zero-pay unexpected；
- employer contribution mismatch。

# 77. 工资波动分析

与上月/基准比较：
- gross delta；
- net delta；
- each item delta；
- percent；
- reason refs。

阈值可配置，异常必须可 drilldown。

# 78. 复核工作流

Payroll clerk → reviewer → authorized approver。
支持组织分片审核，但最终 Period Finalize 为学校级授权。

# 79. 月结

Finalize：
- freeze results；
- hash；
- close tax ledger；
- social/housing outputs；
- generate payslip projection；
- posting/payment packages；
- outbox。

月结失败必须事务性/可恢复。

# 80. 期间锁

CLOSED 后：
- 禁止改 input/result；
- 原工资条 immutable；
- 只能 RetroAdjustment。

# 81. 追溯影响检测

事件：
- HR14 retro appointment；
- HR03 correction；
- HR12 result revision；
- HR11 correction；
- pay standard retro update；
- social/housing base correction；
- tax correction；
- bank/payment correction。

生成 `RetroImpactCase`。

# 82. Retro Run

重算历史“应当是多少”，与原 FINAL 比较：
`delta = recalculated - original final`。

生成 Delta Payroll，不覆盖原工资。

# 83. 补发/追扣

差额进入后续 period 或专项 settlement：
- positive arrears；
- negative recovery；
- tax impact；
- social/housing impact；
- payment recovery strategy；
- employee notice。

# 84. 离职结算

HR16 请求 FinalSettlement：
- last pay；
- arrears；
- recoveries；
- approved leave/other；
- tax；
- social/housing cutoff；
- unpaid amounts；
- final payslip。

不得因为 HR16 case open 就提前删 PayrollProfile。

# 85. HR15-03 UI

```text
/hr/payroll/periods
/hr/payroll/periods/{id}
/hr/payroll/calculations
/hr/payroll/review
/hr/payroll/retro
/hr/payroll/settlements
```
首屏突出异常/阻塞/变化原因。

# 86. HR15-04 业务目标

把岗位变动、薪级晋升、绩效、政策性调资、津贴补贴、一次性奖励都做成 effective-dated 可审批变更。

# 87. CompensationChangeCase

类型：
```text
POSITION_PAY_CHANGE
SALARY_STEP_CHANGE
POLICY_STANDARD_CHANGE
PERFORMANCE_ADJUSTMENT
ALLOWANCE_START
ALLOWANCE_CHANGE
ALLOWANCE_STOP
BONUS
SPECIAL_REWARD
ARREARS
RECOVERY
CORRECTION
```

# 88. 岗位变动调资

HR14 AppointmentEffective
→ CompensationImpactAnalysis
→ resolve PayStandardVersion
→ ProposedChange
→ effective date
→ future/current/retro path。

不能 HR14 一发事件就直接改本月 final。

# 89. 薪级晋升

支持：
- 定期晋级；
- 考核触发；
- 政策调整；
- 重新确定；
- 暂缓；
- 恢复；
- correction。

规则、审批、生效均版本化。

# 90. 政策性调资

新 PayStandardVersion：
- 支持未来生效；
- 支持追溯生效；
- impact preview；
- population；
- delta total；
- budget/finance review；
- staged rollout；
- retro run。

# 91. 绩效工资分配

需要：
- total amount/source；
- allocation rule；
- department share；
- employee share；
- HR12 references；
- manual adjustment with reason；
- cap/floor；
- residual handling；
- approval；
- audit。

# 92. 绩效总量控制

如果学校政策要求总量：
- approved pool；
- allocated；
- reserved；
- remaining；
- final distributed；
- reconciliation。

禁止个人金额之和超过批准总量而系统不报错。

# 93. 津补贴生命周期

Allowance entitlement：
- item；
- staff；
- source；
- amount/rule；
- start/end；
- review date；
- stop condition；
- status/version。

# 94. 一次性奖励

BonusCase：
- source decision；
- amount/pool；
- recipients；
- allocation；
- tax mode；
- pay period；
- approval；
- document；
- version。

# 95. 手工调整

ManualAdjustment 只能：
- authorized roles；
- reason code；
- supporting document；
- amount bounds；
- double review if threshold；
- period；
- tax/social attributes；
- audit。

不能做万能“其他+1000”。

# 96. 负数追扣

Recovery：
- source debt/ref；
- total；
- installment；
- minimum net protection rule；
- employee notice；
- legal/policy basis；
- outstanding balance。

不能一次扣到负工资而无规则。

# 97. 调资冲突

同一 staff/effective date 多变更：
- detect overlaps；
- priority；
- merge policy；
- manual conflict resolution；
- final snapshot。

# 98. HR15-04 UI

```text
/hr/payroll/changes
/hr/payroll/allowances
/hr/payroll/performance-pay
/hr/payroll/bonuses
/hr/payroll/policy-adjustments
```

# 99. HR15-05 业务目标

把社保与公积金从“工资扣款项目”升级成有地区政策、基数、单位/个人双边金额、申报与回执的法定业务。

# 100. Jurisdiction

`StatutoryJurisdiction`：
- country；
- province；
- city；
- agency；
- effective period；
- source refs。

同一 tenant 可有跨地人员。

# 101. SocialInsurancePolicyVersion

每险种：
- pension；
- medical；
- unemployment；
- work injury；
- maternity/merged local rule；
- other authorized。

字段：
base formula、lower/upper、employee rate、employer rate、rounding、eligibility、effective dates。

# 102. HousingFundPolicyVersion

- base formula；
- lower/upper；
- employee ratio；
- employer ratio；
- rounding；
- supplemental housing fund if applicable；
- effective dates；
- local source。

# 103. 缴费基数

`ContributionBaseAssignment`：
- staff；
- type；
- declared base；
- calculated base；
- capped base；
- source year；
- effective period；
- policy version；
- review/approval；
- provider status。

# 104. 年度基数调整

批量：
- import local upper/lower；
- calculate candidate bases；
- preview；
- variance；
- employee list；
- review；
- effective month；
- retro if required；
- submission。

# 105. 新入职参保

HR05/HR03 activation
→ enrollment case
→ jurisdiction resolve
→ account creation/provider
→ effective date
→ first contribution period。

Provider pending ≠ enrolled。

# 106. 停保

HR16 termination/retirement
→ stop case
→ last contribution month
→ provider submission/receipt。

不能仅 `profile.active=False`。

# 107. 单位/个人双边金额

PayrollResultLine 分开：
- employee deduction；
- employer contribution；
- statutory type；
- base；
- rate；
- policy version；
- amount。

# 108. 社保申报批次

`SocialInsuranceFilingBatch`：
- period；
- jurisdiction；
- employees；
- bases；
- employer/employee totals；
- provider payload；
- receipt；
- status；
- reconciliation。

# 109. 公积金申报批次

同样：
- open/change/close；
- base/ratio；
- monthly contribution；
- provider receipt；
- errors；
- retry；
- reconciliation。

# 110. 社保公积金差异

本地计算 vs 机构回执：
- employee count；
- base；
- contribution；
- rejected records；
- difference amount；
- resolution case。

不得自动把机构回执覆盖本地 payroll 而无审计。

# 111. 补缴/退缴

Retro contribution：
- source period；
- original；
- recalculated；
- delta；
- employee/employer portions；
- filing type；
- payroll impact；
- receipt。

# 112. 员工权益展示

本人只看自己的：
- base；
- employee contribution；
- employer contribution；
- period；
- submission status。

不把第三方账户秘密暴露。

# 113. HR15-05 UI

```text
/hr/payroll/social-insurance
/hr/payroll/housing-fund
/hr/payroll/statutory/bases
/hr/payroll/statutory/filings
/hr/payroll/statutory/reconciliation
```

# 114. HR15-06 业务目标

把“工资算出来”推进到员工可查、银行可付、财务可入账、税务/社保/公积金可申报、所有回执可对账。

# 115. Payslip Projection

工资条来自 FINAL PayrollResult：
- period；
- earnings；
- deductions；
- statutory；
- tax；
- net；
- employer contributions（按学校展示策略）；
- year-to-date tax summary；
- retro lines；
- payment status。

Payslip 不自行计算。

# 116. PayslipDocumentVersion

- template version；
- result id/version；
- rendered hash；
- issued_at；
- supersedes；
- revoked/invalid indicator；
- download policy。

历史工资条不可被新模板重写。

# 117. 本人查看

`/api/v1/hr/payroll/me/payslips`
服务端 token → staff。
禁止传任意 staff_id。

# 118. 工资条安全

- re-auth/MFA 可配置；
- signed URL；
- short TTL；
- watermark；
- download audit；
- no-cache headers；
- sensitive masking；
- PDF encryption only as optional extra, not security boundary。

# 119. PaymentBatch

`HrPaymentBatch`：
- payroll period；
- payment channel；
- bank/treasury；
- count；
- total net；
- source result versions；
- file/payload version；
- approved by；
- status；
- idempotency；
- submitted_at。

# 120. PaymentInstruction

每人：
- result id；
- account token；
- amount；
- currency；
- purpose/reference；
- beneficiary masked snapshot；
- status；
- provider reference；
- failure code。

# 121. 银行代发文件

Adapter 按银行/国库模板生成：
- fixed format；
- checksum；
- row count/total；
- encryption/signing；
- file hash；
- sequence no。

原始账户值只在受控生成环境解密。

# 122. 支付回执

Provider/人工导入回执：
- accepted；
- processing；
- success；
- rejected；
- returned；
- unknown。

必须逐笔 reconciliation。

# 123. 支付失败

失败后：
- 不改 PayrollResult net；
- PaymentInstruction FAILED；
- resolve bank/account；
- reissue batch/ref；
- audit；
- employee notice as policy。

不得复制工资结果。

# 124. FinancePostingPackage

输出：
- period；
- pay item totals；
- employer contributions；
- department/cost center；
- project/fund source if applicable；
- debit/credit mapping；
- posting date；
- source result hashes；
- balancing check。

# 125. 会计映射

`GLMappingVersion`：
- pay item；
- employee/employer side；
- org/cost center；
- debit account；
- credit account；
- fund/project rule；
- effective dates。

不把会计科目写在 calculation code。

# 126. 凭证回执

财务系统：
`SUBMITTED → ACCEPTED/REJECTED/POSTED`。
HR15 保存 voucher id/date/receipt。
未过账不等于 payroll 未生效，但必须风险提示。

# 127. 个税扣缴输出

按 TaxRuleVersion 生成：
- taxpayer；
- income；
- exemptions；
- deductions；
- cumulative base；
- tax rate/quick deduction；
- current withholding；
- YTD withholding；
- special bonus handling；
- correction records。

对接可用 file/API adapter。

# 128. 个税申报回执

生成文件 ≠ 申报成功。
保存：
- submission；
- provider receipt；
- accepted/rejected rows；
- tax total；
- reconciliation；
- correction batch。

# 129. 三方对账

至少：
```text
Payroll Final Net
vs Payment Success
vs Finance Posted Payable/Bank
```

再叠加：
```text
Payroll Tax vs Tax Filing Receipt
Payroll Social/HF vs Agency Receipt
```

# 130. Period Reconciliation

CLOSED 后可进入 RECONCILED 只有：
- payroll totals valid；
- payment reconcile；
- finance reconcile；
- statutory reconcile or documented pending；
- no unresolved P0 exceptions。

# 131. HR15-06 UI

```text
/hr/payroll/payslips
/hr/payroll/payments
/hr/payroll/finance-posting
/hr/payroll/tax-filing
/hr/payroll/reconciliation
```

# 132. 核心模型总表

```text
HrPayrollProfile
HrPayGroup
HrCompensationScheme
HrCompensationSchemeVersion
HrPaymentAccount
HrTaxProfile
HrSocialInsuranceProfile
HrHousingFundProfile

HrPayItem
HrPayItemVersion
HrPayStandard
HrPayStandardVersion
HrPayrollRulePack
HrPayrollRuleVersion
HrPayrollRuleExpression
HrPayrollRuleTarget
HrGLMappingVersion

HrPayrollPeriod
HrPayrollPopulationSnapshot
HrPayrollInputSnapshot
HrPayrollCalculationRun
HrPayrollResult
HrPayrollResultLine
HrEmployerContributionLine
HrPayrollValidationIssue
HrPayrollReview
HrPayrollApproval
HrPayrollCloseSnapshot

HrCompensationChangeCase
HrSalaryStepAssignment
HrAllowanceEntitlement
HrPerformancePayPool
HrPerformancePayAllocation
HrBonusCase
HrManualAdjustment
HrRecoveryPlan
HrRetroImpactCase
HrRetroCalculation
HrPayrollDelta

HrStatutoryJurisdiction
HrSocialInsurancePolicyVersion
HrHousingFundPolicyVersion
HrContributionBaseAssignment
HrSocialInsuranceFilingBatch
HrHousingFundFilingBatch
HrStatutoryFilingItem
HrStatutoryReceipt

HrPayslipDocumentVersion
HrPaymentBatch
HrPaymentInstruction
HrPaymentReceipt
HrFinancePostingPackage
HrFinancePostingReceipt
HrTaxWithholdingLedger
HrTaxFilingBatch
HrTaxFilingReceipt
HrPayrollReconciliation
HrPayrollArchivePackage
HrPayrollRiskCase
```

# 133. Money / Decimal 规范

数据库金额：
`Decimal(precision, scale)`。
建议内部计算至少 4–6 小数，中间不提前 round，最终按项目/法规定义 rounding。

所有 RuleVersion 明确：
- rounding point；
- rounding mode；
- final scale。

# 134. 工资计算确定性

相同：
- InputSnapshot；
- RuleVersion；
- engine version；
- rounding settings
必须得到相同 CalculationHash。

# 135. Formula Sandbox

DSL Parser：
- AST 白名单；
- no import；
- no IO；
- no network；
- no file；
- no reflection；
- no DB arbitrary query；
- timeout；
- complexity limit。

Rule 发布前 compile/validate。

# 136. Rule Dependency Graph

Pay items 可依赖其他 pay items。
发布前检查：
- cycle；
- missing dependency；
- ambiguous order；
- tax/statutory phase conflict。

# 137. Calculation Phases

建议：
```text
1 profile/base facts
2 fixed earnings
3 variable earnings
4 pre-statutory adjustments
5 statutory bases
6 employee/employer statutory contributions
7 taxable income
8 PIT withholding
9 post-tax deductions
10 net pay
11 employer total cost
12 reconciliation validations
```

顺序由 engine contract 固定，业务参数由 RuleVersion 配置。

# 138. API 前缀

`/api/v1/hr/payroll/...`；统一 envelope、requestId、sourceStatus、aggregateVersion。

# 139. 错误码

```text
PAYROLL_PROFILE_NOT_READY
PAY_GROUP_NOT_FOUND
RULE_VERSION_NOT_FOUND
RULE_CONFLICT
FORMULA_INVALID
SOURCE_UNAVAILABLE
PERIOD_NOT_OPEN
INPUT_NOT_FROZEN
CALCULATION_FAILED
RESULT_VALIDATION_BLOCKED
PERIOD_ALREADY_CLOSED
RESULT_IMMUTABLE
RETRO_REQUIRED
PAYMENT_ACCOUNT_INVALID
PAYMENT_BATCH_CONFLICT
PAYMENT_PROVIDER_ERROR
TAX_LEDGER_CONFLICT
STATUTORY_POLICY_MISSING
STATUTORY_FILING_REJECTED
FINANCE_POSTING_REJECTED
RECONCILIATION_MISMATCH
```

# 140. 权限代码

```text
hr.payroll.profile.view/manage
hr.payroll.bank.view_masked/manage
hr.payroll.bank.view_full
hr.payroll.rule.view/manage/publish
hr.payroll.period.view/manage
hr.payroll.calculate
hr.payroll.review
hr.payroll.approve
hr.payroll.finalize
hr.payroll.retro.manage
hr.payroll.adjustment.manage
hr.payroll.performance.manage
hr.payroll.statutory.view/manage
hr.payroll.tax.manage
hr.payroll.payment.manage
hr.payroll.finance.manage
hr.payroll.reconcile
hr.payroll.payslip.self
hr.payroll.payslip.admin
hr.payroll.export
hr.payroll.sensitive.view
```

# 141. 数据范围

工资金额默认：
- SELF；
- PAYROLL_TEAM；
- AUTHORIZED_FINANCE；
- SCHOOL_CONTROLLED。

学院业务管理员默认不得查看个人工资。
不能沿用普通 Department scope 自动开放工资。

# 142. SoD

至少：
- 规则发布人与工资期间最终审批可分离；
- 手工调整发起人与审批人分离；
- 银行账户变更审核分离；
- calculate 与 finalize 可分离；
- payment file maker/checker；
- finance posting maker/checker；
- revocation/correction 高权限；
- 平台运维无业务数据权限。

# 143. Idempotency

覆盖：
- profile creation；
- calc run；
- finalize；
- retro run；
- change effective；
- payment submit；
- payment retry；
- tax filing；
- statutory filing；
- finance posting；
- receipt import；
- reconciliation。

# 144. Optimistic Lock

所有可变聚合 version；409 冲突，不 last-write-wins。

# 145. Outbox

```text
PayrollProfileReady
CompensationChangeEffective
PayrollPeriodOpened
PayrollInputFrozen
PayrollCalculated
PayrollFinalized
PayrollDeltaFinalized
PayslipIssued
PaymentBatchSubmitted
PaymentCompleted
PaymentFailed
TaxFilingSubmitted
StatutoryFilingSubmitted
PayrollReconciled
FinalSettlementCompleted
```

# 146. Inbox

银行/税务/社保/公积金/财务 callback 或文件回执必须 providerRef + idempotency + signature/hash。

# 147. 分页

DB WHERE→COUNT→ORDER→OFFSET/LIMIT/cursor，工资台账禁止内存过滤。

# 148. Excel 导入

允许：
- approved variable inputs；
- historical payroll migration；
- salary standard table；
- statutory parameter staging；
- payment/statutory receipts。

必须 staging/validate/error workbook/preview/confirm/async/audit。

# 149. Excel 导出

工资、银行、税务、社保、公积金、财务数据均异步，字段级权限、脱敏、水印、下载过期。

# 150. 文件安全

工资条/银行文件/申报文件/财务文件 private；scan/hash/signed URL/retention/access audit。

# 151. 敏感字段加密

银行账号、税号、社保账号、公积金账号等 field encryption/tokenization + key rotation。

# 152. 可观测性

```text
payroll_profile_not_ready_total
payroll_calc_failed_total
payroll_validation_blocked_total
payroll_variance_high_total
payroll_period_close_failed_total
payroll_retro_open_total
payroll_payment_failed_total
payroll_tax_filing_rejected_total
payroll_social_filing_rejected_total
payroll_housing_fund_filing_rejected_total
payroll_finance_posting_failed_total
payroll_reconciliation_mismatch_total
payroll_legacy_drift_total
```

# 153. 结构化日志

仅写：
tenant、actor、period、run、result id、action、error_code、latency。
禁止工资明细、银行卡、税号、专项附加扣除家庭信息进入日志。

# 154. Data Quality

检查：
- duplicate final result；
- overlapping profile；
- float money residue；
- missing rule version；
- missing source；
- employer/employee statutory mismatch；
- net != line reconciliation；
- YTD tax ledger mismatch；
- payment total != final net；
- GL package imbalance；
- HR14 appointment vs pay basis drift；
- HR16 ended employee still future paid；
- cross-tenant references。

# 155. Retention

工资结果/工资条/支付/税务/社保公积金/财务对账按法定与学校档案政策长期/规定期限保存。
临时银行文件短期保留。
Legal hold 覆盖 purge。

# 156. UI 原则

- 工资员首页先看阻塞/异常/差异；
- 不展示无意义工资排行榜；
- 不做“谁工资最高”卡片；
- 本人页面简洁看工资条；
- 规则编辑全页；
- 月结工作台强调状态机；
- 复杂调资不用右抽屉。

# 157. Accessibility

工资条/表格键盘可用、状态文字、错误关联、敏感值 mask 可读、移动端本人查看。

# 158. Visual Regression

`375/768/1280/1440`；覆盖 loading/empty/stale/source unavailable/blocked/final/paid/reconcile mismatch。

# 159. HR15-01 API

```text
GET/POST /api/v1/hr/payroll/profiles
GET /profiles/{staffId}
POST /profiles/{staffId}/activate
POST /profiles/{staffId}/payment-accounts
POST /profiles/{staffId}/tax
POST /profiles/{staffId}/statutory
GET /readiness
```

# 160. HR15-02 API

```text
GET/POST /items
GET/POST /rules
POST /rules/{id}/versions
POST /rules/{id}/versions/{v}/validate
POST /rules/{id}/versions/{v}/publish
GET/POST /standards
POST /simulate
```

# 161. HR15-03 API

```text
GET/POST /periods
POST /periods/{id}/open
POST /periods/{id}/freeze-input
POST /periods/{id}/calculate
GET /periods/{id}/issues
POST /periods/{id}/review
POST /periods/{id}/approve
POST /periods/{id}/finalize
POST /retro-impact/{id}/calculate
```

# 162. HR15-04 API

```text
GET/POST /changes
POST /changes/{id}/submit
POST /changes/{id}/approve
POST /performance-pools
POST /bonuses
POST /adjustments
POST /recoveries
```

# 163. HR15-05 API

```text
GET/POST /statutory/policies
GET/POST /statutory/bases
POST /social-insurance/filings
POST /housing-fund/filings
POST /statutory/receipts/import
GET /statutory/reconciliation
```

# 164. HR15-06 API

```text
GET /payslips
GET /me/payslips
POST /payment-batches
POST /payment-batches/{id}/submit
POST /payment-receipts/import
POST /finance-postings
POST /tax-filings
GET /reconciliation
```

# 165. 字段级冻结｜PayrollProfile

```text
id tenant_id staff_id person_id employment_relationship_id
pay_group_id compensation_scheme_version_id
tax_profile_id social_profile_id housing_fund_profile_id
primary_payment_account_id
effective_from effective_to status version
created_at updated_at
```

# 166. 字段级冻结｜PaymentAccount

```text
id tenant_id staff_id holder_name_encrypted
bank_code branch_code account_token account_last4
verification_status valid_from valid_to primary_flag
verified_by verified_at version
```

# 167. 字段级冻结｜PayItem

```text
id tenant_id code name category direction
tax_class social_class housing_fund_class
employer_cost_flag cash_flag display_order
valid_from valid_to status version
```

# 168. 字段级冻结｜RuleVersion

```text
id rule_pack_id version_no effective_from effective_to
expression_ast parameter_schema source_requirements
rounding_mode calculation_phase
published_at published_by content_hash status
```

# 169. 字段级冻结｜PayrollPeriod

```text
id tenant_id pay_group_id period_code start_date end_date
cutoff_at pay_date tax_year tax_month
population_snapshot_id input_snapshot_id
status version opened_at closed_at
```

# 170. 字段级冻结｜PayrollResult

```text
id tenant_id period_id staff_id calculation_run_id
gross_amount employee_statutory tax_amount other_deduction
net_amount employer_statutory employer_total_cost
currency status result_version calculation_hash
approved_at finalized_at
```

# 171. 字段级冻结｜PayrollResultLine

```text
result_id pay_item_id amount quantity rate base_amount
taxable_amount statutory_base_component
rule_version_id source_refs explanation
rounding_delta line_hash
```

# 172. 字段级冻结｜TaxWithholdingLedger

```text
tenant_id staff_id tax_year month
cumulative_income cumulative_exempt
cumulative_standard_deduction cumulative_statutory_deduction
cumulative_special_additional_deduction cumulative_other_deduction
cumulative_taxable_income cumulative_tax_due
cumulative_tax_withheld current_tax
tax_rule_version result_id ledger_hash
```

# 173. 字段级冻结｜SocialPolicyVersion

```text
jurisdiction_id insurance_type version
effective_from effective_to
base_rule lower_limit upper_limit
employee_rate employer_rate
rounding eligibility_rule source_ref status hash
```

# 174. 字段级冻结｜HousingFundPolicyVersion

同上，增加 employee_ratio/employer_ratio、supplemental rule、local agency refs。

# 175. 字段级冻结｜CompensationChangeCase

```text
id tenant_id staff_id change_type
source_event_ref proposed_effective_date
before_snapshot after_snapshot
retro_flag approval_status status
approved_by approved_at version
```

# 176. 字段级冻结｜PaymentBatch

```text
id tenant_id period_id batch_no provider_id
instruction_count total_amount currency
source_result_hash file_hash status
approved_by submitted_at provider_ref version
```

# 177. 字段级冻结｜Reconciliation

```text
period_id type
source_total target_total difference
matched_count unmatched_count
status findings resolved_by resolved_at
source_receipt_refs
```

# 178. DB Constraints

- tenant not null；
- money Decimal；
- one FINAL result per staff/period/revision chain；
- no overlapping active profile for same employment/pay group；
- tax ledger unique staff/year/month；
- payment instruction unique result/payment attempt；
- result line amount integrity；
- closed period immutable；
- cross-tenant FK reject；
- version positive；
- effective date valid。

# 179. 关键索引

```text
(tenant_id, period_id, status)
(tenant_id, staff_id, period_id)
(tenant_id, pay_group_id, period_code)
(staff_id, effective_from, effective_to)
(period_id, staff_id, status)
(payment_batch_id, status)
(jurisdiction_id, insurance_type, effective_from)
(staff_id, tax_year, month)
```

# 180. Decimal 精度测试

- 0.1+0.2
- 四舍五入边界
- 负数
- 大金额
- rate precision
- FTE prorate
- 税额 rounding
- 社保上下限

# 181. 规则引擎测试

- AST allowlist
- cycle
- missing source
- version
- phase
- conditional
- cap/floor
- rounding
- no arbitrary Python

# 182. Tenant 安全测试

- cross-tenant profile
- payslip IDOR
- bank IDOR
- export
- payment batch
- statutory filing
- background job
- platform ops denied

# 183. 敏感数据测试

- masked bank
- full-bank permission
- tax id encrypted
- no logs
- signed payslip URL expiry
- export field permission
- audit

# 184. Scope 测试

- SELF payslip only
- payroll team
- finance limited scope
- college admin denied amount
- reviewer assigned group

# 185. SoD 测试

- adjustment maker/checker
- rule publisher/final approver
- bank change maker/checker
- payment maker/checker
- revocation privilege

# 186. 并发测试

- double calculate
- double finalize
- double adjustment approval
- same tax ledger update
- same payment submit
- receipt duplicate
- retro vs current period
- profile update at cutoff

# 187. Period 状态机测试

- DRAFT cannot finalize
- OPEN requires readiness
- freeze locks input
- CLOSED immutable
- PAID not recalculated in place
- retro new delta

# 188. PayrollProfile 测试

- new hire
- rehire
- multi-employment
- external teacher
- bank change
- tax profile
- end profile
- as-of

# 189. HR14 Handoff 测试

- AppointmentEffect pending not paid
- effective event recalculation
- future effective
- retro effective
- revoked appointment
- high/low appointment

# 190. HR12 Handoff 测试

- Final only
- revision
- unavailable
- performance coefficient
- no result modification

# 191. HR11 Handoff 测试

- closed time only
- raw punch ignored
- absence categories
- overtime approved
- correction generates retro

# 192. Tax 累计预扣测试

- Jan-Dec cumulative
- mid-year hire special rule
- special deductions
- negative current withholding rule
- bonus separate/combined option
- correction
- year boundary

# 193. 专项附加扣除测试

- effective months
- provider change
- privacy
- versioned standard
- duplicate deduction blocked

# 194. 社保测试

- base lower/upper
- employee/employer rate
- new hire
- stop
- local policy change
- retro
- receipt difference
- jurisdiction transfer

# 195. 公积金测试

- base lower/upper
- ratio
- annual base change
- new account
- stop
- retro
- local rule
- receipt

# 196. 绩效总量测试

- pool cap
- allocation sum
- rounding residual
- manual override
- HR12 source
- approval
- retro revision

# 197. 工资波动测试

- new hire expected
- promotion expected
- 100% jump flagged
- zero pay flagged
- termination prorate
- reason drilldown

# 198. 追溯测试

- salary standard retro
- appointment retro
- assessment revision
- time correction
- social base correction
- tax correction
- positive/negative delta
- no history overwrite

# 199. 离职结算测试

- last day
- arrears
- recovery
- payment failure
- statutory stop
- final payslip
- HR16 ack

# 200. 支付测试

- file totals
- account validation
- duplicate submit
- partial success
- retry only failed
- unknown status
- return
- reconcile

# 201. 财务凭证测试

- balanced debit/credit
- GL version
- department/cost center
- reject
- repost
- receipt
- no duplicate posting

# 202. 税务申报测试

- payload version
- accepted/rejected rows
- tax total
- correction
- receipt idempotency
- no generated=filed confusion

# 203. Excel 测试

- template version
- Decimal
- tenant
- staging
- error workbook
- preview
- async
- final protection
- audit

# 204. Provider Failure 测试

- HR03 unavailable
- HR11 not closed
- HR12 unavailable
- HR14 effect pending
- bank 500
- tax provider 500
- social provider 500
- finance 500
- UNAVAILABLE != 0

# 205. 性能测试

建议 S0 结合规模校准：
- 1万员工月薪批算 async；
- 单人计算 p95 < 400ms（纯本地已冻结输入）；
- period dashboard p95 < 700ms；
- payslip list p95 < 500ms；
- review list p95 < 600ms；
- 10万历史工资结果可分页；
- payroll result no N+1；
- payment/statutory/export 均 async。

# 206. MySQL 专项测试

- Decimal
- transaction isolation
- row locking
- deadlock retry
- unique constraints
- index explain
- migration rollback
- timezone

# 207. Accessibility 测试

- keyboard
- labels
- error associations
- tables
- focus
- masked sensitive fields
- mobile payslip

# 208. Visual Regression 测试

HR15-01~06 + self payslip + review + retro + payment + reconciliation；375/768/1280/1440。

# 209. E2E 正常月薪主链

1 HR03 active staff；
2 HR15 profile ready；
3 HR14 appointment effective；
4 period open；
5 HR11 previous/current applicable close ready；
6 HR12 performance facts ready；
7 freeze population/input；
8 calculate；
9 tax cumulative；
10 social/housing；
11 validation；
12 variance review；
13 approval；
14 finalize；
15 payslip；
16 payment batch；
17 bank success；
18 finance posted；
19 tax filing accepted；
20 social/housing filing accepted/reconciled；
21 period reconciled；
22 HR18 consumes closed facts。

# 210. E2E 新入职

HR05 bank → HR03 activation → PayrollProfileRequested → profile READY → mid-month proration → tax new-hire rule if applicable → first payslip/payment。

# 211. E2E 岗位晋级调资

HR14 AppointmentEffective → HR15 resolve new standard → effective date → current/future or retro delta → payment → HR03/14 untouched。

# 212. E2E 年度考核影响绩效

HR12 FinalResult → HR15 PerformanceRuleVersion → allocation → approval → payroll line；HR12 unchanged。

# 213. E2E 考勤更正追溯

HR11 closed correction → RetroImpact → re-evaluate historical pay → Delta → next payroll arrears/recovery → original payslip preserved。

# 214. E2E 政策性追溯调资

new PayStandardVersion retro effective → impact 3000 staff → async retro → delta total → review → approved → batch补发。

# 215. E2E 最低净工资保护

recovery exceeds configured recoverable amount → installment plan → net not forced negative → outstanding balance。

# 216. E2E 银行部分失败

1000 instructions → 998 success/2 failed → period payroll remains final → 2 reissue → full reconciliation。

# 217. E2E 税务部分拒绝

tax filing 1 row rejected → case → correction → resubmit → receipt → payroll result not silently altered。

# 218. E2E 社保基数年度调整

new local base policy → preview → employee bases → approval → effective month → filing → receipt diff → reconcile。

# 219. E2E 离职结算

HR16 final date → final settlement → prorated/final amounts → tax/statutory cutoff → bank pay → HR16 settlement receipt。

# 220. E2E 职称撤销但岗位未决定

HR13 revoked → HR14 review open → HR15 不自动改工资；只有 HR14 新 EFFECTIVE event 才调整。

# 221. E2E Provider 不可用

HR14/HR11 source unavailable → payroll issue BLOCK → 不把值当 0 → restore provider → recalc。

# 222. E2E 历史迁移

legacy payslip/contract/wage → staging → Decimal normalization → trust → original monthly results import → no fake tax/social receipts → DUAL compare。

# 223. Legacy Payroll Mapping

S0 搜索 payroll.Contract、Allowance、Deduction、Payslip、FilingStatus、TaxBracket、EmployeeWorkInformation.basic_salary、Excel/report。形成 `LegacyPayrollMapping.md`。

# 224. Legacy Trust Matrix

`CALCULATED_VERIFIED / PAYSLIP_SUPPORTED / BANK_SUPPORTED / FINANCE_SUPPORTED / MANUAL_CONFIRMED / UNVERIFIED / CONFLICTED`。

# 225. Float → Decimal 迁移

保留 raw float、normalized Decimal、rounding delta、source id；对高风险差异人工复核。

# 226. 旧 Contract 解耦

HR07 Authority 上线后，payroll.Contract 不再承担合同真值；其 wage 只作为 legacy compensation source。

# 227. 旧 Allowance/Deduction 映射

逐条映射 PayItem/RuleVersion；arbitrary python/custom conditions 不直接迁移为可执行正式规则。

# 228. 旧 Tax 迁移

FilingStatus/TaxBracket 不作为中国个税 Authority；仅保留历史说明/旧计算 evidence。

# 229. 旧 Payslip 迁移

可迁移 HistoricalPayrollResult + source payslip document；没有输入/规则快照时标 MIGRATED trust。

# 230. Legacy Projection

新 HR15 current basic pay/summary 可投影旧页面只读；禁止旧页面继续 formal writes。

# 231. DUAL_READ_COMPARE

- gross
- net
- basic/position/step
- allowance/deduction
- employee count
- period totals
- payslip count
- current pay basis
- payment totals where available

# 232. Authority Cutover

```text
LEGACY_PAYROLL_ACTIVE
→ HR15_STAGING
→ DUAL_CALC_COMPARE
→ SHADOW_PAYROLL
→ FREEZE_LEGACY_FORMAL_WRITES
→ HR15_AUTHORITY
→ LEGACY_READONLY_PROJECTION
```

# 233. Rollback

切入口/读取，不删除 HR15 facts；已 final 新工资需正式 reversal/correction，不用数据库回滚伪装业务撤销。

# 234. AI 使用边界

- AI 可解释工资条、归类异常、辅助规则差异分析、生成测试用例、提示缺失配置。
- AI 不得决定工资标准。
- AI 不得自动批准调资/奖金。
- AI 不得推断未提供的家庭专项附加扣除。
- AI 不得根据他人工资训练/预测个人应得薪酬。
- AI 输出仅 advisory，不进入 FINAL calculation input 除非人工确认并形成正式输入。

# 235. 编码 AI 施工纪律

- 先读真实 payroll 代码。
- 不重建 HR03/07/11/12/14 Authority。
- 不使用 git add -A。
- 未经授权不 push/merge main。
- 保持 Draft PR。
- 先 Decimal/Authority/transaction/security，再 UI。
- arbitrary python formula 必须退出正式路径。
- Provider unavailable fail-closed。
- 每阶段专项测试 + 既有 payroll regression。
- MySQL 是最终数据库验收。
- 不以 mock 成功冒充正式支付/申报。

# 236. S0 输出物

```text
HR15_GAP_MATRIX.md
LegacyPayrollMapping.md
LegacyPayrollTrustMatrix.md
PayrollAuthorityBoundary.md
PayrollMoneyPrecisionPlan.md
PayrollRuleMigrationMatrix.md
PayrollTaxPolicyMatrix.md
PayrollStatutoryPolicyMatrix.md
PayrollProviderMatrix.md
PayrollSensitiveDataMatrix.md
HR15_PERMISSION_MATRIX.md
HR15_INTEGRATION_MATRIX.md
HR15_TASK_TREE.md
HR15_RISK_REGISTER.md
HR15_MIGRATION_PLAN.md
```

# 237. HR15-S0 基线复审

- read payroll/models/methods/forms/dashboard/scheduler
- search wage/basic_salary/payslip/tax/allowance/deduction
- map HR03/05/07/11/12/14/16 contracts
- audit Float and python_code
- verify local statutory/tax policy
- audit payment/finance integration

# 238. HR15-S1 A0 与 Decimal 基础

- tenant fail-closed
- money Decimal
- permission/scope/SoD
- API/error
- encrypted sensitive fields
- Outbox/Jobs/Audit
- base enums

# 239. HR15-S2 薪酬档案

- PayrollProfile
- PayGroup
- Scheme
- PaymentAccount
- TaxProfile
- Social/HF Profile
- readiness
- HR15-01 UI

# 240. HR15-S3 薪资项目与规则

- PayItem
- StandardVersion
- Rule DSL
- dependency graph
- rounding
- performance/allowance/bonus
- simulator
- HR15-02 UI

# 241. HR15-S4 月度期间与输入冻结

- Period
- PopulationSnapshot
- InputSnapshot
- HR03/11/12/14 provider
- cutoff
- source status
- freeze tests

# 242. HR15-S5 计算/复核/月结

- CalculationRun
- Result/Lines
- tax/statutory
- validation
- variance
- review/approval
- finalize
- close snapshot
- HR15-03 UI

# 243. HR15-S6 调资/津贴/绩效

- ChangeCase
- SalaryStep
- policy adjustment
- PerformancePool
- Allowance
- Bonus
- ManualAdjustment
- Recovery
- HR15-04 UI

# 244. HR15-S7 Retro

- impact detector
- historical recompute
- delta
- arrears/recovery
- tax/statutory impact
- audit
- E2E

# 245. HR15-S8 社保公积金

- jurisdiction
- policy versions
- bases
- enroll/stop
- filings
- receipts
- reconciliation
- HR15-05 UI

# 246. HR15-S9 个税

- China TaxProfile
- cumulative ledger
- special deductions
- new-hire rule
- bonus mode
- filing
- receipt
- correction

# 247. HR15-S10 Payslip/支付/财务

- PayslipVersion
- PaymentBatch
- bank adapter
- receipt
- finance posting
- GL mapping
- reconciliation
- HR15-06 UI

# 248. HR15-S11 Legacy + 全量质量

- float normalization
- rule migration
- historical payroll
- DUAL calc
- security
- concurrency
- performance
- API/provider
- E2E
- A11y
- visual
- observability

# 249. HR15-S12 Authority Cutover

- shadow payroll
- totals compare
- employee sample compare
- freeze old writes
- payment dry run
- tax/statutory dry run
- finance dry run
- rollback rehearsal
- no fallback

# 250. HR15-S13 最终封板

- six workspaces green
- Decimal green
- rules green
- monthly close green
- retro green
- statutory/tax green
- payment/finance green
- security green
- migration/reconcile green
- E2E/performance/observability/A11y/visual green

# 251. 附录｜工资项目分类冻结

建议默认展示但均可版本化：
- 岗位工资；
- 薪级工资；
- 基础绩效；
- 奖励绩效；
- 国家/地方津贴；
- 学校津贴；
- 人才津贴；
- 教学/岗位津贴；
- 加班/值班；
- 一次性奖金；
- 补发；
- 社保个人；
- 公积金个人；
- 个税；
- 其他经批准扣款；
- 追扣。

# 252. 附录｜事业编工资矩阵

`PayStandardVersion` 必须支持 category × appointment_level × salary_step × effective_date lookup；具体金额通过政策表导入/发布，不写代码。

# 253. 附录｜合同制工资

合同制可使用 agreement salary/grade/market band，但仍进入统一 PayrollResult/Tax/Statutory/Payment pipeline。

# 254. 附录｜外聘教师课酬

HR08 提供 VERIFIED workload/service；HR15 可按课时/项目/固定方式支付，但课时事实不由 HR15 自己生成。

# 255. 附录｜返聘人员

返聘可有独立 PayGroup、税务/社保/公积金资格，不能复制原退休前 profile。

# 256. 附录｜多用工关系

一个自然人可能多个 employment relationship；PayrollProfile 绑定关系，支付/税务合并口径按政策处理。

# 257. 附录｜发薪组织

同一学校可有不同法人/核算主体/项目资金；PayrollOrganization 独立于学院组织树。

# 258. 附录｜成本中心

ResultLine 可解析 cost center/fund/project；成本归集规则版本化，不让 HR15 成为完整总账。

# 259. 附录｜预算校验

可在 finalize 前调用 FinanceBudgetProvider 做 WARN/BLOCK，具体取决于学校 policy；预算不可用不得伪装充足。

# 260. 附录｜月中入职折算

proration divisor/working days/calendar days/standard days 均由规则版本决定，不存在唯一全国公式。

# 261. 附录｜月中离职折算

同理；HR16 effective final date 是事实输入，HR15 规则计算。

# 262. 附录｜请假扣款

病假/事假/旷工/产假等是否影响工资及如何影响由 RuleVersion 决定，HR11 只提供分类与时长事实。

# 263. 附录｜加班支付

HR11 仅提供 approved overtime；HR15 根据适用人员/制度决定补休、支付或不适用。

# 264. 附录｜值班津贴

值班事实来自相应 Authority；HR15 只算钱。

# 265. 附录｜教学工作量绩效

工作量事实来自教务/HR12等 Authority；HR15 不能用教师自己填的课时直接发钱。

# 266. 附录｜科研奖励

科研成果/奖励资格来自科研 Authority；HR15 只承接正式奖励决定，不自己认定科研成果。

# 267. 附录｜成果转化奖励

如纳入系统需独立 RewardDecisionProvider/政策，不能简单归为绩效工资；具体税务/总量口径由规则版本处理。

# 268. 附录｜专项人才津贴

人才资格来源 Authority；津贴规则有 start/end/annual review，资格撤销触发 review，不一定自动 clawback。

# 269. 附录｜薪级正常晋升

scheduler 只能创建候选 ChangeCase；是否晋级需政策条件与正式确认，不直接夜间 UPDATE。

# 270. 附录｜薪级暂缓

支持由于政策/考核导致 hold；hold 是事实 Case，不能删除应晋级记录。

# 271. 附录｜工资标准新版本

发布前必须 dry-run 全员 impact、总额、极端值和 retro 影响。

# 272. 附录｜政策追溯生效

必须生成 historical recompute + delta，不改原 final；同时计算税/社保/公积金差额。

# 273. 附录｜税务年度边界

12月→1月累计 ledger reset/new year；bonus/retro 属于哪个 tax year 必须规则明确。

# 274. 附录｜多次发薪

同月正常工资 + 补发/奖金可多个 payment run，但税务 cumulative ledger 必须一致、幂等。

# 275. 附录｜负税额

累计预扣计算本期出现负值时按适用税法处理；系统用 TaxRuleVersion，不擅自自动退款。

# 276. 附录｜年终汇算边界

HR15 做扣缴与年度汇总/证明，不代替个人年度汇算税务机关流程。

# 277. 附录｜专项附加扣除隐私

不得在 HR 列表展示子女、老人、住房贷款等家庭信息；只暴露 payroll calculation 必要汇总。

# 278. 附录｜社保基数来源

可基于上年度工资等当地规则计算，必须保存 source payroll periods、计算值、cap 后值和政策版本。

# 279. 附录｜公积金基数来源

同样保存 source、年度、当地上下限、ratio；年度调整不重写历史。

# 280. 附录｜跨地区调动

HR06/HR03 jurisdiction change → social/housing transfer review；新旧地区 policy version 独立。

# 281. 附录｜支付账户截止日

cutoff 后换卡：当前 batch 保持 frozen account snapshot；新卡从下个/指定批次生效。

# 282. 附录｜支付文件总额守恒

PaymentBatch total 必须等于 included FINAL result net/selected delta；文件 row sum 二次校验。

# 283. 附录｜重复支付防护

provider reference + result payment status + idempotency；支付成功后 retry 不得再次付款。

# 284. 附录｜支付未知状态

网络超时后 `UNKNOWN`，先 query/reconcile，不直接重发。

# 285. 附录｜银行退票

成功后退回需独立 ReturnedPaymentCase；不修改 PayrollResult。

# 286. 附录｜财务平衡

PostingPackage debit total = credit total；不平不得提交。

# 287. 附录｜财务科目版本

会计科目变化只影响新 PostingPackage；旧凭证映射保留。

# 288. 附录｜支付与财务时序

学校可配置先过账后支付或反之；State Machine 不假设单一路径。

# 289. 附录｜工资条重发

模板修复可生成 PayslipDocumentVersion V2，但工资数字引用相同 FINAL result。

# 290. 附录｜工资结果更正

已 FINAL 只能通过 Reverse/Delta/CorrectionCase，不直接 edit line。

# 291. 附录｜工资争议

员工提出工资异议 → PayrollInquiryCase → evidence/review → correction/retro if upheld；原工资保留。

# 292. 附录｜人工成本

EmployerCost = gross + employer statutory + other employer cost；与 employee net 分离。

# 293. 附录｜工资总额统计

统计口径通过 MetricDefinitionVersion；哪些项目计入工资总额不可在前端随意相加。

# 294. 附录｜敏感导出审批

含完整银行卡/税号的导出需专门权限、reason、审批/二次确认、短 TTL、audit。

# 295. 附录｜工资数据最小化

学院/负责人可以看到预算/总额/分布等授权聚合，不默认看到个人明细。

# 296. 附录｜离职欠款

若 recovery 未完成，HR15 输出 SettlementOutstanding；HR16 只消费状态，不在 HR16 自算。

# 297. 附录｜死亡/特殊结算

需单独 SettlementPolicy/authorized beneficiary/payment workflow，不把账户继承规则硬编码。

# 298. 附录｜冻结工资

司法/行政/内部合规冻结仅 formal PaymentHoldCase；不删除应发工资结果。

# 299. 附录｜Payment Hold

hold 影响支付，不一定影响 payroll calculation；解除后可重新进入支付批次。

# 300. 附录｜工资期间日历

PayCalendarVersion 定义 cutoff、review、pay date、holiday shift rule；节假日调整需版本化。

# 301. 附录｜支付日遇节假日

提前/顺延由 PayCalendarVersion，不写死。

# 302. 附录｜工资批次补跑

只对 failed/unprocessed subjects；不得重算已 FINAL 全员后覆盖。

# 303. 附录｜月结 Checklist

Population/Input/Rules/Tax/Statutory/Validation/Review/Approval/Archive/Outbox 全绿才 close。

# 304. 附录｜月结签名快照

CloseSnapshot 保存 approvers、totals、hash、rule versions、source snapshot hashes、engine version。

# 305. 附录｜Payroll Hash

每人 ResultHash + period AggregateHash；便于对账和审计篡改检测。

# 306. 附录｜Reconciliation 优先级

P0：支付金额不符/重复支付/跨租户；P1：申报差异/财务未过账；P2：非金额元数据差异。

# 307. 附录｜灾难恢复

数据库恢复后需重建 Outbox/Payment status/Reconciliation，不允许凭“文件已生成”推断外部状态。

# 308. 附录｜审计抽样

随机 30 个工资结果反向重建：profile→sources→rules→lines→tax/statutory→final→payment→posting→receipt。

# 309. 附录｜历史 as-of

查询 2024-10 工资必须使用当期 profile/rule/source，不用 2026 当前岗位/税参数重算显示。

# 310. 附录｜Shadow Payroll

Authority 切换前至少若干周期对比 legacy vs HR15：employee-level line、gross、net、tax、statutory、totals；差异分类解释。

# 311. 附录｜容差规则

对账容差仅用于历史 Float/外部机构舍入，必须可配置并有 reason；新 HR15 自身不以容差掩盖错误。

# 312. 附录｜上线后七日监控

每天检查 calc failures、large variance、period blockers、payment status、filing reject、finance reject、drift、403/IDOR、legacy writes。

# 313. 附录｜商业化验收

- 人事/财务可以不改代码配置一套学校薪资项目和规则
- 岗位聘任变化能自动产生薪酬复核而不是直接改钱
- 每笔工资可解释
- 月结后历史不可篡改
- 追溯调资产生差额而不是重写历史
- 社保公积金按地区/年度规则版本化
- 个税累计预扣可追溯
- 工资条与银行支付/财务凭证可对账
- 敏感数据权限经得起审计
- 能处理1万人员月薪批算与失败恢复

# 314. 最终封板条件

## 业务
- 6 个三级模块闭环；
- 薪酬档案 effective-dated；
- PayItem/RuleVersion；
- 月度计算/复核/月结；
- 绩效/调资/津贴/奖金；
- Retro/补发/追扣；
- 社保/公积金；
- 个税；
- 工资条；
- 银行支付；
- 财务/申报/对账；
- 离职结算。

## 数据
- 所有金额 Decimal；
- InputSnapshot；
- RuleVersion；
- ResultLine source refs；
- Final immutable；
- Tax YTD ledger；
- Statutory policy version；
- Payment/Posting/Receipt；
- Retro Delta；
- as-of；
- Legacy drift 可解释。

## 安全
- tenant；
- payroll-specific scope；
- bank/tax encryption；
- SELF payslip；
- SoD；
- export；
- signed URL；
- audit；
- no sensitive logs。

## 工程
- transactions；
- idempotency；
- optimistic lock；
- Outbox/Inbox；
- async jobs；
- provider fail-closed；
- MySQL concurrency；
- deterministic calculation；
- Formula sandbox；
- observability；
- migration/rollback。

## 前端
- 六工作区；
- 本人工资条；
- readiness；
- rules simulator；
- monthly close workbench；
- variance/risk；
- retro；
- statutory；
- payments/reconciliation；
- 375/768/1280/1440；
- Accessibility；
- Visual Regression。

只有全部满足：
```text
HR15 READY FOR ACCEPTANCE
```

否则：
```text
HR15 NOT READY
blocking:
- ...
```

# 315. 最终架构冻结图

```text
HR03 Staff/Employment ─────┐
HR14 Appointment ──────────┤
HR12 Assessment ───────────┤
HR11 Closed Time ──────────┤
HR07 Contract Facts ───────┤
HR05 Bank Setup ───────────┤
HR16 Exit Facts ───────────┘
                           ▼
                    PayrollProfile
                           │
                           ▼
        PayStandard / PayItem / RuleVersion
                           │
                           ▼
                     PayrollPeriod
                           │
                           ▼
                    InputSnapshot
                           │
                           ▼
                   CalculationRun
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Earnings      Statutory       Tax
             └─────────────┼─────────────┘
                           ▼
                     PayrollResult
                           │
                    Review / Final
                           │
        ┌──────────────────┼───────────────────┐
        ▼                  ▼                   ▼
     Payslip           PaymentBatch       PostingPackage
                           │                   │
                           ▼                   ▼
                       Bank/Treasury        Finance
                           │                   │
                           └─────────┬─────────┘
                                     ▼
                              Reconciliation

Social/Housing Filing ───────────────┤
Tax Filing ──────────────────────────┤
                                     ▼
                                 HR18 Report

Retro:
Source Revision → RetroImpact → Recalculate Historical Expected
→ Delta Payroll → Pay/Recover → Reconcile
```

# 316. 外部官方依据

S0 必须再次核验最新政策、目标省市的社保/公积金参数及目标学校现行薪酬办法。

当前设计基线至少包括：

1. 《事业单位人事管理条例》  
   第七章明确事业单位工资包括基本工资、绩效工资和津贴补贴，并要求工资分配结合岗位职责、工作业绩、实际贡献等因素。  
   官方公开版本可从国务院/部门政府信息公开渠道复核。

2. 教育部 2019 年关于高校教师薪酬的公开答复  
   明确包括高校在内的事业单位实行岗位绩效工资制度，基本工资包括岗位工资和薪级工资，绩效工资在核定总量内由学校按规范程序自主分配。  
   https://www.moe.gov.cn/jyb_xxgk/xxgk_jyta/jyta_rss/201912/t20191206_411111.html

3. 《中华人民共和国社会保险法》（2018 年修正）  
   覆盖基本养老、基本医疗、工伤、失业、生育等制度。  
   https://www.npc.gov.cn/zgrdw/npc/xinwen/2019-01/07/content_2070267.htm

4. 《住房公积金管理条例》（2019 年第二次修订）  
   事业单位及其在职职工属于适用主体之一。  
   https://xzfg.moj.gov.cn/front/law/detail?LawID=1221

5. 国家税务总局公告 2018 年第 61 号《个人所得税扣缴申报管理办法（试行）》  
   工资薪金对居民个人按累计预扣法计算预扣税款。  
   https://fgk.chinatax.gov.cn/zcfgk/c100012/c5194838/content.html

6. 国家税务总局公告 2020 年第 13 号  
   对年度中间首次取得工资薪金等部分纳税人完善累计减除费用预扣方法。  
   https://fgk.chinatax.gov.cn/zcfgk/c100012/c5194937/content.html

7. 国发〔2023〕13号  
   调整三岁以下婴幼儿照护、子女教育、赡养老人三项专项附加扣除标准，说明税务参数必须 effective-dated/versioned。  
   https://fgk.chinatax.gov.cn/zcfgk/c102440/c5213594/content.html

8. 财政部 税务总局公告 2023 年第 30 号  
   全年一次性奖金相关个人所得税政策延续执行至 2027-12-31；因此 HR15 不得把该模式永久硬编码。  

原则：
**国家/地方政策进入 Tax/Statutory/PayStandard Version；学校内部制度进入 CompensationRuleVersion；任何政策变化不回写历史 payroll。**

# 317. 编码 AI 首条执行指令

```text
你现在施工 HR15 薪酬福利。

唯一权威事实源：
15_HR15_薪酬福利_施工总册_终极版.md

强制先执行 HR15-S0：

1. 读取 penghaibin9/renshi 最新目标分支真实代码；
2. 完整审计 payroll/models、payroll/methods、payroll/forms、payroll/dashboard、payroll/scheduler、payroll/reports，以及 employee/base/attendance/leave/documents/audit/notifications；
3. 搜索 Contract.wage、EmployeeWorkInformation.basic_salary、Allowance、Deduction、Payslip、FilingStatus、TaxBracket、FloatField、python_code、payment/export 等；
4. 读取 HR03/HR05/HR07/HR08/HR11/HR12/HR14/HR16/HR18 已冻结 Provider/Authority 合同；
5. 物化 HR15_GAP_MATRIX、LegacyPayrollMapping、LegacyPayrollTrustMatrix、PayrollAuthorityBoundary、PayrollMoneyPrecisionPlan、PayrollRuleMigrationMatrix、PayrollTaxPolicyMatrix、PayrollStatutoryPolicyMatrix、PayrollProviderMatrix、PayrollSensitiveDataMatrix、HR15_PERMISSION_MATRIX、HR15_INTEGRATION_MATRIX、HR15_TASK_TREE、HR15_RISK_REGISTER、HR15_MIGRATION_PLAN；
6. 核验目标省市当前社保、公积金、个税及目标学校工资/绩效/津贴制度；
7. S0 只审计和落计划，不大改业务代码；
8. S0 后严格按 S1→S13 施工；
9. 所有正式金额迁移为 Decimal，禁止 Float 作为新 Authority；
10. arbitrary python_code 退出正式薪资规则路径，改为受控 DSL；
11. 月结结果 immutable，追溯必须 Delta；
12. HR11 只消费 closed facts，不读 raw punch；
13. HR12/HR14 只提供正式结果，不直接等于工资金额；
14. Tax/Social/Housing policy 全部 versioned，不硬编码地区当前参数；
15. Payment generated != paid；filing generated != accepted；posting generated != posted；
16. Provider failure fail-closed，不 silent fallback；
17. 不关闭 403 修测试；
18. MySQL 全量回归必须绿；
19. 不合并 main，不部署生产。

最终只有 HR15 六模块、Decimal、RuleVersion、月度月结、Retro、社保公积金、个税、支付、财务、对账、敏感安全、迁移、MySQL 并发、E2E、性能、可观测性、Accessibility、Visual Regression 全部绿色，才能输出：

HR15 READY FOR ACCEPTANCE
```

# 318. DoD｜HR15-01

- PayrollProfile
- PayGroup
- Scheme
- payment account encryption
- tax profile
- social/housing profile
- effective history
- readiness
- self view
- tenant/security

# 319. DoD｜HR15-02

- PayItem
- StandardVersion
- Rule DSL
- no eval
- phase graph
- tax/social attributes
- performance/allowance/bonus
- simulator
- publish immutable
- policy tests

# 320. DoD｜HR15-03

- Period
- population/input freeze
- calculation
- validation
- variance
- review
- approval
- finalize
- close snapshot
- retro
- final settlement

# 321. DoD｜HR15-04

- position pay impact
- salary step
- policy adjustment
- performance pool
- allowance lifecycle
- bonus
- manual adjustment controls
- recovery
- conflict

# 322. DoD｜HR15-05

- jurisdiction
- social policy
- housing policy
- bases
- enrollment/stop
- filing
- receipt
- retro contribution
- reconciliation
- self rights

# 323. DoD｜HR15-06

- payslip projection
- secure delivery
- payment batch
- bank receipt
- finance posting
- tax filing
- three-way reconcile
- period reconcile
- archive

# 324. 上线闸门｜敏感数据

- field encryption
- key rotation
- masked UI
- restricted export
- access audit
- no logs
- signed URL
- SELF only
- break-glass

# 325. 上线闸门｜支付

- maker-checker
- idempotency
- unknown-state query
- partial retry
- duplicate payment prevention
- receipt reconcile
- returned payment

# 326. 上线闸门｜税务

- cumulative ledger
- rule version
- special deductions privacy
- bonus policy expiry
- receipt
- correction
- year boundary

# 327. 上线闸门｜社保公积金

- local policy version
- base cap
- employer/employee sides
- filing receipt
- retro
- jurisdiction change
- reconcile

# 328. 上线闸门｜财务

- balanced posting
- GL version
- cost center
- provider receipt
- repost idempotency
- period matching
- total reconcile

# 329. 上线闸门｜迁移

- Float normalization
- historical source preservation
- old contract wage decouple
- old tax no authority
- shadow compare
- write freeze
- rollback

# 330. 上线闸门｜MySQL

- Decimal
- row lock
- deadlock retry
- period finalize lock
- tax ledger concurrency
- payment uniqueness
- indexes
- migration rollback

# 331. 业务角色验收

- 工资员
- 复核员
- 人事负责人
- 财务出纳/会计
- 教师本人
- 学院负责人负向
- 平台运维负向
- 离职人员 final settlement

# 332. 终极异常演练

- HR14 provider down
- HR11 close missing
- bank timeout after accepted
- tax receipt delayed
- social partial reject
- finance posting rejected
- outbox lag
- DB restore
- payment file corrupt
- cross-tenant attack

# 333. 最终商业体验

教师本人只需要理解：
“本月应发什么、扣了什么、实发多少、补发/追扣为什么、是否已支付”。

工资员需要理解：
“谁档案没准备好、哪些输入缺失、哪些工资波动异常、哪些规则生效、月结是否能关”。

财务需要理解：
“总额是否一致、银行是否成功、凭证是否过账、税社保公积金是否申报并对账”。

系统必须把复杂性收在规则和事实链里，而不是让学校工作人员靠 Excel 和人工记忆兜底。

# 334. 最终封板口径再次冻结

仅当 HR15-S0→S13、六个三级模块 DoD、所有金额 Decimal、规则 DSL、安全、多租户、月结、Retro、社保公积金、个税、银行支付、财务、正式回执、三方对账、Legacy/Shadow/MySQL/E2E/性能/可观测性/Accessibility/Visual Regression 全部绿色，且无 P0/P1 阻塞，才允许：

```text
HR15 READY FOR ACCEPTANCE
```

否则只能：

```text
HR15 NOT READY
blocking:
- <精确缺口>
```

禁止“基本可用”“先上线后补”“工资差一点没关系”。
