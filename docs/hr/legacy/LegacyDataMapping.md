# LegacyDataMapping（初版 · 依据真实仓库核对）

> 文档性质：HR01-S3 前置硬门之一。本文依据 `renshi` 仓库真实模型/字段核对后物化。
> 核对基线：`ca7928f`（Horilla HRMS 2.0 fork）
> 物化时间：2026-08-08
> 权威归属：HR02（组织/编制/岗位）、HR03（教职工主档/任职）、HR07（合同）、HR09（双师）、HR11（考勤）、HR15（薪酬）
> 状态：`DRAFT_V1` —— 待 HR02/HR03 编码期以最终模型再次核对并提升版本。

迁移策略取值：

- `MIGRATE`：未来权威模型正式写入时迁移，需做清洗/去重/校验。
- `PROJECT`：作为当前状态投影/兼容字段，不承担历史真值。
- `COMPAT_ONLY`：仅保留 legacy 引用/兼容投影，不作为未来权威。
- `COMPAT/DEFER`：暂以兼容方式保留，未来权威落地后替换。
- `DEFER`：暂缓，需先盘点/清洗，禁止直接当权威。
- `DROP_AFTER_CUTOVER`：切换后移除。

---

## 1. Horilla `Employee`（`employee/models.py`）

| Legacy 字段 | 真实定义 | 当前业务含义 | 未来权威归属 | 策略 |
|---|---|---|---|---|
| `id` | BigAuto PK | legacy 主键 | `HrStaffLegacyRef.legacy_employee_id` | COMPAT_ONLY |
| `badge_id` | CharField(50)，UniqueConstraint(非空) | 员工编号/Badge | HR03 Staff Number | MIGRATE，先做重复/空值检查（unique 已约束非空） |
| `employee_first_name` | CharField(200) NOT NULL | 姓（Horilla 语义） | HR03 Person 法定姓名/显示名 | MIGRATE，中文姓名需重新定义拼接语义（first/last 与中文名/名不对应） |
| `employee_last_name` | CharField(200) NULL | 名（Horilla 语义） | 同上 | MIGRATE，同上 |
| `email` | EmailField(254) unique | 个人邮箱 | HR03 Person Contact（敏感） | MIGRATE，按敏感级别治理；unique 保留 |
| `phone` | CharField(25) + 校验 | 个人电话 | HR03 Person Contact（敏感） | MIGRATE，敏感治理 |
| `address/country/state/city/zip` | 文本 | 住址 | HR03 Person Address（敏感） | DEFER，HR01 不读取 |
| `dob` | DateField | 生日 | HR03 Person（敏感） | MIGRATE，敏感治理；HR01 不用于核心指标 |
| `gender` | CharField(10) choices | 性别 | HR03 Person | MIGRATE，字典对齐 |
| `marital_status/children` | 文本/整数 | 婚姻家庭 | HR03 Person（敏感） | DEFER |
| `emergency_contact*` | 文本 | 紧急联系人 | HR03 Person Contact（敏感） | DEFER，HR01 不读取 |
| `qualification` | CharField(50) | 单字符串资格描述 | HR03 教育/资格履历 | DEFER/清洗，禁止直接当权威结构化资格 |
| `experience` | IntegerField | 粗粒度经验数字 | HR03 工作履历派生 | DEFER，不直接作为历史事实 |
| `is_active` | BooleanField(default=True) | 当前激活状态 | HR03 当前状态投影 | PROJECT，仅兼容，不作为历史在岗真值 |
| `employee_user_id` | OneToOne → HorillaUser | 登录账号关联 | A0/Auth + HR03 Identity Link | MIGRATE/RELINK |
| `additional_info` | JSONField | 附加扩展 | 按字段盘点后决定 | REVIEW |
| `is_from_onboarding` / `is_directly_converted` | Boolean | 入职来源标记 | HR05 入职事实 | COMPAT_ONLY |

注意（真实代码行为，与总册一致）：`Employee.save()` 自动创建 HorillaUser（email 用户名 / phone 初始密码）并自动 `get_or_create(EmployeeWorkInformation)`；归档时若存在业务关联会回弹 `is_active=True`。迁移时必须评估这些隐式副作用。

---

## 2. Horilla `EmployeeWorkInformation`（`employee/models.py`）

