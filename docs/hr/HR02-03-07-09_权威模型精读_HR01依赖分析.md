# HR02/HR03/HR07/HR09 权威模型精读报告（HR01 依赖分析）

> 精读时间：2026-08-08
> 依据：《docs/》全部 15 份施工总册（重点 HR02/HR03/HR07/HR09）
> 用途：为 HR01 收尾 + 后续 HR02/HR03 施工提供依赖契约

---

## 1. 一句话结论

HR01 的收尾边界 = **LEGACY 当前快照 + 历史 UNAVAILABLE**。
之后先做 HR02（拿到稳定组织/岗位 ID），再以 HR03 的 effective-dated 关系/任职事实替换全部在岗/新进/离退/专任教师指标。
两者都按 **tenant × domain** 走 DUAL_READ_COMPARE 验证后才允许切 AUTHORITY_ONLY，任何情况下不允许 fallback legacy 或把 UNAVAILABLE 变 0。

---

## 2. HR02 权威模型（组织/编制/岗位）

### 核心模型（约 15+）
| 模型 | 关键点 |
|---|---|
| `HrOrganization` | 组织身份（stable_code 永久稳定，改名不改 id） |
| `HrOrganizationVersion` | 组织版本（name/parent/validity `[from,to)`，版本区间不重叠） |
| `HrOrganizationRelation` | 关系（ADMIN_PARENT/PARTY_PARENT/TEACHING_PARENT/PARTY_COVERS 等，跨维度） |
| `HrStaffingPlan` | 编制方案（DRAFT→UNDER_REVIEW→APPROVED→EFFECTIVE→SUPERSEDED，版本化） |
| `HrHeadcountQuotaLine` | 编制行（authorized/reserve_headcount，HARD/SOFT/INFO_ONLY） |
| `HrPositionQuotaLine` | 岗位额度行 |
| `HrLeadershipQuotaLine` | 领导职数行 |
| `HrStructureRatioRule` | 结构比例规则（必须绑方案版本） |
| `HrPostCatalog(+Version)` | 岗位标准（类别/等级方案/任职条件） |
| `HrPostGradeScheme(+Grade)` | 岗位等级（租户可配置） |
| `HrPosition` | 岗位实例（独立于人员；占用状态由 HR03 assignment 派生，禁止手填） |
| `HrPositionPool` | 岗位池（POOL_CONTROL） |
| `HrPositionReservation` | 岗位预占（防并发超卖） |
| `HrStructureChangeCase(+Item)` | 重组（合并/拆分/改名走 case，禁止静默改人员历史） |
| `HrLegacyObjectLink` | 迁移链接（防靠名称猜映射） |

### 关键原则
- **明确否定"一棵 parent_id 树"**：行政/党建/教学/业务多维度并存，用关系类型表达
- **编制 ≠ 人数**（INV-07）：禁止 `Employee.objects.count()` 当核定编制
- **行政职务 ≠ 岗位目录**；领导职数独立建模
- **超编细分 7 类异常**，禁止统一显示"超编"
- 与 Horilla 映射：`Company→ADAPT`、`Department→COMPAT_ONLY`、`JobPosition→COMPAT_ONLY`、`JobRole→绝不自动映射岗位等级`（P0-04）

---

## 3. HR03 权威模型（教职工主档/任职关系）

### 核心模型（约 20+）
| 模型 | 关键点 |
|---|---|
| `HrPerson` | 自然人层（person_uid 不可变；不代表在本校任职） |
| `HrPersonIdentityDocument` | 身份证（明文加密 + fingerprint 去重 + masked_display） |
| `HrStaffMaster` | 教职工身份（staff_no tenant 唯一；projection 字段可重建不可当历史） |
| `HrEmploymentRelationship` | 聘用关系（正式/合同/人事代理/外聘/返聘；effective_dated） |
| `HrStaffAssignment` | 任职事实（PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT；同关系同日期最多一个 PRIMARY） |
| `HrEducationExperience` 等 6 类 | 结构化背景履历（**禁止 JSON 黑洞**；学历≠学位分开） |
| `HrCorrectionCase(+Item)` | 数据更正（保留 before/after+理由+证据） |
| `HrSensitiveAccessLog` | 敏感访问审计 |

