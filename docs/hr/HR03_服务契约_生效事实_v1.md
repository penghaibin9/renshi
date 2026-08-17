# HR03 生效服务契约（S3/S4/S5 交付 · 消费闸门）

> 消费闸门：HR05-S4（入职建立 Person/Staff/Relationship/Assignment）与 HR08-S2（外聘教师挂任职）必须在 HR03 权威服务就绪后调用本契约，不得自行直写 HrStaff* 表。
> 版本：v1（2026-08-09，随 S3/S4/S5 物化）；破坏性变更前升级 v2，旧版至少跨一个稳定版本周期。
> 现状：HR03 权威模型与服务已具备；HR02 稳定 ID（hr_structure）已注册并有迁移；legacy Department/JobPosition 不固化，走 legacy_* 映射列。

---

## 1. 分层与权威事实链

```
HrPerson（自然人，tenant-private，person_uid 不可变）
  └─ HrPersonIdentityDocument（证件：ciphertext + tenant fingerprint + masked_display）
  └─ HrPersonContact / HrEmergencyContact（RESTRICTED/SENSITIVE）
HrStaffMaster（学校教职工身份；(tenant_id, staff_no) 唯一；canonical (tenant_id, person_id)）
  └─ HrEmploymentRelationship（聘用关系；[effective_from, effective_to)；一人可多关系）
      └─ HrStaffAssignment（任职事实；PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT）
  └─ HrStatusHistory（显式状态段：离职/退休/停职；不 DELETE）
  └─ HrAccountLink（账号解耦；authority save 不自动建 User）
```

- 外键：`HrStaffAssignment.organization_id → hr_structure.HrOrganization`、`position_id → hr_structure.HrPosition`、`post_catalog_id → hr_structure.HrPostCatalogVersion`。
- `legacy_department_id / legacy_job_position_id` 仅映射列（LEGACY_CURRENT_SNAPSHOT 预览），不是 authority。

---

## 2. 创建自然人（HR05-S4 入职第一步）

### `PersonIdentityService.create_person_with_identity(...)`
参数（关键字）：
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tenant_id` | int | ✅ | A0 学校 id |
| `legal_name` | str | ✅ | 法定姓名 |
| `preferred_name` | str | | 常用名 |
| `gender_code` | str | | M/F/O/U |
| `birth_date` | date | | SENSITIVE |
| `document_type` | str | | NATIONAL_ID/PASSPORT/… |
| `document_number` | str | | 证件号（明文入参，服务内部加密） |
| `contacts` | list[dict] | | `[{"contact_kind","contact_value","is_primary"}]` |

返回：`HrPerson`（幂等：同 tenant 同证件 HARD 命中返回已有 Person）。
异常（统一 `code` 供错误信封）：
- `PERSON_DUPLICATE_HARD_MATCH`：同 tenant 同证件已归属他人（跨 person 冲突）；
- `PERSON_DUPLICATE_REVIEW_REQUIRED`：姓名+生日 LIKELY 命中 → **必须人工去重**，系统不自动合并也不静默新建；
- 并发兜底：`document_number_fingerprint` 条件唯一约束（DB 级）。

### 生效事实语义
- 一个自然人在某学校只有一份 Person；HR05 不得为返聘/外聘再建新 Person。

---

## 3. 建立教职工身份（HR05-S4）

### `StaffMasterService.create_staff(...)`
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tenant_id` | int | ✅ | |
| `person_id` | HrPerson | ✅ | |
| `staff_category_code` | str | | TEACHER/ADMIN/… |
| `staff_no` | str | | 缺省由 StaffNumberService 生成（tenant 前缀可配） |
| `legacy_employee_id` | int | | 仅映射 |
| `source` | str | | HR_ENTERED/HR05_ONBOARDING/… |

异常：
- `STAFF_NO_CONFLICT`（(tenant, staff_no) 已存在）；
- `DUPLICATE_STAFF_MASTER`（同 tenant 同 person 已有 canonical StaffMaster）。

---

## 4. 建立聘用关系（HR05-S4）

### `EmploymentService.start_relationship(...)`
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tenant_id` | int | ✅（构造器） | |
| `staff_id` | HrStaffMaster | ✅ | |
| `relationship_type` | str | ✅ | REGULAR_EMPLOYMENT/CONTRACT/LABOR_DISPATCH/EXTERNAL_PART_TIME/SECONDMENT/RETIRED_REHIRE/REHIRE/OTHER |
| `employment_type` | str | | FULL_TIME/PART_TIME/EXTERNAL/… |
| `effective_from` | date | ✅ | 入职生效日 |
| `effective_to` | date | | NULL=开放（半开区间 [from, to)） |
| `source_business_type` / `source_business_id` | str | | HR05_ONBOARDING + 业务单号 |
| `reason_code` | str | | |

异常：`ASSIGNMENT_OVERLAP`（同 staff 同类型区间重叠）、`EFFECTIVE_DATE_INVALID`。

### `EmploymentService.end_relationship(...)`
- 结束关系：自动关闭所有未结束 assignment（不 DELETE），更新 `status=ENDED`。
- HR16 离职/退休调用此接口（或 HR16_REHIRE 前先 end 旧关系）。

---

## 5. 建立任职事实（HR05-S4 / HR08-S2）

### `AssignmentService.create_assignment(...)`（PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT）
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tenant_id` | int | ✅（构造器） | |
| `employment_relationship_id` | HrEmploymentRelationship | ✅ | |
| `assignment_type` | str | ✅ | PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT |
| `effective_from` | date | ✅ | 任职生效日 |
| `effective_to` | date | | 半开区间 |
| `organization_id` | hr_structure.HrOrganization | ✅* | *或无权威组织时必须给 `legacy_department_id` |
| `position_id` / `post_catalog_id` | hr_structure | | as_of 必须有效 |
| `fte` | Decimal | | ≤ 学校策略上限（V1 1.50） |
| `source_business_type` / `source_business_id` | str | | HR05_ONBOARDING 等 |

