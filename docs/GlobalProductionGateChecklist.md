# GlobalProductionGateChecklist

> 来源：00_高校人事系统全局架构与旧系统接管合同.md §70, §153–§158
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09

---

## 1. 全系统施工阶段门控

| 阶段 | 含义 | 状态 |
|---|---|---|
| G0 | Baseline | ✅ 部分完成（7/18 模块有代码） |
| G1 | A0/Security foundation | 🔄 进行中 |
| G2 | Authority foundations (HR02/HR03) | 🔄 HR02 S8 完成 / HR03 S12 完成 |
| G3 | Cross-domain contracts | 🔄 HANDOFF + Service 契约已交付 |
| G4 | Features (HR04-16) | 🔄 4 模块接近封板 |
| G5 | Dual Compare | ⏳ 待 CI 环境 |
| G6 | Cutover | ⏳ 未开始 |
| G7 | Full Regression | ⏳ 未开始 |
| G8 | Production Readiness | ⏳ 未开始 |

---

## 2. 系统级最终商业化 Gate

只有以下全部绿色，才允许 `SYSTEM READY FOR PRODUCTION ACCEPTANCE`：

| Gate | 描述 | 状态 |
|---|---|---|
| `GLOBAL ARCHITECTURE CONTRACT READY` | 00 合同所有条款落实 | 🔄 本 Global-S0 产出物为此 Gate 服务 |
| `DOCUMENT CONTRACT BASELINE READY` | PATCH-00~12 全部完成 | 🔄 PATCH-00/01/03/05 已完成；PATCH-02/04 已裁决不迁移；其余待做 |
| `HR01 READY FOR ACCEPTANCE` | 人事工作台 READY | ⚠️ S1-S7 完成；Metric 待 HR18 |
| `HR02 READY FOR ACCEPTANCE` | 组织机构 READY | ⚠️ S1-S8 完成；S4-S6 部分待做 |
| `HR03 READY FOR ACCEPTANCE` | 教职工主档 READY | ⚠️ S0-S12 代码完成（169 tests OK）；待全栈 CI 签发 |
| `HR04 READY FOR ACCEPTANCE` | 招聘 READY | ❌ `HR04 NOT READY`（100/100 绿；S11 待 CI + E2E） |
| `HR05 READY FOR ACCEPTANCE` | 入职 READY | ❌ `HR05 NOT READY`（代码完成；待 CI） |
| `HR06 READY FOR ACCEPTANCE` | 异动 READY | ❌ 未开窗 |
| `HR07 READY FOR ACCEPTANCE` | 合同 READY | ❌ 未开窗 |
| `HR08 READY FOR ACCEPTANCE` | 外聘 READY | ⚠️ `HR08 NOT READY`（S13 封板评估；待 CI + B1-B7） |
| `HR09 READY FOR ACCEPTANCE` | 教师资格 READY | ❌ 未开工 |
| `HR10 READY FOR ACCEPTANCE` | 培训 READY | ❌ 未开工 |
| `HR11 READY FOR ACCEPTANCE` | 考勤 READY | ⚠️ S1-S9 完成（105/105 绿）；S10 待做 |
| `HR12 READY FOR ACCEPTANCE` | 考核 READY | ❌ 未开工 |
| `HR13 READY FOR ACCEPTANCE` | 职称 READY | ❌ 未开工 |
| `HR14 READY FOR ACCEPTANCE` | 聘任 READY | ❌ 未开工 |
| `HR15 READY FOR ACCEPTANCE` | 薪酬 READY | ❌ 未开工 |
| `HR16 READY FOR ACCEPTANCE` | 退休 READY | ❌ 未开工 |
| `HR17 READY FOR ACCEPTANCE` | ESS READY | ❌ 未开工 |
| `HR18 READY FOR ACCEPTANCE` | 数据中心 READY | ❌ 未开工 |
| `CROSS-DOMAIN E2E GREEN` | 12 条跨域 E2E 全绿 | ❌ 未执行 |
| `MYSQL FULL REGRESSION GREEN` | MySQL 全量回归全绿 | ❌ MySQL CI 不可用 |
| `SECURITY / TENANT ISOLATION GREEN` | 安全 + 租户隔离全绿 | ⚠️ 已施工模块各自有安全测试，但未全系统验证 |
| `BACKUP / RESTORE DRILL GREEN` | 备份恢复演练全绿 | ❌ 未执行 |
| `LEGACY FORMAL WRITES = 0` | Cutover 后旧写入口调用为 0 | ❌ 未 Cutover |
| `P0 = 0` | 零个 P0 缺陷 | ⚠️ 当前无已知 P0 代码缺陷 |
| `P1 BLOCKING = 0` | 零个 P1 阻塞项 | ❌ CI 环境、PG/MySQL 验收、跨模块联调等多 P1 阻塞 |

