# HR11 GAP_MATRIX（初版 · 依据真实仓库核对）

> 文档性质：HR11-S0 前置交付；以总册 §14 KEEP/ADAPT/REWRITE 与 Authority 模型清单为纲，对照 `renshi` 真实仓库逐项打勾。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`

---

## 1. 结论

- Legacy 已覆盖的**功能面**：打卡、宽限、迟到早退、加班 diff、hour account、shift/rotating shift、leave type/request/allocation/carryforward/comp-off、多级审批、clash 计数、报表、Excel 导入导出、biometric/geofence/IP 基础。
- 但**全部落在“功能演示级”，无任何一项满足总册 Authority 语义**（版本化、不可变事件、Ledger、审批快照、月结冻结、Provider 边界）。
- HR11 = **REWRITE AS AUTHORITY**，Legacy 保留为 projection。

## 2. GAP 总矩阵（Authority 模型 × Legacy 现状）

| 总册 Authority 对象（§14） | Legacy 对应 | 现状缺口 | 施工阶段 |
|---|---|---|---|
| `HrTimePolicyPack` / `HrTimePolicyVersion` | 无 | **全缺**：无政策包/版本/发布冻结/eligibility | S2 |
| `HrTimeRecordingProfile` | `AttendanceGeneralSetting`+`AttendanceValidationCondition`（全局单行） | 全局单行，无 recording method、无版本、无适用范围 | S2 |
| `HrWorkCalendar` / `HrWorkCalendarVersion` / `HrCalendarDay` | `Holidays`+`CompanyLeaves`（base） | 无年度日历版本、无调休/补班、无 day_type；`is_holiday` 实时查表 | S2 |
| `HrShiftDefinition` / `HrShiftVersion` | `EmployeeShift` / `EmployeeShiftSchedule` | 无版本、无 effective_from/to、无 grace/break/rounding 版本字段 | S3 |
| `HrWorkPattern` | `RotatingShift` / `RotatingShiftAssign` | 轮转靠 JSON+assign 启发式，无 cycle 模板/校验 | S3 |
| `HrScheduleAssignment` | `EmployeeWorkInformation.shift_id` + `RotatingShiftAssign` | 无 as-of 生效、无 assignment 维度 | S3 |
| `HrScheduleException` | 无 | **全缺**（临时换班/出差/培训/教务 overlay） | S3 |
| `HrRawTimeEvent` | `AttendanceActivity`（可变） | **无不可变事件账本**、无 source/event_id/幂等键、无 payload hash | S4 |
| `HrTimeEventSource` / `HrAttendanceDevice` | `BiometricDevices` / `AttendanceAllowedIP` | 设备=凭证明文+轮询；无签名校验/信任级别/心跳 | S4 |
| `HrTimeEventPair` | AttendanceActivity in/out 配对（原地改） | 无配对状态机（OPEN/AMBIGUOUS/INVALID_ORDER…） | S4 |
| `HrAttendanceDayFact` | `Attendance` | 有日卡片但无评估版本、无 schedule_snapshot、无状态语义（漏卡=未定义） | S5 |
| `HrTimeSheetPeriod/Entry` | 无 | **全缺** | S5 |
| `HrAttendanceException` | `AttendanceLateComeEarlyOut`（bool 记录） | 无异常目录、无证据、无关闭流程 | S5/S6 |
| `HrAttendanceCorrectionCase` / Fact Version | `request_type`+`requested_data`（JSON diff） | 无正式 case、无 fact 版本替换 | S6 |
| `HrOvertimeRequest` / `HrOvertimeFact` | `attendance_overtime_approve` 布尔 | 申请/事实分离缺失；`overtime=worked−min` 简单差 | S6 |
| `HrCompTimeAccount` / `Ledger` | `CompensatoryLeaveRequest`+`LeaveType.is_compensatory_leave` | 无独立账户/Ledger；来源未经 verified fact | S6 |
| `HrLeaveType` / `HrLeavePolicyPack` / `HrLeavePolicyVersion` | `LeaveType` | 目录与规则混在一个模型；无版本化、无 per-jurisdiction 政策 | S7 |
| `HrLeaveEnrollment` | `AvailableLeave` | 无 enrollment 快照、无 re-enrollment 事件 | S7 |
| `HrLeaveAccount` / `HrLeaveLedgerEntry` | `AvailableLeave.available_days`（running total） | **无 Ledger**；余额=单数字 | S7 |
| `HrLeaveRequest` 状态机 | `LeaveRequest`（4 状态） | 缺 RETURNED/SCHEDULED/IN_PROGRESS/RETURNED_FROM_LEAVE、WITHDRAW | S8 |
| `HrLeaveApprovalSnapshot` | `LeaveRequestConditionApproval`+HorillaAuditLog | 无提交数据 hash、无决策链快照 | S8 |
| `HrAbsenceFact` | WorkRecords(ABS/CONF) 投影 | **全缺**：无独立 Absence Fact；旧系统把“请假”直接写成 ABS 投影 | S8 |
| `HrReturnFromLeaveCase` | 无 | **全缺**：销假无 case、无提前返岗/用量回算 | S8 |
| `HrTimeClosePeriod` / `Snapshot` | 无 | **全缺**：无月结冻结 | S9 |
| `HrTimeCorrectionBatch` | 无 | **全缺**：无重开/更正批次 | S9 |
| `HrTimeRiskCase` | 无 | **全缺**：无风险中心（旷工阈值等） | S9 |

## 3. KEEP（可复用）

| Legacy 资产 | 复用方式 |
|---|---|
| Check-in/out 交互（web UI）、clock_in/out 视图骨架 | ADAPT：改走 HR11 ingestion pipeline |
| Attendance list/filter/calendar 页面交互 | ADAPT：数据源切 DayFact |
| Leave list / self-service 交互 | ADAPT |
| Biometric provider 技术基础（zk/anviz/cosec/dahua/etimeoffice） | ADAPT：加签名/幂等/健康检查 |
| Geofencing 技术基础（坐标校验） | ADAPT：去掉 Nominatim 网络依赖；只存 verdict |
| Notifications / horilla_documents / horilla_audit 能力 | KEEP：复用框架 |
| Permissions/group、generic form/list/pagination | KEEP |
| GraceTime / AttendanceAllowedIP 基础配置概念 | ADAPT：并入版本化政策 |
| Excel 导入/导出视图模式 | ADAPT：改造为异步 validate→preview→confirm 全量原子 |
| `MultipleApprovalCondition` 多级审批配置 | ADAPT：并入 ApprovalRule version |

## 4. 关键 Cross-Module 缺口（S9 联动）

| 联动方 | 总册要求 | Legacy 现状 | 缺口 |
|---|---|---|---|
| HR03 | Policy eligibility 引用 staff_master/assignment | 只有 `Employee.employee_work_info` | HR03 Authority（HrStaffMaster 等）**仓库尚未实现** → HR11 Provider 接口需按目标模型预留并 fail-closed |
| HR06 | `AttendanceRuleReevaluationRequested` | 无异动事件消费 | 无 change-event 集成 |
| HR07 | 合同工作安排只读参考 | `Contract` 存在（payroll） | 未接事件 |
| HR10 | TimeConflict/Availability/ApprovedAbsence/ReleasedTime Provider | 无 | 全缺（S9） |
| HR12 | 只读冻结指标 | 无 | 全缺（S9） |
| HR15 | 只消费 closed basis | **直读 Attendance/LeaveRequest 模型** | 违反边界（见 PAYROLL_TIME_DEPENDENCY） |
| 教务 | 课程/监考只作冲突证据 | 无 | 全缺（S9 Provider） |

## 5. 硬门相关缺口（直接违反红线的代码点）

| 红线（总册 §2） | 现状证据 | 处置 |
|---|---|---|
| `if no_checkin: absent=True` | `leave/signals.py` 审批通过写 WorkRecords `ABS`；`attendance/views/views.py` attendance 缺卡逻辑 | S6/S10 移除，改为 `MISSING_TIME→核查` 流 |
| 打卡事件直接作 Payroll 输入 | `payslip_calc.py`/`methods.py` 直读 Attendance | S10 解耦（Provider + close basis） |
| 删除原始打卡事件 | `Attendance.delete()` 级联删 AttendanceActivity | S4 起禁止；迁移期只软删 |
| 补卡 UPDATE 原始事件 | AttendanceActivity 原地关闭/重写 | S4/S6 改不可变事件 |
| 设备上报覆盖人工更正 | clock_in_out 无版本控制，save() 覆盖 | S5/S6 |
| 教师无行政打卡算旷工 | `create_work_record` 30min 补 DFT + 报表可能误读 | S2 recording profile 先解决 eligibility |
| 加班只看下班后打卡 | `overtime_calculation = worked − min` | S6 重写评估 |
| 假别规则硬编码 | `leave/models.py` 大量 `if leave_type...` 逻辑 | S7 版本化 |
| 一个学校配置污染另一学校 | `Holidays/CompanyLeaves` company FK 可 NULL；HorillaCompanyManager 对 NULL company 不过滤 | S1 A0 加固 |
| 年休假只存数值 | `AvailableLeave.available_days` | S7 Ledger |
| 取消已休完直接恢复余额 | 依赖 views 逻辑，无 usage partition | S8 Cancel/Change case |
| RETURNED 与 REJECTED 混为一个状态 | 无 RETURNED | S8 |
| 已批准可无审计改日期 | `LeaveRequest` update 无快照/版本 | S8 |
| 月结后直接 UPDATE 已冻结事实 | 无月结概念 | S9 |

## 6. 自我纠错清单（总册 §184 对照）

1. 考勤 ≠ 打卡：Legacy 是打卡卡片，Authority 需分离 raw/评估/投影 ✔（已列 GAP）
2. 教师非固定坐班：需 `HrTimeRecordingProfile.method`（NEGATIVE_TIME/ABSENCE_ONLY）→ S2
3. raw 与 evaluated 分离 → S4/S5
4. attendance 与 absence 分离 → S8
5. 年度调休日历版本 → S2
6. leave ledger → S7
7. 并发 reservation → S8
8. approved leave change/cancel/return → S8
9. overtime request vs fact → S6
10. closed period correction → S9
11. Payroll amount 不进 HR11 → S9/S10
12. 最终状态可解释 → S5 RuleExplanation
13. 跨午夜/时区 → S4
14. 设备故障 → S4/S6
15. 敏感医疗/定位/生物识别 → S1/S4/S7
16. 无 legacy fallback → S10
17. as-of → S2/S3
18. Excel 错误行 → S1/S10
19. provider failure 测试 → S11
20. 多租户越权测试 → S1/S11

> 状态：`DRAFT_V1`。
