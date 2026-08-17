# HR11 LegacyLeaveMapping（初版 · 依据真实仓库核对）

> 文档性质：HR11-S0 前置交付；依据 `renshi` 仓库真实模型/字段核对后物化。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork 克隆基线）+ HR01 阶段提交
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`
> 权威事实源：`docs/11_HR11_考勤与请假_施工总册_终极版.md`

---

## 1. 结论先行

- Legacy Horilla Leave 是 **“假别目录 + 余额数字 + 4 状态申请”**，不是“版本化假别政策 + 账户 Ledger + 预占 + Absence Fact + 销假/变更”的权威账本。
- 总册对 HR11 接管策略 = **REWRITE AS AUTHORITY**；Legacy leave 最终降级为 projection。
- 核心缺陷（S0 确认）：
  1. `AvailableLeave.available_days` 是**单一 running total**，无 Ledger、无 reversal、无 expiry/usage 明细；
  2. 申请状态仅 `requested/approved/cancelled/rejected` 四态，**无 RETURNED、无 SCHEDULED/IN_PROGRESS/RETURNED_FROM_LEAVE、WITHDRAW 与 CANCEL 未区分**；
  3. 余额扣减发生在**审批动作**（无事务化预占/并发锁），存在并发超卖窗口；
  4. 无 `HrAbsenceFact`、无 approval snapshot（只有 `LeaveRequestConditionApproval` 链 + `HorillaAuditLog` 历史）；
  5. 年休假**无工作年限法定档评估**，全部依赖人工分配 `AvailableLeave`；
  6. 无寒暑假交互、无未休结算投影。

## 2. Legacy 模型清单（真实仓库核对）

| 模型 | 表语义 | HR11 裁决 |
|---|---|---|
| `LeaveType` | 假别目录 + 部分规则字段 | `RECALCULATE` → `HrLeaveType` + `HrLeavePolicyVersion` |
| `LeaveTypeCondition` | 假别适用条件（gender/department/…） | `RECALCULATE` → eligibility rule |
| `AvailableLeave` | 员工×假别 余额行 | `RECALCULATE` → `HrLeaveAccount` + `HrLeaveLedgerEntry` |
| `LeaveRequest` | 请假申请（4 状态） | `RECALCULATE` → `HrLeaveRequest` + `HrAbsenceFact` |
| `LeaveRequestConditionApproval` | 多级审批链 | `COMPAT_ONLY` → `HrLeaveApprovalSnapshot` 生成器 |
| `LeaveAllocationRequest` | 额度分配申请 | `RECALCULATE` → `LeaveAdjustmentCase` 流程 |
| `CompensatoryLeaveRequest` | 调休申请（关联 Attendance） | `RECALCULATE` → `HrCompTimeAccount/Ledger` + leave request |
| `RestrictLeave` | 限制请假日期（部门/岗位） | `RECALCULATE` → ScheduleException/政策规则 |
| `LeaverequestFile` / `LeaverequestComment` | 附件/评论 | `MIGRATE` → `HrLeaveEvidence` / comment |
| `LeaveGeneralSetting` | 调休开关 | `COMPAT_ONLY` → 并入政策版本 |
| `EmployeePastLeaveRestrict` | 禁止补过去假 | `COMPAT_ONLY` → 政策规则 |
| `OverrideLeaveRequests` | 空壳（signal 迁移用，注释掉） | `DROP_AFTER_CUTOVER` |
| `MultipleApprovalCondition`(base) | 条件多级审批配置 | `RECALCULATE` → approval rule version |

## 3. 字段级映射

### `LeaveType` → `HrLeaveType` + 政策版本（RECALCULATE）

| Legacy 字段 | 处置 | 说明 |
|---|---|---|
| `name` | `MIGRATE` | `HrLeaveType.name` |
| `payment` / `payment_type` / `payment_percentage` | `RECALCULATE` | **付费分类应移入 `LeavePolicyVersion`（HR15 结算分类），不留在目录级**；迁移期保留显示 |
| `count` / `period_in` / `limit_leave` / `total_days` | `RECALCULATE` | 进入 grant/entitlement 规则 |
| `reset` / `reset_based` / `reset_month` / `reset_day` / `reset_weekend` / `custom_reset_days` | `RECALCULATE` | 进入 accrual/reset 规则；旧实现有缺陷（月/周/自定义混合） |
| `carryforward_type` / `carryforward_max` / `carryforward_expire_in` / `_period` / `_date` | `RECALCULATE` | 进入 carry_forward/expiry 规则 |
| `require_approval` / `require_attachment` | `MIGRATE` | approval/evidence 规则 |
| `exclude_company_leave` / `exclude_holiday` | `RECALCULATE` | 进入 duration engine 的日历排除规则 |
| `is_compensatory_leave` | `MIGRATE` | 标记补偿假别；与调休账户分开 |
| `conditions` (M2M) | `RECALCULATE` | eligibility rule（gender 等敏感条件尽量经 HR03 Provider 判定） |
| `company_id` | `MIGRATE` | tenant 归属 |

### `AvailableLeave` → `HrLeaveAccount` + Ledger（RECALCULATE）

| Legacy 字段 | 处置 | 说明 |
|---|---|---|
| `employee_id` | `MIGRATE` | `staff_id` |
| `leave_type_id` | `MIGRATE` | `leave_type_id` |
| `available_days` | `RECALCULATE` | **只作对账起点；Authority 余额 = Ledger 求和** |
| `carryforward_days` | `RECALCULATE` | 迁为 `CARRY_FORWARD` ledger 条目 |
| `total_leave_days` | `RECALCULATE` | 展示字段，权威改为实时计算 |
| `assigned_date` / `reset_date` / `expired_date` | `MIGRATE` | 作为 GRANT/expiry 时间线参考 |

**禁止**：把 `available_days` 直接抄成 Authority 唯一事实（无 ledger、无 reversal 溯源）。

### `LeaveRequest` → `HrLeaveRequest` + `HrAbsenceFact`（RECALCULATE）

| Legacy 字段 | 处置 | 说明 |
|---|---|---|
| `employee_id` / `leave_type_id` | `MIGRATE` | staff / leave_type |
| `start_date` / `end_date` | `MIGRATE` | start_at/end_at 起点（迁移为含时区当天范围） |
| `start_date_breakdown` / `end_date_breakdown` | `RECALCULATE` | **升级为 partial day/hour 语义（HALF_DAY_AM/PM/HOURS）** |
| `requested_days` | `RECALCULATE` | 旧算法基于日期相减 + 排除节假日；必须用 Duration Engine（按 ScheduleSnapshot）重算 |
| `leave_clashes_count` | `RECALCULATE` | 旧逻辑按部门/岗位统计，语义模糊；Authority 改为正式 overlap 检查 |
| `description` | `MIGRATE` | reason_text（sensitive 标记待定） |
| `attachment` | `MIGRATE` | → `HrLeaveEvidence`（私有存储 + 短期签名 URL） |
| `status`（requested/approved/cancelled/rejected） | `RECALCULATE` | 状态机扩展：SUBMITTED/UNDER_REVIEW/SCHEDULED/IN_PROGRESS/COMPLETED/RETURNED_FROM_LEAVE + RETURNED/WITHDRAWN/VOID |
| `approved_available_days` / `approved_carryforward_days` | `RECALCULATE` | 迁移为 usage ledger 条目 |
| `reject_reason` | `MIGRATE` | 审批决策记录 |
| `created_by` | `MIGRATE` | 申请者快照 |

**关键不变量**：
- `approved` 的旧数据 → 需要按（是否已发生、是否已销假）分类；**已销假 ≠ 已请假**；
- 已批准的旧申请不可直接改日期；变更必须走 `LeaveChangeCase`；
- 取消已部分使用的申请必须计算已用 portion，禁止整额恢复。

### `CompensatoryLeaveRequest` → 调休账户（RECALCULATE）

| Legacy 字段 | 处置 |
|---|---|
| `attendance_id`(M2M Attendance) | `RECALCULATE` → 来源必须是 **verified overtime fact**，禁止直接引用日卡片 |
| `requested_days` / `status` | `RECALCULATE` → `HrCompTimeAccount/Ledger` credit/debit |

## 4. 无法迁移/必须人工裁决

- 历史上“余额被直接改”的调整（无证据）→ 迁移为 `ADMIN_CONFIRMED` 的一次性 `ADJUST` 条目并留痕；
- 已批准但已过期的额度 → `EXPIRE` 条目；
- 跨年结转口径不一致 → 以学校提供年结清单为准，不自行推断；
- 年休假法定档（1/10/20 年）→ **全部重算**，不以旧余额为准。

## 5. 迁移阶段（对齐 HR11-S10）

```
M0 盘点 → M1 对账基线（余额=旧 available_days 快照）
→ M2 HrLeaveType + PolicyVersion 建设
→ M3 账户迁移（GRANT/ADJUST/MIGRATION 条目）
→ M4 历史申请迁移（4 状态 → 新状态机，含销假事实重建）
→ M5 双读对账（余额/申请/使用）
→ M6 旧写入口关闭 → Authority Cutover → 封板
```

## 6. 退出合同

- Authority 后 `AvailableLeave/LeaveRequest` 全部只读投影；
- 旧表单/API 关闭，返回 `HR11_LEGACY_WRITE_DISABLED`；
- `leave/signals.py`（审批→写 WorkRecords ABS/CONF）与 `leave/scheduler.py` 在 Authority 前冻结。

> 状态：`DRAFT_V1`。HR11-S7/S8 建模型时升级。