---

## 3. 跨模块 E2E 12 条必测清单（§99）

| # | E2E 场景 | 参与模块 | 状态 |
|---|---|---|---|
| 1 | HR02 Position → HR04 招聘 → HR05 入职 → HR03 Staff/Relationship/Assignment | HR02/03/04/05 | ❌ |
| 2 | HR03 Relationship → HR07 Contract → HR17 我的合同 | HR03/07/17 | ❌ |
| 3 | HR06 异动 → HR03 Assignment history → HR02 occupancy → HR15 reevaluation → HR18 as-of | HR02/03/06/15/18 | ❌ |
| 4 | HR10 verified 企业实践/培训 → HR09 双师证据 → HR12 考核证据 | HR09/10/12 | ❌ |
| 5 | HR11 TimePeriodClosed → HR15 PayrollFinalized → HR17 Payslip → HR18 cost | HR11/15/17/18 | ❌ |
| 6 | HR12 Final → HR13 Title Effective → HR14 Appointment Effective → HR15 Compensation Review | HR12/13/14/15 | ❌ |
| 7 | HR16 RetirementEffective → HR03 关系关闭 → HR14 聘任关闭 → HR15 final settlement → HR17 retiree | HR03/14/15/16/17 | ❌ |
| 8 | HR16 ExitEffective → IAM/资产/交接 → HR15 final settlement → HR18 turnover | HR15/16/18 | ❌ |
| 9 | 今天改变组织/职称/岗位/工资后，2024/2025 as-of 仍为当时事实 | HR02/03/07/14/15 | ❌ |
| 10 | HR02–HR16 → HR18 Snapshot → Validate → Approve → Send → Receipt → Correction | HR02-16/18 | ❌ |
| 11 | DisciplinaryDecision 生效后，HR14/15/16 各走自己流程，不自动跨域改事实 | HR03/14/15/16 | ❌ |
| 12 | HR16 档案转递 → ArchiveProvider → Receipt → Reconciliation → Closed | HR16/ArchiveProvider | ❌ |

---

## 4. Failure Injection 必测清单（§99）

| # | 故障场景 | 验证要求 | 状态 |
|---|---|---|---|
| 1 | Provider 500 / timeout | 无 silent fallback | ❌ |
| 2 | 请求超时但业务实际成功 | 幂等重放结果一致 | ❌ |
| 3 | 重复 webhook / event | Inbox 幂等去重 | ❌ |
| 4 | worker down | Job retry + 死信 | ❌ |
| 5 | Outbox 积压 | 可恢复消费 | ❌ |
| 6 | MySQL deadlock | retry + 一致性 | ❌ |
| 7 | 最后一个岗位额度并发竞争 | 防超卖 | ❌ |
| 8 | payroll finalize 重复请求 | 幂等 | ❌ |
| 9 | object storage outage | 文件操作 fail-safe | ❌ |
| 10 | IAM 停权失败 | 风险记录 + 重试 | ❌ |
| 11 | 电子签署成功但 callback 丢失 | 可查询/补消费 | ❌ |
| 12 | payment / finance partial success | 可跟踪/对账 | ❌ |
| 13 | HR18 SENT 长期无 receipt | 超时告警 | ❌ |
| 14 | restore 后 projection 缺失 | 可重建 | ❌ |
| 15 | legacy write 被旧书签调用 | metric 记录 | ❌ |
| 16 | 跨 tenant 猜 ID | 403 全拒绝 | ❌ |
| 17 | 权限缓存未失效 | 调离后不可继续访问旧学院 | ❌ |