真实字段核对（总册第 30 节描述基本一致，补充 `email/mobile/location` 等）：典型 current snapshot，无完整 effective-dated 历史能力（`history` 为 HorillaAuditLog 变更审计，可追溯“何时改过”，不可回答“某日当时是什么”）。

| Legacy 字段 | 真实定义 | 未来权威归属 | 策略 |
|---|---|---|---|
| `id` | PK | `HrOrgAssignmentLegacyRef`/`HrStaffLegacyRef` | COMPAT_ONLY |
| `employee_id` | OneToOne → Employee | HR03 Person 关联 | MIGRATE |
| `company_id` | FK → Company (PROTECT) | A0 School/Tenant | MIGRATE/VALIDATE |
| `department_id` | FK → Department (PROTECT) | HR02 Organization + HR03 OrgAssignment | MIGRATE 当前快照，未来 effective-dated 关系替代 |
| `job_position_id` | FK → JobPosition (PROTECT) | HR02 Position + HR03 PositionAssignment | MIGRATE 当前快照 |
| `job_role_id` | FK → JobRole (PROTECT) | HR03/H14 任职或岗位角色 | 先语义盘点，再迁移；不得直接等同高校行政职务 |
| `reporting_manager_id` | FK → Employee (PROTECT) | HR03 ReportingRelation | MIGRATE 当前关系，历史若缺失明确不可回溯 |
| `employee_type_id` | FK → EmployeeType (PROTECT) | HR03 EmploymentRelation / PersonnelCategory | 映射字典后 MIGRATE |
| `shift_id` | FK → EmployeeShift (DO_NOTHING) | HR11 Attendance | COMPAT/DEFER |
| `work_type_id` | FK → WorkType (PROTECT) | HR11 Attendance | COMPAT/DEFER |
| `location` | CharField(254) | HR03 WorkLocationAssignment | MIGRATE 当前值 |
| `email` / `mobile` | 工作邮箱/电话 | HR03 Person Contact（工作） | MIGRATE，敏感治理 |
| `date_joining` | DateField | HR03 EmploymentRelation.effective_from | MIGRATE，需识别“首次入校”还是“当前关系开始日” |
| `contract_end_date` | DateField | HR07 Contract Projection | COMPAT/DEFER，不继续在 HR03 当合同真相 |
| `basic_salary` / `salary_hour` | IntegerField(default=0) | HR15 Payroll | 高敏感；DEFER/MIGRATE 到薪酬域，不进 HR01 普通指标 |
| `experience` | FloatField | HR03 工作履历派生 | DEFER |
| `tags` | M2M → EmployeeTag | HR03 标签/分类（非权威结构） | REVIEW |
| `additional_info` | JSONField | 附加扩展 | REVIEW |
| `history` | HorillaAuditLog | 变更审计（非 effective-dated） | ADAPT：审计保留，不作为历史任职真值 |

---

## 3. Horilla 基础组织字典（`base/models.py`）

| Legacy 模型 | 真实字段 | 未来 | 策略 |
|---|---|---|---|
| `Company` | company/hq/address/country/state/city/zip/icon/date_format/time_format | A0 School/Tenant Root | ADAPT + COMPAT |
| `Department` | department + company_id M2M | HR02 Organization | MIGRATE 当前结构 + 建 legacy ref |
| `JobPosition` | job_position + department_id FK + company_id M2M | HR02 Position | MIGRATE/重构 |
| `JobRole` | job_role + job_position_id FK + company_id M2M | HR02/HR14 role semantics | REVIEW 后迁移 |
| `EmployeeType` | employee_type + company_id M2M | HR03 PersonnelCategory | 配置映射后迁移 |
| `EmployeeShift` / `WorkType` | 考勤班次/工作制 | HR11 | COMPAT/DEFER |

---

## 4. 清洗规则（初始）

