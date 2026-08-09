# HR11 LegacyAttendanceMapping（初版 · 依据真实仓库核对）

> 文档性质：HR11-S0 前置交付；依据 `renshi` 仓库真实模型/字段核对后物化。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork 克隆基线）+ HR01 阶段提交（`bebd299`/`32a88ac`，feature/hr01-control-center）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1` —— HR11 编码期以最终 Authority 模型核对后升级
> 权威事实源：`docs/11_HR11_考勤与请假_施工总册_终极版.md`

---

## 1. 结论先行

- Legacy Horilla Attendance 是**“日考勤卡片 + 可变活动记录”**，不是“版本化规则 + 不可变事件 + 评估事实”的权威时间账本。
- 总册对 HR11 接管策略 = **REWRITE AS AUTHORITY**；Legacy attendance 最终降级为 projection / compatibility，不再双写权威。
- 本映射文档给出每个 Legacy 字段的处置标记：
  `MIGRATE / PROJECT / COMPAT_ONLY / RECALCULATE / STAGING / DROP_AFTER_CUTOVER`。

## 2. Legacy 模型清单（真实仓库核对）

| 模型 | 表语义 | HR11 裁决 |
|---|---|---|
| `AttendanceActivity` | 打卡活动（in/out 配对），**可原地修改** | `STAGING`（只作为迁移参考源；不得直接当 Raw Event 真值） |
| `Attendance` | 每日考勤卡片（unique employee+date） | `RECALCULATE`（迁移为 `HrAttendanceDayFact` 必须重算，不能直接抄字段） |
| `AttendanceOverTime` | 月度小时账户（worked/pending/overtime） | `RECALCULATE` → `HrTimeBalanceLedger` |
| `AttendanceLateComeEarlyOut` | 迟到/早退记录 | `RECALCULATE` → `HrAttendanceException` |
| `AttendanceValidationCondition` | 全局唯一验证/OT 自动审批配置 | `DROP_AFTER_CUTOVER`（单行全局配置违反政策版本化） |
| `GraceTime` | 宽限时间（单默认值 + shift 引用） | `COMPAT_ONLY` → 并入 `HrShiftVersion.grace_*` |
| `AttendanceGeneralSetting` | 打卡开关 | `COMPAT_ONLY` → 并入 TimePolicy/RecordingProfile |
| `WorkRecords` | 日工作状态投影（FDP/HDP/ABS/HD/CONF/DFT） | `PROJECT`（只读投影；禁止继续当权威） |
| `AttendanceAllowedIP`(base) | IP 白名单 | `ADAPT`（服务端 enforcement 保留） |
| `TrackLateComeEarlyOut`(base) | 迟到早退跟踪开关 | `DROP_AFTER_CUTOVER`（并入 PolicyVersion） |
| `PenaltyAccounts`(base) | 迟到/早退/请假扣减账户 | `RECALCULATE`（扣减规则移入 HR15 basis；HR11 只留 fact） |

## 3. 字段级映射

### `AttendanceActivity` → 迁移参考（STAGING）

| Legacy 字段 | 类型 | 处置 | 说明 |
|---|---|---|---|
| `employee_id` | FK Employee | `MIGRATE` | 映射到 `staff_master_id`（经 HR03 person mapping） |
| `attendance_date` | Date | `RECALCULATE` | 事件自然日 ≠ shift_business_date；跨午夜需重判 |
| `shift_day` | FK EmployeeShiftDay | `PROJECT` | 由 ScheduleAssignment 投影 |
| `in_datetime` / `out_datetime` | DateTime (naive) | `RECALCULATE` | 无时区；按 tenant IANA 重算 UTC + local |
| `clock_in` / `clock_in_date` | Time/Date | `STAGING` | 进入 `HrRawTimeEvent` 迁移清洗，不直接落库 |
| `clock_out` / `clock_out_date` | Time/Date | `STAGING` | 同上；无 out 的活动 = `MISSING_OUT` 候选 |

**风险点**：`clock_out` 会被新一次 clock_in 原地关闭（`clock_in_attendance_and_activity`），且 `Attendance.delete()` 会级联删除活动记录 → **原始事件可丢失**，历史恢复受限，迁移 Trust Level 只能到 `LEGACY_UNVERIFIED`/`ADMIN_CONFIRMED`。

### `Attendance` → `HrAttendanceDayFact`（RECALCULATE）

| Legacy 字段 | 处置 | Authority 映射 |
|---|---|---|
| `employee_id` | `MIGRATE` | `staff_master_id` |
| `attendance_date` | `MIGRATE` | `business_date`（需按跨午夜修正后确认） |
| `shift_id` / `work_type_id` / `attendance_day` | `PROJECT` | schedule_snapshot_json 的投影来源 |
| `attendance_clock_in`/`_date`、`attendance_clock_out`/`_date` | `STAGING` | 评估参考，不直接作为事实字段 |
| `attendance_worked_hour` / `at_work_second` | `RECALCULATE` | `actual_minutes` 必须按规则重算（去重、扣休、配对） |
| `minimum_hour` | `RECALCULATE` | `expected_minutes` 来自 ShiftVersion/Calendar，禁止沿用旧值 |
| `attendance_overtime` / `overtime_second` | `RECALCULATE` | 旧算法 = worked − minimum 的简单差，违反总册 §78；必须重算 |
| `attendance_overtime_approve` | `RECALCULATE` | 批准状态需要审计链；旧布尔无审批人快照 |
| `attendance_validated` | `STAGING` | 映射到 fact.status / validation 阶段 |
| `is_holiday` | `RECALCULATE` | 基于 `HrCalendarDay.day_type` 重判 |
| `request_type` / `requested_data` / `is_validate_request` / `is_validate_request_approved` | `STAGING` | 进入 `HrAttendanceCorrectionCase` 迁移 |
| `approved_by` | `MIGRATE` | approval snapshot actor |
| `batch_attendance_id` | `PROJECT` | 保留引用，Authority 后不再承载编辑 |

**禁止**：直接把 `attendance_worked_hour`/`attendance_validated` 抄成 Authority 事实（旧数据 trust 不足、算法已被规则替换）。

### `WorkRecords` → 只读投影（PROJECT）

| Legacy 字段 | 处置 |
|---|---|
| `work_record_type`(FDP/HDP/ABS/HD/CONF/DFT) | `PROJECT`：由 `HrAttendanceDayFact.status` 投影；**禁止再用 DFT/CONF 代表事实** |
| `at_work`/`min_hour`/`at_work_second`/`min_hour_second` | `PROJECT` |
| `is_attendance_record` / `attendance_id` | `PROJECT`（保留关联） |
| `is_leave_record` / `leave_request_id` | `PROJECT`（保留关联） |
| `shift_id` / `day_percentage` / `message` / `last_update` | `PROJECT` |

**风险点**：`scheduler.py create_work_record` 每 30 分钟为所有有 shift 的员工补 `DFT` 行；`leave/signals.py` 审批通过后写入 `ABS`/`CONF`。这些投影若被 Payroll/报表当“旷工真值”，会污染工资与考核 → **必须在 Authority 切转前冻结 legacy write 入口（S10）并让投影只读**。

## 4. 迁移数据来源与 Trust Level

| 数据 | 来源 | 建议 Trust |
|---|---|---|
| 设备打卡（biometric 拉取） | `BiometricEmployees` + 拉取线程 → AttendanceActivity | `LEGACY_UNVERIFIED`（无签名/幂等键；可重复拉取） |
| Web/移动打卡 | clock_in/out 视图 | `ADMIN_CONFIRMED`（有账号，但时间可伪造） |
| Excel 导入（attendance import / activity import） | `pd.read_excel` 视图 | `ADMIN_CONFIRMED` |
| 手工补录/批处理 | BatchAttendance | `ADMIN_CONFIRMED` |

**原则**：没有 raw/source 证据的历史“出勤”，绝不伪装成设备 VERIFIED。

## 5. 迁移阶段（总册 §195 HR11-S10 对齐）

```
M0 盘点 → M1 双读对账基线（LEGACY_AUTHORITY）
→ M2 HrRawTimeEvent 迁移清洗（事件重建，保留 legacy 引用）
→ M3 DayFact 重算（规则版本化评估）
→ M4 WorkRecords 投影冻结（只读）
→ M5 旧写入口关闭（表单/API 403）
→ M6 Authority Cutover 演练 → 双月对账 → 封板
```

## 6. 退出合同

```
LEGACY_AUTHORITY → HR11_STAGING → DUAL_READ_COMPARE → HR11_AUTHORITY → LEGACY_READONLY_PROJECTION
```
- Authority 后：`Attendance/AttendanceActivity/WorkRecords` 全部只读投影；旧表单关闭；旧 write API 返回 `HR11_LEGACY_WRITE_DISABLED`；禁止 fallback。
- Cutover 硬门：员工映射 100%、日事实重算通过抽样对账、WorkRecords 投影与 DayFact 偏差全部解释、Payroll basis 影子对账 green。

> 状态：`DRAFT_V1`。HR11-S1 建基时升级到 `REVIEWED`。
