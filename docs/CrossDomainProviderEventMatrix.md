# CrossDomainProviderEventMatrix

> 来源：00_高校人事系统全局架构与Horilla接管合同.md §13–§17, §28.3, §89–§105
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09
> 原则：跨域写只能通过 source domain command API、durable event 或受控 Provider action。

---

## 1. 全局正式跨域事件 Registry（Canonical）

| 事件名 | eventVersion | Owner | Consumers | Aggregate | 说明 | PII | Idempotency |
|---|---|---|---|---|---|---|---|
| `StaffActivated` | 1 | HR05 | HR03, HR02 | OnboardingCase | 入职激活完成，创建 Person/Staff/Relationship/Assignment | `SENSITIVE_PERSONAL` | `(tenant_id, case_id, eventType)` |
| `ProbationConfirmed` | 1 | HR05 | HR03, HR07, HR15 | ProbationCase | 试用转正确认 | `PERSONAL` | `(tenant_id, probation_id, eventType)` |
| `PersonnelChangeEffective` | 1 | HR06 | HR03, HR14, HR15, HR18 | ChangeCase | 人事异动生效，更新 Assignment/Relationship | `PERSONAL` | `(tenant_id, change_case_id, eventType)` |
| `ContractEffective` | 1 | HR07 | HR03, HR17 | Agreement | 合同/协议生效 | `SENSITIVE_PERSONAL` | `(tenant_id, agreement_id, eventType)` |
| `ContractTerminated` | 1 | HR07 | HR03, HR16, HR17 | Agreement | 合同/协议解除终止 | `SENSITIVE_PERSONAL` | `(tenant_id, agreement_id, eventType)` |
| `QualificationResultEffective` | 1 | HR09 | HR03, HR10, HR13, HR17 | QualificationCase | 教师资格/双师型正式结果生效 | `PERSONAL` | `(tenant_id, qualification_id, eventType)` |
| `DevelopmentFactVerified` | 1 | HR10 | HR09, HR12, HR17, HR18 | DevelopmentRecord | 培训/进修/企业实践 VERIFIED | `PERSONAL` | `(tenant_id, record_id, eventType)` |
| `TimePeriodClosed` | 1 | HR11 | HR12, HR15, HR18 | ClosePeriod | 考勤月结冻结 | `PERSONAL` | `(tenant_id, period_id, eventType)` |
| `AssessmentResultFinalized` | 1 | HR12 | HR09, HR13, HR14, HR15, HR17, HR18 | AssessmentCase | 考核正式结果 finalized | `SENSITIVE_PERSONAL` | `(tenant_id, assessment_id, eventType)` |
| `ProfessionalTitleResultEffective` | 1 | HR13 | HR03, HR14, HR15, HR17, HR18 | TitleCase | 职称评审正式结果生效 | `PERSONAL` | `(tenant_id, title_case_id, eventType)` |
| `ProfessionalTitleResultRevised` | 1 | HR13 | HR03, HR14, HR15, HR17, HR18 | TitleCase | 职称结果修订 | `PERSONAL` | `(tenant_id, title_case_id, eventType)` |
| `ProfessionalTitleResultRevoked` | 1 | HR13 | HR03, HR14, HR15, HR17, HR18 | TitleCase | 职称结果撤销 | `PERSONAL` | `(tenant_id, title_case_id, eventType)` |
| `PositionAppointmentEffective` | 1 | HR14 | HR03, HR02, HR15, HR17, HR18 | AppointmentCase | 岗位聘任正式生效 | `PERSONAL` | `(tenant_id, appointment_id, eventType)` |
| `CompensationReevaluationRequested` | 1 | HR14/HR03/HR06 | HR15 | — | 聘任/异动后触发薪酬复核请求 | `SENSITIVE_PERSONAL` | `(tenant_id, staff_id, effective_date, eventType)` |
| `PayrollFinalized` | 1 | HR15 | HR17, HR18 | PayrollPeriod | 月度工资结算 finalized | `HIGHLY_RESTRICTED` | `(tenant_id, period_id, eventType)` |
| `ExitEffective` | 1 | HR16 | HR03, HR14, HR15, IAM, HR17, HR18 | ExitCase | 离校生效（辞职/调出/解除） | `SENSITIVE_PERSONAL` | `(tenant_id, exit_case_id, eventType)` |
| `RetirementEffective` | 1 | HR16 | HR03, HR14, HR15, IAM, HR17, HR18 | RetirementCase | 退休生效 | `SENSITIVE_PERSONAL` | `(tenant_id, retirement_id, eventType)` |

### 事件命名规则
- 事实事件：**过去式**（`StaffActivated`, `AppointmentEffective`, `PayrollFinalized`）
- 请求事件：**显式 `...Requested`**（`CompensationReevaluationRequested`）

### 已禁止的同义词
- ~~`ProfessionalTitleAppointmentEffective`~~ → 统一使用 `ProfessionalTitleResultEffective`
- ~~`AppointmentEffective`~~ → 统一使用 `PositionAppointmentEffective`
- ~~`HR05_ONBOARDING` / `HR13_TITLE_APPOINTMENT`~~ → 保留为 Legacy alias（HR03 `CANONICAL_EVENT_HANDLERS` 别名映射）

---

## 2. 关键跨域 Provider/Event Contract（§89–§105）

