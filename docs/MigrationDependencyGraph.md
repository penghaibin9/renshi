# MigrationDependencyGraph

> 来源：00_高校人事系统全局架构与旧系统接管合同.md §26–§27, 00 §21
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09
> 目标 DB：MySQL（PATCH-00 冻结）

---

## 1. Migration 分类体系

| 类型 | 含义 | 执行时机 |
|---|---|---|
| `ADDITIVE_SAFE` | 新增表/列/索引（不破坏现有数据） | 随时可执行 |
| `BACKFILL_REQUIRED` | 需要回填已有数据 | 在 DUAL_WRITE 阶段 |
| `DUAL_WRITE_TEMPORARY` | 临时双写（新旧并存） | DUAL_READ_COMPARE 期间 |
| `CUTOVER_REQUIRED` | Cutover 关键步骤 | FREEZE_LEGACY_FORMAL_WRITES 前 |
| `DESTRUCTIVE_POST_CUTOVER` | 删除旧结构 | POST_CUTOVER_CLEANUP 阶段 |

---

## 2. 跨 App Migration 依赖图

```text
                    hr_structure (HR02)
                         │
                         ├──→ hr_staff (HR03)  [FK: HrOrganization, HrPosition]
                         │
                    ┌────┴────┐
                    ▼         ▼
            hr_recruitment  hr_external
              (HR04)         (HR08)
                    │           │
                    ▼           │ [FK: HrPerson]
            hr_onboarding       │
              (HR05)            │
                    │           │
              ┌─────┴─────┐     │
              ▼           ▼     ▼
         hr_changes   hr_contracts  hr_time
           (HR06)       (HR07)      (HR11)
              │           │
              │     ┌─────┴─────┐
              │     ▼           ▼
              │  hr_external  hr_changes
              │    (HR08)      (HR06)
              │
         ┌────┴──────────┐
         ▼               ▼
     hr_payroll      hr_assessment
      (HR15)           (HR12)
         │               │
         ▼               ▼
      hr_exit         hr_title
      (HR16)           (HR13)
         │               │
         ▼               ▼
      hr_self         hr_appointment
      (HR17)           (HR14)
         │               │
         └───────┬───────┘
                 ▼
              hr_data
              (HR18)
```

### 关键 FK 依赖链

| 依赖 | 方向 | 约束 |
|---|---|---|
| `hr_staff → hr_structure` | FK: HrOrganization, HrPosition, HrPostCatalogVersion | HR02 先于 HR03 创建 |
| `hr_recruitment → hr_structure` | FK: Position (preflight/reservation) | HR02 先于 HR04 S4 |
| `hr_external → hr_staff` | FK: HrPerson | HR03 先于 HR08 S2 |
| `hr_onboarding → hr_staff` | 服务调用: StaffMasterService | HR03 先于 HR05 S4 |
| `hr_onboarding → hr_recruitment` | 服务调用: Handoff provider | HR04 先于 HR05 S4 |
| `hr_external → hr_contracts` | Provider: AgreementProvider (占位 UNAVAILABLE) | HR07 未交付; HR08 用 Provider 占位 |
| `hr_changes → hr_staff` | FK: HrEmploymentRelationship, HrStaffAssignment | HR03 先于 HR06 |
| `hr_contracts → hr_staff` | FK: HrEmploymentRelationship | HR03 先于 HR07 |
| `hr_time → hr_staff` | Provider: FakePersonProvider (占位) | HR03 先于 HR11 |

---

## 3. 当前已生成的 Migration 清单

### HR02 (hr_structure) — 组织/岗位
| 迁移 | 说明 | 依赖 |
|---|---|---|
| `0001_initial` | 组织/岗位核心模型 | — |

### HR03 (hr_staff) — 教职工主档
| 迁移 | 说明 | 依赖 |
|---|---|---|
| `0001` | Person/Identity/StaffMaster + 加密 + fingerprint | hr_structure.0001 |
| `0002` | EmploymentRelationship | hr_staff.0001 |
| `0003` | StaffAssignment (effective-dated + PRIMARY unique) | hr_staff.0002 |
| `0004` | Education/Credential | hr_staff.0003 |
| `0005` | Material/Version/DownloadTicket | hr_staff.0004 |
| `0006` | CorrectionCase/Item | hr_staff.0005 |
| `0007` | BusinessEventInbox/OutboxEvent | hr_staff.0006 |
| `0008` | PermissionMeta | hr_staff.0007 |
| `0009-0011` | 增量优化 | 前序迁移 |

### HR04 (hr_recruitment) — 招聘
| 迁移 | 说明 | 依赖 |
|---|---|---|
| `0001` | PermissionMeta | — |
| `0002-0008` | 招聘 Authority 模型全量（Plan/Campaign/Application/Assessment/Offer/Handoff） | hr_structure.0001 |

### HR05 (hr_onboarding) — 入职
| 迁移 | 说明 | 依赖 |
|---|---|---|
| `0001` | Case/Template/Task/Portal/Material | hr_structure.0001, hr_staff.0001, hr_recruitment.0001 |
| `0002-0004` | 增量（Probation/Provisioning/投影） | 前序迁移 |
| `0005` | Material Requirement 唯一约束补强 | hr_onboarding.0004 |
| `0006` | PermissionMeta + CSRF 豁免 | hr_onboarding.0005 |

### HR08 (hr_external) — 外聘
| 迁移 | 说明 | 依赖 |
|---|---|---|
| `0001` | Category seed | — |
| `0002` | Authority models (Profile/Engagement/Assignment/Hiring/Ethics/Conflict/...) | hr_staff.0001, hr_external.0001 |
| `0003` | Import staging | hr_external.0002 |
| `0004` | Industry (专项/成果/工作室) | hr_external.0003 |
| `0005` | Academic Identity | hr_external.0004 |
| `0006` | Tasks (任务/工作量/结算) | hr_external.0005 |
| `0007` | Renewal/Exit | hr_external.0006 |
| `0008` | Projection | hr_external.0007 |
| `0009` | Authority Config | hr_external.0008 |
| `0010` | Materials + FileTicket | hr_external.0009 |
| `0011` | Portal | hr_external.0010 |
| `0012-0014` | 增量（Material version/短索引名） | 前序迁移 |

### HR11 (hr_time) — 考勤
| 迁移 | 说明 | 依赖 |
|---|---|---|
| `0001` | TenantModel base | — |
| `0002-0009` | 政策/事件/月结/投影 | 前序迁移 |
| `0010` | ClosePeriod 冻结 | hr_time.0009 |
| `0011` | 短索引名修复 | hr_time.0010 |

---

## 4. 破坏性改动规则

- 跨 app migration 建依赖图
- 删除旧结构只能在 Authority cutover 之后
- 后发模块的 migration 依赖前序模块的已确认 migration 编号
- 若前序模块 migration 被重写（squash/reset），后发模块必须同步调整

---

## 5. 施工波次与 Migration 建议顺序

| 波次 | 模块 | 迁移时机 |
|---|---|---|
| W0 | 全局底座（Audit/Docs/Jobs） | 最优先 |
| **W1** | **HR02 → HR03** | 事实底座 migration 优先 |
| W2 | HR04 → HR05 → HR07 | 入人主链 |
| W3 | HR06 → HR08 | 人事变化 |
| W4 | HR09 → HR10 → HR11 | 教师发展与时间 |
| W5 | HR12 → HR13 → HR14 | 评价裁决 |
| W6 | HR15 → HR16 | 薪酬离退 |
| W7 | HR17 → HR18 | 统一体验与数据 |

---

*由 00_高校人事系统全局架构与旧系统接管合同.md §160 自动生成。*