### 关键原则
- **effective-dated = 统一半开区间 `[effective_from, effective_to)`**，NULL 开放结束；全部 as-of 查询走统一 `EffectiveDatedQueryService`
- **人员类别 = 六个正交概念**（StaffCategory/EmploymentType/Assignment/RoleTag/ProfessionalTitle/AdministrativeRole），否定单一下拉框
- **离职/退休不是 `is_active`**：由关系/任职段 + 状态机（PENDING_ENTRY/ACTIVE/DEPARTURE_PENDING/DEPARTED/RETIRED）推导；正式离职不 DELETE
- **敏感字段四级**：PUBLIC_HR→RESTRICTED_HR→SENSITIVE→HIGH_SENSITIVE；高敏字段默认不进 API，查看走 purpose+审计+60 秒重遮罩
- **HR01 本年离退（K05）= 关系/任职段结束事件**（离职+调出+退休按 reason_code 分类），不得用 is_active 反算

---

## 4. HR07/HR09 权威模型（HR01 预警依赖）

### HR07 合同
- 权威：`HrAgreement` + 不可变 `HrAgreementVersion` + 独立 `review_date`
- 提醒：`HrAgreementAlertPolicy`（多梯度）+ `HrAgreementRiskCase`（去重）
- 旧 `payroll.Contract` / `EmployeeWorkInformation.contract_end_date` 降级为投影
- **状态不得由日期推断**

### HR09 双师/资格
- 权威：`HrPersonCredential` + `HrDoubleTeacherRecognition`
- 复核：`review_due_at` + `HrDoubleTeacherRecheckCase`（证据失效只开 RecheckCase 不自动撤销）
- 双师率共用 `MetricDefinition` 统一口径

### 对 HR01 预警的演进
| 规则 | 现状（LEGACY） | HR07/HR09 落地后 |
|---|---|---|
| `contract.expire_90d` | `EmployeeWorkInformation.contract_end_date` | 切 `HrAgreement`（过滤 PRIMARY_EMPLOYMENT，source_object_id=agreement_id） |
| `retirement.within_180d` | dob+性别推断 | HR03 关系段结束事件 |
| `staff.required_field_missing` | 当前快照 | HR02 组织映射 |
| `hr09.*` 资格/双师到期 | **未实现（正确）** | HR09 落地后启用 5 类规则 + 双师结构规则 |

**已验证**：现有 dedupe_key（含截止日）天然支持「续签产生新实例、旧实例闭环」，无需改结构。

---

## 5. 施工依赖与量级

### 依赖序列
```
H0/A0 封板（Docker + 多学校隔离）
  → HR01 收尾（LEGACY_ONLY，历史 UNAVAILABLE）   ← 当前
  → HR02 主体（稳定组织/岗位 ID）
  → HR03 事实层（依赖 HR02 ID）
  → HR02 台账占用投影 ↔ HR03 任职互相对齐
  → HR02 先切 authority（ORGANIZATION domain）→ HR03 再切（STAFF domain）
```

### 量级
- **HR02**：约 15+ 模型、60+ API、20-25 页面、S0-S11（12 阶段）。复杂度：effective-dated、重组 case、岗位预占并发、多租户导入。**HR01 的数倍，最难一档。**
- **HR03**：约 20+ 模型、50+ API、15-20 页面、S0-S12（13 阶段）。复杂度：effective-dated as-of、敏感字段加密/脱敏/reveal、CorrectionCase。**与 HR02 相当，安全合规最重。**
- **HR07**：REWRITE+Strangler（S0-S13），payroll 解耦 + Legacy 迁移为最大风险。
- **HR09**：NEW，依赖 HR10/教务 Provider 成熟度。

### 独立性
- **HR02 可完全独立施工**（不依赖 HR03 权威事实，占用用 LEGACY_CURRENT_SNAPSHOT 降级）
- **HR03 开发可并行但权威化依赖 HR02**（FK 需要稳定组织/岗位 ID）

---

## 6. 对当前 HR01 施工的确认

| HR01 现状 | 与总册一致性 |
|---|---|
| LEGACY_ONLY 提供 current snapshot | ✅ 正确 |
| 历史 headcount → UNAVAILABLE | ✅ 正确（不伪造历史） |
| 学历/职称/双师 → UNAVAILABLE | ✅ 正确 |
| 高敏字段不读 | ✅ 正确 |
| contract.expire_90d dedupe_key 含截止日 | ✅ 已验证支持续签闭环 |
| open_risk_count = HIGH/CRITICAL OPEN 预警数 | ✅ 符合总册 K06 |

**下一步**：完成 HR01 的 S4-S7 页面收尾 → 提交 → 进入 HR02 施工（独立可先行）。