1. **姓名**：`employee_first_name`/`employee_last_name` 与中文姓名语义不对应。需学校提供姓名规范（单“姓名”字段 vs 名/字）。迁移前必须定拼接/拆分规则，禁止直接拼接造成错名。
2. **badge_id**：唯一约束存在，但历史脏数据（空串 vs NULL）需归一。迁移前做重复/空值检查。
3. **email**：unique 约束，但可能存在大小写/前后空格脏数据；迁移前归一化。
4. **date_joining**：需区分“首次入校”与“当前关系开始日”；若两者混用，无法自动拆分，需人工/字典辅助。
5. **employee_type_id**：EmployeeType 是自由文本字典，必须先建立 高校人员类别（专任教师/管理/辅导员/教辅/工勤/外聘）映射字典，再迁移。
6. **contract_end_date / basic_salary**：属 HR07/HR15 域，HR01 迁移期不读；禁止被普通 KPI 依赖。

## 5. 唯一键 / 去重规则（初始）

- `Employee`：`badge_id`（非空唯一）+ `(employee_first_name, employee_last_name, email)` 复合。
- 迁移唯一键建议：`tenant_id + badge_id`（学校工号唯一）；无 badge 的按 `tenant_id + 姓名 + email` 兜底并打标记。
- `EmployeeWorkInformation`：OneToOne 到 Employee（唯一）；迁移后由 effective-dated 关系替代。

## 6. Tenant 映射

- Horilla `Company` → A0 School/Tenant Root。
- `EmployeeWorkInformation.company_id`、各字典 `company_id M2M` → tenant 归属。
- **HorillaCompanyManager 的 `isnull=True` 兜底**：对 HR01 fail-closed 语义不成立（未绑定公司的教职工不应在无 school context 时全校可见），HR01 scope 解析层必须重新裁决。

## 7. 历史可追溯能力

- **现状**：仅 `EmployeeWorkInformation.history`（HorillaAuditLog）提供“变更日志”，**不能**回答 effective-dated 历史（如“2025-06-30 该人属于哪个学院”）。
- 迁移不得“猜历史”。`historicalCoverage = CURRENT_SNAPSHOT_ONLY`，直到学校提供历史 Excel/旧库或 HR02/HR03 建立 effective-dated 事实。
- HR01 历史指标在无权威历史事实时返回 `UNAVAILABLE`。

## 8. 切换前后读写权威关系（Authority 三阶段）

| 阶段 | HR01 读 | 写（HR01 本身不写业务事实） |
|---|---|---|
| `LEGACY_ONLY` | Legacy current snapshot（`dataBasis=LEGACY_CURRENT_SNAPSHOT`） | 业务动作走各域 |
| `DUAL_READ_COMPARE` | 优先 authority；legacy 仅对账 | 同上 |
| `AUTHORITY_ONLY` | 仅 authority provider；legacy 生产调用硬失败 | 同上 |

## 9. 验证 SQL / 测试口径（初始，需随实现固化）

- 在岗人数（legacy vs authority）差异 = 0；
- 按学院人数差异 = 0；
- 按人员类别人数差异 = 0；
- 当前组织映射覆盖率 100%；
- active staff 未映射组织 = 0（白名单特例除外）；
- 重复工号 / 身份冲突 = 0；
- 跨租户错配 = 0。

## 10. 回滚限制

- `AUTHORITY_ONLY` 后回滚仅允许到 `DUAL_READ_COMPARE`（受控迁移开关，强制 reason + 审计），禁止静默 Legacy fallback。
- legacy cache 需具备一键失效；回滚后首页显示“数据迁移验证中”数据质量提示。
- 删除 legacy adapter 的条件：所有生产 tenant 进入 `AUTHORITY_ONLY` + 连续发布周期 legacy call = 0 + 旧 API usage = 0 + 相关模块 projection 完成 + 回归证据与快照归档。

---

## 附：本文与总册第 30 节的差异点

1. 总册未列 `Employee` 的 `marital_status/children/emergency_contact*/address/country/state/city/zip/is_from_onboarding` 等——本文按真实模型补齐（均 DEFER/敏感）。
2. 总册未列 `EmployeeWorkInformation` 的 `email/mobile/location/tags/experience/additional_info`——本文补齐。
3. 总册“映射字典后 MIGRATE”的 employee_type，本文明确必须先建高校人员类别字典。
4. 新增“归档回弹 is_active=True”行为风险项（`Employee.save()`）。

> 状态：`DRAFT_V1`。HR02/HR03 编码期必须以此文件为基线再次核对最终模型，升级到 `REVIEWED` 后才可进入 S3。
