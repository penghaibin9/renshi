# LegacyDataMappingIndex

> 来源：00_高校人事系统全局架构与Horilla接管合同.md §53–§57
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09

---

## 1. Legacy 裁决类型定义

| 裁决 | 含义 |
|---|---|
| `KEEP` | 保留原模块，做安全加固/适配 |
| `ADAPT` | 适配为 Provider/Adapter/占位 |
| `REWRITE` | 完全重建新的 Authority 模型 |
| `PROJECT` | 新 Authority → 单向投影到旧模块 |
| `READONLY` | 旧模块只读，写入口全部关闭 |
| `DEPRECATE` | 弃用，写入口冻结 |
| `DROP_AFTER_CUTOVER` | Cutover 验证后从代码中移除 |

---

## 2. 已物化的 Legacy Mapping 文件清单

| 文件 | 模块 | 大小 | 状态 |
|---|---|---|---|
| `docs/hr/legacy/LegacyDataMapping.md` | HR01 | — | ✅ 已物化 |
| `docs/hr/legacy/HR02_LegacyDataMapping.md` | HR02 | — | ✅ 已物化 |
| `docs/hr/legacy/HR03_LegacyDataMapping.md` | HR03 | — | ✅ 已物化 |
| `docs/hr/legacy/HR04_LegacyDataMapping.md` | HR04 | — | ✅ 已物化 |
| `docs/hr/legacy/HR05_LegacyOnboardingMapping.md` | HR05 | — | ✅ 已物化 |
| `docs/hr/legacy/HR05_RecruitToHireMapping.md` | HR04→HR05 | — | ✅ 已物化 |
| `docs/hr/legacy/HR06_LegacyChangeMapping.md` | HR06 | — | ✅ 已物化 |
| `docs/hr/legacy/HR07_LegacyContractMapping.md` | HR07 | — | ✅ 已物化 |
| `docs/hr/legacy/HR08_LegacyExternalWorkerMapping.md` | HR08 | — | ✅ 已物化 |
| `docs/hr/legacy/HR11_LegacyAttendanceMapping.md` | HR11 考勤 | — | ✅ 已物化 |
| `docs/hr/legacy/HR11_LegacyLeaveMapping.md` | HR11 请假 | — | ✅ 已物化 |
| `docs/hr/legacy/HR11_LegacyShiftMapping.md` | HR11 班次 | — | ✅ 已物化 |
| `docs/hr/legacy/HR11_LegacyHourAccountMapping.md` | HR11 工时 | — | ✅ 已物化 |

---

## 3. 待物化的 Legacy Mapping 文件

以下模块尚未开窗，但其 Legacy Mapping 文件在 S0 阶段需要物化：

| 模块 | 待物化文件 |
|---|---|
| HR09 | `docs/hr/legacy/HR09_LegacyQualificationMapping.md` |
| HR10 | `docs/hr/legacy/HR10_LegacyDevelopmentMapping.md` |
| HR12 | `docs/hr/legacy/HR12_LegacyAssessmentMapping.md` |
| HR13 | `docs/hr/legacy/HR13_LegacyTitleMapping.md` |
| HR14 | `docs/hr/legacy/HR14_LegacyAppointmentMapping.md` |
| HR15 | `docs/hr/legacy/HR15_LegacyPayrollMapping.md` |
| HR16 | `docs/hr/legacy/HR16_LegacyExitMapping.md` |
| HR17 | `docs/hr/legacy/HR17_LegacySelfServiceMapping.md` |
| HR18 | `docs/hr/legacy/HR18_LegacyReportMapping.md` |

---

## 4. LegacyDataMapping 标准字段

每份 Legacy Mapping 文件必须记录以下属性：

```text
legacy_field          — 旧系统字段名
new_authority         — 新 Authority 实体.字段
transform             — 转换逻辑（直迁/计算/查找/丢弃）
trust_level           — 信任等级
tenant_resolution     — 租户解析方式
person_resolution     — 人员解析方式
effective_date        — 生效日期来源
conflict_strategy     — 冲突处理策略
evidence              — 证据来源
notes                 — 备注
```

信任等级枚举：

```text
MIGRATED_VERIFIED    — 人工验证通过
MIGRATED_PARTIAL     — 部分字段可靠
MIGRATED_UNVERIFIED  — 未验证（默认）
```

---

## 5. Legacy Projection 规则

Cutover 后只允许：

```text
New Authority → Legacy Projection（单向）
```

禁止：
- 双向同步形成双主
- 旧 UI/form 继续写 Legacy 表
- Legacy Projection 反过来覆盖 Authority

旧 UI/form 进入 readonly/redirect 模式。

---

## 6. No Silent Fallback 守卫

```text
Authority 切换后严禁: catch Exception → legacy
迁移模式必须: 显式 flag + metric + audit
```

代码层面的守卫实现：
- `AuthorityModeService`（HR03/HR05/HR08 已实现）
- `is_authority()` 检查
- `legacy_write_disabled` flag
- 任何 legacy fallback 必须记录 metric + audit

---

## 7. Cutover 状态跟踪

| 模块 | 当前阶段 | Cutover 就绪 |
|---|---|---|
| HR02 | S10 Authority Cutover ✅ | ✅ |
| HR03 | S12 封板（本地验证） | ⏳ 待全栈 CI |
| HR04 | S11（待 CI） | ⏳ LEGACY_ACTIVE |
| HR05 | S11 Authority 切换完成 | ⏳ 待 CI |
| HR08 | S12 Authority 切换完成 | ⏳ 待 CI |
| HR11 | S9（S10 Legacy 退出待做） | ⏳ LEGACY_ACTIVE |

---

*由 00_高校人事系统全局架构与Horilla接管合同.md §160 自动生成。*
