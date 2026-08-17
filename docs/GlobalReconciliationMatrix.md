# GlobalReconciliationMatrix

> 来源：00_高校人事系统全局架构与Horilla接管合同.md §47, §55, §62
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09

---

## 1. 定期对账清单

| # | 对账双方 | 对账内容 | 频率 | 实现状态 |
|---|---|---|---|---|
| 1 | **HR02 ↔ HR03** | Position 编制 ↔ StaffAssignment 实际任职 | 日 | ⚠️ HR02 有 3 处占位等待 HR03 任职事实层 |
| 2 | **HR02 ↔ HR14** | Position 编制 ↔ 岗位聘任 | 日 | 待 HR14 开窗 |
| 3 | **HR07 ↔ HR03** | Contract ↔ EmploymentRelationship | 日 | 待 HR07 开窗 |
| 4 | **HR15 ↔ 财务/支付** | Payroll period ↔ Payment/Fiance posting | 月结后 | 待 HR15 开窗 |
| 5 | **HR16 ↔ HR03** | Exit ↔ EmploymentRelationship 关闭 | 离校生效后 | 待 HR16 开窗 |
| 6 | **HR16 ↔ HR14** | Exit ↔ Appointment 关闭 | 离校生效后 | 待 HR14/16 开窗 |
| 7 | **HR16 ↔ IAM** | Exit ↔ 账号停权 | 离校生效后 | 待 HR16 + IAM 对接 |
| 8 | **HR18 ↔ 源 Snapshot** | Submission ↔ source snapshot | 上报前 | 待 HR18 开窗 |
| 9 | **HR08 ↔ IAM** | ACADEMIC_IDENTITY_DRIFT | 日 | ✅ HR08 reconciliation_service 已实现 |
| 10 | **HR08 ↔ ACCESS** | ACCESS_OUTLIVES_ENGAGEMENT | 日 | ✅ HR08 reconciliation_service 已实现 |
| 11 | **Legacy ↔ New Authority** | DUAL_READ_COMPARE（Projection vs Authority） | Cutover 期间高频 | ✅ HR03/05 S11 已实现 |
| 12 | **HR18 Submission ↔ External Receipt** | 正式上报 ↔ 主管部门回执 | 上报后 | 待 HR18 开窗 |
| 13 | **HR16 Archive Transfer ↔ ArchiveProvider** | 档案转递 ↔ 接收回执 | 转递后 | 待 HR16 + ArchiveProvider |

---

## 2. 对账规则

- 对账发现 discrepancy → 不自动修复，生成 reconciliation report
- 严重差异 → 人工介入，走 `DataQualityFinding`
- `DataQualityFinding` 只发现/跟踪，不直接改 Authority
- 对账结果记录：ruleVersion/severity/objectRef/observed/expected/owner/status/resolution/evidence

---

## 3. DUAL_READ_COMPARE 规则（§55 Cutover 阶段）

```text
NEW_STAGING
→ DUAL_READ_COMPARE
    ├── 同请求同时读 Legacy 和 New Authority
    ├── 比较结果 → compare report
    ├── 不一致 → discrepancy log（不自动覆盖）
    └── 一致性达标 → SHADOW_EXECUTION
```

HR03 DUAL_READ_COMPARE 已实现：
- `reconciliation.py` 比较两个投影结果
- `management/commands/hr03_migrate.py` Wave 0/1/2
- 测试用 mock 占位验证（Legacy Employee 依赖全栈，CI 补真实对账）

---

## 4. 备份恢复对账（§62）

恢复后必须执行：

| # | 对账项 | 验证方式 |
|---|---|---|
| 1 | Projection 重建 | 重建后与 Authority 对账 |
| 2 | Outbox 重复检查 | 恢复后 Outbox 按 eventId 去重 |
| 3 | Inbox 重复检查 | 恢复后 Inbox 按 eventId 去重 |
| 4 | HR02↔03↔14 对账 | 恢复后重新跑对账 |
| 5 | HR07↔03 对账 | 恢复后重新跑对账 |
| 6 | HR15↔Finance 对账 | 恢复后重新跑对账 |
| 7 | HR16↔IAM 对账 | 恢复后重新跑对账 |
| 8 | HR18 Submission↔External Receipt | 恢复后重新跑对账 |

不能只恢复数据库然后看页面能打开（只看 `health=200`）。

---

## 5. Legacy Projection 对账

Cutover 后 `New Authority → Legacy Projection` 单向，定期对账确保：
- Projection 无遗漏
- 旧 UI/form 进入 readonly/redirect
- Legacy formal write attempts = 0

---

## 6. 对账指标（Observability）

```text
reconciliation_drift_total        — 总漂移数
reconciliation_drift_by_pair      — 按对账 pair 分组
reconciliation_execution_duration — 对账耗时
legacy_write_attempts_total       — 旧写入口调用次数（Cutover 后应为 0）
```

---

*由 00_高校人事系统全局架构与Horilla接管合同.md §160 自动生成。*
