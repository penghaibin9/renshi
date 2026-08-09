# HR11 LegacyHourAccountMapping（初版 · 依据真实仓库核对）

> 文档性质：HR11-S0 前置交付；依据 `renshi` 仓库真实模型/字段核对后物化。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork 克隆基线）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`
> 权威事实源：`docs/11_HR11_考勤与请假_施工总册_终极版.md`（§64, §77-79, §118）

---

## 1. 结论先行

- Legacy 工时账户 = `AttendanceOverTime`（按月汇总行），维护 `worked/pending/overtime` 三个**展示字符串 + 秒数冗余**。
- 它**不是 Ledger**：没有 credit/debit 流水、没有 reversal、没有 source 追溯、没有 balance_after；月汇总通过 `Attendance.save()` 的 **diff 机制**增量维护（`hour_account_second + diff_work` 等），且存在 `update_ot()` 独立重算路径，**两条路径并存，历史漂移风险**。
- HR11 采用 **REWRITE**：`HrTimeBalanceLedger`（account_type/credit/debit/source_type/reversal/balance_after）为权威；`AttendanceOverTime` 降级为对账投影。

## 2. Legacy 模型字段

### `AttendanceOverTime`
| Legacy 字段 | 类型 | 处置 | 说明 |
|---|---|---|---|
| `employee_id` | FK | `MIGRATE` | `staff_id` |
| `month` | Char | `MIGRATE` | 迁移为 account period（year + month index） |
| `month_sequence` | SmallInt | `RECALCULATE` | 月序冗余；Authority 由日期推导 |
| `year` | Char | `MIGRATE` | account_year |
| `worked_hours` / `hour_account_second` | Char/Int | `RECALCULATE` | 进入 `HrTimeBalanceLedger`（credit 来源=DayFact actual） |
| `pending_hours` / `hour_pending_second` | Char/Int | `RECALCULATE` | 由 expected−actual 推导，**不迁移数值** |
| `overtime` / `overtime_second` | Char/Int | `RECALCULATE` | 旧值=worked−minimum 简单差；Authority 只计 **verified overtime fact** |

## 3. 关键行为审计（真实代码）

### 写入路径（两套并存，S0 确认）
1. **`Attendance.save()`（diff 机制，models.py §751-833）**：每次日卡片保存时计算 `diff_work / diff_approved_ot / diff_pending`，用 `F()` 表达式增量累加到当月 `AttendanceOverTime`，再刷新字符串展示字段。
2. **`Attendance.update_ot()` / `create_ot()`（models.py §878-952）**：按“已验证且非批准请假日”**重算整月** worked/pending；`Attendance.delete()` 后也会调用。
3. **`AttendanceOverTime.save()`（models.py §1246-1268）**：由秒数字段反推字符串展示（`format_time`），并推导 `month_sequence`。
4. **`ot.update_ot()` 存在独立审批逻辑**：`approved_overtime_second` 只累计“批准且非请假日”的 OT（`update_ot` 排除批准请假日期）。

**风险**：diff 路径与重算路径并存 → 同一月份不同入口可能给出不同数字；字符串/秒数字段双写易不一致；`Attendance.delete()` 触发 `update_ot` 但 diff 路径没有对应逆向，可能遗留不一致。

### 消费方（HR15 / 报表）
- `payroll/methods/payslip_calc.py` `calculate_based_on_overtime` 直接读 `Attendance.overtime_second`（`attendance_overtime_approve=True`）求和；
- `payroll/methods/methods.py` `hourly_computation` 读 `attendance.at_work_second - attendance.overtime_second`；
- `attendance/cbv/hour_account.py` 等页面直接展示 `AttendanceOverTime`。
→ **Authority 切换后这些消费方必须改为读 `HrTimeCloseSnapshot`/`HrPayrollTimeBasis`，禁止直读日卡片/月度行**（S10 解耦）。

## 4. 迁移策略

- **迁移值**：按 `(tenant, employee, year, month)` 迁移一个对账基线（`MIGRATION` 条目），并**标记 Trust = `SYSTEM_DERIVED`**（由旧 diff/重算产生，非设备来源）；
- **迁移流水**：若按月粒度重建 Ledger，则每笔 DayFact 生成 `credit`（actual）与 `pending`（expected−actual）条目，`source_type=ATTENDANCE_DAY_FACT_MIGRATION`；
- **调休**：Legacy `CompensatoryLeaveRequest` 的额度**不并入** `AttendanceOverTime`（那是加班余额，不是调休）；调休单独迁入 `HrCompTimeAccount/Ledger`；
- **对账**：`ledger 求和 == 旧 AttendanceOverTime 汇总`，差 = 历史漂移 → 生成 `LEAVE_LEDGER_DRIFT`/`HOUR_ACCOUNT_DRIFT` 风险并人工裁决，**禁止静默覆盖**。

## 5. Authority 设计要点（对应总册 §64）

```text
HrTimeBalanceLedger
- account_type: WORK_HOURS / OVERTIME / COMP_TIME / PENDING
- credit_minutes / debit_minutes
- source_type: ATTENDANCE_DAY_FACT / OVERTIME_FACT / COMP_TIME / ADJUST / MIGRATION / REVERSAL
- source_id / effective_date / reversal_of / balance_after
```

- **禁止只存 running total**；
- 加班只有 `HrOvertimeFact VERIFIED` 才能产生 credit；
- 调休与年休假**分账**；
- 月结后更正 → 先 reverse 再补新条目，不改历史条目。

## 6. 退出合同

- Authority 后 `AttendanceOverTime` 只读投影；
- `Attendance.save()` 中的 diff 侧写**必须移除**（Authority 由 DayFact 评估器驱动 Ledger）；
- `update_ot/create_ot` 关闭；旧 hour_account 页面改接 HR11 ledger 视图。

> 状态：`DRAFT_V1`。HR11-S5/S6 实现时升级。
