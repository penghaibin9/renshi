# GlobalAuthorityOwnershipMatrix

> 来源：00_高校人事系统全局架构与旧系统接管合同.md（系统宪法）
> 生成指令：§160 Global-S0 编码 AI 首条执行指令
> 生成日期：2026-08-09
> 原则：**一个事实一个 Authority**；其他域只能 Provider/Event/Projection 消费。

---

## 1. 权威事实归属矩阵

| 事实域 | Authority Owner | 消费方（Consumer） | 消费方式 |
|---|---|---|---|
| 组织树（Organization Tree） | **HR02** | HR03/HR04/HR05/HR06/HR08/HR11/HR12/HR14/HR17/HR18 | Provider: read FK reference + as-of org name |
| 岗位定义与编制（Position/Quota） | **HR02** | HR03/HR04/HR05/HR14/HR18 | Provider: reserve/commit/release + occupancy query |
| 岗位预占（Position Reservation） | **HR02** | HR04/HR05/HR14 | Provider API: reserve/commit/release/list/availability |
| 编制方案（Staffing Plan） | **HR02** | HR04/HR18 | Provider: plan preflight/approval |
| 党政组织关系 | **HR02** | HR03/HR18 | Provider: relation read |
| Person 身份根（身份证/指纹去重） | **HR03** | HR04/HR05/HR08/HR17 | `PersonIdentityService`: fingerprint dedup |
| StaffMaster（工号/Staff 基础档案） | **HR03** | HR05/HR07/HR08/HR11/HR12/HR13/HR14/HR15/HR16/HR17/HR18 | `StaffMasterService`: staff_no generation + read |
| EmploymentRelationship（聘用关系 [from,to)） | **HR03** | HR06/HR07/HR08/HR11/HR14/HR15/HR16/HR17/HR18 | `EffectiveDatedQueryService`: as-of relationships |
| StaffAssignment（任职段 PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT） | **HR03** | HR02/HR06/HR14/HR15/HR16/HR18 | `EffectiveDatedQueryService`: as-of assignments |
| 状态历史（StatusHistory） | **HR03** | HR17/HR18 | Provider: status timeline |
| 教育资格/证书/工作经历 | **HR03** | HR09/HR13/HR17 | Provider: background facts |
| 材料档案（Material/Version/DownloadTicket） | **HR03** | HR05/HR16/HR17 | `material_service`: secure file access |
| 信息更正（CorrectionCase） | **HR03** | HR17 | `correction_service`: correction workflow |
| 正式奖励/处分决策（PersonnelDecision） | **HR03** | HR14/HR15/HR16/HR17/HR18 | Event: RewardDecisionEffective / DisciplinaryDecisionEffective |
| 用人计划（RecruitmentPlan） | **HR04** | HR02/HR18 | Provider: plan approval |
| 招聘岗位公告（Campaign/JobPosting） | **HR04** | HR05 | Provider: campaign read |
| 应聘申请（Application） | **HR04** | HR05 | `HrRecruitmentHandoff`: proposed_hire → HR05 |
| 评估/评分方案 | **HR04** | — | 本域 Authority |
| 拟录用/Offer | **HR04** | HR05 | Event: OfferAccepted → trigger handoff |
| HANDOFF 幂等契约 | **HR04** | HR05 | `POST .../handoff-to-hr05` + Idempotency-Key |
| 入职 Case（OnboardingCase） | **HR05** | HR03/HR07/HR17 | Event: StaffActivated / ProbationConfirmed |
| 待报到/Portal/材料核验 | **HR05** | HR17 | Provider: portal status |
| 报到激活（Activation Gate） | **HR05** | HR03/HR02/HR07 | Outbox: StaffActivated → HR03 activation |
| 试用转正（Probation） | **HR05** | HR03/HR07/HR15 | Event: ProbationConfirmed |
| 人事异动 Case | **HR06** | HR03/HR14/HR15/HR18 | Event: PersonnelChangeEffective → HR03 update assignment |
| 合同/协议（Agreement） | **HR07** | HR03/HR05/HR08/HR14/HR16/HR17 | Event: ContractEffective / ContractTerminated |
| 签署/续签/解除终止 | **HR07** | HR03/HR16 | Provider: agreement status |
| 外聘教师 Profile/Engagement | **HR08** | HR03/HR17/HR18 | `PersonProvider`: person identity reuse |
| 外聘聘用审批（HiringCase） | **HR08** | HR07/IAM/教务/HR15 | Provider: agreement gate (占位 UNAVAILABLE) |
| 外聘任务/工作量/结算 | **HR08** | HR15 | Event: ExternalWorkloadVerified → SettlementBasis |
| 教师资格认定（Qualification） | **HR09** | HR03/HR10/HR13/HR17 | Event: QualificationResultEffective |
| 双师型认定 | **HR09** | HR10/HR13/HR17 | Provider: qualification status |
| 培训/进修事实（VERIFIED） | **HR10** | HR09/HR12/HR17/HR18 | Event: DevelopmentFactVerified |
| 企业实践事实（VERIFIED） | **HR10** | HR09/HR12/HR17 | Provider: practice evidence |
| 考勤制度/政策包（PolicyVersion） | **HR11** | HR15 | Provider: policy snapshot |
| 日历/排班 | **HR11** | HR12/HR15 | Provider: schedule data |
| 打卡/请假/加班原始事件 | **HR11** | — | 本域 append-only ledger |
| 月结冻结事实（ClosedPeriod） | **HR11** | HR12/HR15/HR18 | Event: TimePeriodClosed |
| 年度/聘期考核结果（AssessmentResult） | **HR12** | HR09/HR13/HR14/HR15/HR17/HR18 | Event: AssessmentResultFinalized |
| 师德考核 | **HR12** | HR13/HR14/HR17 | Provider: ethics assessment result |
| 考核申诉 | **HR12** | HR17 | Provider: appeal status |
| 职称申报/评议/公示（TitleCase） | **HR13** | — | 本域 workflow Authority |
| 职称正式结果 | **HR13** | HR03/HR14/HR15/HR17/HR18 | Event: ProfessionalTitleResultEffective / Revised / Revoked |
| 岗位竞聘/聘任（AppointmentCase） | **HR14** | HR02/HR03/HR15/HR17/HR18 | Event: PositionAppointmentEffective + CompensationReevaluationRequested → HR15 |
| 薪酬档案/薪资规则 | **HR15** | HR17 | Provider: salary info |
| 月度工资结算（PayrollFinalized） | **HR15** | HR17/HR18 | Event: PayrollFinalized |
| 调资/津补贴/社保公积金 | **HR15** | HR17/HR18 | Provider: compensation detail |
| 支付/财务对账（PostingPackage） | **HR15** | 财务系统 | Provider: posting data |
| 职业年金/福利计划 | **HR15** | HR17/HR18 | Provider: benefit statement |
| 辞职/调出/解除/退休 Case | **HR16** | HR03/HR14/HR15/HR17/HR18/IAM | Event: ExitEffective / RetirementEffective |
| 离校编排/交接 | **HR16** | IAM/资产/档案 | Provider: exit task pipeline |
| 档案转递 | **HR16** | ArchiveProvider/HR17 | Provider: transfer receipt |
| 本人 SELF 视图（聚合只读） | **HR17** | — | 聚合消费 HR03-16 Provider |
| 本人动作入口（请假/查看/申诉） | **HR17** | HR11/HR12/HR15 | Provider: action delegation |
| 指标定义（MetricDefinition） | **HR18** | HR01 | Provider: metric definition + population |
| 报表/数据质量/交换 | **HR18** | 外部系统 | Provider: SubmissionPackage |
| 正式上报（SubmissionPackage） | **HR18** | 上级主管部门 | Provider: submission send/receipt |
| 首页仪表盘布局/卡片 | **HR01** | — | 只消费 HR18 Metric + 各域 Provider |
| Alert/Todo/QuickAction | **HR01** | — | 聚合各域待办/预警 |
| 全局权限码注册 | **全域**（统一 registry） | all | PermissionAliasMapping |
| 全局事件注册 | **全域**（GlobalEventRegistry） | all | outbox/inbox 契约测试 |
| 文件存储/下载票据 | **全域**（Horilla Documents Provider） | all | `material_service` / ticket exchange |
| 审计日志 | **全域**（Horilla Audit） | all | audit event record |
| 通知 | **全域**（Notifications） | all | Event → template → channel → delivery |

