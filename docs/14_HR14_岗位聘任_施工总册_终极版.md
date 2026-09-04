# 14_HR14_岗位聘任_施工总册（终极冻结版）

> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、API（`/api/v1/hr`）、数据库目标（MySQL-only）、事件（canonical `PositionAppointmentEffective`，废除模糊 `AppointmentEffective`）、权限、Legacy、审计、安全和最终生产 Gate。

> 产品：跃科高校人事管理与教师发展系统  
> 二级模块：HR14 岗位聘任  
> 三级模块数量：6  
> 总体策略：NEW（复用 HR02 岗位/编制 Authority、HR03 人员任职事实、HR12 考核、HR13 职称、Horilla 权限/文件/通知/审计/通用评议能力；岗位聘任 Authority 新建）  
> 版本：V1.0 终极冻结版  
> 文档性质：HR14 唯一权威施工事实源；可直接整份交给编码 AI 执行“Horilla/HR02/HR03 当前岗位与任职基线复审 → 岗位聘任制度与等级规则 → 岗位额度/结构比例/空岗 → 聘任批次 → 申报竞聘 → 资格审查 → 评议/评审/排序 → 拟聘与公示 → 正式聘任 → HR03 Assignment 生效 → HR15 薪酬复核 → 聘期变更/解聘/低聘/高聘/续聘 → 历史档案 → Legacy Projection → 双读对账 → 安全/并发/E2E → Authority 切换”的生产级施工。  
> 适配底座：Horilla HRMS 2.0（当前 `penghaibin9/renshi` 基线；S0 必须以目标分支真实代码再次核验）  
> 前置标准：继承《01_HR01》至《13_HR13》终极版的 A0 多学校 fail-closed、API 版本化、统一错误信封、公共 UI、权限/数据范围、文件安全、敏感字段、异步任务、审计、可观测性、Excel、幂等、事务、Outbox、规则/模板版本冻结、Legacy 退出和 AI 施工纪律。  
> 强依赖：HR02 提供组织、岗位目录、岗位实例、编制/职数、结构比例与空岗；HR03 提供 Person/Staff/EmploymentRelationship/Assignment 并接收 HR14 正式生效的岗位任职事实；HR12 提供年度/聘期正式考核结果；HR13 提供正式职称结果；HR15 负责岗位相关工资/津贴/薪级的实际计算与支付；HR06 负责人事异动但不得替代专业技术岗位等级聘任；HR16 负责离退/离校闭环；HR18 负责正式统计与上报。  
> 编写日期：2026-08-08  
> 核心原则：**岗位存在 ≠ 人已被聘任；职称取得 ≠ 岗位聘任；资格审查通过 ≠ 获得岗位；专家评议 ≠ 正式聘任决定；聘任结果 ≠ 自动涨薪；岗位变动 ≠ 静默覆盖 HR03 历史。HR14 必须把“岗位供给—结构比例—批次—申报—资格—评议—择优—公示—正式聘任—生效—变更/终止—历史档案”做成可追溯事实链。**
# 0. 六个三级模块冻结

```text
HR14 岗位聘任
├─ HR14-01 聘任制度与岗位等级
├─ HR14-02 岗位额度与聘任批次
├─ HR14-03 申报竞聘与资格审查
├─ HR14-04 评议评审与择优排序
├─ HR14-05 拟聘公示与正式聘任
└─ HR14-06 聘期变更与聘任档案
```

职责严格分离：

- **HR14-01 聘任制度与岗位等级**：岗位类别、等级、资格条件、结构比例规则、竞聘方式、优先规则、聘期规则、转聘/高聘/低聘/续聘规则和版本。
- **HR14-02 岗位额度与聘任批次**：读取 HR02 岗位供给与结构比例，形成可竞聘岗位额度、批次、适用人群、时间表和冻结快照。
- **HR14-03 申报竞聘与资格审查**：个人/组织申报、诚信承诺、资格预检、学院/学校审核、退回补正、资格不通过、撤回。
- **HR14-04 评议评审与择优排序**：业绩证据引用、专家/评委、答辩/述职、评分/排序/投票、同岗竞争、同等条件处理和拟聘建议。
- **HR14-05 拟聘公示与正式聘任**：拟聘名单、岗位占用预占、公示、异议、集体审定、正式聘任、聘任文书、HR03 Assignment 生效与 HR15 handoff。
- **HR14-06 聘期变更与聘任档案**：聘期台账、到期、续聘衔接、岗位变更、低聘/高聘/解聘、撤销/更正、历史档案、as-of 和监管风险。

# 1. 结论先行

HR14 不是“把 JobPosition 改成副高五级”。

真正生产级事实链：

```text
HR02 Organization / Position / Quota / Structure Ratio
                        │
                        ▼
             Appointment Policy Version
                        │
                        ▼
              Appointment Batch Snapshot
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
      Available Positions      Eligible Population
            │                       │
            └───────────┬───────────┘
                        ▼
                  Application
                        │
                        ▼
               Eligibility Review
                        │
                        ▼
        Evidence / HR12 / HR13 / HR03
                        │
                        ▼
              Review / Ranking / Vote
                        │
                        ▼
                 Proposed Offer
                        │
                        ▼
                    Publicity
                        │
                        ▼
              Collective Final Decision
                        │
                        ▼
             Appointment Agreement/Term
                        │
                        ▼
               Effective Appointment
                        │
           ┌────────────┼──────────────┐
           ▼            ▼              ▼
          HR03         HR15           HR18
      Assignment    Compensation    Reporting
```

HR14 必须回答：
1. 这个岗位是谁批准存在的？
2. 该等级可聘多少人？
3. 当前已聘多少、空多少、结构比例是否允许再聘？
4. 这轮竞聘使用哪个制度版本？
5. 谁可以申请、谁不能申请，原因是什么？
6. 职称是资格条件还是自动聘任？——只能是前者。
7. 年度/聘期考核如何作为证据输入？
8. 同一岗位多人竞争时如何排序、如何留痕？
9. 评议/评分/票决是什么关系？
10. 拟聘后是否占用岗位额度，何时正式占用？
11. 公示异议如何阻断生效？
12. HR03 什么时候生成新的 Assignment？
13. HR15 什么时候开始计算岗位工资变化？
14. 聘期到期、续聘、低聘、解聘如何保留历史？
15. 今天改聘任规则会不会污染两年前的聘任历史？

# 2. 生产级红线

- 不得把 `EmployeeWorkInformation.job_position` 直接当 HR14 聘任权威。
- 不得把 HR02 Position 的 incumbent 字段当聘任评审过程。
- 不得 HR13 职称通过后自动生成 HR14 Appointment。
- 不得 HR12 年度优秀自动等于岗位晋级。
- 不得把岗位额度只做前端提示，后端无并发控制。
- 不得在结构比例已满时仍静默新增聘任。
- 不得用一个 `grade` 字段表达岗位类别、职称、职级、岗位等级和工资等级。
- 不得把专业技术岗位一至十三级与职称等级混为同一枚举。
- 不得把管理岗位等级与专业技术岗位等级混成同一规则表而无类型。
- 不得把工勤技能等级硬套专业技术岗位规则。
- 不得把所有高校岗位竞聘都写死为同一评审流程。
- 不得把单位当前政策写死在 Python if/else。
- 不得批次发布后静默改资格条件、结构比例、评分或公示规则。
- 不得申报人自己审核自己。
- 不得学院管理员跨学院审查。
- 不得把 RETURNED 与 REJECTED 混为一个状态。
- 不得资格不满足时通过前端隐藏按钮绕过。
- 不得用附件数量替代业绩质量。
- 不得在 HR14 复制 HR12/HR13 正式结果。
- 不得从教务/科研实时当前值重算历史竞聘而无 snapshot。
- 不得专家评分直接变成最终聘任结果。
- 不得平均分最高者必然自动聘任而无制度依据。
- 不得同分处理无明确规则。
- 不得手工排序后不记录原因。
- 不得公示未结束就生效。
- 不得公示异议存在时自动生效。
- 不得拟聘即写 HR03 正式 Assignment。
- 不得正式聘任后原地 UPDATE 历史结果。
- 不得聘任变更后删除旧聘期。
- 不得解聘岗位就删除人员。
- 不得 HR14 直接停用登录账号。
- 不得 HR14 直接修改 HR07 合同正文。
- 不得 HR14 直接算 HR15 工资金额。
- 不得跨 tenant 预占同一岗位。
- 不得后台任务不带 tenant。
- 不得平台运营默认查看学校竞聘材料。
- 不得正式文书用公开裸 URL。
- 不得 Excel 直接创建 EFFECTIVE Appointment。
- 不得批量导入直接覆盖 HR03 Assignment。
- 不得 Provider unavailable 时 fallback legacy 并冒充 OK。
- 不得把 UNAVAILABLE 当 0、PASS 或“无问题”。
- 不得 mock 评审/岗位额度冒充生产事实。
- 不得 AI 自动决定谁应该被聘任。
- 不得 AI 自动生成评委意见、排名理由或集体决定。
- 不得为修测试关闭 403、放宽 data scope。
- 不得跳过 migration/reconciliation/concurrency/E2E。
- 不得施工阶段直接合并 main。

# 3. 国家岗位设置制度层级

HR14 的制度来源必须分层：

```text
National Institution Position Baseline
        ↓
Education-sector Guidance
        ↓
Province / Local Implementation
        ↓
University Position Appointment Policy
        ↓
Category / Level / Track Rule Version
        ↓
Batch Snapshot
```

产品内置“能力模板”，不内置某省某校永恒数值。

# 4. 事业单位三类岗位边界

高校岗位至少支持：
- 管理岗位；
- 专业技术岗位；
- 工勤技能岗位。

每类岗位有独立等级体系、资格条件、结构比例和聘用规则。
系统不能用一个 `job_grade` 全部表达。

# 5. 专业技术岗位 13 级模型

事业单位专业技术岗位通常划分 13 个等级：
- 高级：1–7；
- 中级：8–10；
- 初级：11–13。

其中正高/副高映射、最高等级、结构比例等必须由制度/行业/地方/学校 RuleVersion 决定。
不得把“教授=四级、副教授=七级”之类映射写死为全国唯一规则。

# 6. 结构比例控制

HR14 必须读取 HR02 已核准岗位结构比例与岗位供给。
需要同时判断：
- 岗位总量；
- 类别总量；
- 高/中/初比例；
- 细分等级比例；
- 已占用；
- 已预占；
- 本批次可用额度；
- 特设岗位/政策例外。

比例不足或额度为 0 时必须 fail-closed 或走正式 ExceptionCase。

# 7. 高校岗位设置指导边界

高校岗位设置需结合：
- 教学科研任务；
- 学科建设；
- 人才培养；
- 队伍结构；
- 学校层次和定位；
- 岗位职责任务。

岗位设置属于 HR02；岗位具体聘用过程属于 HR14。

# 8. 民主公开竞争择优

HR14 必须支持：
- 公开岗位；
- 明确条件；
- 个人申报/组织推荐；
- 资格审查；
- 评议或竞聘；
- 择优；
- 拟聘公示；
- 正式决定；
- 申诉/异议；
- 全程留痕。

具体环节由学校 PolicyVersion 决定。

# 9. Workday Position Management 启发

吸收成熟 HCM 的关键思想：
- Position 先于 incumbent；
- 必须存在已批准 position 才允许 staffing；
- position 有独立限制/规则；
- 人离开后 position 仍存在；
- position history 与 worker history 分离。

转化为跃科：
HR02 = position supply authority；
HR14 = appointment decision process；
HR03 = effective worker assignment facts。

