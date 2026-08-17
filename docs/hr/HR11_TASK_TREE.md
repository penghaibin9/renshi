# HR11 TASK_TREE（初版 · 依总册 §185-198 对齐）

> 文档性质：HR11-S0 前置交付。一个阶段一个可验证提交，全程 Draft PR，未经授权不合并 main。
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`

---

## 工作区划分（六模块）

```text
HR11-01 工作制度与考勤规则   HR11-02 工作日历与排班   HR11-03 打卡与工时
HR11-04 异常、补卡与加班     HR11-05 请假休假与销假   HR11-06 考勤台账与月结
```

## S0 基线复审（已完成物化）

- 交付：LegacyAttendanceMapping / LegacyLeaveMapping / LegacyShiftMapping / LegacyHourAccountMapping / GAP_MATRIX / PAYROLL_TIME_DEPENDENCY / TIME_POLICY_MATRIX / TASK_TREE / RISK_REGISTER
- 未动业务代码。

## S1 基础骨架（提交 HR11-S1）

- [ ] 新 app `hr_time`（domain/policies、calendars、schedules、events、attendance、overtime、leave、close、risks；services/providers/api/v1/jobs/projections/migrations/tests）
- [ ] 基础 enums/catalogs（event_type、day_type、attendance_status、exception_code、leave_category、ledger entry_type、close status、risk code）
- [ ] 权限 `HR11_*`（13 个角色）+ data scope（SELF/DIRECT_REPORTS/ORG_SUBTREE/ASSIGNED_ORGS/LOCATION/TENANT_ALL/AUDIT_READONLY）+ SoD 约束
- [ ] API envelope `{apiVersion,schemaVersion,requestId,data,meta}` + 错误码（总册 §139）
- [ ] Provider 接口定义（Person/Assignment→HR03，ChangeEvent→HR06，Agreement→HR07，DevelopmentTime→HR10，AssessmentConsumer→HR12，PayrollTimeConsumer→HR15，AcademicSchedule→教务，Document/Notification）
- [ ] 公共 UI 组件（PolicyVersionBadge/ScheduleTimeline/TimeStatusChip/AttendanceFactCard/RawEventTimeline/ExceptionBanner/LeaveBalanceCard/LeaveLedgerDrawer/RuleExplanation/ConflictPanel/PeriodCloseBanner/DataFreshnessBadge/SourceHealthChip）
- [ ] base migrations + 约束（tenant_id NOT NULL、幂等、版本锁）
- [ ] **A0 加固**：HorillaCompanyManager fail-closed 复核；tenant fail-closed 负向测试；无 request 上下文默认 deny
- [ ] 时区/`today` 语义基线：tenant IANA timezone；禁止服务器本地时间当业务"今天"
- [ ] 日志红线：不落生物识别原始数据/病假诊断/坐标明文
- 验收：S1 全部单元测试绿；`HR11-S1` Draft PR

## S2 工作制度与规则版本（提交 HR11-S2）

- [ ] `HrTimePolicyPack` / `HrTimePolicyVersion`（PUBLISHED immutable + content_hash + publish gate）
- [ ] `HrTimeRecordingProfile`（7 种 method）
- [ ] `resolve_time_policy()` Eligibility Resolver（优先级 + `TIME_POLICY_AMBIGUOUS` fail-closed）
- [ ] `HrWorkCalendar` / `HrWorkCalendarVersion` / `HrCalendarDay`（7 种 day_type；年度调休；不能覆盖历史）
- [ ] 发布前 gate + future impact simulation
- [ ] HR11-01 规则中心 UI（版本 diff/覆盖/冲突/无规则人员）
- 验收：教师/行政/轮班可配置不同 recording method；as-of 可解释；规则变更不污染历史

## S3 工作日历与排班（提交 HR11-S3）

- [ ] `HrShiftDefinition` / `HrShiftVersion`（grace/rounding/break/跨午夜）
- [ ] `HrWorkPattern`（做一休一/四班三运转/值班轮转/自定义周期）
- [ ] `HrScheduleAssignment`（as-of）+ `HrScheduleException`（TEMP_SHIFT_CHANGE/AUTHORIZED_TRAINING/ENTERPRISE_PRACTICE/OFFICIAL_DUTY/TRAVEL/SPECIAL_CLOSURE/MANUAL_CORRECTION）
- [ ] `HrScheduleChangeRequest` 状态机
- [ ] Team Schedule 周/月视图 + 冲突分级（HARD/SOFT/INFO/SOURCE_UNAVAILABLE）
- [ ] HR11-01/02 UI
- 验收：跨午夜班次正确；未来排班可查；多 Assignment 冲突可查

## S4 原始打卡事件（提交 HR11-S4）

- [ ] `HrRawTimeEvent`（append-only、tenant、event_at_utc/local、source_id/source_event_id、raw_payload_hash、trust_level、ingest_status）
- [ ] `HrTimeEventSource` + `HrAttendanceDevice`（secret_ref→Secret Manager、心跳、签名）
- [ ] Ingestion pipeline（receive→auth→tenant resolve→validate→person map→normalize→dedupe→persist→emit→async pair）
- [ ] 幂等去重（(source_id,source_event_id)；provider+device+person+type+at+hash）
- [ ] `HrTimeEventPair` 状态机（PAIRED/OPEN/AMBIGUOUS/INVALID_ORDER/CROSS_SHIFT/MANUAL_REVIEW）+ `shift_business_date`
- [ ] Biometric/Geofence adapter 包装（cursor/retry/health/unknown-person staging）；**不落生物模板**
- [ ] 设备故障 `HrTimeSourceIncident`
- 验收：重复 webhook 200 幂等；缺卡不等于缺勤；raw 不可变

## S5 工时/考勤事实（提交 HR11-S5）

- [ ] `HrAttendanceDayFact`（schedule_snapshot/expected/actual/credited/authorized_absence/overtime_candidate/status/evaluation_version）
- [ ] 评估引擎（缺卡核查、迟到早退、最小工时、部分缺勤）
- [ ] `HrTimeSheetPeriod/Entry`
- [ ] `HrTimeBalanceLedger`（WORK_HOURS/OVERTIME/COMP_TIME/PENDING）
- [ ] My Time portal + Manager Team Time + HR11-03 UI
- 验收：每个最终状态可解释；MISSING_TIME 不等于 ABSENT

## S6 异常/补卡/加班（提交 HR11-S6）

- [ ] `HrAttendanceException`（异常目录 13 类 + code 稳定）
- [ ] `HrAttendanceCorrectionCase`（月结前/后不同流程）+ Fact Version 替换（禁原地覆盖）
- [ ] Manual Time Entry（MANUAL_DECLARATION/OFFICIAL_DUTY/DEVICE_OUTAGE/MIGRATION/AUTHORIZED_CORRECTION；不伪装设备来源）
- [ ] `HrOvertimeRequest`（APPROVED≠实际工时）与 `HrOvertimeFact`（actual/eligible/settlement_mode）
- [ ] `HrCompTimeAccount` + `HrCompTimeLedger`（来源=verified OT fact）
- [ ] HR11-04 UI（申请/实际/可结算三列）
- 验收：设备故障不批量误判；OT fact 可验证；补卡有审批/版本

## S7 请假休假基础（提交 HR11-S7）

- [ ] `HrLeaveType`（catalog）+ `HrLeavePolicyPack` / `HrLeavePolicyVersion`（PUBLISHED immutable）
- [ ] `HrLeaveEnrollment`（eligibility snapshot）
- [ ] `HrLeaveAccount` + `HrLeaveLedgerEntry`（GRANT/ACCRUAL/RESERVE/USE/RESTORE/ADJUST/CARRY_FORWARD/EXPIRE/CONVERT/MIGRATION；reversal）
- [ ] 年休假法定档 Evaluator（1/10/20 年）+ `HrSchoolBreakFact` 寒暑假交互
- [ ] 对账（opening+grants−used−expired+adjust=closing；`LEAVE_LEDGER_DRIFT`）
- 验收：余额=ledger 求和；教师寒暑假不直接等于 0 年假

## S8 请假申请/审批/销假（提交 HR11-S8）

- [ ] `HrLeaveRequest` 状态机（DRAFT→SUBMITTED→UNDER_REVIEW→APPROVED→SCHEDULED→IN_PROGRESS→COMPLETED→RETURNED_FROM_LEAVE→CLOSED；RETURNED/REJECTED/WITHDRAWN/CANCELLED/CHANGE_IN_PROGRESS/VOID）
- [ ] 并发预占（row lock/乐观锁/幂等/超卖防护）
- [ ] Leave Duration Engine（按 ScheduleSnapshot；partial day/hour）
- [ ] `HrLeaveApprovalSnapshot`（workflow_version/approver_chain/规则快照/提交 hash/决策链）
- [ ] Evidence（私有对象存储+短期签名 URL+下载鉴权+sensitivity）
- [ ] `HrAbsenceFact`（独立于打卡）
- [ ] Withdraw/Cancel/Change/ReturnFromLeave case（销假=case，不是改 status；已用 portion 回算）
- [ ] HR11-05 UI
- 验收：RETURNED≠REJECTED；WITHDRAW≠CANCEL；并发不超卖；敏感证明受控

## S9 月结冻结与联动（提交 HR11-S9）

- [ ] `HrTimeClosePeriod`（OPEN/PRE_CLOSE/CLOSED/REOPENED）+ Pre-close Gate（P0 blockers）
- [ ] `HrTimeCloseSnapshot`（metric_definition_version/policy+calendar versions/hash）
- [ ] 重开/`HrTimeCorrectionBatch`/re-close（旧 snapshot 保留）
- [ ] `HrPayrollTimeBasis`（不含金额）+ `PayrollTimeProvider`（与 HR15 窗口对齐契约）
- [ ] HR12 Metric Basis（冻结指标）+ HR10 TimeConflictProvider
- [ ] HR11-06 UI（台账/月结/风险中心）
- 验收：月结硬闸门；闭期不可直接编辑；HR15 只拿 basis

## S10 Legacy 退出（提交 HR11-S10）

- [ ] 迁移 job（trust level：VERIFIED_SOURCE/SYSTEM_DERIVED/ADMIN_CONFIRMED/LEGACY_UNVERIFIED/AMBIGUOUS）
- [ ] Legacy projection（只读；防双写）
- [ ] DUAL_READ_COMPARE（employee/day/worked minutes/leave balance/overtime/monthly/payroll basis）
- [ ] 旧写入口阻断（表单隐藏 + API 403/`HR11_LEGACY_WRITE_DISABLED`）
- [ ] 关闭 `create_work_record`/`auto_punch_out` legacy scheduler + 两处 signals 投影写
- [ ] Payroll 直读切换到 Provider（影子对账）
- [ ] rollback plan
- 验收：差异全部分类解释；无静默 fallback

## S11 测试与质量（提交 HR11-S11）

- [ ] 安全：tenant 越权/SELF/manager/document/webhook forgery/replay/scope escalation/export/signed URL/SoD/raw GPS+medical restricted
- [ ] 并发/幂等/时区/跨午夜（22:00→06:00、23:59→00:01、月末跨月、年末跨年）
- [ ] E2E 主链 25 步 + 教师链 + 夜班链 + 异常链（总册 §172-175）
- [ ] 法定/政策边界测试（§176）+ performance（§178）+ 可观测性（§179）+ Excel 错误行
- [ ] Visual regression 375/768/1280/1440；Accessibility
- [ ] 数据质量规则（§181）+ 数据保留（§182）
- 验收：S11 全绿

## S12 Cutover 演练（提交 HR11-S12）

- [ ] Authority cutover rehearsal；freeze new legacy writes
- [ ] 月结影子对账 / payroll shadow compare / leave balance compare / device reconciliation
- [ ] 显式 rollback plan（含数据回滚点）
- 验收：演练报告 green

## S13 最终封板

- [ ] P0/P1 验收全绿；no silent legacy fallback；month close green；payroll basis reconciliation green；security green；migration/rollback drill green
- 输出：`HR11 READY FOR ACCEPTANCE` 或 `HR11 NOT READY + blocking[]`

## 里程碑与提交纪律

- 每个 S 阶段一个可验证提交（如 `feat(hr11): S1 基础骨架与 A0 fail-closed`），全程 **Draft PR**；
- 不合并 main；不部署生产；不越界改 HR02/HR03/HR15；
- 阶段依赖：S2←S1，S3←S2，S4←S1/S3，S5←S4，S6←S5，S7←S1/S2，S8←S7，S9←S5/S6/S7，S10←S9，S11←S10，S12←S11，S13←S12。

> 状态：`DRAFT_V1`。每阶段验收后更新进度。