异常（统一 code）：
- `CROSS_TENANT_REFERENCE`（组织/岗位跨学校）；
- `EFFECTIVE_DATE_INVALID`（组织/岗位 as_of 无有效版本）；
- `ORG_MAPPING_MISSING`（无组织也无 legacy 映射）；
- `ASSIGNMENT_OVERLAP`（同关系 PRIMARY 段重叠）；
- `POSITION_CAPACITY_EXCEEDED`（POSITION_CONTROL 岗位已占满）；
- `FTE_POLICY_EXCEEDED`。

### `AssignmentService.switch_primary(...)`（HR06 调动 / HR14 聘任）
- 事务内 `select_for_update` 锁当前 PRIMARY → 校验新组织/岗位 as_of → 关旧段（ENDED；同日切换 CANCELLED）→ 建新段 → 更新投影 → 写审计。
- 保证"不会出现人员无主岗"；DB 条件唯一 `uniq_hr_assignment_open_primary_per_rel` 兜底并发双主岗。

### `AssignmentService.close_assignment(...)`
- 关闭任职段（effective_to + status=ENDED）。

---

## 6. 统一 as-of 查询（所有读路径唯一入口）

### `EffectiveDatedQueryService(tenant_id)`
| 方法 | 说明 |
|---|---|
| `relationships_as_of(staff_id, as_of)` | 关系段 |
| `relationship_open_now(staff_id)` | 当前开放关系 |
| `assignments_as_of(staff_id, as_of)` | 任职段（PRIMARY+并发） |
| `primary_assignment_as_of(staff_id, as_of)` | 当前主岗 |
| `status_as_of(staff_id, as_of)` | 状态投影（PENDING_ENTRY/ACTIVE/SUSPENDED/DEPARTURE_PENDING/DEPARTED/RETIRED） |
| `timeline(staff_id)` | 任职履历时间线 |
| `org_name_as_of(org_id, as_of)` | HR02 组织历史名称解析 |

- 半开区间 `[effective_from, effective_to)`，NULL=开放结束。
- **禁止各页面/各模块自行拼日期条件**；历史 as-of 禁止读 current projection。

---

## 7. 事件与幂等

- 写服务均原子；写后自动：投影刷新（StaffMaster.current_employment_status / primary_assignment_id）+ `HrStaffAuditEvent`。
- 调用方必须携带 `source_business_type/source_business_id`（业务单号）作为幂等/溯源键；HR05/HR06/HR14 事件消费方（S10）据此去重。

---

## 8. 错误信封（公共）

```json
{"apiVersion":"1.0","requestId":"...","error":{"code":"<CODE>","message":"...","retryable":false}}
```
本契约抛出异常的 `code` 即错误信封 code。关键：`CROSS_TENANT_REFERENCE`、`PERSON_DUPLICATE_HARD_MATCH`、`ASSIGNMENT_OVERLAP`、`POSITION_CAPACITY_EXCEEDED`、`EFFECTIVE_DATE_INVALID`、`STAFF_NO_CONFLICT`、`VERSION_CONFLICT`（S9 更正应用时）。

---

## 9. 待替换占位（[总控占位]）

- `organization_id/position_id` 权威 FK：直接绑 hr_structure（随 HR02 演进；`org_version_as_of(tenant_id, org_id, as_of)` 已适配 INV-01 加固）。
- `HrAccountLink.auth_user_id`：仅存 HorillaUser.id 数字列（避免跨 app FK 耦合）；S11 账号解耦落地时回填真实关联。
- ✅ 敏感 reveal endpoint 已落地：`POST /api/hr/v1/staff/{id}/sensitive-fields/{field}/reveal`（purpose+审计+60s 遮罩）；身份证 exact 搜索 `GET /api/hr/v1/staff/search-by-identity`（命中/未命中统一 200+null 防探测）。
- ✅ 下载票据已落 DB（`HrMaterialDownloadTicket`，迁移 0010）：短时效一次性、事务消费、归属预校验不烧票。
- ✅ 权威导出已落地（`HrExportJob` 迁移 0011 + `POST /api/hr/v1/staff/export` + 一次性 ticket 下载）：用途必填 + 字段级权限（`hr.staff.export_sensitive`）+ 审计；CSV 内容暂存内存（`ExportContentStore`），大导出异步与受控文件存储待 HR00 job runner/对象存储交付后替换。
- ✅ 权威导入已接线（`POST /api/hr/v1/staff/import` + `/import/{id}/commit` 真实 `StaffMasterRowApplier`）：CSV staging → 校验 → 精确失败行 → 逐行原子 commit + checkpoint；异步 runner 待 HR00。
- ✅ 工号序列（`HrStaffNumberSequence` 迁移 0011）：O(1) 分配 + 行锁，无截断/并发安全。
- user↔scope membership 深层绑定：当前 tenant 级 membership 已校验（fail-closed）+ ScopeEnforcer 组织级数据裁剪；组织级 membership 依赖 HR00/HR01 权限基建交付后强化。
