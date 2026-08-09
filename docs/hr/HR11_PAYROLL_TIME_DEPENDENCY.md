# HR11_PAYROLL_TIME_DEPENDENCY（初版 · HR15 冲突面审计）

> 文档性质：HR11-S0 硬门交付。**先画依赖图再动工**，避免与 HR15 施工窗口冲突。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`
> 参考：`docs/15_HR15_薪酬福利_施工总册_终极版.md` §22（HR11 边界）、§72（考勤扣款输入）、§191/§262

---

## 1. 依赖总图（当前实现 · Legacy 直读）

```text
                     ┌──────────────────────────────────────────────┐
                     │              payroll 模块（HR15）               │
                     │                                                │
  payroll/methods/methods.py  get_leaves()/get_attendance()/         │
  hourly_computation()/daily_computation()                           │
  payroll/methods/payslip_calc.py  FILTER_MAP + calculate_based_on_*  │
  payroll/views/views.py / component_views.py / dashboard.py          │
                     │                                                │
        ┌────────────┴─────────────┬──────────────────┬──────────────┘
        ▼                          ▼                  ▼
  attendance.Attendance      leave.LeaveRequest   base.Holidays/
  (attendance_validated,     (status="approved",   CompanyLeaves
   at_work_second,            leave_type.payment /  (get_working_days)
   overtime_second,           payment_type /
   attendance_overtime_       payment_percentage)
   approve)
        ▼                          ▼                  ▼
  attendance.WorkRecords  ←← leave/signals.py（审批写 ABS/CONF 投影）
  （scheduler 每30min补 DFT）└→ 也被报表/考核面读取
