# HR11 RISK_REGISTER（初版 · 依据真实仓库核对）

> 文档性质：HR11-S0 前置交付。风险 = 真实代码定位 + 总册红线对照 + owner/处理阶段。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1`

---

## 风险矩阵

| # | 级别 | 风险 | 代码证据 | 影响 | 处置阶段 |
|---|---|---|---|---|---|
| R01 | P0 | **服务器本地时间当"今天"** | `clock_in_out.py` `date.today()/datetime.now()`；`models.py` `datetime.now()`；`scheduler.py` `datetime.today()`；`leave/models.py` `date.today()` | 跨时区学校考勤/请假日期错乱（硬门 H0/A0） | S1 引入 tenant IANA；S4 事件规范化 |
| R02 | P0 | **A0 fail-open：无 request 上下文时不过滤 tenant** | `horilla_company_manager.py get_queryset()`：`company` 为 None 直接返回全量；scheduler/job 无 `_thread_locals.request` | 学校数据互读/串写 | S1 A0 加固 + 负向测试 |
| R03 | P0 | **NULL company 行对全校可见** | `get_queryset` 过滤带 `Q(...isnull=True)`；`Holidays/CompanyLeaves/GraceTime` 等 company 可 NULL | 一校配置污染全校 | S1/S2 政策版本化 + tenant 校验 |
| R04 | P0 | **原始打卡事件可被删除/修改** | `Attendance.delete()` 级联删 `AttendanceActivity`；`clock_in_attendance_and_activity` 原地关闭旧活动并重写 | 历史考勤不可恢复、审计断裂 | S4 不可变事件；S10 迁移 Trust=LEGACY_UNVERIFIED |
| R05 | P0 | **无设备幂等/签名 → 重复或伪造事件** | biometric 线程直接调用 `clock_in`（`biometric/views.py`）；无 source_event_id/幂等键/签名校验 | 重复工时、伪造打卡 | S4 ingestion pipeline |
| R06 | P0 | **WorkRecords 自动补 DFT + 审批写 ABS → 假缺勤面** | `attendance/scheduler.py create_work_record`（30min/cron）；`leave/signals.py`（approved→ABS/CONF）；`attendance/signals.py` | 报表/工资/考核误判旷工；教师被 DFT 淹没 | S2 recording profile；S6 缺卡核查；S10 冻结投影写 |
| R07 | P0 | **余额=单数字，无 Ledger、无预占、并发超卖** | `AvailableLeave.available_days`；余额扣减在审批动作（views），无行锁/版本 | 超卖、追溯不可行 | S7 Ledger；S8 预占+并发锁 |
| R08 | P0 | **月结冻结缺失：闭期事实可被任意 UPDATE/DELETE** | 无 close 概念；`Attendance/AttendanceActivity` 可直改直删 | 工资依据被篡改 | S9 月结硬闸门 |
| R09 | P1 | **Payroll 直读未月结考勤/请假模型** | `payroll/methods/methods.py`、`payslip_calc.py` 直查 `Attendance/LeaveRequest` | raw/未确认时间进入工资（违反 HR15 §22） | S9 basis；S10 Provider 切转 |
| R10 | P1 | **加班=简单差，无申请/事实分离、无审批审计** | `overtime_calculation()` = worked−min；`attendance_overtime_approve` 布尔 + 全局 auto_approve | 虚增加班、不可追溯 | S6 |
| R11 | P1 | **迟到早退=无证据布尔记录** | `AttendanceLateComeEarlyOut` 仅 type 字段 | 无法解释/申诉 | S5/S6 Exception Case |
| R12 | P1 | **无年休假法定档评估/寒暑假交互** | 年假全靠人工 `AvailableLeave`；无 service-years 计算 | 不合规/教师年假误判 | S7 |
| R13 | P1 | **请假状态机 4 态，RETURNED/销假/变更/部分取消缺失** | `LEAVE_STATUS` 4 态；销假无 case；cancel 直接恢复余额 | 业务闭环断裂 | S8 |
| R14 | P1 | **调休与年假混用字段/来源不可信** | `LeaveType.is_compensatory_leave` + `CompensatoryLeaveRequest.attendance_id`(M2M) | 调休余额失真 | S6 CompTime 分账 |
| R15 | P1 | **节假日无年度版本、无调休、重复覆盖历史** | `Holidays`(recurring/is_specific) + `CompanyLeaves`(周规则)；无版本 | 调休日判定错误、历史被覆盖 | S2 CalendarVersion |
| R16 | P1 | **跨午夜靠 12:00 启发式** | `clock_in_out.py` 用 `mid_day_sec` 判断夜班归属；`EmployeeShiftSchedule.is_night_shift` 由 start>end 推导 | 夜班/跨月跨年错误 | S3/S4 shift_business_date |
| R17 | P1 | **无时区处理，naive datetime** | `AttendanceActivity.in_datetime` naive；`timezone.localtime()` 用服务器 TZ；设备 TZ 不校验 | 跨时区打卡归错日 | S4 |
| R18 | P1 | **设备凭证明文入库** | `BiometricDevices.api_key/api_secret/zk_password/bio_password` 明文 | 泄露风险 | S4 secret_ref→Secret Manager；存量迁移 |
| R19 | P2 | **Geofencing 依赖 Nominatim 反地理编码（save 时网络调用）** | `geofencing/models.py clean()` | 保存失败/网络依赖/坐标永久保存 | S4 只存 verdict；去网络 |
| R20 | P2 | **Excel 导入可能半成功** | `attendance/views/views.py` import 逐行处理（生成错误行 Excel）；`leave/views.py` assign import | 部分写入无原子性 | S1/S10 异步 validate→preview→原子确认 |
| R21 | P2 | **全局单行配置** | `AttendanceValidationCondition` 单行（clean 禁止多行）；`GraceTime` 单默认 | 无法差异化 | S2 版本化 |
| R22 | P2 | **多 Assignment/教师差异不支持** | eligibility 只有 `EmployeeWorkInformation` 当前行 | 副岗/例外被忽略 | S2/S3 |
| R23 | P2 | **旧写入口未阻断期报表误读投影** | `report/views/attendance_report.py` 直读 Attendance | 双源不一致 | S10 |
| R24 | P2 | **日志/审计缺口：审批无快照、余额调整无 case** | 无 approval snapshot；无 LeaveAdjustmentCase | 审计合规风险 | S8/S11 |
| R25 | P2 | **HR03 Authority 未落地 → eligibility 依赖过渡 Provider** | 仓库无 `HrStaffMaster` 等 | 切换期数据错位 | S2 过渡 Provider fail-closed；S10 复核 |
| R26 | P2 | **设备数据缺失时无 SOURCE_UNAVAILABLE 语义** | 无 freshness/心跳判定；WorkRecords 照常 DFT | 设备断连被当无人打卡 | S4/S5 |
| R27 | P2 | **医疗/敏感字段最小化未落实** | `LeaveRequest.description` 自由文本；attachment 用 `upload_path` 公开存储 | 病假诊断泄露 | S7/S8 evidence + 权限 |
| R28 | P3 | **性能：月度汇总全表/字符串时间比较** | `AttendanceOverTime` 字符串 HH:MM 存储、`format_time` 反复解析 | 大数据量慢 | S5 ledger int minutes；S11 perf |

## 处理优先级说明

- **P0（6 项）**：S1/S4/S9 必须清零，否则封板失败（R01-R08）。
- **P1（12 项）**：S2/S6/S7/S8/S10 按阶段消化。
- **P2（10 项）**：S1-S10 随工程推进处理。
- **P3（1 项）**：S11 性能验收。

## 开放性事项（S0 无法定论的）

1. 目标学校现行考勤/请假/年休假/寒暑假/加班制度 → 需校方确认后填入 RuleVersion 基线；
2. HR03/HR15 窗口的 Provider 契约细节 → S2/S9 与对应窗口对齐；
3. 历史数据量/设备型号清单 → S10 迁移 job 需真实数据摸底；
4. 教务日程数据源 → S9 前需教务侧接口确认。

> 状态：`DRAFT_V1`。每阶段结项更新风险状态。
