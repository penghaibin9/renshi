# HR11-HR12 迁移施工图

> 施工线 F：`agent/refactor-f-hr11-hr12`
> 接管目标：`agent/renshi-takeover-cleanup-20260810`
> 权威文档：`11_HR11_考勤与请假_施工总册_终极版.md`、`12_HR12_年度与聘期考核_施工总册_终极版.md`

## 1. 目录归属

| 模块 | 新 Authority 目录 | 旧能力来源 | 裁决 |
|---|---|---|---|
| HR11 考勤与请假 | `hr_time/` | `attendance/`、`leave/`，以及 biometric/geofencing/facedetection 等采集能力 | **REWRITE + ADAPT**：采集技术可适配，班次、请假、工时/月结和历史事实归 HR11 |
| HR12 年度与聘期考核 | `hr_assessment/` | `pms/` goal/feedback 等技术能力 | **REWRITE**：考核周期、方案版本、指标、评分、结果、申诉与冻结事实归 HR12 |

## 2. 小白目录规则

所有正式规则只进入 `hr_time/` 与 `hr_assessment/` 的 models/services/selectors/providers/api/tests。旧 `attendance/`、`leave/`、`pms/` 和设备采集目录只做 adapter/legacy source，不允许继续产生新 Authority 规则。

## 3. 搬迁顺序

1. HR11 盘点 attendance/leave/shift/hour account 与设备采集入口，先把“原始采集事实”和“考勤判定/月结事实”分开。
2. 请假、加班、调休、班次变更必须保留有效期和审批依据；设备数据不能直接覆盖正式月结结果。
3. HR12 盘点 pms goal/feedback 的可复用技术，重建正式考核周期、方案版本、对象范围、指标快照、评分和结果冻结。
4. HR12 的数据库约束、迁移和命名必须通过 MySQL gate；SQLite 通过不视为生产通过。
5. 两模块的跨域数据只读 provider；HR12 可引用 HR10/HR11 等事实，但不得反向修改来源域。
6. 新旧对账、租户/越权/审计和 MySQL 回归通过后才冻结旧写入口，最后再删除废弃代码。

## 4. 当前已落地骨架

`hr_time/` 与 `hr_assessment/` 已有 README、`module_contract.py` 和合同测试；HR12 还已增加命名约束合同测试，后续必须继续按 MySQL 生产口径验证。

## 5. 下一块代码

优先施工 **HR11 attendance/leave legacy read adapter + 原始事实/判定事实分层测试**；HR12 随后把一个 pms goal/feedback 读取链路迁入 selector/provider，并补 MySQL 命名约束回归，不删除原 pms 页面。