---

## 2. 禁止跨域直写清单

以下行为在系统宪法中明确禁止：

| # | 禁止行为 | 违规模块 | 正确做法 |
|---|---|---|---|
| 1 | 其他模块直接 HR03 `HrEmploymentRelationship.save()` | any | 通过 HR05/HR06/HR16 Event → HR03 consumer |
| 2 | HR13 直接写 HR14 聘任事实 | HR13 | 通过 Event: ProfessionalTitleResultEffective → HR14 consumer |
| 3 | HR14 直接写 HR15 工资金额 | HR14 | 通过 Event: CompensationReevaluationRequested → HR15 |
| 4 | HR16 直接改 HR03 Staff Assignment | HR16 | 通过 Event: ExitEffective → HR03 consumer |
| 5 | HR01 直接定义 Metric 公式/Population | HR01 | 通过 HR18 MetricProvider 消费 |
| 6 | Excel 导入直接覆盖 FINAL/EFFECTIVE | any | staging → validation → error workbook → confirm → async |
| 7 | Dashboard/Report/Legacy/External callback → direct overwrite Authority | any | Provider/Event/Projection only |
| 8 | 共享 ORM 模型跨域 `.save()` 正式事实 | any | 走 source domain command API / durable event / 受控 Provider action |
| 9 | 前端"双接口写入保持一致" | any | 只走 Authority API；另一接口 readonly/redirect |