**底线：绝不能造成** 重复 Staff、Contract、Appointment、Payroll、Submission 或跨租户泄露。

---

## 5. 全系统历史抽验（§154）

- 随机选人员跨 3–5 个历史日期查询：组织、岗位、合同、资格、考核、职称、聘任、工资、离退状态
- 今天修改组织/岗位/职称后，历史结果必须保持当时事实
- 状态：❌ 未执行

---

## 6. 全系统角色验收（§155）

需要正/负权限测试的角色：

| 角色 | 测试范围 |
|---|---|
| 学校人事管理员 | 全功能 |
| 人事负责人 | 审批/最终操作 |
| 学院秘书 | COLLEGE scope |
| 学院负责人 | COLLEGE scope + 审批 |
| 普通教职工 | SELF scope |
| 评委/专家 | ASSIGNED scope |
| 工资员 | HR15 payroll scope |
| 财务 | HR15 posting |
| IAM/资产/档案 | Provider API |
| 退休人员 | Retiree SELF |
| 外聘人员 | External SELF |
| 平台运营 | SYSTEM scope（无学校人事/工资权限） |

状态：❌ 未执行

---

## 7. 全系统上线顺序原则（§157）

```text
优先 HR02/HR03 基础 Authority
→ HR04/05/07 入人主链
→ HR08 外聘
→ HR09/10/11 教师发展与时间
→ HR12/13/14 评价裁决
→ HR15/16 薪酬离退
→ HR17 统一 ESS
→ HR18 统一数据中心
```

实际顺序以已施工状态和依赖图为准，不允许 18 个域同夜无演练切换。

---

## 8. 最终验收口径

```
GLOBAL ARCHITECTURE CONTRACT READY
```

若任何 Authority 重叠、tenant fail-open、silent legacy fallback、历史污染、跨域直写、目标数据库未验收、回滚/恢复缺失，则只能：

```
GLOBAL ARCHITECTURE CONTRACT NOT READY
blocking:
- <精确缺口>
```

---

## 9. 当前最紧迫的阻断项

| # | 阻断项 | 影响范围 | 优先级 |
|---|---|---|---|
| 1 | MySQL CI 环境不可用 | 全部（无法真验证数据库） | P0 |
| 2 | Docker/Playwright CI 不可用 | HR03-05/08/11 无法 E2E/性能验收 | P0 |
| 3 | PostgreSQL 并发测试未跑 | HR02/04 的 20 并发用例 | P1 |
| 4 | 备份恢复演练从未执行 | 全部 | P1 |
| 5 | hr_contracts (HR07) 未开窗 | HR08 Agreement gate 占位 | P2（HR08 用 UNAVAILABLE 占位） |
| 6 | IAM/教务真实接口未对接 | HR08 IAM/教务 Provider | P2（UNAVAILABLE 占位） |
| 7 | HR09-HR18 未开工 | 全系统 E2E | P2（按依赖顺序逐步推进） |

---

## 10. Global-S0 产物自我验收

| 文件 | 状态 |
|---|---|
| `GlobalAuthorityOwnershipMatrix.md` | ✅ 已生成 |
| `LegacySystemTakeoverMatrix.md` | ✅ 已生成 |
| `CrossDomainProviderEventMatrix.md` | ✅ 已生成 |
| `TenantIdentityPermissionMatrix.md` | ✅ 已生成 |
| `LegacyDataMappingIndex.md` | ✅ 已生成 |
| `MigrationDependencyGraph.md` | ✅ 已生成 |
| `TargetDatabaseCompatibilityMatrix.md` | ✅ 已生成 |
| `GlobalReconciliationMatrix.md` | ✅ 已生成 |
| `GlobalProductionGateChecklist.md` | ✅ 本文件 |

---

*由 00_高校人事系统全局架构与旧系统接管合同.md §160 自动生成。GLOBAL ARCHITECTURE CONTRACT READY ← 本批次 S0 产物交付后即达成。*