```

**结论**：当前 HR15 **直读 Legacy Attendance / LeaveRequest 模型**，无任何 Provider/Close 边界；HR11 raw/未月结数据可能直接进入工资计算。

## 2. 读取入口清单（真实代码定位）

| # | 入口 | 文件:行 | 读取对象/过滤条件 | HR11 处置 |
|---|---|---|---|---|
| R1 | `get_leaves(employee,start,end)` | `payroll/methods/methods.py:49-139` | `employee.leaverequest_set.filter(status="approved")`；`leave_type.payment/payment_type/payment_percentage` → paid/unpaid/custom 日期集 | 改读 `HrAbsenceFact`+close basis |
| R2 | `get_attendance(employee,start,end)` | `methods.py:145-189` | `Attendance.filter(attendance_validated=True)`；用 Holidays/CompanyLeaves 计算 working/conflict | 改读 DayFact（closed） |
| R3 | `hourly_computation` | `methods.py:192-225` | 遍历 validated Attendance，`at_work_second - overtime_second`，`wage/3600` | 改读 `HrPayrollTimeBasis.regular_work_minutes` |
| R4 | `daily_computation` | `methods.py:255-339` | `get_working_days` + `get_leaves` + 半日逻辑；`contract.calculate_daily_leave_amount / deduction_for_one_leave_amount`；custom payment 按 `1-pct/100` 扣 | 改读 unpaid_absence_minutes basis；扣率保留 HR15 |
| R5 | `FILTER_MAP` | `payslip_calc.py:40-75` | keys：leave(validated)/overtime(approve+validated)/attendance(validated) | 改读 close snapshot 字段 |
| R6 | `calculate_based_on_attendance` | `payslip_calc.py:868-898` | `Attendance.filter(validated)` count × `per_attendance_fixed_amount` | 改读 frozen attendance count |
| R7 | `calculate_based_on_shift` | `payslip_calc.py:905-934` | 同上 + shift 过滤 | 同上 |
| R8 | `calculate_based_on_overtime` | `payslip_calc.py:940-972` | `Attendance.filter(attendance_overtime_approve=True)`；`sum(overtime_second)` × 每秒金额 | 改读 `verified_overtime_minutes`（close basis） |
| R9 | `calculate_based_on_work_type` | `payslip_calc.py:983-1014` | validated + work_type | 同上 |
| R10 | `dispatch`/`payslip_generation` | `payslip_calc.py` 其余 + `views.py` 各 payslip 生成 | 组装上述计算结果 | 同 R3/R4 |
| R11 | `payroll/models/models.py:2363` | `EncashmentGeneralSettings.leave_amount`（假期折算参考） | HR11 只提供未休依据，折算值归 HR15 |
| R12 | `report/views/attendance_report.py` | 直读 Attendance 报表 | HR11 报表面改接 Provider（S10 后可保留 legacy 报表只读投影） |

## 3. Save 副作用清单（payroll → attendance/leave）

S0 审计确认：**当前 payroll 代码对 attendance/leave 无任何直接写回**（`OverrideAttendance/OverrideLeaveRequest` 全部为注释代码，未启用）。真正的写侧副作用发生在反向：

| 副作用 | 位置 | 说明 |
|---|---|---|
| `leave/signals.py leaverequest_pre_save` | 审批通过 → 写 `attendance.WorkRecords` ABS/CONF | 供报表/工资"出勤/缺勤"面；**Authority 后此投影改为由 AbsenceFact 生成** |
| `attendance/signals.py attendance_post_save` | 日卡片保存 → 写 `attendance.WorkRecords` FDP/HDP/ABS/CONF | 同上 |
| `attendance/scheduler.py create_work_record` | 每 30 min 为有 shift 员工补 DFT 行 | **风险**：被报表/考核当"缺勤/待核"面 |
| `attendance/signals.py create_attendance_setting` | Company 创建时建 AttendanceGeneralSetting | 只影响开关 |

HR11 不做工资计算；HR15 不反向写 HR11 原始事实（总册 §20/§199）。

## 4. 冲突矩阵（HR11 S9/S10 与 HR15 窗口）

| 事项 | HR11 承诺 | HR15 依赖 | 冲突窗口 | 协调方式 |
|---|---|---|---|---|
| 月结冻结 | S9 提供 `HrTimeClosePeriod/Snapshot` | HR15 需确认 close 后 basis 可用 | 同一月结时间点 | 先冻结 HR11，再允许 HR15 读取；未 close 不得进入 payslip |
| Payroll basis 字段 | `HrPayrollTimeBasis`（不含金额） | HR15 计算金额 | S9 | 字段名在 S9 冻结前与 HR15 窗口对齐 |
| 加班 | `HrOvertimeFact VERIFIED` + `settlement_mode` | OT 金额/补休 | S6/S9 | HR11 不写金额；`PAY_CANDIDATE` 只是候选 |
| 请假扣款 | unpaid_absence_minutes / paid_classification | 扣率/金额 | S7/S9 | 分类+时长归 HR11，金额归 HR15（对齐 §262） |
| WorkRecords 投影 | 只读；Authority 后改投影 | 旧报表仍读 | S10 | 双读对账期保留；cutover 后旧面只读 |
| 历史数据 | Legacy 迁移 Trust=SYSTEM_DERIVED | 历史 payslip 已存在 | S10 | 迁移不改已发 payslip；只提供对账差异说明 |

## 5. 解耦计划（S9-S10 落地顺序）

1. **S9**：实现 `HrTimeClosePeriod/Snapshot` + `HrPayrollTimeBasis`；新增 `PayrollTimeProvider`（只输出 closed basis）；
2. **S9**：与 HR15 窗口对齐 basis 字段契约（regular_work_minutes/payable_authorized_absence_minutes/unpaid_absence_minutes/verified_overtime_minutes/comp_time_minutes/unexcused_absence_minutes/basis_version）；
3. **S10**：HR15 代码从 `Attendance/LeaveRequest` 直读切换到 Provider（影子对账期两路并行）；
4. **S10**：`payslip_calc.FILTER_MAP`/`methods.get_leaves/get_attendance` 改为 closed-basis 输入；`hourly_computation/daily_computation` 迁移；
5. **S10**：禁用 `leave/signals.py`、`attendance/signals.py` 的 WorkRecords 写投影与 `create_work_record` scheduler（Authority 后由 DayFact/AbsenceFact 投影生成）；
6. **S10**：旧报表只读投影；写入口返回 `HR11_LEGACY_WRITE_DISABLED`。

## 6. 硬门核对

- ✔ payroll 读 attendance/leave 的入口**已全部列出**（R1-R12）；
- ✔ payroll 的 save 副作用：**当前无直接写回**；反向写投影的 4 个副作用已列出；
- ✔ 不重写 HR15 薪酬计算逻辑，只提供考勤事实与依赖清单；
- ✔ 冲突窗口与协调方式已记录，S0 后动工按 §5 顺序执行，避免与 HR15 窗口冲突。

> 状态：`DRAFT_V1`。S9 冻结 basis 契约时升级为 `REVIEWED`。
