# HR11_TIME_POLICY_MATRIX（初版 · 依据真实仓库核对）

> 文档性质：HR11-S0 前置交付；描述 Legacy 现有“时间政策”事实 vs 总册目标 `HrTimePolicyPack/Version + RecordingProfile + Calendar + Shift + Schedule` 的映射，作为 S2/S3 施工依据。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`

---

## 1. 结论

- Legacy **没有政策概念**：考勤行为由 `EmployeeWorkInformation.shift_id/work_type_id` + 全局单行配置（`AttendanceValidationCondition`/`GraceTime`/`AttendanceGeneralSetting`）决定。
- 没有 eligibility、没有版本、没有适用范围、没有冲突裁决 → 无法回答"这个人今天为什么适用这套规则"。
- HR11-S2/S3 将整套重建为版本化政策，下表为拆解依据。

## 2. 政策要素矩阵（Legacy → HR11）

| 要素 | Legacy 实现 | 问题 | HR11 目标 | 阶段 |
|---|---|---|---|---|
| 记录方式 recording method | 无；所有人默认"打卡+日卡片" | 教师/外聘/值班无法差异化 | `HrTimeRecordingProfile.method`（FIXED/FLEXIBLE/NEGATIVE/ABSENCE_ONLY/OVERTIME_ONLY/DUTY_BASED/HYBRID） | S2 |
| 打卡开关 | `AttendanceGeneralSetting.enable_check_in`（company FK） | 全局/公司级，非人员级 | 政策版本内配置 + eligibility | S2 |
| 宽限 grace | `GraceTime`（单一默认值 + shift FK 引用） | 单默认值；in/out 分离但不版本化 | `HrPolicyVersion.grace_policy_json`（late/early/minutes/free count） | S2 |
| 取整 rounding | 无 | 无 | `rounding_policy_json`（raw 永不取整） | S2 |
| 缺卡 missing punch | 无；无卡则无 Attendance 行 | 缺卡=无事实=被 WorkRecords DFT 兜底 | `missing_punch_policy`（MISSING_TIME → 核查） | S2 |
| 验证条件 | `AttendanceValidationCondition.validation_at_work`（**单行全局**，`clean()` 禁止多行） | 无法按学校/人员差异化 | `HrPolicyVersion` 内嵌 + 评估器版本 | S2 |
| OT 审批 | `AttendanceValidationCondition.minimum_overtime_to_approve/overtime_cutoff/auto_approve_ot` | 单行全局；auto-approve 无审计 | overtime_policy_ref（request vs fact） | S2/S6 |
| 迟到早退 | `TrackLateComeEarlyOut.is_enable`（company FK）+ GraceTime | 开关级 | exception 目录 + grace 版本 | S2/S5 |
| 缺勤判定 | 无正式规则；由报表/WorkRecords 推断 | `ABS` 推断不可信 | absence_policy（UNEXCUSED_ABSENCE 候选流程） | S2 |
| 工作日历 | `Holidays`（recurring/is_specific）+ `CompanyLeaves`（周规则） | 无年度版本、无调休、无 day_type | `HrWorkCalendar/Version/Day` | S2 |
| 班次 | `EmployeeShift` + `EmployeeShiftSchedule`（周模板） | 无版本/生效日 | `HrShiftDefinition/Version` | S3 |
| 轮班 | `RotatingShift` + `RotatingShiftAssign` | 启发式 JSON | `HrWorkPattern` | S3 |
| 排班 | `EmployeeWorkInformation.shift_id` + assign | 无 as-of | `HrScheduleAssignment` | S3 |
| 异常排班 | 无 | 全缺 | `HrScheduleException` | S3 |
| 适用优先级 | 无；默认取当前 shift | 冲突静默 | `resolve_time_policy()` + `TIME_POLICY_AMBIGUOUS` fail-closed | S2 |

## 3. Recording Method 现状判定（Legacy 数据无法区分）

Legacy 无法区分“教师负向考勤 / 行政固定考勤”，因为：
- `EmployeeWorkInformation` 只有 `employee_type_id`/`shift_id`，无 recording profile；
- 总册 §25 明确**禁止** `if employee_type=="teacher": no attendance`。

S2 施工必须：为每个 tenant 建立默认 RecordingProfile（FIXED_POSITIVE_TIME），教师/弹性/值班等由 `HrTimePolicyPack.policy_family` 显式建模（ADMIN_FIXED/TEACHER_FLEX/LAB_SHIFT/SECURITY_ROTATION/COUNSELOR_DUTY/EXTERNAL_SERVICE/OTHER），学校可扩展。

## 4. 政策版本验收点（S2/S3 自检）

- [ ] `resolve_time_policy(staff, assignment, as_of)` 可解释（policyVersionId/calendarVersionId/method/scheduleSource/matchedRules/reason）
- [ ] PUBLISHED 后 immutable（DB guard + content_hash）
- [ ] 发布前 gate：eligibility overlap/calendar/shift/OT/leave policy 齐全
- [ ] 规则变更不污染历史（as-of 引用当时版本）
- [ ] 教师 NEGATIVE_TIME：无打卡不产生缺勤
- [ ] 多 Assignment：primary + overlays + duty events，冲突形成 TimeConflict 不静默
- [ ] `HrCalendarDay` 支持 7 种 day_type，含 MAKEUP_WORKDAY（调休）
- [ ] 跨午夜班次 `shift_business_date` 正确

## 5. 联动确认

- 政策适用人员来自 HR03（staff_master/assignment）；HR03 Authority 仓库尚未实现，S2 的 eligibility 读取先走 `Employee/EmployeeWorkInformation` 过渡 Provider，**接口按 HR03 目标模型预留，读取失败必须 fail-closed（SOURCE_UNAVAILABLE），禁止静默回退**。
- 规则变化不得触发历史月结重算（关闭期间保留旧版本引用）。

> 状态：`DRAFT_V1`。S2/S3 实现时升级。