---

## 3. 当前施工状态（2026-08-09）

| 模块 | app | Authority Owner 就绪状态 | 消费方接入状态 |
|---|---|---|---|
| HR01 | `hr_control_center` | S1-S7 完成；Metric 待 HR18 | — |
| HR02 | `hr_structure` | S1-S8 完成；预占 API 已暴露 | HR03/HR04/HR05 已接入 FK |
| HR03 | `hr_staff` | S0-S12 全部完成（169 tests OK） | Service 契约 v1 已交付 |
| HR04 | `hr_recruitment` | S1-S11 完成（100/100 绿） | HANDOFF 已交付 HR05 |
| HR05 | `hr_onboarding` | S0-S12 代码完成；待 CI | Activation 出站事件已定义 |
| HR06 | `hr_changes` | 未开窗（app 已注册） | — |
| HR07 | `hr_contracts` | 未开窗（app 已注册） | HR08 以 Provider 占位 UNAVAILABLE |
| HR08 | `hr_external` | S0-S13 施工链交付；待 CI | HR03 Person 已复用 |
| HR09-HR18 | — | 未开工 | — |

---

## 4. 权威归属判定规则

1. 若事实已在矩阵中有 Authority Owner → 只允许该 Owner 执行正式写入。
2. 若事实未在矩阵中 → 按 HRxx 模块边界第 2 节 18 模块总目录判定。
3. 无法判定时 → 默认 fail-closed：不得写入，提报 00 合同裁决。
4. 任何模块的 Projection/ReadModel 丢失可重建；Authority 丢失是生产事故。

---

## 5. Provider 不可用时的处置

| Provider 状态 | 含义 | 消费方行为 |
|---|---|---|
| `OK` | 正常 | 正常消费 |
| `PARTIAL` | 部分可用 | 标注 partial 继续；不转 0/空 |
| `UNAVAILABLE` | 不可用 | 显式标注，**不得 silent fallback legacy** |
| `STALE` | 过期未刷新 | 只允许非交易页面使用；标注 stale 时间 |
| `ERROR` | 错误 | 同 UNAVAILABLE；记录 error detail |
| `NOT_APPLICABLE` | 不适用 | 请求语义不支持，返回 N/A |

---

*由 00_高校人事系统全局架构与旧系统接管合同.md §160 自动生成。只审计和物化治理清单，不大改业务代码。*
