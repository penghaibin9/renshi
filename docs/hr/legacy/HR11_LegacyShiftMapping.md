# HR11 LegacyShiftMapping（初版 · 依据真实仓库核对）

> 文档性质：HR11-S0 前置交付；依据 `renshi` 仓库真实模型/字段核对后物化。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork 克隆基线）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`
> 权威事实源：`docs/11_HR11_考勤与请假_施工总册_终极版.md`（§34-38, §104-144）

---

## 1. 结论先行

- Legacy Shift 体系 = `EmployeeShift/EmployeeShiftDay/EmployeeShiftSchedule/RotatingShift(Assign)/WorkType(Rotating)`，全部位于 `base` app。
- 它是**周循环固定班次 + 简易轮班**，**没有**：班次版本化、班次生效日期、跨午夜 `shift_business_date` 语义（只有 `is_night_shift` 布尔 + 12:00 启发式）、日历版本、个人/岗位排班赋值、ScheduleException。
- HR11 采用 **REWRITE**：`HrShiftDefinition/HrShiftVersion/HrWorkPattern/HrWorkCalendar(Version/Day)/HrScheduleAssignment/HrScheduleException` 为权威；Legacy base shift 降级为 projection。

## 2. Legacy 模型清单

| 模型 | 语义 | HR11 裁决 |
|---|---|---|
| `EmployeeShiftDay` | 周一~周日枚举行（day + company M2M） | `PROJECT`（不再作为权威；由 CalendarDay 生成） |
| `EmployeeShift` | 班次逻辑（weekly_full_time/full_time + grace FK） | `RECALCULATE` → `HrShiftDefinition` + 默认版本 |
| `EmployeeShiftSchedule` | 班次×星期 的 start/end/minimum_working_hour/night/auto-punch | `RECALCULATE` → `HrShiftVersion` + `HrWorkPattern` |
| `RotatingShift` | 轮班集合（shift1/shift2/additional_data） | `RECALCULATE` → `HrWorkPattern`（cycle 语义） |
| `RotatingShiftAssign` | 轮班指派（start/next_change/current/next_shift/based_on） | `RECALCULATE` → `HrScheduleAssignment` |
| `WorkType` | 工种（仅名称 + company M2M） | `COMPAT_ONLY`（若学校需要 authorized duty/工作类型，映射到 AuthorizedTimeType） |
| `RotatingWorkType` / `RotatingWorkTypeAssign` | 工种轮转 | `COMPAT_ONLY` |

## 3. 字段级映射

### `EmployeeShift` → `HrShiftDefinition`
| Legacy | 处置 | Authority |
|---|---|---|
| `employee_shift` | `MIGRATE` | `code/name` |
| `weekly_full_time` | `RECALCULATE` | 默认模式时长；Authority 以版本内最小工时为准 |
| `full_time` | `RECALCULATE` | 同上 |
| `days`(M2M via Schedule) | `RECALCULATE` | 生成 WorkPattern 的每周模板 |
| `grace_time_id` | `COMPAT_ONLY` | 并入 `HrShiftVersion.grace_in/out_minutes` |
| `company_id`(M2M) | `MIGRATE` | tenant 归属（M2M→单 tenant 需清理多公司关联） |

### `EmployeeShiftSchedule` → `HrShiftVersion` / `HrWorkPattern`
| Legacy | 处置 | 说明 |
|---|---|---|
| `day` | `RECALCULATE` | 周模板：生成 pattern_json（周一~周日） |
| `shift_id` | `MIGRATE` | 版本所属 shift |
| `minimum_working_hour` | `RECALCULATE` | → `standard_minutes`（同 shift 不同天时长不同，Authority 支持 per-day） |
| `start_time` / `end_time` | `RECALCULATE` | 保留分钟精度；**版本化生效日期** |
| `is_night_shift` | `RECALCULATE` | 旧字段由 `start>end` 自动推导；Authority 用 `cross_midnight` + 版本化 |
| `is_auto_punch_out_enabled` / `auto_punch_out_time` | `RECALCULATE` | 保留为班次特性，但须版本化 + 审计 |

### `RotatingShift` / `RotatingShiftAssign` → `HrWorkPattern` / `HrScheduleAssignment`
| Legacy | 处置 | 说明 |
|---|---|---|
| `RotatingShift.shift1/shift2/additional_data` | `RECALCULATE` | pattern_json 周期序列（做一休一/四班三运转等） |
| `RotatingShiftAssign.employee_id` | `MIGRATE` | schedule_assignment.staff_master_id |
| `start_date` / `next_change_date` | `RECALCULATE` | effective_from/to（下一变更需按 pattern 推导并校验连续性） |
| `current_shift` / `next_shift` | `RECALCULATE` | 由 pattern 推导，不信任存量冗余字段 |
| `based_on` / `rotate_after_day` / `rotate_every_weekend` / `rotate_every` | `RECALCULATE` | 并入 pattern 生成算法，代码不复制旧实现 |

### `WorkType` → `COMPAT_ONLY`
仅保留显示兼容。HR11 的 authorized duty / 工作类型走 `ScheduleException.exception_type` 与 `AuthorizedTimeType`，不复制 WorkType。

## 4. 关键缺口（Authority 必须补）

1. **班次版本化**：改班次 = 新 `HrShiftVersion`，历史 DayFact 引用旧版本；
2. **生效日期**：`effective_from/to` 于 ShiftVersion / ScheduleAssignment；
3. **跨午夜**：`shift_business_date` + `cross_midnight`，禁止 12:00 启发式；
4. **日历版本**：国家/学校日历 `HrWorkCalendarVersion` + `HrCalendarDay`（含调休 MAKEUP_WORKDAY）；
5. **个人/岗位排班**：`HrScheduleAssignment` as-of 查询；
6. **ScheduleException**：临时换班/出差/培训/教务任务 overlay；
7. **排班冲突**：`HARD_CONFLICT/SOFT_CONFLICT/SOURCE_UNAVAILABLE` 分级。

## 5. 迁移阶段

```
M0 盘点现有 shift/rotating 数据（按 tenant）
→ M1 ShiftDefinition+Version 导入（start/end/min_hour/grace）
→ M2 WorkPattern 生成（周模板/轮转周期）
→ M3 ScheduleAssignment 生成（按 EmployeeWorkInformation.shift_id + RotatingShiftAssign）
→ M4 校准跨午夜/节假日（与旧 is_night_shift 对齐抽查）
→ M5 双读对账（当日班次、最小工时）
→ M6 Authority Cutover → base shift 表单只读
```

## 6. 退出合同

- Authority 后 `EmployeeShift/EmployeeShiftSchedule/RotatingShift(Assign)` 只读投影；
- `Employee.get_shift_schedule()`、`shift_schedule_today()`、`auto_punch_out()` scheduler 改接 HR11 Provider；
- base 的班次表单关闭；write API 返回 `HR11_LEGACY_WRITE_DISABLED`。

> 状态：`DRAFT_V1`。HR11-S2/S3 建模型时升级。
