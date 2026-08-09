# HR06 GAP MATRIX（S0 基线复审 · 现状→目标差距矩阵）

> 依据：《06_HR06_人事异动_施工总册_终极版》§80 S0 + 当前 `renshi` 仓库真实代码（2026-08-09 复审）。
> 范围：5 个三级模块 + 横向硬合同（A0/effective-dated/Case 状态机/Impact/审批/台账/Outbox/权限）。
> 严重度：P0=阻塞封板；P1=必须 S1-S12 内完成；P2=可后置但必须登记。
> 已就绪依赖：HR02（hr_structure，组织/岗位/预占/重组）、HR03（hr_staff，Person/Staff/Relationship/Assignment effective-dated + 服务契约）均已交付。

---

## 1. 横向硬合同缺口（决定 S1-S2 架构）

| ID | 能力 | 现状（代码事实） | 目标 | 缺口 | 严重度 | 归属阶段 |
|---|---|---|---|---|---|---|
| G-H-01 | HR06 模块存在性 | **无 `hr_changes` app**；未注册 INSTALLED_APPS | 独立 app + 页面路由 `/hr/changes/*` + API `/api/hr/v1/changes/*` | 全缺（NEW） | P0 | S1 |
| G-H-02 | A0 tenant fail-closed | `hr_control_center.context.resolve_tenant_from_request` 复用；hr_staff/hr_onboarding 模式可照抄 | 所有 HR06 表带 tenant_id；请求无 tenant → 403 fail-closed | 复用即可 | P0 | S1 |
| G-H-03 | effective-dated `[from,to)` | HR03 `HrStaffAssignment` 已半开区间 + `EffectiveDatedQueryService` | HR06 Case 的 requested/approved effective_at 语义；Apply 走 HR03 service | **基本闭合**（HR06 自己新增日期字段需一致） | P0 | S2/S8 |
| G-H-04 | Case 状态机 | HR03 `HrCorrectionCase`、HR02 `HrStructureChangeCase` 有状态机可参考；HR06 无 | DRAFT→…→EFFECTIVE/CLOSED + REJECTED/WITHDRAWN/CANCELLED/APPLY_FAILED/RESCINDED/CORRECTED | 全缺 | P0 | S2 |
| G-H-05 | RETURNED≠REJECTED | HR03 correction 状态机含 RETURNED/RESUBMITTED 可参考 | HR06 Case 显式区分；重新提交产生新版本 | 缺（需独立实现） | P0 | S2 |
| G-H-06 | Future-dated 队列 | 无 HR06 调度；HR02 `effective_runner` 模式可参考 | `APPROVED_WAITING_EFFECTIVE` + 到期 Scheduler + 人工提前生效（需 reason+审计） | 全缺 | P0 | S8 |
| G-H-07 | 未来事件冲突/Rebase | HR03 switch_primary 有重叠检测；无 HR06 base snapshot | `NO_CONFLICT/REBASE_REQUIRED/HARD_CONFLICT`；base_snapshot_version/base_effective_at | 全缺 | P0 | S2/S8 |
| G-H-08 | 并发控制 | HR03 用 select_for_update + version + 条件唯一 | Case 行锁 + 审批并发重检 + position 预占防超卖 | 需 HR06 独立实现 | P0 | S2/S8 |
| G-H-09 | 权限码 | HR03 `hr.staff.*` 已按 00 §28.2 命名 | `hr.change.*` + `hr06.*` alias 迁移；ScopeEnforcer 数据裁剪 | 缺（S1 建权限常量） | P0 | S1 |
| G-H-10 | 统一事件/Outbox | HR03 `HrOutboxEvent`、HR05 `HrOnboardingOutboxEvent` 已有；00 §28.3 冻结 `PersonnelChangeEffective` | HR06 outbox（Approved/Effective/…）同事务写入 | 缺（可复用 HR03 outbox 或独立） | P1 | S8 |
| G-H-11 | 审批并发重检 | 无 | approve 时重检 status 快照/岗位容量/未来冲突 | 缺 | P0 | S2/S8 |
| G-H-12 | 正式结果不可原地改 | HR03/HR02 均遵守 | EffectiveSnapshot 不可变；correction 走受控流程 | 缺 | P0 | S2/S7 |
| G-H-13 | 审计 | `HrStaffAuditEvent` 模式可参考；legacy HorillaAuditLog 不适合 | `HrChangeTransition` + audit 事件 | 缺 | P1 | S2 |

