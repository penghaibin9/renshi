# HR07 Legacy Contract Mapping（S0 物化 · 对照 HR07 总册 §96）

> 目标：Horilla `payroll.Contract` → HR07 `HrAgreement` 体系的字段级映射、迁移策略与历史数据分类。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`
> 硬约束：不删 payroll 旧表（迁移前）；AMBIGUOUS 不自动"猜"；旧库数据不自动 VERIFIED（00 §54）。

---

## 1. 字段映射表

| Horilla `payroll.Contract` | HR07 目标 | 策略 |
|---|---|---|
| `employee_id`（→ legacy Employee） | HR03 `HrEmploymentRelationship` / `HrStaffMaster` | 重映射（经 `HrStaffMaster.legacy_employee_id`），映射失败 → AMBIGUOUS |
| `contract_name` | `HrAgreement.title` / AgreementType | ADAPT（生成 AgreementType 默认名） |
| `contract_start_date` | `HrAgreement.contract_start_date` | MIGRATE |
| `contract_end_date` | `HrAgreement.contract_end_date`（NULL=开放） | MIGRATE |
| `contract_status`（draft/active/expired/terminated） | `HrAgreement.lifecycle_status` | MAP_WITH_VALIDATION（见 §2 状态映射） |
| `wage`（Float，薪资权威） | `HrAgreementTerm(COMPENSATION_REFERENCE)` + HR15 | 移出权威；不做统计；映射为条款引用 |
| `wage_type` / `pay_frequency` | HR15 / HR11 | 移出 |
| `filing_status` | HR15 / tax | 移出 |
| `department` / `job_position` / `job_role` | `signing_context_snapshot` | 仅快照，不作权威（HR07 §70） |
| `shift` / `work_type` | HR11 / current assignment | 移出 |
| `notice_period_in_days` | `HrAgreementTerm(NOTICE_PERIOD)` | MIGRATE |
| `contract_document`（public FileField） | `HrAgreementDocument`（private storage + hash + ticket） | MIGRATE（复制到 private storage 并计算 hash；源文件保留归档） |
| `deduct_leave_from_basic_pay` / `calculate_daily_leave_amount` / `deduction_for_one_leave_amount` | HR11 / HR15 | 移出 |
| `note` | `HrAgreement.notes` 或首次事件 note | MIGRATE |
| `history`（HorillaAuditLog） | `HrAgreementAuditEvent`（正式） + legacy history 归档 | 非正式 ledger，仅供迁移证据 |
| `company_id`（经 HorillaCompanyManager 解析） | `tenant_id`（Tenant↔Company 映射） | MIGRATE |

---

## 2. 状态映射（含校验）

| Legacy status | HR07 lifecycle_status | 校验/迁移条件 |
|---|---|---|
| `draft` | `DRAFT` | 直接映射；无 signed 事实 |
| `active` | `ACTIVE` | 必须有 employment relationship；start<=today<end（end 有值）或 open-ended；否则 → AMBIGUOUS |
| `expired` | `EXPIRED` | end < today；需生成 review/risk 记录 |
| `terminated` | `TERMINATED` | 生成 `AgreementEvent(TERMINATE)` 作为终止证据；record 来源=legacy |

> **禁止**：迁移时按日期重新推断状态（HR07 §16）。status 与日期矛盾 → `AMBIGUOUS` 人工处理。

## 3. 数据质量分类（§95）

| 类别 | 判定 | 处理 |
|---|---|---|
| CLEAR | 映射全部命中、状态与日期一致、单 active | 直接迁移（source=MIGRATION，MIGRATED_VERIFIED） |
| AMBIGUOUS | active 多份 / start-end 重叠 / status 与日期矛盾 / wage 与 payroll 不一致 / Employee 已离职但 active / mapping 冲突 | 生成迁移报告人工处理；不自动合并 |
| INVALID | 缺 employee 映射 / start>end / 无类型 | blocked，不迁移 |

## 4. 迁移门（§125）

切换前产出 `LegacyContractMigrationReport`，字段：
`total / migrated / ambiguous / blocked / missing_documents / overlap / status_conflict / employee_mapping_conflict / payroll_dependency`。
P0 conflict 必须人工处理或有批准 migration policy。

## 5. 退出路径（§97）

```text
LEGACY_CONTRACT_ONLY → DUAL_READ_COMPARE → HR07_AUTHORITY
```

- **LEGACY_CONTRACT_ONLY**：payroll.Contract 仍权威，HR07 影子写入。
- **DUAL_READ_COMPARE**：HR07 读写影子 + legacy projection，对账 employee/dates/status/document/wage reference。
- **HR07_AUTHORITY**：新合同只写 HR07；legacy 只 projection；旧 create/edit 页面跳 HR07；禁止自动 fallback（00 §57）。

## 6. Legacy Projection（§98）

`current PRIMARY_EMPLOYMENT Agreement → Horilla Contract`（只投影主合同，不含 supplementary）。
Payroll 需要的 wage 由 HR15 明确提供，禁止从 HR07 签署文件临时解析。