# 10. SAP Position Management 启发

吸收：
- position independent from employee；
- planned FTE / vacancy；
- incumbent/previous incumbent；
- position organization chart；
- position-level controls；
- position to job information sync。

但高校 HR14 在此基础上增加：
- 结构比例；
- 专技岗位等级；
- 竞聘批次；
- 评议/排序；
- 公示；
- 聘期；
- 监管。

# 11. HR02 边界

HR02 权威：
- Organization；
- PostCatalog；
- Position；
- PositionQuota/Headcount；
- StructureRatio；
- position history。

HR14：
- 读取“可聘岗位池”；
- 不创建第二套 Position；
- 竞聘前可 reserve；
- 正式生效后确认 consume；
- 释放/撤销 reservation；
- 不修改 HR02 历史。

# 12. HR03 边界

HR03 权威：
- Person；
- StaffMaster；
- EmploymentRelationship；
- Assignment；
- 任职历史。

HR14 正式生效后发送：
`PositionAppointmentEffective`
→ HR03 关闭/调整旧 Assignment（按业务类型）
→ 创建新 Assignment / Position occupancy fact。

HR14 不直接 UPDATE HR03 表。

# 13. HR06 边界

HR06 管一般人事异动：
- 学院调动；
- 部门变化；
- 普通岗位变化；
- 临时借调等。

HR14 管：
- 专业技术岗位等级聘任；
- 正式竞聘；
- 岗位等级晋升/低聘；
- 需要聘任程序的岗位结果。

若 HR14 生效导致组织变化，需协调 HR06/HR03，不允许两套流程并发覆盖。

# 14. HR07 边界

HR07 管劳动/聘用合同法律文书。
HR14 管岗位聘任决定和岗位聘期。

若学校需要“岗位聘用协议/聘任书”：
- HR14 owns business decision / term / duties snapshot；
- Agreement/Document provider owns formal document body/signature/version；
- HR07 是否承接由系统统一 AgreementProvider 决定。

不要复制合同引擎。

# 15. HR12 边界

HR14 可读取：
- FinalAssessmentResult；
- AnnualResultHistory；
- TermResult；
- VerifiedPerformanceEvidence refs。

HR14 不修改 HR12。
聘期到期是否续聘/低聘可把 HR12 结果作为证据之一，但最终仍由 HR14 Policy + 正式程序决定。

# 16. HR13 边界

**职称 ≠ 岗位聘任。**

HR13 输出：
- ProfessionalTitleResult；
- series/level/title；
- effective_date；
- status。

HR14 把 HR13 结果作为资格/优先条件之一。
取得副教授但无副高岗位 → 不自动聘副高。
HR13 撤销时 → HR14 创建 AppointmentReviewRequired，不直接自动解聘。

# 17. HR15 边界

HR14 输出：
- effective appointment；
- position/level；
- appointment term；
- effective date；
- change reason；
- source policy。

HR15 决定：
- 岗位工资；
- 薪级；
- 津贴；
- 绩效工资；
- 追溯调整；
- 实际金额/支付。

HR14 不计算钱。

# 18. HR16 边界

离职/退休/离校会结束或影响岗位聘任。
HR16 负责离退业务编排；
HR14 接收终止请求/生效事件并关闭 appointment term；
HR02 释放岗位；
HR03 关闭 Assignment。

HR14 不自己完成离校全流程。

# 19. HR18 边界

HR18 消费：
- 岗位类别/等级结构；
- 已聘/空岗；
- 竞聘批次；
- 晋级/低聘/解聘；
- 聘任历史；
- 结构比例完成情况。

正式报表按 as-of 和 MetricDefinitionVersion。

# 20. 岗位类别枚举

建议：
```text
MANAGEMENT
PROFESSIONAL_TECHNICAL
WORK_SKILL
SPECIAL
CUSTOM
```

实际名称/映射以学校 RulePack 为准。

# 21. 聘任业务类型

```text
INITIAL_APPOINTMENT
COMPETITIVE_APPOINTMENT
LEVEL_PROMOTION
LEVEL_ADJUSTMENT
HIGHER_APPOINTMENT
LOWER_APPOINTMENT
TRANSFER_APPOINTMENT
REAPPOINTMENT
RENEWAL
SPECIAL_POSITION
CORRECTION
REVOCATION
```

# 22. 岗位占用状态

```text
AVAILABLE
RESERVED
OFFERED
OCCUPIED
SUSPENDED
RELEASING
CLOSED
```

HR02 Position 为根，HR14 只管理本轮 reservation/appointment usage。

# 23. 聘任申请状态

```text
DRAFT
SUBMITTED
ORG_REVIEW
RETURNED
REJECTED
SCHOOL_REVIEW
ELIGIBLE
INELIGIBLE
UNDER_REVIEW
RANKED
PROPOSED
PUBLICITY
FINALIZED
EFFECTIVE
WITHDRAWN
CANCELLED
SUSPENDED
SUPERSEDED
```

# 24. 批次状态

```text
DRAFT
CONFIGURING
PUBLISHED
APPLICATION_OPEN
APPLICATION_CLOSED
ELIGIBILITY_REVIEW
REVIEWING
RANKING
PROPOSED
PUBLICITY
FINALIZING
CLOSED
ARCHIVED
```

# 25. 聘任结果状态

```text
PROPOSED
PUBLICITY
FINAL
EFFECTIVE
EXPIRED
TERMINATED
SUPERSEDED
REVOKED
```

# 26. 证据可信度

统一继承：
`AUTHORITY_VERIFIED / PROVIDER_VERIFIED / DOCUMENT_VERIFIED / MANUAL_VERIFIED / SELF_REPORTED / MIGRATED_VERIFIED / MIGRATED_UNVERIFIED / UNAVAILABLE / DISPUTED / REVOKED`。

# 27. 聘任期限模型

必须明确：
- fixed term；
- open-ended where policy allows；
- effective_from；
- effective_to；
- probation/assessment checkpoint；
- renewal_due_at；
- source policy；
- term revision history。

禁止用 `2099-12-31` 伪装长期聘任。

# 28. HR14-01 业务目标

建立“岗位等级—任职资格—竞聘方式—结构比例—聘期—变更”版本化制度中心。

# 29. AppointmentPolicyPack

`HrAppointmentPolicyPack`：
- tenant_id；
- name/code；
- category_scope；
- status；
- current_version_id；
- authority_source；
- owner_org。

# 30. AppointmentPolicyVersion

字段：
- version_no；
- effective_from/to；
- source_refs；
- category/level rules；
- eligibility rules；
- review flow；
- ranking rules；
- publicity rule；
- appointment term rule；
- change/termination rule；
- hash；
- published_at/by。

PUBLISHED 后 immutable。

# 31. 岗位等级目录

`HrAppointmentLevelDefinition`：
- category；
- grade/level code；
- display name；
- hierarchy order；
- national/local mapping；
- title prerequisites；
- management grade mapping；
- valid_from/to。

岗位等级与职称等级必须独立。

# 32. 资格规则

支持：
- HR13 职称；
- HR03 学历/资历；
- 任职年限；
- 现岗位等级年限；
- HR12 考核；
- 师德；
- HR09 资格；
- HR10 企业实践/培训；
- mandatory training；
- disciplinary restriction；
- special exception。

每条规则输出可解释 GateResult。

# 33. 结构比例规则

Policy 只描述“如何判断”，实际额度来自 HR02：
- category ratio；
- grade group ratio；
- exact level ratio；
- school/college scope；
- temporary/special quota；
- rounding rule；
- carryover rule；
- reserve policy。

# 34. 聘任路径规则

支持：
- 逐级晋升；
- 跨级例外；
- 平级转聘；
- 高职低聘；
- 低职高聘（如制度允许）；
- 特设岗位；
- 竞聘上岗；
- 组织聘任；
- 直接聘任例外。

任何 exception 必须 formal case。

# 35. 聘期规则

PolicyVersion 定义：
- term length；
- start boundary；
- renewal window；
- probation/checkpoint；
- midterm review link；
- early termination；
- post expiration grace；
- return/reversion semantics。

# 36. 排序规则

可配置：
- hard gates；
- weighted score；
- categorical review；
- ballot；
- composite；
- seniority tie-break；
- representative achievement tie-break；
- random tie-break（仅制度允许并需审计）；
- collective decision override。

禁止全系统硬编码唯一排序公式。

# 37. 同分/同条件规则

必须明确：
- tie status；
- additional review；
- second ballot；
- seniority；
- priority category；
- defer；
- additional quota request。

禁止工作人员手工拖拽排序后无理由。

# 38. 例外/特设岗位规则

`AppointmentExceptionCase`：
- policy clause；
- quota exception；
- candidate；
- reason；
- authority；
- approval；
- expiry；
- conditions；
- audit。

特设岗位不能成为绕过结构比例的万能开关。

# 39. Policy Simulator

输入：
staff + target position/level + as_of + hypothetical batch。

输出：
- quota availability；
- eligibility gates；
- current title；
- current appointment；
- minimum service；
- assessment；
- exception needed；
- source status。

Simulator 仅预检。

# 40. HR14-01 UI

```text
/hr/appointments/policies
/hr/appointments/levels
/hr/appointments/policies/{id}/versions
/hr/appointments/rules/simulator
```

复杂规则全页编辑；展示版本 diff 和生效日期。

# 41. HR14-02 业务目标

把 HR02 的岗位供给转成“这一轮实际可竞聘额度”，并在并发下不超占。

# 42. PositionSupplySnapshot

`HrAppointmentPositionSupplySnapshot`：
- batch_id；
- HR02 position ids；
- category/level；
- org；
- authorized headcount/FTE；
- occupied；
- reserved；
- available；
- structure ratio refs；
- snapshot_at；
- source version/hash。

# 43. Quota Pool

`HrAppointmentQuotaPool`：
- scope；
- category；
- level_group；
- exact_level；
- authorized；
- occupied；
- reserved；
- available；
- exception quota；
- version。

不能以一个“可聘人数”字段丢失结构比例层级。

# 44. 批次模型

`HrAppointmentBatch`：
- batch_no/name；
- business_type；
- policy_version_id；
- target categories/levels；
- position_scope；
- quota_snapshot；
- population snapshot；
- application window；
- review calendar；
- publicity rule；
- status；
- version/hash。

# 45. 批次冻结

PUBLISHED 时冻结：
- RuleVersion；
- PositionSupplySnapshot；
- quota/ratio；
- eligibility population；
- review workflow；
- ranking/tie rule；
- publicity；
- appointment term template。

后续 HR02 变化只产生 `SOURCE_CHANGED` 风险，不静默重写批次。

# 46. 岗位池模式

支持：
1. 指定单个 position 竞聘；
2. 同学院同等级 position pool；
3. 全校同系列/等级 quota pool；
4. 特设岗位；
5. 晋级额度池。

具体由学校制度决定。

# 47. 可聘额度计算

```text
available =
authorized capacity
- current effective occupancy
- active reservations
- protected capacity
+ approved temporary exception
```

计算必须带版本和 source status。

# 48. Reservation

`HrPositionReservation`：
- batch；
- position/quota pool；
- application/proposed appointment；
- units/FTE；
- reserved_at；
- expires_at；
- status；
- version。

数据库级并发控制，防止两人抢同一最后额度。

# 49. 批次适用人群

从 HR03 生成 PopulationSnapshot：
- active relationship；
- organization；
- personnel category；
- current appointment；
- title；
- service time；
- exclusions。

中途调岗不改变历史 snapshot，只产生 review task。

