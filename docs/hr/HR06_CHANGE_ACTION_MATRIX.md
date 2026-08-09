# HR06 CHANGE ACTION MATRIX（S0 基线复审 · 动作/原因/字段/策略矩阵）

> 依据：《06_HR06_人事异动_施工总册_终极版》§7（Change Action 冻结）/ §8（Change Reason）/ §18（申请人范围）/ §22（直属关系）/ §25（用工性质）/ §27-30（临时异动）。
> 此矩阵是 S1 `HrChangeAction/HrChangeReason` 种子数据与 S4-S6 各 policy 的单一事实源。
> 边界（禁止越界）：不抢 HR14 聘任、HR07 合同、HR15 薪酬；临时异动保留 return 语义；兼岗不覆盖主岗。

---

## 1. V1 动作冻结（16 个）

| Action Code | 中文名 | 归属模块 | 影响的权威层 | 是否临时 | 关键策略 |
|---|---|---|---|---|---|
| `ORG_TRANSFER` | 组织调动 | HR06-02 | HR03 Assignment.organization | 否 | reporting manager policy；容量校验 |
| `POSITION_TRANSFER` | 岗位调动 | HR06-02 | HR03 Assignment.position | 否 | 岗位 as_of 有效 + 容量 |
| `ORG_POSITION_TRANSFER` | 组织+岗位调动 | HR06-02 | Assignment.organization + position | 否 | 两者同事务生效 |
| `POST_CATEGORY_CHANGE` | 岗位类别变更 | HR06-03 | Assignment.post_catalog / 岗位类别 | 否 | 专业技术/管理/工勤 之间 |
| `EMPLOYEE_CATEGORY_CHANGE` | 人员类别变更 | HR06-03 | HrStaffMaster.staff_category_code | 否 | 专任教师/辅导员/管理/其他专技/工勤/外聘 |
| `EMPLOYMENT_TYPE_CHANGE` | 用工性质变更 | HR06-03 | HrEmploymentRelationship | 否 | UPDATE_RELATIONSHIP / CLOSE_AND_CREATE_RELATIONSHIP / REQUIRE_HR07_CONTRACT |
| `MANAGER_CHANGE` | 直属上级变更 | HR06-03 | Assignment.reporting_staff_id | 否 | 显式选择 |
| `LOCATION_CHANGE` | 工作地点变更 | HR06-03 | Assignment.location（V1 legacy 映射列） | 否 | — |
| `ADD_SECONDARY_ASSIGNMENT` | 增加兼岗 | HR06-03 | 新建 CONCURRENT Assignment | 否 | 绝不覆盖主岗 |
| `END_SECONDARY_ASSIGNMENT` | 取消兼岗 | HR06-03 | 关闭 CONCURRENT Assignment | 否 | close_assignment |
| `PRIMARY_ASSIGNMENT_SWITCH` | 主岗切换 | HR06-03 | HR03 switch_primary | 否 | one-primary 硬不变量 |
| `TEMPORARY_SECONDMENT` | 借调 | HR06-04 | 新建 TEMPORARY/SECONDMENT Assignment + link | 是 | expected_return_at + return_policy |
| `TEMPORARY_ATTACHMENT` | 挂职 | HR06-04 | 同上 | 是 | 同上 |
| `RETURN_FROM_TEMPORARY` | 返岗 | HR06-04 | 关 temp、恢复 source | 是（终态动作） | `RETURN_TARGET_INVALID` exception |
| `BULK_ORG_RESTRUCTURE_MOVE` | 批量组织调整 | HR06-01/02 | 逐人独立 Case | 否 | PREVALIDATE_ALL + ATOMIC_BATCH |
| `DATA_CORRECTION` | 数据纠错 | HR06-05 | 依 correction 字段 | — | **更高权限**，语义不同于业务异动 |

## 2. 动作 → 允许的 Reason（S1 种子）

| Action | Reason 种子 |
|---|---|
| ORG_TRANSFER | SCHOOL_ORG_OPTIMIZATION（学校组织优化）/ PERSONAL_APPLICATION（个人申请）/ WORK_NEED（工作需要）/ ORGANIZATION_RESTRUCTURE（组织重组） |
| POSITION_TRANSFER | WORK_NEED / PERSONAL_APPLICATION / POSITION_RESTRUCTURE（岗位调整） |
| ORG_POSITION_TRANSFER | 上两者合并 |
| POST_CATEGORY_CHANGE | PROFESSIONAL_TO_ADMIN（专技转管理）/ ADMIN_TO_PROFESSIONAL（管理转专技）/ WORK_NEED |
| EMPLOYEE_CATEGORY_CHANGE | CATEGORY_RECLASSIFICATION（类别重新认定）/ WORK_NEED |
| EMPLOYMENT_TYPE_CHANGE | LABOR_CONTRACT_CHANGE（合同用工变化）/ POLICY_ADJUSTMENT（政策调整） |
| MANAGER_CHANGE | ORG_REORGANIZATION / WORK_NEED |
| LOCATION_CHANGE | ORG_MOVE（单位搬迁）/ CAMPUS_ADJUSTMENT（校区调整） |
| ADD_SECONDARY_ASSIGNMENT | WORK_NEED / TALENT_DEVELOPMENT（人才培养） |
| END_SECONDARY_ASSIGNMENT | WORK_NEED / PROJECT_END（项目结束） |
| PRIMARY_ASSIGNMENT_SWITCH | WORK_NEED / ORG_REORGANIZATION |
| TEMPORARY_SECONDMENT | PROJECT_SUPPORT（项目支援）/ HIGHER_AUTHORITY_ASSIGNMENT（上级部门借调） |
| TEMPORARY_ATTACHMENT | PROJECT_SUPPORT / HIGHER_AUTHORITY_ASSIGNMENT / TALENT_DEVELOPMENT |
| RETURN_FROM_TEMPORARY | TEMPORARY_PERIOD_END（借调期满）/ EARLY_RETURN（提前返岗） |
| BULK_ORG_RESTRUCTURE_MOVE | ORGANIZATION_RESTRUCTURE |
| DATA_CORRECTION | DATA_ENTRY_ERROR（录入错误）/ SOURCE_DOCUMENT_REVISION（依据材料修订） |