## 2. HR06-01 异动申请中心

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-01-01 | 异动中心首页 | 无 | `/hr/changes` + 统计卡（待我处理/审批中/待生效/本月生效/风险） | 全缺 | P0 | S3 |
| G-01-02 | 发起向导 | 无 | Step1-6（选人→类型→When&Why→Proposed→Preview→提交） | 全缺 | P0 | S3 |
| G-01-03 | Action/Reason 联动 | 无 | HrChangeAction + HrChangeReason；action→reason 约束；版本化/停用 | 全缺 | P0 | S1 |
| G-01-04 | 申请人范围 | 无 | 不同 action 允许不同 initiator（本人/直属/学院人事/目标学院/校人事/重组管理员） | 全缺 | P1 | S1/S3 |
| G-01-05 | 双边组织审批 | 无 | Workflow Resolver 按 action/reason/scope；ApprovalSnapshot 冻结 | 全缺 | P1 | S3 |
| G-01-06 | Target Authorization | 无 | 创建可"申请调往"，正式批准必须 TargetOrg approver 或 school scope | 缺 | P0 | S3/S8 |
| G-01-07 | RETURN/RESUBMIT | 无 | 可补正重交；RETURNED≠REJECTED | 缺 | P0 | S3 |
| G-01-08 | Withdraw/Cancel | 无 | 发起人撤、管理员取消未生效 | 缺 | P1 | S3 |

## 3. HR06-02 校内调动

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-02-01 | ORG/POSITION/ORG_POSITION_TRANSFER | 无（legacy 直接改字段） | Case + Before/After + Apply 关旧段开新段 | 全缺 | P0 | S4 |
| G-02-02 | 岗位容量/预占 | HR02 `PositionService.reserve/commit/release` 已就绪 | 批准前 reserve，生效时 commit；旧岗 release；同一事务/可补偿 saga | 全缺（服务已可用） | P0 | S4/S8 |
| G-02-03 | Reporting Manager Policy | 无 | KEEP / DERIVE_FROM_TARGET_ORG / SELECT_EXPLICIT（action policy） | 缺 | P1 | S4 |
| G-02-04 | 历史教务不污染 | 无 | 只发布 `StaffAssignmentChanged(effective_at)`；下游当前目录更新不回写历史 | 缺 | P1 | S4/S8 |
| G-02-05 | 调动页面 | 无 | 当前任职↔拟调任左右对照 | 缺 | P0 | S4 |

## 4. HR06-03 岗位与身份变更

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-03-01 | POST_CATEGORY_CHANGE | 无（legacy JobPosition/EmployeeType 混） | 岗位类别（专业技术/管理/工勤） | 全缺 | P0 | S5 |
| G-03-02 | EMPLOYEE_CATEGORY_CHANGE | 无 | 人员类别（专任教师/辅导员/管理/其他专技/工勤）↔ HrStaffMaster.staff_category_code | 全缺 | P0 | S5 |
| G-03-03 | EMPLOYMENT_TYPE_CHANGE | 无 | 用工性质；Policy：UPDATE_RELATIONSHIP / CLOSE_AND_CREATE_RELATIONSHIP / REQUIRE_HR07_CONTRACT | 缺 | P0 | S5 |
| G-03-04 | ADD/END_SECONDARY_ASSIGNMENT | 无 | 兼岗不覆盖主岗（create CONCURRENT assignment） | 缺 | P0 | S5 |
| G-03-05 | PRIMARY_ASSIGNMENT_SWITCH | HR03 `switch_primary` 已实现（one-primary 约束） | HR06 Case 调用 HR03 switch_primary | 全缺（服务已可用） | P0 | S5/S8 |
| G-03-06 | Change Matrix 页面 | 无 | 维度表（岗位类别/人员类别/用工性质/主岗/考勤/薪酬） | 缺 | P1 | S5 |
| G-03-07 | HR07/HR15 follow-up | 无 | `ContractReviewRequired` / `CompensationRecalculationRequested` outbox 事件 | 缺 | P1 | S8 |

## 5. HR06-04 借调挂职

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-04-01 | Temporary link | 无 | `HrTemporaryAssignmentLink`（source/temp/expected_return/return_case） | 全缺 | P0 | S2/S6 |
| G-04-02 | Source Policy | 无 | KEEP_ACTIVE / SUSPEND / REDUCE_FTE | 缺 | P1 | S6 |
| G-04-03 | RETURN_FROM_TEMPORARY | 无 | Return Service：关 temp、恢复/调整 source、检查原岗仍有效 | 缺 | P0 | S6 |
| G-04-04 | 原岗已撤销 exception | HR02 close_position 已就绪 | `RETURN_TARGET_INVALID` → human resolution → new return target → approval | 缺 | P0 | S6 |
| G-04-05 | 延期 | 无 | `TemporaryAssignmentExtension`（old/new return_at + reason + approval） | 缺 | P1 | S6 |
| G-04-06 | 到期/超期提醒 | HR05 reminders 模式可参考 | due/overdue 通知 | 缺 | P2 | S6 |