# 50. 批次时间表

Milestone：
- announce；
- application open/close；
- qualification；
- review；
- proposed list；
- publicity；
- final decision；
- effective date；
- document deadline。

每个 milestone 有 owner/status/alert。

# 51. 批次风险中心

风险：
- HR02 quota changed；
- structure ratio full；
- candidate shortage；
- over-reservation；
- policy conflict；
- unfinished HR12/HR13 dependency；
- publicity conflict；
- effective date position invalid；
- batch overdue。

# 52. HR14-02 UI

首屏：
- 本批次岗位总量；
- 可聘额度；
- 已申请；
- 合格；
- 拟聘；
- 预占；
- 剩余额度；
- 结构比例风险；
- 下一动作。

支持 drilldown 到具体 HR02 position/quota source。

# 53. HR14-03 业务目标

完成教师/职员竞聘申请、资格验证、组织审核和补正闭环。

# 54. Application

`HrAppointmentApplication`：
- batch；
- staff/person；
- target position/quota pool；
- target level；
- business_type；
- current appointment snapshot；
- title snapshot；
- assignment snapshot；
- policy snapshot；
- status；
- version。

# 55. 申请版本

补正生成 ApplicationVersion：
- form snapshot；
- evidence refs；
- target preference；
- applicant statement；
- created/submitted_at；
- reason；
- content hash。

旧版本不可覆盖。

# 56. 多岗位志愿

若制度允许一人多个岗位志愿：
- preference_no；
- target position；
- exclusive/parallel；
- acceptance strategy；
- lock rules。

禁止同一人最终同时占多个互斥岗位。

# 57. 诚信承诺

申请提交前必须记录模板版本、签署时间、内容 hash 和身份。

# 58. Eligibility Engine

Gate 来源：
- HR03 人事；
- HR13 职称；
- HR12 考核；
- HR09 资格；
- HR10 发展事实；
- current appointment/service；
- disciplinary/ethics provider；
- quota prerequisites。

任何硬依赖 UNAVAILABLE → 不得 PASS。

# 59. 现岗位任职年限

必须从 HR03/HR14 历史 effective-dated facts 计算：
- exact start；
- suspension；
- leave policy effect if any；
- prior equivalent appointment；
- correction history。

禁止 `today.year - start.year`。

# 60. 组织审核

学院/部门审核：
- 真实性初核；
- 工作表现/岗位需要意见；
- evidence；
- recommendation；
- reviewer；
- version；
- time。

组织推荐不等于最终资格。

# 61. 学校资格审核

人事/岗位管理部门执行：
- Rule Gate；
- quota compatibility；
- history；
- exceptions；
- decision；
- reason；
- policy clause；
- audit。

# 62. RETURNED vs REJECTED

RETURNED = 可补正；
REJECTED/INELIGIBLE = 本轮正式不通过。

必须有不同状态、权限、通知和统计。

# 63. 撤回

申请人在制度允许阶段可 WITHDRAW；不得 hard delete。

# 64. Late Supplement

截止后补材料必须有 privilege + reason + approval + fields scope + deadline + audit。

# 65. 批量资格预检

异步运行，逐人 GateResult，支持 preview/error workbook，不得一键全部合格。

# 66. HR14-03 UI

本人：
`/hr/appointments/me/applications`

后台：
`/hr/appointments/applications`
`/hr/appointments/eligibility`

申请详情必须显示“我为什么符合/不符合”，而不是只显示红叉。

# 67. HR14-04 业务目标

把多人竞聘的评议、打分、投票、排序和集体决定做成可解释、可审计的择优过程。

# 68. EvidenceSnapshot

进入评审前冻结：
- HR12 result refs；
- HR13 title refs；
- HR03 current/history；
- teaching/research evidence refs；
- applicant materials；
- organization recommendation；
- policy version；
- hash。

评委看 frozen snapshot。

# 69. 评审方式

支持：
- document review；
- structured scoring；
- peer review；
- defense/presentation；
- democratic evaluation；
- committee ballot；
- composite；
- collective deliberation。

流程由 PolicyVersion 配置。

# 70. Reviewer Assignment

评委/专家：
- internal/external；
- assigned scope；
- conflict check；
- confidentiality；
- voting right；
- role；
- task status。

可复用 HR13 专家基础服务，但 HR14 评审任务独立。

# 71. 回避

至少支持：
- 本人；
- 近亲属；
- 直接上下级；
- 同一竞争利益链；
- 其他制度规定冲突。

未清除冲突不得提交 review/ballot。

# 72. 评分 Rubric

RubricVersion：
- dimensions；
- scale；
- weights；
- hard gate；
- narrative required；
- normalization policy；
- missing value handling。

不允许发布后修改。

# 73. 评分锁定

评委提交后 immutable；需 `ReviewCorrectionCase` 才能重开，原记录保留。

# 74. 排序模型

`RankingRun` 保存：
- candidates；
- metric inputs；
- rule version；
- score components；
- tie rule；
- exclusions；
- output order；
- input hash；
- algorithm version；
- run_by/at。

排序是建议事实，不一定等于 final decision。

# 75. 同岗竞争

同一 position/quota group 下：
- candidates；
- capacity；
- eligible count；
- ranked count；
- proposed selected；
- waitlist/backup；
- not selected。

未被选中 ≠ 资格不合格。

# 76. 同分处理

严格执行 RuleVersion；任何人工 tie-break 必须 reason/authority/audit。

# 77. 票决

Ballot：
- session；
- application；
- voter；
- choice；
- submitted_at；
- secret flag；
- hash；
- version。

通过阈值/弃权/无效票由 DecisionRuleVersion 决定。

# 78. Quorum

会议开始前校验成员数量、回避后有效人数、外部成员比例、投票资格。

# 79. CollectiveDecision

集体决定可：
- ACCEPT；
- NOT_ACCEPT；
- DEFER；
- REMAND；
- WAITLIST；
- CONDITIONAL。

必须保存 decision basis、meeting refs、quota effect。

# 80. 拟聘建议

`ProposedAppointment`：
- application；
- target position；
- target level；
- term；
- proposed effective date；
- reservation_id；
- rank/decision refs；
- status。

此时仍不是 HR03 Assignment。

# 81. HR14-04 UI

工作台必须显示：
- competition group；
- quota；
- eligible candidates；
- evidence readiness；
- conflict；
- review completion；
- ranking；
- proposed selection；
- blocking reasons。

禁止前端一次加载全校全部候选材料。

# 82. HR14-05 业务目标

把拟聘、额度预占、公示、异议、正式决定和 HR03 生效做成原子且可回滚的闭环。

# 83. 拟聘名单

拟聘名单必须来自：
- valid collective decision；
- valid quota reservation；
- target position still active；
- eligibility still valid；
- no blocking case。

名单每次生成有 version/hash。

# 84. 岗位额度预占

进入拟聘时 reserve。
正式生效时：
`RESERVED → CONSUMED/OCCUPIED`。
未通过/撤回/超时：
`RESERVED → RELEASED`。

防止公示期同一额度被另一批次占用。

# 85. 拟聘公示

`AppointmentPublicity`：
- fields；
- scope；
- start/end；
- privacy redaction；
- snapshot；
- objection channel；
- proof。

不得公开不必要 PII、评委身份或敏感材料。

# 86. 公示异议

`AppointmentObjectionCase`：
- target proposed appointment；
- allegation；
- evidence；
- confidentiality；
- triage；
- investigation；
- status；
- finding；
- resolution。

OPEN blocking case 时禁止 finalize。

# 87. 集体最终审定

正式聘任前可配置：
- 校长办公会；
- 党委会；
- 人事工作领导机构；
- 授权委员会；
- 其他合法决策主体。

系统保存 DecisionAuthoritySnapshot，不硬编码组织名称。

# 88. Final Appointment Result

`HrAppointmentResult`：
- application；
- staff/person；
- HR02 position；
- category；
- level；
- term；
- effective_from/to；
- policy/batch；
- decision/publicity refs；
- status；
- version/hash。

FINAL/EFFECTIVE 后 immutable。

# 89. 聘任文书

可生成：
- 聘任通知；
- 岗位聘书；
- 岗位职责确认；
- 岗位聘用协议引用。

TemplateVersion + variables snapshot + document hash。

# 90. 生效前一致性检查

必须重新检查：
- Person active；
- EmploymentRelationship valid；
- HR02 Position valid；
- quota still reserved；
- no overlapping incompatible appointment；
- no HR16 planned termination；
- no blocking objection；
- title/qualification not revoked；
- effective date legal。

# 91. HR03 生效合同

调用 HR03 Provider：
```text
apply_appointment_effect(
  person/staff,
  current_assignment_ref,
  target_position,
  target_level,
  effective_from,
  appointment_result_ref
)
```

HR03 原子关闭/调整旧 Assignment、创建新事实。
HR14 保存 receipt，不直接写表。

# 92. HR15 handoff

生效事件：
`AppointmentEffective`
→ HR15 CompensationReevaluationRequested。

HR14 只提供岗位/等级/日期/政策，不提供金额。

# 93. HR02 handoff

生效后确认 position occupancy；
终止/失效后释放。
HR02 source of truth 仍是 position capacity。

# 94. 失败补偿

如果 HR14 Result FINAL 但 HR03 effect 失败：
- status `EFFECT_PENDING`；
- reservation 保留；
- retry/reconciliation；
- 不通知“已正式上岗”；
- 不触发 HR15 actual calculation。

# 95. 通知

通知：
- proposed；
- publicity；
- objection；
- final；
- effective；
- not selected；
- waitlist；
- effect failure/resolved。

模板版本化 + 去重。

# 96. HR14-05 UI

```text
/hr/appointments/proposed
/hr/appointments/publicity
/hr/appointments/results
/hr/appointments/effect-workbench
```

明确区分 PROPOSED / FINAL / EFFECTIVE。

# 97. HR14-06 业务目标

让岗位聘任结果进入长期聘期治理，而不是生效后只留下一个当前等级字段。

# 98. AppointmentTerm

`HrAppointmentTerm`：
- result_id；
- staff；
- position；
- level；
- effective_from/to；
- duties_snapshot；
- source policy；
- current status；
- renewal_due_at；
- version。

# 99. 聘期职责快照

可引用：
- HR02 position duties；
- 岗位目标；
- workload expectation；
- mandatory qualifications；
- assessment requirements。

发布后保留当时 snapshot。

# 100. 聘期考核边界

HR12 才做聘期考核。
HR14：
- 到期前请求 HR12 TermAssessment；
- 读取 Final TermResult；
- 按 HR14 RuleVersion 决定续聘/竞聘/低聘/解聘流程。

不得在 HR14 自己重新算考核。

# 101. 续聘

续聘不是改旧 term end_date：
`Old Term → RenewalCase → New AppointmentResult/Term`。
旧聘期保持历史。

# 102. 岗位等级晋升

需要新 Application/Review/Result；不得直接把 level 7 改成 level 6。

# 103. 高职低聘

若制度允许：
- title remains HR13 fact；
- appointment level is lower；
- reason；
- term；
- rights；
- notice；
- HR15 impact。

不得把 HR13 职称降级。

# 104. 低职高聘

若制度允许，必须 Exception/Rule evidence，HR13 title fact不被改写。

# 105. 平级转聘

跨岗位/学院转聘需协调 HR06/HR03；流程保留 source/target positions。

# 106. 解聘/终止

Appointment termination ≠ employment termination。
终止岗位聘任后：
- HR03 assignment impact；
- HR02 position release；
- HR15 review；
- 是否继续其他岗位/关系由 HR03/HR06/HR16 决定。