> Reason 必须版本化/停用，不删除历史已使用 reason（总册 §8）。

## 3. 动作 → 允许的 Initiator 范围（总册 §18）

| Action | 本人 | 直属负责人 | 学院人事 | 目标学院 | 学校人事 | 重组管理员 |
|---|---|---|---|---|---|---|
| ORG/POSITION/ORG_POSITION_TRANSFER | 意向 | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST/EMPLOYEE_CATEGORY_CHANGE | ✗ | ✗ | ✓ | ✓ | ✓ | ✗ |
| EMPLOYMENT_TYPE_CHANGE | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| MANAGER_CHANGE | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ |
| LOCATION_CHANGE | ✗ | ✓ | ✓ | ✗ | ✓ | ✗ |
| ADD/END_SECONDARY | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| PRIMARY_SWITCH | ✗ | ✓ | ✓ | ✗ | ✓ | ✗ |
| TEMPORARY_SECONDMENT/ATTACHMENT | 申请 | ✓ | ✓ | ✓ | ✓ | ✗ |
| RETURN_FROM_TEMPORARY | 申请 | ✓ | ✓ | ✓ | ✓ | ✗ |
| BULK_ORG_RESTRUCTURE_MOVE | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| DATA_CORRECTION | ✗ | ✗ | ✗ | ✗ | ✓（+审批） | ✗ |

## 4. 动作 → 受影响字段（Proposal domain/field_code）

| Action | domain | field_code |
|---|---|---|
| ORG_TRANSFER | assignment | organization |
| POSITION_TRANSFER | assignment | position |
| ORG_POSITION_TRANSFER | assignment | organization, position |
| POST_CATEGORY_CHANGE | assignment | post_catalog（岗位类别） |
| EMPLOYEE_CATEGORY_CHANGE | staff | staff_category_code |
| EMPLOYMENT_TYPE_CHANGE | relationship | relationship_type / employment_type |
| MANAGER_CHANGE | assignment | reporting_staff |
| LOCATION_CHANGE | assignment | location |
| ADD_SECONDARY_ASSIGNMENT | assignment | （新建段）organization/position/fte |
| END_SECONDARY_ASSIGNMENT | assignment | effective_to |
| PRIMARY_ASSIGNMENT_SWITCH | assignment | organization/position（切换） |
| TEMPORARY_SECONDMENT | temporary | （新建段 + link） |
| TEMPORARY_ATTACHMENT | temporary | （新建段 + link） |
| RETURN_FROM_TEMPORARY | temporary | link.status / source 恢复 |
| BULK_ORG_RESTRUCTURE_MOVE | assignment | organization/position（批量） |
| DATA_CORRECTION | 依 case | 依字段 |

## 5. 动作 → Reporting Manager Policy（总册 §22）

| Action | Policy |
|---|---|
| ORG/POSITION/ORG_POSITION_TRANSFER | DERIVE_FROM_TARGET_ORG（可改 SELECT_EXPLICIT） |
| MANAGER_CHANGE | SELECT_EXPLICIT |
| 其余 | KEEP（不盲复制，不默认改） |

## 6. 动作 → Follow-up（总册 §4.3/4.5/4.6）

| Action | 触发事件 | 消费域 |
|---|---|---|
| ORG_TRANSFER / ORG_POSITION_TRANSFER | `ContractReviewRequired`（如合同条款变化）、`AttendanceRuleReevaluationRequested`、`CompensationRecalculationRequested` | HR07/HR11/HR15 |
| EMPLOYEE_CATEGORY_CHANGE / POST_CATEGORY_CHANGE | `AttendanceRuleReevaluationRequested`、`CompensationRecalculationRequested` | HR11/HR15 |
| EMPLOYMENT_TYPE_CHANGE | `ContractReviewRequired` | HR07 |
| 全部生效动作 | `PersonnelChangeEffective`（00 §28.3 冻结） | 各消费域 |

## 7. 动作 → 生效策略

- 永久动作（除 RETURN）：`[effective_from, ∞)` 半开；旧段 `[..., effective_from)` 关闭；同日切换旧段 CANCELLED（对齐 HR03 switch_primary 语义）。
- 临时动作：temp 段 `[start, expected_return_at)`；source 段按 source_policy（KEEP_ACTIVE/SUSPEND/REDUCE_FTE）。
- DATA_CORRECTION：校正错误记录，不伪造成第二次业务异动；影响下游历史事实时强制 Impact Analysis。

---

**文档状态：S0 复审物化；S1 实现以其为种子数据源，S4-S6 实现以其为 policy 源。**
