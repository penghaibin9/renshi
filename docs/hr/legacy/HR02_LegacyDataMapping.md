# HR02 LegacyDataMapping（初版 · 依据真实仓库核对）

> 文档性质：HR02-S0 前置交付；依据 `renshi` 仓库真实模型/字段核对后物化。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork）+ HR01 阶段修复（`bebd299`/`32a88ac`）
> 物化时间：2026-08-08
> 状态：`DRAFT_V1` —— HR02 编码期以最终模型核对后升级

---

## 1. 结论先行

- Horilla 的 `Company/Department/JobPosition/JobRole/EmployeeWorkInformation` **不具备**高校组织/编制/岗位权威能力（无 hierarchy、无 effective-dated、无编制、无岗位等级、无撤并语义）。
- HR02 采用 `REWRITE`：新建 `hr_structure` app 承载权威事实；Horilla 旧模型降级为**单向投影（projection）**，Authority 切换后旧写入口关闭。
- **禁止推断**：不根据公司名识别 tenant、不根据名称猜组织 parent、不把当前人数当编制、不把 JobRole 当岗位等级。

## 2. 引用盘点（S0 输出）

### Department / JobPosition / JobRole 被引用的范围
- **后端模型**：`employee/models.py`（EmployeeWorkInformation FK）、`recruitment/models.py`（Recruitment/Stage/Candidate）、`pms/models.py`、`payroll/models/models.py`（Contract）、`report/views/*`（各报表）、`whatsapp/flows.py`
- **模板**：`templates/dashboard.html`（25 处）、`templates/initialize_database/*`、`recruitment/templates/*`、`report/templates/*`、`pms/templates/*`
- **HR01 相关**：`hr_control_center/providers/workforce.py`（当前用 Department 做学院分布投影）

### 接管裁决

| Horilla 对象 | HR02 决策 | 终局用途 |
|---|---|---|
| `Company` | ADAPT | A0 学校租户安全边界；保留 stable tenant id；与 HR02 根组织 1:1 映射 |
| `Department` | COMPAT_ONLY | 由 HR02 当前行政组织投影生成，旧模块兼容；不承载历史 |
| `JobPosition` | COMPAT_ONLY | 由 HR02 当前岗位投影生成，旧模块兼容 |
| `JobRole` | COMPAT_ONLY / DEFER | 绝不自动映射为高校岗位等级 |
| `EmployeeWorkInformation.department/job_position` | PROJECT | HR03 上线前 current snapshot；之后由权威任职投影 |
| `HorillaCompanyManager` | REWRITE/HARDEN | A0 fail-closed tenant scope |
| 旧组织图 UI | ADAPT | 交互可参考，数据源改 HR02 |
| 旧 Department/JobPosition 写入口 | REMOVE_AFTER_CUTOVER | Authority 切换后隐藏/只读 |

## 3. 字段级映射

### `Company` → A0 Tenant + HR02 Root
```
Company.id                 → tenant_id（安全边界，永不变）
Company.company            → HR02 根组织当前名称投影（可改名，不影响 tenant id）
Company.hq                 → 不自动等于"总校"
Company.address/icon       → 学校基础展示，非 HR02 核心身份
```

### `Department` → HrOrganization (dimension=ADMIN)
```
Department.id              → HrLegacyObjectLink(legacy_pk) + HrOrganization(ADMIN)
Department.department      → HrOrganizationVersion.name（初始投影）
Department.company_id(M2M) → tenant 归属校验；多 Company 关联必须拆分/人工裁决
```
**限制**：Horilla 无 hierarchy → 初始仅作为 root 下一级临时映射；正式层级由学校 Excel/人工确认。

### `JobPosition` → 候选 HrPostCatalog + org usage / HrPosition 投影
```
JobPosition.id             → HrLegacyObjectLink
JobPosition.job_position   → 候选岗位目录名称（按 tenant+department+name 建 mapping，不全校同名 dedupe）
JobPosition.department_id  → 组织归属
JobPosition.company_id(M2M)→ tenant 校验
```
**不推断**：不推断岗位等级、不推断编制额度。

### `JobRole` → COMPAT_ONLY
除非学校明确给出 `JobRole X → HrPostGrade Y` 映射规则，否则绝不自动映射岗位等级。

### `EmployeeWorkInformation` → 仅迁移对账读取
HR02 只读当前 `company_id/department_id/job_position_id` 用于 DUAL_READ_COMPARE 对账；人员归属权威最终由 HR03 处理。

## 4. 无法迁移的事实（MANUAL_IMPORT_REQUIRED）
- 编制核定数；
- 历年编制方案；
- 历史组织树；
- 历史岗位席位；
- 领导职数；
- 岗位等级结构比例。

以上必须 `UNAVAILABLE / MANUAL_IMPORT_REQUIRED`，禁止根据当前人数"补历史"。

## 5. 迁移阶段（总册 31 节）
```
M0 只盘点 → M1 创建 Tenant Root → M2 迁移 Department Stable Identity（flat）
→ M3 人工/Excel 确认 hierarchy → M4 JobPosition Mapping → M5 不迁移"假的编制"
→ M6 Dual Read → M7 Authority Cutover
```

## 6. 退出合同（总册 30 节）
```
LEGACY_STRUCTURE_ONLY → DUAL_READ_COMPARE → HR02_AUTHORITY
```
- Authority 后：新增/改组织只写 HR02；Department/JobPosition 由 projection 维护；legacy 表单关闭；legacy write API 返回 `HR02_LEGACY_WRITE_DISABLED`；禁止 fallback。
- Cutover 硬门：tenant mapping 100%、active Department 映射 100%、组织树无 cycle、as-of tree 可读、HR01 provider 可切新源。

> 状态：`DRAFT_V1`。HR02 编码期必须以此文件为基线再次核对最终模型，升级到 `REVIEWED`。