## 6. HR06-05 异动台账

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-05-01 | 台账列表 | 无 | `/hr/changes/ledger` + 筛选（年度/学院/动作/原因/状态/生效区间/发起组织/目标组织/人员） | 全缺 | P0 | S7 |
| G-05-02 | Case Detail Tabs | 无 | 变更摘要/Before-After/审批/影响/生效快照/下游同步/附件/Correction-Rescind/审计 | 全缺 | P0 | S7 |
| G-05-03 | EffectiveSnapshot 不可变 | 无 | `HrChangeEffectiveSnapshot` + checksum | 缺 | P0 | S2/S7 |
| G-05-04 | Correction | HR03 correction 模式可参考 | `HrChangeCorrection` 高权限受控；影响下游必须 Impact Analysis | 缺 | P0 | S7 |
| G-05-05 | Rescind | 无 | `RESCIND_REQUESTED→APPROVED→APPLYING→RESCINDED`；依赖检查 `DEPENDENT_CHANGES_EXIST` | 缺 | P0 | S7 |
| G-05-06 | As-of 互相验证 | HR03 `EffectiveDatedQueryService` 可参考 | 台账与 HR03 facts 可互相验证 | 缺 | P1 | S7 |
| G-05-07 | 导出 | HR03 export 模式可参考 | ledger export + scope 审计 | 缺 | P2 | S7 |

## 7. 批量异动与 Excel

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-07-01 | 批量模型 | HR02 `HrStructureChangeCase/Item` 可参考 | `HrBulkChangeBatch/Item`；每人独立 Case | 缺 | P1 | S8 |
| G-07-02 | 批量失败策略 | 无 | PREVALIDATE_ALL + ATOMIC_BATCH/ITEMIZED_COMMIT + error workbook + retry | 缺 | P1 | S8 |
| G-07-03 | Excel 输入渠道 | legacy `bulk_create_work_info` 直改（禁） | 模板→staging→校验→preview→确认→异步执行（00 §33） | 缺 | P2 | S8 |

## 8. Legacy/切换

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-08-01 | 受管字段入口清点 | **已物化**（HR06_LegacyChangeMapping.md §2，20 个入口） | 全部标策略 | 已完成 | — | S9 |
| G-08-02 | Legacy Projection | 无 | HR03 事实 → WorkInformation 投影 | 缺 | P0 | S9 |
| G-08-03 | 批量 UPDATE 封堵 | `save_employee_bulk_update`（views.py:1511）存在 | 禁直改受管字段 | 缺 | P0 | S9 |
| G-08-04 | DUAL_WRITE_COMPARE | HR03 authority_mode/DataBasis 模式可参考 | 投影漂移 `HR06_PROJECTION_DRIFT` 记录不静默修 | 缺 | P1 | S10 |
| G-08-05 | Authority 切换 | HR03 `authority_mode_service`、HR02 `cutover` 模式可参考 | `LEGACY_ACTIVE→…→NEW_AUTHORITY→LEGACY_READONLY` | 缺 | P1 | S12 |

## 9. 质量/安全/测试

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-09-01 | 数据质量命令 | HR03 `hr03_data_quality` 模式可参考 | EFFECTIVE 无 snapshot / 双主岗 / occupancy 超额 / projection drift 等 | 缺 | P1 | S11 |
| G-09-02 | 并发测试 | HR03/HR05 test_concurrency 可参考 | 抢岗位/同日双调动/future 冲突/双 approve/调度与人工 Apply | 缺 | P0 | S11 |
| G-09-03 | 安全负测 | HR03/HR05 test_security 可参考 | 跨校/跨学院/IDOR/scope/export/批量 scope | 缺 | P0 | S11 |
| G-09-04 | E2E | HR03/HR05 模式 | 申请→source→target→HR→future→生效→投影→台账 | 缺 | P1 | S11 |
| G-09-05 | 前端中文化 | 各 HR 模块已有 `labels.py`+成对 label 规范 | HR06 全部可见文案中文 + Django i18n | 缺 | P1 | 全程 |

---

**结论：HR06 为 NEW 模块（绿地）。复用 HR02/HR03 已交付服务与公共模式，缺失集中在 HR06 自己的 Case 域模型、状态机、Apply、台账、权限与前端。P0 缺口全部需在 S1-S8 内闭合，S9-S12 为切换/质量/封板。**
