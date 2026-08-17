# HorillaGlobalTakeoverMatrix

> 来源：00_高校人事系统全局架构与Horilla接管合同.md §106–§119
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09
> 原则：Horilla 旧系统只能被接管、投影和退出，不能永久双主。

---

## 1. Horilla 模块 → 目标域接管矩阵

| Horilla 原始模块 | 目标域 | 裁决类型 | 说明 | S0 核查状态 |
|---|---|---|---|---|
| `employee.Employee` / `EmployeeWorkInformation` | **HR03** | `REWRITE + PROJECT` | 旧 current snapshot 只做兼容投影，不能承担历史 | ⚠️ 待核验目标分支 |
| `base.Company` / `Department` / `JobPosition` | **A0 / HR02** | `REWRITE / ADAPT` | 映射 Tenant/Org/Position；旧对象逐步只读 | ⚠️ 待核验目标分支 |
| `recruitment` | **HR04** | `REWRITE` | 复用 pipeline/UI 技术，重建高校招聘 Authority | ⚠️ 待核验目标分支 |
| `onboarding` | **HR05** | `REWRITE` | 复用 task/portal，重建 Activation + 跨域事务 | ⚠️ 待核验目标分支 |
| `payroll.Contract` | **HR07 / HR15** | `DEPRECATE + PROJECT` | 合同归 HR07；工资归 HR15 | ⚠️ 待核验目标分支 |
| `attendance` / `leave` | **HR11** | `REWRITE` | 保留采集/申请能力，重建高校规则与月结 | ⚠️ 待核验目标分支 |
| `pms` | **HR12** | `REWRITE` | 保留 goal/feedback 技术，重建正式考核 | ⚠️ 待核验目标分支 |
| `payroll` | **HR15** | `REWRITE` | 保留 payslip/allowance/job，重建薪酬 Authority | ⚠️ 待核验目标分支 |
| `offboarding` | **HR16** | `REWRITE` | 保留 Task/Pipeline，重建 ExitCase/RetirementFact | ⚠️ 待核验目标分支 |
| `employee ESS/dashboard` | **HR17** | `REWRITE` | 管理指标回 HR01；普通员工统一 HR17 | ⚠️ 待核验目标分支 |
| `report` | **HR18** | `REWRITE` | 保留 dynamic report/pivot/template，重建指标/质量/交换/上报 | ⚠️ 待核验目标分支 |
| `horilla_documents` | **全域** | `KEEP / ADAPT` | 做安全 Document Provider | ⚠️ 待核验目标分支 |
| `horilla_audit` | **全域** | `KEEP / ADAPT` | 补 correlation/高敏审计 | ⚠️ 待核验目标分支 |
| `notifications` | **全域** | `KEEP / ADAPT` | 事件驱动、模板版本、去重和回执 | ⚠️ 待核验目标分支 |

---

## 2. 裁决类型定义

```text
KEEP          — 保留原模块，仅做安全加固/适配
ADAPT         — 适配为 Provider/Adapter/占位，不新建 Authority
REWRITE       — 完全重建新的 Authority 模型，旧模块只做 Legacy Projection
PROJECT       — 新 Authority → 单项投影到旧模块（读写分离）
READONLY      — 旧模块只读，写入口全部关闭
DEPRECATE     — 弃用，写入口冻结，只保留兼容读取
DROP_AFTER_CUTOVER — Cutover 验证后从代码中移除
```

---

## 3. 接管策略双层语义（P0-04 已修正）

`strategy.authority` 与 `strategy.legacy_technical_reuse` 是两层独立维度：

| 模块 | strategy.authority | strategy.legacy_technical_reuse | 说明 |
|---|---|---|---|
| HR04 recruitment | `REWRITE` | `ADAPT` (pipeline/UI/filter/portal where safe) | 不能把 Horilla Candidate/Onboarding Stage 当新系统正式 Authority |
| HR05 onboarding | `REWRITE` | `ADAPT` (task/portal/workflow UI where safe) | 不能把 Horilla Onboarding Stage 当新系统正式 Authority |
| HR02 base | `REWRITE` | `ADAPT` (Company→Tenant mapping) | 旧 Company/Department/JobPosition 逐步只读 |

---

## 4. Horilla Signal 治理

- S0 必须清点所有 `signal/save hook/thread-local side effects`
- 正式跨域副作用迁入 domain service + outbox
- 禁止继续依赖 Horilla 原始 signal 链执行 Authority 逻辑

---

## 5. Legacy Cutover 统一流程

```text
LEGACY_ACTIVE
→ NEW_STAGING
→ DUAL_READ_COMPARE
→ SHADOW_EXECUTION
→ FREEZE_LEGACY_FORMAL_WRITES
→ NEW_AUTHORITY
→ LEGACY_READONLY_PROJECTION
→ POST_CUTOVER_CLEANUP
```

- Cutover 后：legacy formal write attempts 必须为 0
- 旧 deep link → redirect
- No silent fallback (`catch Exception → legacy` 禁止)
- Rollback 回入口/consumer，不删除已发生的新正式事实

---

## 6. LegacyDataMapping 规则

- 旧字段 → 新 Authority：必须记录 transform、trust level、tenant/person resolution、effective date、conflict、evidence
- 旧库数据不自动标记为 `VERIFIED`
- 迁移信任等级：
  ```text
  MIGRATED_VERIFIED   — 人工验证通过
  MIGRATED_PARTIAL    — 部分字段可靠
  MIGRATED_UNVERIFIED — 未验证
  ```

---

## 7. 当前 Legacy Mapping 文件清单

| 文件 | 模块 | 状态 |
|---|---|---|
| `legacy/LegacyDataMapping.md` | HR01 | ✅ 已物化 |
| `legacy/HR02_LegacyDataMapping.md` | HR02 | ✅ 已物化 |
| `legacy/HR03_LegacyDataMapping.md` | HR03 | ✅ 已物化 |
| `legacy/HR04_LegacyDataMapping.md` | HR04 | ✅ 已物化 |
| `legacy/HR05_LegacyOnboardingMapping.md` | HR05 | ✅ 已物化 |
| `legacy/HR05_RecruitToHireMapping.md` | HR04→HR05 | ✅ 已物化 |
| `legacy/HR06_LegacyChangeMapping.md` | HR06 | ✅ 已物化 |
| `legacy/HR07_LegacyContractMapping.md` | HR07 | ✅ 已物化 |
| `legacy/HR08_LegacyExternalWorkerMapping.md` | HR08 | ✅ 已物化 |
| `legacy/HR11_LegacyAttendanceMapping.md` | HR11 | ✅ 已物化 |
| `legacy/HR11_LegacyLeaveMapping.md` | HR11 | ✅ 已物化 |
| `legacy/HR11_LegacyShiftMapping.md` | HR11 | ✅ 已物化 |
| `legacy/HR11_LegacyHourAccountMapping.md` | HR11 | ✅ 已物化 |

---

## 8. Horilla Company 接管（§9）

- `Company` / `selected_company` 只能作为 Legacy/兼容来源
- S0 必须给出 Tenant ↔ Company 映射、跨法人策略、后台 Job tenant 解析
- 退出 thread-local 的计划：新 Authority 不能依赖有 HTTP request 才能保证租户隔离
- 已实施：HR02 `hr_structure` 将 Company→Department→JobPosition 映射为 Tenant→HrOrganization→HrPosition

---

*由 00_高校人事系统全局架构与Horilla接管合同.md §160 自动生成。*