# 107. 暂停/保留岗位

长期离岗、借调、休假等是否保留 position/term 由 Policy 决定；不能在 HR14 自造 HR11 请假。

# 108. 结果更正

数据错误通过 CorrectionCase + ResultVersion；不改原 EFFECTIVE Result。

# 109. 结果撤销

若违规聘任需：
- Investigation/authority；
- Revocation；
- effective handling；
- downstream review；
- notice；
- archive。

撤销 ≠ delete。

# 110. 个人聘任历史

支持：
- 多岗位；
- 主岗/兼岗；
- 多聘期；
- 等级晋升；
- 平级转聘；
- 高职低聘；
- 低职高聘；
- 终止；
- 撤销；
- as-of。

# 111. 风险中心

风险：
- term expiring；
- HR12 term assessment missing；
- HR13 title revoked；
- position removed；
- quota drift；
- overlapping appointment；
- effect pending；
- HR15 ack missing；
- HR03 drift；
- publicity/legal hold case；
- legacy mismatch。

# 112. HR14-06 UI

```text
/hr/appointments/terms
/hr/appointments/history
/hr/appointments/renewals
/hr/appointments/changes
/hr/appointments/risk
```

复杂变更使用全页，不用通用右抽屉。

# 113. 核心模型总表

```text
HrAppointmentCategory
HrAppointmentLevelDefinition
HrAppointmentPolicyPack
HrAppointmentPolicyVersion
HrAppointmentEligibilityRule
HrAppointmentReviewRule
HrAppointmentRankingRule
HrAppointmentDecisionRule
HrAppointmentTermRule
HrAppointmentBatch
HrAppointmentMilestone
HrAppointmentPopulationSnapshot
HrAppointmentPositionSupplySnapshot
HrAppointmentQuotaPool
HrPositionReservation
HrAppointmentApplication
HrAppointmentApplicationVersion
HrAppointmentApplicantSnapshot
HrAppointmentIntegrityCommitment
HrAppointmentEligibilityEvaluation
HrAppointmentEligibilityGateResult
HrAppointmentEligibilityReview
HrAppointmentEvidenceRef
HrAppointmentEvidenceSnapshot
HrAppointmentReviewTask
HrAppointmentReviewerAssignment
HrAppointmentReview
HrAppointmentDefense
HrAppointmentRankingRun
HrAppointmentBallot
HrAppointmentCollectiveDecision
HrProposedAppointment
HrAppointmentPublicity
HrAppointmentObjectionCase
HrAppointmentResult
HrAppointmentTerm
HrAppointmentRenewalCase
HrAppointmentChangeCase
HrAppointmentCorrection
HrAppointmentRevocation
HrAppointmentDownstreamEffect
HrAppointmentArchivePackage
HrAppointmentRiskCase
```

# 114. Authority ID 与业务编号

内部稳定主键；外部 `batch_no/application_no/result_no/case_no` tenant-scoped。知道编号不等于有权限。

# 115. Effective-dated 统一模型

Policy、Level、Quota snapshot、Result、Term、Change 均支持 as-of。今天变更不得重写昨天。

# 116. Optimistic Lock

`version` + If-Match；冲突 409，禁止 last-write-wins。

# 117. 事务边界

state + audit + outbox + idempotency result 同事务或可恢复一致性边界。

# 118. Idempotency

- application submit
- eligibility decide
- reservation
- review submit
- ballot
- proposed list generate
- publicity start/close
- finalize
- effect HR03
- release quota
- renewal
- revocation
- Excel/import/export

# 119. Outbox 事件

```text
AppointmentBatchPublished
AppointmentApplicationSubmitted
AppointmentEligibilityDecided
PositionQuotaReserved
AppointmentReviewCompleted
AppointmentProposed
AppointmentPublicityStarted
AppointmentFinalized
AppointmentEffective
AppointmentEffectFailed
AppointmentTermExpiring
AppointmentTerminated
AppointmentRevised
AppointmentRevoked
PositionQuotaReleased
```

# 120. Inbox 消费幂等

HR02/03/15/18 consumer 使用 event_id + aggregate_version 去重。

# 121. 权限代码

```text
hr.appointment.policy.view/manage/publish
hr.appointment.batch.view/manage/publish
hr.appointment.application.self
hr.appointment.application.review.org
hr.appointment.application.review.school
hr.appointment.quota.view/reserve
hr.appointment.review.assigned
hr.appointment.review.manage
hr.appointment.ranking.run
hr.appointment.ballot.cast
hr.appointment.proposed.manage
hr.appointment.publicity.manage
hr.appointment.result.finalize
hr.appointment.effect.manage
hr.appointment.term.manage
hr.appointment.change.manage
hr.appointment.revoke
hr.appointment.export
hr.appointment.sensitive.view
```

# 122. 数据范围

`SELF / ASSIGNED / DEPARTMENT / COLLEGE / SCHOOL / SPECIAL_CASE_SET`。评委仅 assigned；敏感申诉/撤销使用 Case ACL。

# 123. SoD

- 申请人不能审核自己
- 学院推荐人与学校最终审定可配置分离
- quota admin 不得替评委评分
- 评委管理员不能替评委投票
- Result finalizer 与普通编辑权限分离
- Revocation 为高权限
- 平台管理员不因技术角色获得业务数据

# 124. API 前缀

`/api/v1/hr/appointments/...`；统一 requestId、asOf、sourceStatus、error envelope。

# 125. 错误码

```text
TENANT_CONTEXT_REQUIRED
DATA_SCOPE_DENIED
POLICY_NOT_FOUND
POLICY_CONFLICT
POSITION_SOURCE_UNAVAILABLE
POSITION_NOT_AVAILABLE
QUOTA_EXHAUSTED
STRUCTURE_RATIO_BLOCKED
BATCH_NOT_OPEN
APPLICATION_VERSION_CONFLICT
ELIGIBILITY_FAILED
SOURCE_UNAVAILABLE
REVIEW_CONFLICT
RANKING_NOT_READY
QUORUM_NOT_MET
DUPLICATE_BALLOT
RESERVATION_CONFLICT
PUBLICITY_NOT_COMPLETE
OPEN_OBJECTION_EXISTS
RESULT_IMMUTABLE
HR03_EFFECT_FAILED
DOWNSTREAM_ACK_MISSING
```

# 126. 分页规则

DB WHERE → COUNT → ORDER → OFFSET/LIMIT 或 cursor；禁止先分页后 Python 过滤。

# 127. 搜索

姓名/工号、学院、position、level、batch、application status、eligibility reason、result、term、risk；敏感全文索引按 scope。

# 128. Excel 导入

允许历史聘任、候选名单、受控 quota 辅助数据。
流程：
`template → upload → staging → validate → error workbook → preview → confirm → async apply → audit`。
禁止 Excel 直接生成 EFFECTIVE Appointment。

# 129. Excel 导出

申报/资格/评审/拟聘/结果/聘期/结构比例均异步、scope、脱敏、水印、下载过期。

# 130. 异步 Job

`PENDING → RUNNING → SUCCESS / PARTIAL_FAILED / FAILED / CANCELLED`。用于批量 precheck、排名、材料包、Excel、projection reconciliation。

# 131. 文件安全

private object storage + scan + MIME + hash + watermark + signed URL + retention + access audit。

# 132. 数据新鲜度

Dashboard 可缓存；资格、quota reserve、finalize、effect 必须强一致/实时。

# 133. Provider 状态

`OK / PARTIAL / UNAVAILABLE / STALE / ERROR`；不得 silent legacy fallback。

# 134. 审计字段

`tenant actor role action object before after reason request_id policy_version batch result timestamp`；敏感材料访问也审计。

# 135. 日志红线

- 不写身份证
- 不写银行卡
- 不写完整评审私密意见
- 不写临时 signed URL
- 不写举报人敏感身份
- 不把逐票身份与票值写入普通日志

# 136. 可观测性

```text
appointment_application_total
appointment_eligibility_failed_total
appointment_quota_available
appointment_quota_reservation_conflict_total
appointment_structure_ratio_block_total
appointment_review_overdue_total
appointment_session_blocked_total
appointment_publicity_objection_total
appointment_effect_pending_total
appointment_hr03_effect_failed_total
appointment_downstream_ack_missing_total
appointment_term_expiring_total
appointment_legacy_drift_total
```

# 137. 数据质量

- published policy mutable
- quota negative
- occupied+reserved > authorized
- result without reservation
- effective result without HR03 receipt
- term overlap
- revoked result current
- position invalid but appointment active
- HR13 revoked title without review task
- cross-tenant FK
- legacy projection drift

# 138. Retention

正式 Result/Term/Archive 长期；申请/评审按制度；临时材料包短期；legal hold 覆盖 purge。

# 139. 隐私

竞聘公示最小字段；评委资料最小化；申报材料不暴露身份证/家庭/工资等无关 PII。

# 140. Accessibility

keyboard/focus/label/table/error association/status text/modal trap/移动端公示和本人申请。

# 141. Visual Regression

`375 / 768 / 1280 / 1440` + loading/empty/partial/stale/error/permission/source unavailable/conflict/publicity/immutable。

# 142. UI 总原则

- 首屏给 quota、竞争、阻塞和下一动作
- 不堆无意义 KPI
- 申请人看到缺口与状态
- 评委只看 assigned
- 复杂规则/申请/会议/结果使用全页
- 不使用通用右抽屉承载复杂录入

# 143. HR14-01 API

```text
GET/POST /api/v1/hr/appointments/policies
POST /policies/{id}/versions
POST /policies/{id}/versions/{v}/validate
POST /policies/{id}/versions/{v}/publish
GET /levels
POST /rules/simulate
```

# 144. HR14-02 API

```text
GET/POST /batches
POST /batches/{id}/publish
POST /batches/{id}/open
POST /batches/{id}/close
GET /batches/{id}/position-supply
POST /batches/{id}/quota/refresh-preview
POST /reservations
DELETE /reservations/{id}
```

# 145. HR14-03 API

```text
GET/POST /applications
POST /applications/{id}/submit
POST /applications/{id}/withdraw
POST /applications/{id}/return
POST /applications/{id}/reject
POST /applications/{id}/eligibility/evaluate
POST /applications/{id}/eligibility/decide
```

# 146. HR14-04 API

```text
GET /review-tasks
POST /review-tasks/{id}/submit
POST /ranking-runs
POST /sessions/{id}/ballots
POST /applications/{id}/collective-decision
POST /applications/{id}/propose
```

# 147. HR14-05 API

```text
GET /proposed
POST /publicity/start
POST /publicity/{id}/close
POST /objections
POST /results/{id}/finalize
POST /results/{id}/effect
GET /effect-workbench
```

# 148. HR14-06 API

```text
GET /terms
POST /renewals
POST /changes
POST /results/{id}/corrections
POST /results/{id}/revocations
GET /staff/{id}/history
GET /risk
```

# 149. SELF API

`/api/v1/hr/appointments/me/...` 服务端从 token 解析 staff，不接受任意 staff_id。

# 150. AppointmentPolicyVersion 字段级冻结

`id tenant_id pack_id version_no effective_from effective_to source_refs content_hash published_at published_by status supersedes_id schema_version`。
PUBLISHED immutable。

# 151. AppointmentBatch 字段级冻结

`id tenant_id batch_no name business_type policy_version_id population_snapshot_id position_supply_snapshot_id application_start/end review_start/end publicity_rule status version hash`。

# 152. PositionSupplySnapshot 字段级冻结