| # | 边界 | 方向 | 契约类型 | 消费方式 | 实现状态 |
|---|---|---|---|---|---|
| 1 | **HR02→HR03** | 组织/岗位供给 → 任职参考 | Provider: org/position read | `selectors.effective` as-of | ✅ HR02 S3 已交付 |
| 2 | **HR02→HR04** | 岗位供给 → 招聘引用 | Provider: position availability | `PositionService.reserve/commit/release` (S7) | ✅ 预占 API 已暴露 |
| 3 | **HR04→HR05** | 拟录用/Offer → 入职 handoff | Outbox: `OfferAccepted` + API | `POST handoff-to-hr05` + Idempotency-Key | ✅ HANDOFF 已交付 |
| 4 | **HR05→HR03** | Activation Gate → 创建 Staff | Outbox: `StaffActivated` | HR03 `event_service` 消费 | ✅ Service 契约 v1 已交付 |
| 5 | **HR03→HR07** | EmploymentRelationship → 合同绑定 | Provider: relationship read | `selectors.effective` | 待 HR07 开窗 |
| 6 | **HR03→HR06** | Assignment → 异动变更 | Event: `PersonnelChangeEffective` | HR03 consumer 更新历史 | 待 HR06 开窗 |
| 7 | **HR03→HR08** | Person 身份复用 | Provider: `PersonIdentityService` | fingerprint 去重 | ✅ HR08 已复用 |
| 8 | **HR10→HR09** | VERIFIED 培训/实践 → 双师证据 | Provider: verified facts | 不自动认定 | 待 HR09/10 开窗 |
| 9 | **HR11→HR12** | ClosedPeriod → 考核考勤依据 | Provider: frozen time facts | closed/frozen 数据 | 待 HR12 开窗 |
| 10 | **HR12→HR13** | 正式考核 → 职称证据 | Provider: assessment results | 不反向改考核 | 待 HR12/13 开窗 |
| 11 | **HR13→HR14** | 职称结果 → 聘任资格 | Provider: title results | 不自动占岗 | 待 HR13/14 开窗 |
| 12 | **HR14→HR03** | EFFECTIVE Appointment → 更新任职投影 | Event: `PositionAppointmentEffective` | HR03 consumer | 待 HR14 开窗 |
| 13 | **HR14→HR15** | 聘任 → 薪酬复核 | Event: `CompensationReevaluationRequested` | HR15 consumer | 待 HR14/15 开窗 |
| 14 | **HR16→HR14** | ExitEffective → 关闭聘任 | Event: `ExitEffective` | HR14 consumer | 待 HR16 开窗 |
| 15 | **HR16→HR15** | 离退 → 最终结算 | Provider: final dates + settlement request | HR15 计算金额 | 待 HR15/16 开窗 |
| 16 | **HR03–16→HR17** | SELF 聚合 | Provider: read + action delegation | HR17 不复制真值 | 待 HR17 开窗 |
| 17 | **HR01–17→HR18** | 数据中心消费 | Provider/Event + Snapshot | HR18 不反向写源域 | 待 HR18 开窗 |

---

## 3. 事件信封标准

```json
{
  "eventId": "uuid",
  "eventType": "StaffActivated",
  "eventVersion": 1,
  "tenantId": "t_xxx",
  "aggregateType": "OnboardingCase",
  "aggregateId": "xxx",
  "aggregateVersion": 7,
  "occurredAt": "2026-08-09T08:00:00+08:00",
  "effectiveAt": "2026-08-09T08:00:00+08:00",
  "correlationId": "uuid",
  "causationId": "uuid",
  "payload": {}
}
```

---

## 4. Outbox/Inbox 规则

- 正式事务必须 `domain state + audit + outbox` 同事务
- 发布失败可重试
- 消费者按 `eventId` / `providerEventId` 幂等
- 重复 10 次结果一致
- 旧 `aggregateVersion` 不覆盖新状态
- Correlation: 跨 HR04→05→03→07→15 等长链用 `correlationId/causationId`
- 事故排查必须能从 UI 一直追到源事件

---

## 5. Provider Contract 标准

每个 Provider 必须固定以下属性：

```text
owner_domain     — 数据源域
consumer         — 消费域
tenant           — 租户上下文
ids              — 唯一标识符
as_of            — 时间点
source_version   — 源版本号
freshness        — 新鲜度（实时/分钟/小时/天）
timeout          — 超时时间
sensitivity      — 敏感等级
authorization    — 授权方式
errors           — 错误语义
cache_policy     — 缓存策略
```

Provider 不可用：
- 不得 `silent fallback legacy`
- 必须显式返回 `UNAVAILABLE` 状态
- `UNAVAILABLE != 0 != false != empty list`

---

## 6. 跨域长链追踪示例

```text
HR04 Plan → Campaign → Application → Offer → Handoff
→ HR05 OnboardingCase → Activation Gate
→ HR03 Person/StaffMaster/EmploymentRelationship/StaffAssignment (effective-dated)
→ HR07 Contract (bound to EmploymentRelationship)
→ HR15 Payroll (triggered by EmploymentRelationship)
→ HR18 Snapshot + Report
```

每个环节必须保留 `correlationId`，事故排查从 HR18 一路追回 HR04。

---

*由 00_高校人事系统全局架构与Horilla接管合同.md §160 自动生成。*
