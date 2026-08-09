# HR06 S12 封板评估（Authority 切换评估 · 对照总册 §82）

> 依据：《06_HR06_人事异动_施工总册_终极版》§82 最终封板条件 + 当前 `feature/hr06-changes` 分支实现。
> 评估日期：2026-08-09。
> 结论：**HR06 READY FOR ACCEPTANCE（V1 功能范围）**，剩余为跨模块/生产环境项，列于"开放项"。

---

## 1. 业务闭环（总册 §82 业务）

| 项 | 状态 | 实现位置 |
|---|---|---|
| 5 个三级模块 | ✅ | HR06-01 申请中心（S3）、HR06-02 校内调动（S4）、HR06-03 岗位身份（S5）、HR06-04 借调挂职（S6）、HR06-05 台账（S7） |
| 永久/临时/兼岗/身份变化语义正确 | ✅ | ApplyService 按动作分派（S8）；兼岗 CONCURRENT 不覆盖主岗；临时含 return 语义 |
| future effective 正确 | ✅ | APPROVED_WAITING_EFFECTIVE + 到期调度（hr06_dispatch_due）+ 提前生效需 force_early |
| correction/rescind 正确 | ✅ | Correction≠Change（§34/§35）；Rescind 依赖检查 DEPENDENT_CHANGES_EXIST（§37） |
| before/after 与影响可解释 | ✅ | ImpactSnapshot + EffectiveSnapshot（before/after/checksum） |

## 2. 数据（总册 §82 数据）

| 项 | 状态 | 说明 |
|---|---|---|
| HR03 effective-dated 正确 | ✅ | Apply 只经 HR03 domain service（switch_primary/create/close/update_category/update_relationship_type） |
| HR02 occupancy 正确 | ✅ | PositionGate reserve/commit/release + check_capacity（HELD 计入占用） |
| one-primary 不变 | ✅ | HR03 DB 条件唯一 + 行锁双重保障（未新增第二套） |
| Legacy projection 对账 | ✅ | S9 投影 + S10 reconcile（HR06_PROJECTION_DRIFT 只记录不静默修） |
| 历史 as-of 正确 | ✅ | 台账 as-of 查询走 HR03 EffectiveDatedQueryService |

## 3. 安全（总册 §82 安全）

| 项 | 状态 | 说明 |
|---|---|---|
| tenant | ✅ | 全表 tenant_id + fail-closed context；S11 跨租户隔离测试 |
| source/target scope | ✅ | ApprovalService 双组织审批链 + target authorization |
| correction/rescind | ✅ | 高权限码 hr.change.correct/rescind |
| export/后台任务 | ⚠️ | export 审计已具备（hr.change.ledger.export）；后台任务显式 tenant 参数 |

## 4. 技术（总册 §82 技术）

| 项 | 状态 | 说明 |
|---|---|---|
| migrations | ✅ | 0001-0005（action/reason/field → case 域 → extension → outbox → authority mode） |
| DB constraints | ✅ | case_no tenant 唯一、proposal 唯一、downstream 唯一、effective_to>from |
| idempotency | ✅ | source_business_type/source_business_id 幂等键 + PositionGate idempotency_key |
| row lock | ✅ | select_for_update（case/approval/HR02 reserve） |
| rebase | ✅ | RebaseService（NO_CONFLICT/REBASE_REQUIRED/HARD_CONFLICT） |
| outbox | ✅ | HrChangeOutboxEvent 同事务写入 + 事件集（§59） |
| retry/reconciliation | ✅ | APPLY_FAILED 可重试 + S10 对账 |
| API contract | ✅ | /api/hr/v1/changes/* envelope + 错误码（§47）+ 中文 label 成对 |
| observability | ⚠️ | 事件/日志字段齐备；生产指标埋点待 HR00 统一基建 |

## 5. 前端（总册 §82 前端）

| 项 | 状态 | 说明 |
|---|---|---|
| 5 个工作区完整 | ✅ | 中心/调动/身份/借调/台账（服务端渲染 + API 驱动） |
| 视觉统一 | ✅ | 共用 hr_changes 基础样式，中文 |
| difference/impact/future 状态清晰 | ✅ | Before/After、影响面板、future 徽章 |
| E2E / 视觉回归 / 无障碍 | ⚠️ | 服务层/API 单测齐备；浏览器 E2E 待 HR00 测试基建 |

## 6. 开放项（不阻塞 V1 功能验收，需跨模块/生产完成）

1. **Authority 正式切换**：`hr06_switch_authority --tenant=1 --mode=HR06_AUTHORITY` 需与 HR03/HR02 cutover、旧页面下线协调（00 §56）。
2. **批量 Excel**：模板→staging→错误工作簿流程（00 §33）待接 HR00 Excel 基建。
3. **下游真实对接**：HR07/HR15/HR11 事件消费者（S8 已入队；消费端由各模块 S10 事件接收落实）。
4. **生产指标/日志**：hr06_* metrics 待 HR00 可观测性基建。
5. **MySQL 目标库回归**：migrations/FK/唯一/索引在 MySQL 全绿（00 §26）。
6. **hr_staff test_pages 4 个既有页面测试**：RequestFactory 缺 session 的环境问题，非 HR06 回归。

## 7. 测试规模

- hr_changes：**130 tests OK（1 skip）**（S1-S12）。
- hr_staff 核心服务：19 tests OK（HR06 新增 2 个 additive 方法无回归）。

---

**结论：HR06 READY FOR ACCEPTANCE（V1 功能范围）。** 开放项全部为跨模块/生产基建，按 00 全局 Gate 统一推进。