`batch_id source_hr02_version snapshot_at position_id org_id category level authorized_fte occupied_fte reserved_fte available_fte structure_ratio_ref hash`。

# 153. QuotaPool 字段级冻结

`id batch_id scope_type scope_id category level_group exact_level authorized occupied reserved available exception_units version`。

# 154. PositionReservation 字段级冻结

`id tenant_id batch_id quota_pool_id position_id application_id proposed_id units status expires_at version idempotency_key`。

# 155. Application 字段级冻结

`id tenant_id application_no batch_id staff_id person_id target_position_id target_pool_id target_level current_assignment_snapshot_id current_title_snapshot_id status current_version_id submitted_at version`。

# 156. EligibilityEvaluation 字段级冻结

overall status + per-rule GateResult：`rule_id status actual required evidence_refs source_status explanation override_case`。

# 157. EvidenceSnapshot 字段级冻结

保存 HR03/12/13/教务/科研引用、版本、trust、hash，评审后 immutable。

# 158. Review 字段级冻结

`task application_version rubric_version structured_answers score narrative recommendation submitted_at locked_at content_hash`。

# 159. RankingRun 字段级冻结

`competition_group input_hash algorithm_version rule_version candidate_inputs outputs tie_handling run_by run_at`。

# 160. Ballot 字段级冻结

`session application voter_assignment ballot_version choice submitted_at secret receipt_hash`，唯一 voter/application/version。

# 161. CollectiveDecision 字段级冻结

`application session decision_rule aggregate rank quota decision reason decided_at hash`。

# 162. ProposedAppointment 字段级冻结

`application target_position target_level term proposed_effective reservation_id decision_id status version`。

# 163. AppointmentResult 字段级冻结

`result_no staff/person position category level effective_from/to batch decision publicity policy status revision_no supersedes_result hash`。

# 164. AppointmentTerm 字段级冻结

`result position level effective_from/to duties_snapshot renewal_due status version`。

# 165. ArchivePackage

manifest + all snapshot/document ids + hashes + retention + legal hold + aggregate hash。

# 166. 数据库 Constraints

- tenant_id NOT NULL
- published version immutable
- batch_no tenant unique
- application_no tenant unique
- reservation cannot exceed quota
- no incompatible overlapping effective terms
- result references valid reservation
- cross-tenant FKs blocked
- ballot unique
- term date valid
- revision chain valid

# 167. 关键索引

```text
(tenant_id,batch_id,status)
(tenant_id,staff_id,status)
(batch_id,target_level,status)
(quota_pool_id,status)
(position_id,status,effective_from,effective_to)
(application_id,status)
(session_id,application_id)
(tenant_id,org_id,level,status)
(staff_id,effective_from,effective_to)
```

# 168. HR14-01 验收

- Policy/version
- level catalog
- category separation
- quota rule
- eligibility
- term rule
- simulator
- publish immutable
- as-of
- tenant

# 169. HR14-02 验收

- HR02 supply snapshot
- structure ratios
- quota pool
- reservation
- concurrency
- batch freeze
- population freeze
- risk center
- source changed handling

# 170. HR14-03 验收

- self apply
- multi-preference if enabled
- integrity
- precheck
- manual review
- RETURNED/REJECTED
- withdraw
- late supplement
- provider unavailable
- audit

# 171. HR14-04 验收

- evidence snapshot
- reviewer assignment
- conflict
- rubric
- submit lock
- ranking
- tie
- ballot
- quorum
- collective decision
- proposed

# 172. HR14-05 验收

- reservation before publicity
- publicity
- objection
- final authority
- pre-effect checks
- HR03 effect receipt
- HR02 occupancy
- HR15 event
- failure recovery
- notifications

# 173. HR14-06 验收

- term history
- renewal new term
- promotion new result
- high/low appointment
- transfer
- termination
- correction
- revocation
- as-of
- risk

# 174. Tenant 安全测试

- tenant A policy/batch/application/result inaccessible to tenant B
- cross-tenant position reservation
- document IDOR
- export scope
- background job tenant
- platform ops denied

# 175. Scope 测试

- SELF
- college reviewer
- school reviewer
- assigned committee
- special case ACL
- sensitive result revocation

# 176. SoD 测试

- self review blocked
- quota admin cannot vote
- review admin cannot forge review
- subject cannot close objection
- revocation privileged

# 177. 并发测试

- last quota two applicants
- same reservation duplicate
- same application double submit
- same reviewer double submit
- same ballot double submit
- same proposed finalize twice
- HR02 source change during finalize
- HR03 effect retry
- renewal vs termination

# 178. 状态机测试

- DRAFT cannot jump EFFECTIVE
- RETURNED resubmit versioned
- REJECTED blocked
- PROPOSED not HR03
- PUBLICITY blocker
- EFFECTIVE immutable
- REVOKED not current

# 179. Quota 测试

- authorized zero
- ratio full
- reservation expiry
- reservation release
- exception quota
- FTE fractional
- pool vs exact position
- cross batch reservation

# 180. 结构比例测试

- high/mid/junior
- exact level
- rounding
- school/college scope
- source changed
- special position
- historical snapshot

# 181. Eligibility 测试

- HR13 title valid/revoked
- HR12 result
- service time
- qualification
- ethics
- UNAVAILABLE
- exception
- as-of

# 182. Ranking 测试

- weights
- missing source
- tie
- manual override reason
- rerun deterministic
- rule version
- candidate withdrawn after ranking

# 183. Ballot 测试

- eligible voter
- quorum
- abstention
- threshold
- secret boundary
- duplicate
- re-vote version

# 184. Publicity 测试

- timezone
- redaction
- objection boundary
- open case blocks
- snapshot proof
- close idempotency

# 185. HR03 Effect 测试

- position valid
- old Assignment close
- new Assignment
- main/secondary semantics
- effect retry
- receipt
- partial failure
- rollback/reconciliation

# 186. HR15 Handoff 测试

- no amount in HR14
- event once
- effective date
- revision/revocation triggers review
- ack missing risk

# 187. Provider Failure 测试

- HR02 unavailable
- HR03 unavailable
- HR12 stale
- HR13 revoked
- Documents failed
- Notifications failed
- UNAVAILABLE != PASS

# 188. Excel 测试

- template
- tenant
- invalid rows
- staging
- error workbook
- confirm
- async
- no direct EFFECTIVE write
- audit

# 189. 安全测试

- IDOR
- CSRF
- XSS
- mass assignment
- file MIME
- signed URL
- permission escalation
- export leakage
- secret ballot leakage

# 190. 性能测试

建议：
- batch dashboard p95 < 700ms；
- application list p95 < 600ms；
- eligibility single p95 < 500ms（外部 provider 除外）；
- quota check/reserve p95 < 300ms；
- ranking list p95 < 800ms；
- result detail p95 < 500ms；
- 1万候选批量 precheck async；
- 10万 appointment history 可分页；
- dashboard no N+1；
- export async。

# 191. Visual Regression 测试

覆盖六工作区、本人申请、review workbench、ranking、publicity、effect workbench、history/risk；375/768/1280/1440。

# 192. Accessibility 测试

- keyboard
- focus
- labels
- status text
- table semantics
- error association
- dialog focus
- mobile self/publicity

# 193. E2E 专技岗位晋级主链

1. HR02 有副高六级可用额度；
2. HR03 教师当前副高七级 Assignment；
3. HR13 有有效副教授职称；
4. HR12 考核满足政策；
5. HR14 发布六级晋级批次；
6. freeze position/quota/population；
7. 教师申请；
8. eligibility PASS；
9. evidence freeze；
10. reviewers complete；
11. ranking；
12. collective decision ACCEPT；
13. reservation；
14. proposed；
15. publicity；
16. no blocking objection；
17. finalize；
18. pre-effect recheck；
19. HR03 old assignment adjusted/new level fact；
20. HR02 occupancy confirmed；
21. HR15 recalculation event；
22. HR18 consume；
23. archive/as-of green。

# 194. E2E 职称有但无岗位

HR13 副教授 EFFECTIVE
→ HR14 simulator
→ HR02 副高 quota=0
→ QUOTA_EXHAUSTED
→ 不创建 Appointment
→ 不写 HR03
→ 不触发 HR15。

# 195. E2E 两人抢最后一个额度

available=1
→ A/B 同时 proposed
→ DB reservation lock
→ 仅一人 reserve 成功
→ 另一人 WAITLIST/CONFLICT
→ no overbooking。

# 196. E2E RETURNED

申请缺件 → RETURNED → V2 补正 → resubmit → V1 保留。

# 197. E2E INELIGIBLE

职称/年限不满足 → 正式 reason/policy clause → notice → 不进入评审。

# 198. E2E 同分

Ranking tie → 按 RuleVersion second review/ballot → 留痕 → 不能管理员静默排序。

# 199. E2E 公示异议

PROPOSED → PUBLICITY → objection OPEN → finalize blocked → investigation → resolved → continue/remand。

# 200. E2E HR03 生效失败

Final Result → HR03 timeout → EFFECT_PENDING → reservation retained → retry → effect success → HR15 event。

# 201. E2E 聘期续聘

Term expiring → HR12 term assessment → RenewalCase → new batch/result/term → old term immutable。

# 202. E2E 高职低聘

HR13 professor remains → HR14 lower appointment according policy → HR03 appointment projection changes → HR13 unchanged。

# 203. E2E 职称撤销后

HR13 revoked → HR14 review task → human/policy decision → retain/change/terminate appointment → HR15/HR03 effects only after formal decision。

# 204. E2E 离校

HR16 effective termination → HR14 term close → HR02 release → HR03 close → no history delete。

# 205. E2E 历史迁移

Legacy job/grade data → staging → person/position resolve → trust → manual confirm → historical Result/Term → no fake review history → DUAL compare。

# 206. Legacy Mapping

S0 搜索 JobPosition/JobRole/EmployeeWorkInformation、custom fields、payroll grade、pms、Excel、reports，形成 `LegacyAppointmentMapping.md`。

# 207. Legacy Trust Matrix

`VERIFIED_SOURCE / DOCUMENT_SUPPORTED / MANUAL_CONFIRMED / UNVERIFIED / CONFLICTED`。

# 208. Migration Staging

tenant/person/position/level/effective dates/overlap/source/trust/duplicate 全部校验后再写 Authority。

# 209. 无历史过程数据

只能迁移 historical appointment fact；不得伪造 application/reviewer/ballot/publicity。

# 210. Legacy Projection

HR14 Result/HR03 Assignment → 投影旧 WorkInformation/Report，只读兼容。

# 211. DUAL_READ_COMPARE

- current position
- level
- term
- org
- occupancy
- history count
- effective date
- HR15 downstream basis
- report aggregates

# 212. Authority Cutover

```text
LEGACY_CURRENT_STATE
→ HR14_STAGING
→ DUAL_READ_COMPARE
→ FREEZE_LEGACY_APPOINTMENT_WRITES
→ HR14_AUTHORITY
→ LEGACY_READONLY_PROJECTION
```

# 213. Rollback

只切读取/入口，保留新 HR14 facts；禁止删表回滚。

# 214. AI 使用边界

- AI 可做材料分类、缺口提示、规则解释、排名输入异常提示、风险摘要。
- AI 不得决定谁聘任。
- AI 不得生成评委意见。
- AI 不得自动给人工 override 理由。
- AI 不得把职称/考核结果推断成聘任结果。
- 所有 AI 输出 advisory + source refs + human review。

# 215. 编码 AI 施工纪律

- 先读真实代码，不按本文猜文件。
- HR02/03/12/13 Authority 不得被 HR14 重建。
- 不使用 git add -A。
- 未经授权不 push/merge main。
- 保持 Draft PR。
- 一个阶段一个可验证提交。
- A0 fail-closed 不得跳。
- Provider failure 不得 silent fallback。
- 不得用 mock quota/assessment/title 冒充生产成功。
- 先事实模型/事务/权限/测试，再美化 UI。

# 216. S0 输出物

```text
HR14_GAP_MATRIX.md
LegacyAppointmentMapping.md
LegacyAppointmentTrustMatrix.md
AppointmentAuthorityBoundary.md
AppointmentPolicyMatrix.md
PositionQuotaSourceMatrix.md
AppointmentEligibilityMatrix.md
AppointmentReviewMatrix.md
AppointmentDecisionRuleMatrix.md
HR14_PERMISSION_MATRIX.md
HR14_INTEGRATION_MATRIX.md
HR14_TASK_TREE.md
HR14_RISK_REGISTER.md
HR14_MIGRATION_PLAN.md
```

# 217. HR14-S0 基线复审

- 读 base/employee/pms/documents/audit/notifications/report
- 读 HR02/03/06/12/13 contracts
- 搜索 job_position/job_role/grade/rank/promotion/appointment
- 核验目标省/学校岗位设置与聘任制度
- 只审计不大改代码

# 218. HR14-S1 A0 与公共合同

- tenant
- permission/scope/SoD
- API/error
- enums
- Provider
- Outbox/Job/Audit
- shared UI
- security tests

# 219. HR14-S2 制度与等级

- category/level
- PolicyPack/Version
- EligibilityRule
- QuotaRule
- Review/Ranking/DecisionRule
- TermRule
- Simulator
- HR14-01 UI

# 220. HR14-S3 岗位供给与批次

- HR02 provider
- SupplySnapshot
- QuotaPool
- PopulationSnapshot
- Batch
- Milestones
- publish freeze
- HR14-02 UI

# 221. HR14-S4 申请与资格

- Application/Version
- integrity
- precheck
- org/school review
- RETURNED/REJECTED
- withdraw
- late supplement
- HR14-03 UI

# 222. HR14-S5 Evidence 与评议

- EvidenceSnapshot
- reviewers
- conflict
- rubric
- review submit lock
- defense optional
- provider failure tests

# 223. HR14-S6 排名与决策

- RankingRun
- tie
- competition groups
- ballot
- quorum
- CollectiveDecision
- ProposedAppointment

# 224. HR14-S7 预占与公示

- Reservation
- proposed list
- publicity
- redaction
- objection
- blocker
- notifications

# 225. HR14-S8 Final 与 HR03 生效

- Result
- pre-effect recheck
- HR03 effect contract
- HR02 occupancy
- EFFECT_PENDING recovery
- HR15 event
- HR18 event

# 226. HR14-S9 聘期与变更

- Term
- renewal
- promotion
- high/low appointment
- transfer
- termination
- correction
- revocation
- history/risk

# 227. HR14-S10 Legacy

- mapping
- staging
- trust
- projection
- DUAL compare
- old write block
- rollback

# 228. HR14-S11 全量质量

- security
- tenant/scope
- concurrency
- performance
- API/provider
- policy regression
- E2E
- accessibility
- visual
- migration
- reconciliation
- data quality
- observability

# 229. HR14-S12 Authority Cutover

- freeze legacy writes
- quota shadow compare
- current appointment compare
- HR03 effect rehearsal
- HR15 downstream shadow
- rollback drill
- no silent fallback

# 230. HR14-S13 最终封板

- 六工作区绿
- quota/reservation绿
- eligibility绿
- review/ranking绿
- publicity绿
- HR03 effect绿
- term/history绿
- security绿
- migration/reconciliation绿
- E2E/performance/observability/A11y/visual绿

# 231. 附录｜岗位等级与职称映射原则

职称只提供资格映射，不直接等同岗位等级。
维护 `TitleToAppointmentEligibilityMappingVersion`：
- title series/level；
- eligible appointment categories/levels；
- minimum/maximum rule；
- exception；
- effective dates；
- source policy。

映射变化不污染旧批次。

# 232. 附录｜岗位额度四账一致

必须可对账：
1. HR02 authorized；
2. HR14 reserved；
3. HR03 effective occupancy；
4. HR15 active compensation basis。

任何 drift 都进入 RiskCase，不允许静默修数。

# 233. 附录｜FTE/多人岗

Position 若允许多人：
- capacity_fte；
- incumbent_fte；
- reservation_fte；
- proposed_fte；
- available_fte。

并发控制以 FTE 为单位，不仅 headcount。

# 234. 附录｜兼岗

兼岗必须显式：
- PRIMARY / SECONDARY；
- FTE；
- conflict rule；
- compensation responsibility；
- term；
- source approval。

HR14 生效后 HR03 创建相应 Assignment type。

# 235. 附录｜岗位职责版本

聘任时冻结 position duty snapshot；HR02 后续修改职责不回写旧聘期。

# 236. 附录｜岗位撤销影响

HR02 position planned deactivation → HR14 impact list → formal transfer/termination path；不得静默把人移走。

# 237. 附录｜调岗冲突

HR06 与 HR14 同时对同一 staff 发起变动时必须有 person-level transition lock/impact check。

# 238. 附录｜退休冲突

HR16 planned retirement 与 HR14 future appointment overlap → DEPENDENCY_CONFLICT，需人工处理。

# 239. 附录｜合同到期冲突

HR07 contract end before proposed term end → warn/block per Policy；HR14 不改合同。

# 240. 附录｜聘期考核缺失

到期续聘若 HR12 term assessment required 且 unavailable → `ASSESSMENT_REQUIRED_UNAVAILABLE`，不能假装合格。

# 241. 附录｜资格撤销后的处理

HR09/HR13 source revoked → create review task；不自动解聘，除非有明确 fail-closed legal rule and formal decision path。

# 242. 附录｜岗位占用预占 TTL

Reservation 有 expires_at；scheduler idempotent release；publicity/finalization阶段可 extend with audit。

# 243. 附录｜批次取消

取消 batch → release all active reservations → preserve applications/reviews → notice → audit；不得 delete。

# 244. 附录｜候补机制

WAITLIST 有顺序/有效期/触发条件；前位放弃后按规则转拟聘，需重新校验 eligibility/quota。

# 245. 附录｜拟聘放弃

candidate decline → release reservation → waitlist/next action；保存 declaration。

# 246. 附录｜生效日期

可 future-effective；HR03 effect scheduler 在日期到达时执行，提前 Final 不等于提前占当前 Assignment。

# 247. 附录｜追溯生效

retroactive appointment 必须高权限 + impact analysis + HR03/HR15 reconciliation，不允许普通用户自由回填。

# 248. 附录｜更正 vs 变更

Correction 修历史数据错误；Change 改真实业务事实。两者状态机、权限和下游影响分开。

# 249. 附录｜撤销 vs 解聘

Revocation 否定/撤销原结果合法有效性；Termination/解聘是从某日终止有效聘任。不得混淆。

# 250. 附录｜异议保密

举报人/证据按 Case ACL；公示页不公开举报身份。

# 251. 附录｜批次统计口径

APPLICATION_TOTAL / ELIGIBLE / REVIEWED / PROPOSED / EFFECTIVE / NOT_SELECTED / WITHDRAWN / WAITLIST / QUOTA_USED / QUOTA_AVAILABLE。

# 252. 附录｜结构比例仪表

显示 authorized/occupied/reserved/available + ratio rule version + sourceUpdatedAt；不能只显示百分比。

# 253. 附录｜风险码

```text
POSITION_SOURCE_UNAVAILABLE
POSITION_DEACTIVATING
QUOTA_EXHAUSTED
STRUCTURE_RATIO_BLOCKED
RESERVATION_DRIFT
ELIGIBILITY_SOURCE_UNAVAILABLE
TITLE_REVOKED
ASSESSMENT_MISSING
REVIEW_INCOMPLETE
QUORUM_BLOCKED
RANKING_TIE
PUBLICITY_OBJECTION_OPEN
EFFECT_PENDING
HR03_DRIFT
HR15_ACK_MISSING
TERM_EXPIRING
LEGACY_DRIFT
```

# 254. 附录｜通知去重键

`batch+staff+event+version`、`result+event+revision`、`term+event+window`。

# 255. 附录｜归档包

policy/batch/supply/quota/application/eligibility/evidence/review/ranking/decision/reservation/publicity/result/effect receipt/term/change 全部 manifest+hash。

# 256. 附录｜Runbook

HR02 outage、quota drift、reservation deadlock、HR03 effect failure、publicity outage、outbox lag、legacy write attempt、cross-tenant alert、archive mismatch。

# 257. 附录｜发布后七日监控

daily 检查 new writes source、quota、reservations、effect pending、HR03 drift、HR15 ack、403/404、provider status、legacy drift。

# 258. 附录｜商业化验收

- 学校能自己配置新一轮岗位聘任而不改代码
- 能处理专技岗位等级晋升和同岗竞争
- 能解释每个不合格/未聘原因
- 最后一个岗位额度不会并发超占
- 公示异议能真正阻断
- 正式生效能正确落到 HR03
- 岗位工资只交 HR15
- 历史聘期不因今天改规则而改变
- 能经受审计、投诉、政策变化和迁移

# 259. 最终封板条件

## 业务
- 6 个三级模块完整闭环；
- HR02 岗位供给联动；
- 结构比例/额度控制；
- 竞聘申请/资格；
- 评议/排序/票决；
- 拟聘/公示/异议；
- 正式聘任；
- HR03 生效；
- 聘期/续聘/变更/解聘/撤销；
- 个人历史。

## 数据
- Policy/Rule/Batch/Snapshot versioned；
- Quota/Reservation 可对账；
- EvidenceSnapshot；
- Ranking/Decision 可解释；
- Result immutable；
- Term effective-dated；
- as-of；
- Legacy drift 可解释。

## 安全
- tenant；
- scope；
- SELF/ASSIGNED；
- SoD；
- file；
- ballot/privacy；
- objection confidentiality；
- export；
- audit。

## 技术
- constraints；
- idempotency；
- optimistic lock；
- concurrency；
- Outbox/Inbox；
- jobs；
- provider failure/reconciliation；
- async Excel；
- migration/rollback；
- no silent fallback。

## 前端
- 六个工作区；
- self-service；
- reviewer workbench；
- quota/competition views；
- publicity；
- effect workbench；
- history/risk；
- 375/768/1280/1440；
- Accessibility；
- Visual Regression；
- loading/empty/error/stale/permission/source-unavailable/conflict/immutable。

只有全部满足：
```text
HR14 READY FOR ACCEPTANCE
```

否则：
```text
HR14 NOT READY
blocking:
- ...
```

# 260. 最终架构冻结图

```text
                     HR02 Position / Quota
                              │
                              ▼
                   Supply / Ratio Snapshot
                              │
                              ▼
                    PolicyVersion + Batch
                              │
             ┌────────────────┴────────────────┐
             ▼                                 ▼
        Applications                    Quota / Positions
             │                                 │
             ▼                                 │
        Eligibility                            │
             │                                 │
             ▼                                 │
       Evidence Snapshot                       │
             │                                 │
             ▼                                 │
      Review / Ranking / Vote                  │
             │                                 │
             └──────────────┬──────────────────┘
                            ▼
                       Reservation
                            │
                            ▼
                    Proposed Appointment
                            │
                            ▼
                         Publicity
                            │
                            ▼
                      Final Decision
                            │
                            ▼
                     Appointment Result
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
             HR03          HR02          HR15
         Assignment      Occupancy   Compensation Review
              │
              ▼
          HR18 Reporting

Term lifecycle:
Result → Term → HR12 Term Assessment → Renewal/Change/Termination
```

# 261. 外部官方依据

S0 必须再次核验最新版本及目标省/学校现行制度。

当前产品设计基线：

1. 《事业单位岗位设置管理试行办法》（国人部发〔2006〕70号）  
   关键：事业单位岗位分类、岗位等级、岗位总量/结构比例、岗位设置管理。

2. 《〈事业单位岗位设置管理试行办法〉实施意见》（国人部发〔2006〕87号）  
   关键：管理/专业技术/工勤技能三类岗位，专业技术高级/中级/初级及内部等级，结构比例和岗位聘用。

3. 人事部、教育部《关于高等学校岗位设置管理的指导意见》（2007-05-07）  
   关键：高校三类岗位体系、岗位设置与聘用结合高校特点实施。  
   https://www.mohrss.gov.cn/xxgk2020/fdzdgknr/zcfg/gfxwj/rcrs/201407/t20140717_136277.html

4. 《事业单位人事管理条例》  
   作为公开招聘、竞聘上岗、聘用关系、考核等事业单位人事制度总基线之一。

5. SAP SuccessFactors Employee Central Position Management 1H 2026  
   核心启发：Position 独立于 incumbent、position control、planned vacancy、position hierarchy、employee-to-position assignment。  
   https://help.sap.com/docs/successfactors-employee-central/implementing-position-management/creating-new-positions

6. Workday Staffing Models / Position Management  
   核心启发：需先有 approved/open position，再进行 hire/promote/transfer/demote；position 可具有独立 hiring restrictions。  
   https://doc.workday.com/admin-guide/en-us/human-capital-management/staffing/staffing-models/dan1370797387431.html

产品原则：**HR02 管“岗位供给”，HR14 管“岗位聘任裁决”，HR03 管“生效任职事实”，HR15 管“薪酬应用”。**

# 262. 编码 AI 首条执行指令

```text
你现在施工 HR14 岗位聘任。

唯一权威事实源：
14_HR14_岗位聘任_施工总册_终极版.md

强制先执行 HR14-S0：

1. 读取 penghaibin9/renshi 最新目标分支真实代码；
2. 完整审计 base/employee/pms/horilla_documents/horilla_audit/notifications/report；
3. 搜索 JobPosition、JobRole、EmployeeWorkInformation、grade、rank、promotion、appointment、incumbent、position、competition 等现有字段/页面/导入/报表；
4. 读取 HR02/HR03/HR06/HR07/HR12/HR13/HR15/HR16/HR18 已冻结 Provider/Authority 合同；
5. 物化 HR14_GAP_MATRIX、LegacyAppointmentMapping、LegacyAppointmentTrustMatrix、AppointmentAuthorityBoundary、AppointmentPolicyMatrix、PositionQuotaSourceMatrix、AppointmentEligibilityMatrix、AppointmentReviewMatrix、AppointmentDecisionRuleMatrix、HR14_PERMISSION_MATRIX、HR14_INTEGRATION_MATRIX、HR14_TASK_TREE、HR14_RISK_REGISTER、HR14_MIGRATION_PLAN；
6. 核验目标省份、主管部门和目标学校当前岗位设置、结构比例、竞聘、聘用、公示、聘期制度；
7. S0 只审计和落计划，不大改业务代码；
8. S0 评审后严格按 S1→S13 施工；
9. 全程保持 A0 fail-closed、多租户、版本化、幂等、事务、Outbox、Excel、文件安全、审计、可观测性、Legacy 退出纪律；
10. 严格坚持 HR02 岗位供给、HR14 聘任过程、HR03 生效任职、HR15 薪酬四域分离；
11. 不把 HR13 职称结果自动变成 HR14 聘任；
12. 不把 HR12 考核结果自动变成晋级；
13. 不允许 quota/reservation 前端控制代替数据库并发控制；
14. 不使用 mock/legacy fallback 冒充 provider 成功；
15. 不关闭 403 修测试；
16. 不合并 main，不部署生产。

最终只有业务、数据、安全、迁移、额度/结构比例、并发、HR03 生效、HR15 handoff、E2E、性能、可观测性、Accessibility、Visual Regression 和全量对账全部绿，才能输出：

HR14 READY FOR ACCEPTANCE
```

# 263. 字段级冻结｜HrAppointmentCategory

最低字段：
```text
id
tenant_id
code
name
category_type
national_mapping
display_order
status
valid_from
valid_to
source_ref
version
```

不同类别的 level schema 不允许互相套用。

# 264. 字段级冻结｜HrAppointmentLevelDefinition

最低字段：
```text
id
tenant_id
category_id
level_code
level_name
level_order
group_code
national_mapping
eligible_title_mapping_ref
valid_from
valid_to
status
version
```

同一 category 内 level_order 唯一且不可形成循环。

# 265. 字段级冻结｜HrAppointmentEligibilityRule

最低字段：
```text
policy_version_id
rule_code
rule_type
source_provider
source_metric
operator
threshold
window
hard_gate
allow_override
override_permission
failure_code
explanation_template
display_order
```

`hard_gate=true` 且 source unavailable 时不得默认 PASS。

# 266. 字段级冻结｜HrAppointmentRankingRule

至少：
```text
policy_version_id
ranking_mode
score_components
normalization_rules
tie_break_rules
manual_override_allowed
override_permission
override_reason_required
algorithm_version
```

任何运行都冻结该版本。

# 267. 字段级冻结｜HrAppointmentDecisionRule

包括：
- quorum；
- reviewer count；
- voting rights；
- ballot type；
- pass threshold；
- abstention；
- invalid ballot；
- tie/revote；
- collective authority；
- publicity prerequisite；
- final approval requirement。

所有数值都来自版本化规则。

# 268. 岗位结构比例事实链

必须形成：

```text
HR02 Authorized Structure
        ↓
StructureRatioSnapshot
        ↓
Current HR03 Occupancy
        ↓
Active HR14 Reservations
        ↓
Available Appointment Capacity
        ↓
Batch Allocation
        ↓
Result Effective
        ↓
Reconciliation
```

每一步保存 source version 与 calculated_at。

# 269. 四账一致性守恒式

对任一 quota scope：

```text
authorized
>= occupied_effective
 + reserved_active
 + protected_capacity
```

若存在允许的 exception quota：

```text
effective_authorized
= authorized + approved_exception
```

系统必须每日 reconciliation。

# 270. Quota Reconciliation Job

每日/事件触发检查：
- HR02 authorized changed；
- HR03 occupancy changed；
- HR14 reservation expired；
- result effective；
- result revoked/terminated；
- batch cancelled。

发现 drift：
`OPEN_RISK_CASE`，禁止后台静默把数字改平。

# 271. Reservation 并发实现约束

最后一个额度必须依赖：
- DB row lock / atomic conditional update；
- version；
- idempotency key；
- unique active reservation constraint；
- transaction。

禁止：
```text
if available > 0:
    save()
```
这种 read-then-write 无锁逻辑。

# 272. 多人岗与 FTE 约束

若 HR02 position 支持多人：

```text
capacity_fte = 2.0
occupied_fte = 1.0
reserved_fte = 0.5
available_fte = 0.5
```

必须支持 decimal 精度和舍入规则。
headcount 与 FTE 同时可审计。

# 273. 主岗/兼岗占用规则

主岗与兼岗分别定义：
- 是否占编；
- 是否占 position capacity；
- FTE；
- 是否影响结构比例；
- 是否产生 HR15 compensation basis；
- 是否互斥。

不得默认兼岗 FTE=0。

# 274. 一人多申请冲突

同一批次可按政策：
- 禁止多申请；
- 允许多志愿但只能最终一个；
- 允许互不冲突的主/兼岗位；
- 允许不同类别并行。

最终生效前必须执行 `AppointmentConflictCheck`。

# 275. 同一岗位多批次冲突

HR02 position 被两个 active batch 引用时：
- source snapshot 允许；
- reservation 必须全局互斥；
- 后一个批次看到已预占；
- 不允许各批次独立认为 available。

# 276. 批次中途岗位撤销

HR02 Position 进入 DEACTIVATING：
- 标记 batch source changed；
- 阻断新 reservation；
- 已申请生成 impact；
- 已 proposed 进入 human review；
- 已 effective 走正式变更/终止。

不直接删除申请。

# 277. 批次中途组织撤并

HR02 组织撤并：
- PopulationSnapshot 不改；
- display 用 snapshot；
- 新 decision 前检查 target position current validity；
- 若需切换新组织/岗位，建立 RebaseCase。

历史申报组织仍保留当时名称/ID。

# 278. 批次中途人员调动

HR06/HR03 assignment 变化：
- 生成 `ApplicantContextChanged`；
- 比较资格是否仍满足；
- 需要时重新资格审核；
- 不静默替换 submitted snapshot。

# 279. HR06 与 HR14 Person Transition Lock

对同一人员生效窗口必须协调：
- HR06 transfer；
- HR14 appointment；
- HR16 termination/retirement；
- HR05 onboarding 等。

使用 impact check / transition lock，不允许两个事务互相覆盖 HR03 Assignment。

# 280. Future-effective 聘任

允许：
```text
Finalized at 2026-08-20
Effective at 2026-09-01
```

状态：
`FINALIZED_WAITING_EFFECTIVE`。

到生效日重新校验 position/relationship/reservation。

# 281. Retroactive 聘任

追溯生效仅高权限：
- policy basis；
- reason；
- original approval date；
- position historical availability；
- HR03 history impact；
- HR15 retro impact；
- report correction；
- audit。

禁止普通管理员补一个过去日期就完成。

# 282. 生效 Scheduler 幂等

Scheduler 扫：
`FINALIZED_WAITING_EFFECTIVE where effective_at <= now`。

每个 result：
- idempotency；
- person transition lock；
- HR03 call；
- receipt；
- outbox；
- retry backoff；
- poison queue；
- reconciliation。

# 283. HR03 Effect Receipt

保存：
```text
appointment_result_id
request_id
hr03_event_id
old_assignment_refs
new_assignment_refs
effective_at
status
applied_at
source_version
```

无 receipt 不得标 EFFECTIVE。

# 284. HR02 Occupancy Receipt

HR03 effect 成功后由权威事件驱动 HR02 occupancy。
HR14 只保存 observed acknowledgement。
若 HR03 与 HR02 不一致 → drift risk。

# 285. HR15 Ack

HR15 收到 `AppointmentEffective` 后回执：
- accepted；
- ignored_not_applicable；
- failed；
- pending。

HR14 不等待实际发薪才能 EFFECTIVE，但必须监控 ack。

# 286. 聘任职责 Snapshot

聘任时冻结：
- position title；
- duties；
- level；
- reporting relation；
- workload；
- qualification requirements；
- key responsibilities；
- source HR02 version。

后续 HR02 修改不改旧 Term。

# 287. 聘期目标引用

若学校设置聘期目标：
- 目标定义可引用 HR12 Objective/Term Assessment；
- HR14 保存 required assessment profile/ref；
- 不在 HR14 建第二套绩效系统。

# 288. Term Expiry Scheduler

可配置：
180/120/90/60/30/15/7 天预警。
风险去重键：
`term + alert_type + threshold`。
避免每天重复创建待办。

# 289. 聘期到期状态

到期不等于离职：

```text
ACTIVE
→ EXPIRING
→ RENEWAL_IN_PROGRESS
→ RENEWED / EXPIRED / TERMINATED / REAPPOINTMENT_REQUIRED
```

HR03/HR07/HR16 是否受影响由正式业务结果决定。

# 290. 续聘与重新竞聘区分

Policy 可规定：
- 直接续聘；
- 续聘需 HR12 term result；
- 到期必须重新竞聘；
- 部分等级重新竞聘；
- quota 重新核验。

不得把所有续聘统一为 `extend end_date`。

# 291. 岗位晋级与职称晋升时序

允许：
1. 先取得 HR13 职称，再参加 HR14 岗位晋级；
2. 已有较高职称但等待岗位；
3. 学校政策允许的其他映射。

系统不能强制两者同日。

# 292. 岗位低聘的历史解释

必须同时显示：
- HR13 current title；
- HR14 current appointment level；
- reason/policy；
- effective dates。

例如“职称：教授；当前聘任岗位：专业技术五级”是可表达的两个独立事实。

# 293. 岗位高聘的风险标识

若学校制度允许高聘：
- exception basis；
- target level；
- term；
- expiration；
- eligibility；
- approval；
- risk flag。

不得污染 HR13 title。

# 294. 解聘后的岗位释放

正式 AppointmentTerminated：
- HR03 Assignment close/adjust；
- HR02 capacity release；
- HR15 compensation review；
- HR18 reporting；
- Result/Term history preserved。

# 295. 撤销后的岗位释放

Revocation 可有：
- original effective invalidation semantics；
- from-now termination；
- retroactive effect。

必须由 authorized decision 指定，系统不能猜。

# 296. 公示 Snapshot Proof

保存：
- rendered list hash；
- visible field schema；
- start/end；
- publication channel；
- screenshots/document proof ref（如制度要求）；
- objection count/status。

Finalize 必须验证 proof 完整。

# 297. 公示小样本隐私

当岗位只有 1–2 人时，统计页面避免额外暴露不必要敏感维度。
公示字段由 Tenant RuleVersion 控制。

# 298. Not Selected 与 Ineligible 分离

`INELIGIBLE` = 不满足资格。
`NOT_SELECTED` = 满足资格但竞争中未获聘。

报表、通知、申诉和再次申报策略必须区分。

# 299. WAITLIST 状态机

```text
WAITLISTED
→ PROMOTED_TO_PROPOSED
→ DECLINED
→ EXPIRED
→ CANCELLED
```

转拟聘前重新校验：
- quota；
- eligibility；
- current employment；
- source revocation；
- conflicts。

# 300. 候选人放弃

拟聘前/后放弃分别处理：
- before reservation；
- after reservation；
- during publicity；
- after final but before effect。

每种阶段的 quota release 和 notice 不同。

# 301. Review Correction Case

评委已提交的错误修正：
- reopen authority；
- reason；
- original hash；
- correction window；
- new review version；
- audit。

工作人员不得替评委编辑。

# 302. Ranking Override Case

集体决定与机械排名不一致时：
- policy 是否允许；
- override reason；
- authority；
- evidence；
- before/after；
- signed minutes ref。

报表显示“有 override”，但不泄露不必要私密讨论。

# 303. Decision Revision

在 Final 前发现程序问题：
- decision version；
- remand；
- re-review；
- re-vote；
- new proposed list；
- reservation reconciliation。

不覆盖旧 Decision。

# 304. 公示异议复核后改拟聘

若异议成立：
- Proposed V1 superseded；
- release/retain reservation per rule；
- re-rank/review if needed；
- Proposed V2；
- 重新公示是否需要由 policy 决定；
- full audit。

# 305. 正式 Result Correction

仅数据录入错误：
- CorrectionCase；
- fields allowed；
- authority；
- ResultRevision；
- downstream compare。

不能借 correction 改真实聘任决定。

# 306. 正式 Result Revocation

需要：
- source regulatory/disciplinary case；
- legal/policy basis；
- authority；
- effective semantics；
- HR03/02/15/18 impact plan；
- notice；
- archive。

# 307. Appointment RiskCase

`HrAppointmentRiskCase`：
- risk_type；
- severity；
- object refs；
- detected_by；
- opened_at；
- owner；
- due_at；
- status；
- remediation；
- resolved_at；
- evidence。

Risk 不直接改 Authority。

# 308. 风险升级规则

P0 示例：
- quota overbooked；
- cross-tenant reference；
- effective result but no HR03 assignment；
- revoked result still paid/occupied；
- publicize skipped；
- unauthorized finalization。

P1 示例：
- term expiring unresolved；
- source stale；
- reviewer overdue；
- HR15 ack missing。

# 309. Dashboard 指标定义

每个 KPI 必须有：
- metricDefinitionVersion；
- asOf；
- numerator/denominator；
- filters；
- sourceUpdatedAt；
- calculatedAt；
- freshness status；
- drilldown query。

禁止前端数组自己聚合正式统计。

# 310. Competition Ratio

竞聘比：
```text
eligible_applicants / available_quota
```
必须明确：
- eligible 口径；
- quota snapshot；
- batch；
- as_of；
- withdrawn 是否排除。

不能把 submitted 人数直接当竞争比。

# 311. Appointment Rate

聘任率：
```text
effective_appointments / eligible_applicants
```

必须按 category/level/org 分层，避免混算。

# 312. Vacancy after Batch

批次结束后：
- unfilled quota；
- unfilled positions；
- reasons；
- next action；
- whether carry forward。

数据回 HR02/HR01/HR18 作为经营/治理指标。

# 313. Data Quality 批量检查

每日：
- orphan reservation；
- expired reservation active；
- negative quota；
- position invalid；
- overlapping term；
- missing HR03 receipt；
- result effective but position unoccupied；
- term active but staff inactive；
- revoked title dependency；
- missing archive hash；
- outbox backlog。

# 314. 审计抽样验收

上线前随机抽：
- 20 个 EFFECTIVE；
- 20 个 NOT_SELECTED；
- 20 个 RETURNED；
- 20 个 quota reservations；
- 20 个 promotion；
- 20 个 term renewals；
- 10 个 correction/revocation。

要求从最终状态反向重建全链路。

# 315. 历史 as-of 验收

查询 2024-09-01：
- 当时岗位；
- 当时岗位等级；
- 当时组织；
- 当时 policy；
- 当时 quota snapshot；
- 当时 term；
- 当时 result。

2026 当前值不得污染。

# 316. 跨模块 Reconciliation Matrix

至少：
| 比较 | Authority A | Authority B |
|---|---|---|
| Position capacity | HR02 | HR14 reservation |
| Occupancy | HR02 | HR03 |
| Effective appointment | HR14 | HR03 |
| Title eligibility | HR13 | HR14 snapshot |
| Assessment eligibility | HR12 | HR14 snapshot |
| Pay basis | HR14 | HR15 |
| Reporting | HR14/HR03 | HR18 |

每项有 scheduled reconciliation。

# 317. 故障注入矩阵

注入：
- DB deadlock；
- Redis/cache loss；
- HR02 500；
- HR03 500；
- HR12/13 timeout；
- Documents 500；
- Notification 500；
- Outbox worker down；
- scheduler duplicate run；
- network timeout after HR03 success before local receipt。

要求无重复生效、无超额、可恢复。

# 318. 网络超时后的不确定提交

典型：
HR14 调 HR03 → HR03 已成功 → HTTP timeout。

恢复：
- 使用 idempotency key；
- query effect status；
- reconciliation；
- 禁止再次创建第二 Assignment。

# 319. 批量任务可取消性

未产生不可逆正式结果前，批量 precheck/export/material package 可 cancel。
Finalize/effect 不能通过普通“取消任务”回滚事实。

# 320. API 审计 Contract

所有决策类 API 返回：
- aggregateVersion；
- policyVersion；
- requestId；
- decision status；
- nextAction；
- auditRef（内部可见）。

客户端不得自行推断“提交成功=生效”。

# 321. 前端 Action Guard

按钮同时基于：
- permission；
- data scope；
- state；
- source readiness；
- version；
- blocker；
- effective date。

但服务端必须再次校验，前端 guard 不是安全边界。

# 322. 本人门户

本人应看到：
- 可申报批次；
- 我的资格预检；
- 我的申请；
- 补正；
- 评审进度（按可公开颗粒度）；
- 拟聘/公示；
- 正式结果；
- 当前聘任；
- 历史聘期；
- 申诉/异议入口。

不得看到保密评议身份。

# 323. 学院工作台

学院看到：
- 本院 quota/positions；
- applicants；
- eligibility blockers；
- pending reviews；
- proposed；
- publicity；
- term expiries。

不得看到其他学院无授权材料。

# 324. 学校岗位管理工作台

人事处首屏：
- structure ratio；
- available/reserved/occupied；
- active batches；
- application funnel；
- conflicts；
- effect pending；
- expiring terms；
- high-risk cases；
- data drift。

每个卡片能钻取到明细。

# 325. 评委工作台

仅显示 assigned candidates：
- snapshot；
- rubric；
- conflict；
- deadline；
- submit state。

不展示 quota 管理、他人票值、无权限人事敏感字段。

# 326. 移动端边界

移动端适合：
- 本人申请进度；
- 补简单材料；
- 查看拟聘/结果；
- 评委查看摘要/简单确认（若学校允许）。

复杂规则、批次配置、排名和 Finalize PC 优先。

# 327. 上线闸门｜MySQL

最终必须在目标 MySQL 版本运行：
- migrations；
- constraints；
- decimal FTE；
- transactional reservation；
- concurrency tests；
- indexes；
- explain plans；
- rollback rehearsal。

不得只在 SQLite 跑绿。

# 328. 上线闸门｜安全

必须全绿：
- tenant；
- IDOR；
- scope；
- SoD；
- file；
- export；
- cross-tenant FK；
- privileged finalization；
- revocation；
- sensitive audit；
- secret ballot。

# 329. 上线闸门｜业务

至少真实角色输入：
- 普通教师；
- 学院秘书；
- 学院负责人；
- 人事岗位管理员；
- 人事负责人；
- 评委；
- 学校决策人员；
- 平台运维负向角色。

所有角色走真实 UI/API。

# 330. 最终商业体验

成熟后的 HR14 不应让老师理解“数据库岗位”。

老师看到的是：
“本轮有哪些岗位可以申报 → 我是否符合 → 缺什么 → 什么时候评 → 当前进度 → 是否拟聘 → 是否正式聘任”。

人事处看到的是：
“岗位额度是否够 → 结构比例是否合规 → 谁在竞争 → 哪些环节阻塞 → 拟聘是否超额 → 公示是否有异议 → 谁已经真实生效 → 哪些聘期即将到期”。

# 331. 最终封板口径再次冻结

HR14 只能在以下全部成立后输出：

```text
HR14 READY FOR ACCEPTANCE
```

必须：
- HR14-S0→S13 全部完成；
- 六个工作区全部 DoD；
- HR02 quota/structure reconciliation 全绿；
- DB 并发 reservation 全绿；
- HR12/HR13 eligibility Provider 全绿；
- review/ranking/decision 全绿；
- publicity/objection 全绿；
- HR03 effect + uncertain-submit reconciliation 全绿；
- HR15 handoff 全绿；
- term/renewal/change/revocation 全绿；
- migration/DUAL_READ_COMPARE/rollback 全绿；
- MySQL、安全、E2E、性能、可观测性、Accessibility、Visual Regression 全绿；
- no silent legacy fallback；
- no unresolved P0/P1。

否则只能：

```text
HR14 NOT READY
blocking:
- <精确缺口>
```

禁止“基本完成”“可先上线”“后面再补”。
