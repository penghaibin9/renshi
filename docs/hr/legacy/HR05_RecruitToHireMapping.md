# HR05 RecruitToHireMapping（HR04 HANDOFF → HR05 幂等对接契约）

> 依据：《00_全局合同》§91（HR04→HR05 关键跨域边界）、§23（统一幂等）；《04_HR04_总册》§1.4/§13.7/§25.6/§40（handoff 前置条件与幂等）；《05_HR05_总册》§21（Recruit-to-Hire Mapping）、§35（错误码）、§47（并发）。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`
> 角色分工：**HR04 是录用结论 Authority，HR05 是待报到/入职编排 Authority；`HANDOFF_TO_HR05` 是显式、幂等、可审计的领域动作，不是“Candidate.hired=True”的副作用。**

---

## 0. 契约一句话

> **只有当 HR04 的 `ProposedHire APPROVED + PublicNotice 闭环 + Offer ACCEPTED（若学校流程要求）+ PositionReservation VALID` 全部满足时，`POST /api/hr/v1/recruitment/proposed-hires/{id}/handoff-to-hr05` 才被允许；重复调用必须返回同一个 HR05 case，绝不生成第二份。**

---

## 1. Handoff 触发与前置条件

### 1.1 触发方（HR04 侧 · 由 HR04-S8 实现）

```http
POST /api/hr/v1/recruitment/proposed-hires/{proposedHireId}/handoff-to-hr05
Idempotency-Key: <uuid>
```

前置条件（HR04 校验，全部满足才允许）：
- `HrProposedHire.decision = APPROVED`；
- 公示 `HrPublicNotice` 已 CLOSED 且无 blocker 异议；
- `HrRecruitmentOffer.status = ACCEPTED`（学校流程要求时）；
- `HrPositionReservation` 状态 HELD（未过期，可 commit）。

### 1.2 消费方（HR05 侧 · 本窗口实现）

- HR05 提供幂等消费者 `HandleRecruitmentHandoff(proposed_hire_id, idempotency_key)`；
- 入参携带 HR04 的 `proposed_hire_id` + `application_id` + `reservation_id` + 录用来源版本；
- HR05 以其为准创建 `HrOnboardingCase(source_type=HR04_HIRE, source_id=proposed_hire_id, hr04_proposed_hire_id, hr04_application_id, position_reservation_id)`；
- HR04 保存 `handoff_id / handoff_at / hr05_case_id`（04 §13.7）。

### 1.3 幂等合同

| 场景 | 行为 |
|---|---|
| 同一 proposed_hire 第一次 handoff | 创建唯一 `HrOnboardingCase`，发布 `OnboardingCaseCreated` |
| 同一 proposed_hire 重复 handoff（网络重试/双人点击） | **返回同一 case**（按 `source_type+source_id` unique 或 idempotency key 命中） |
| 同一 HR04 Application 重复建两份 case | **禁止**：DB 约束 `UNIQUE(tenant_id, source_type, source_id)` 兜底 + 服务层 `ONBOARDING_CASE_DUPLICATE` |
| HR04 端 Offer 接受重复点击 | HR04 侧幂等（04 §25.5），HR05 不重复消费 |
| 旧 aggregateVersion 覆盖 | 事件消费按 `eventId/providerEventId` 幂等，旧版本不覆盖新状态（00 §16） |

### 1.4 事件链

```text
HR04: OfferAccepted
        ↓
HR04: RecruitmentHandoffCreated (outbox)
        ↓
HR05: HandleRecruitmentHandoff（幂等）
        ↓
HR05: OnboardingCaseCreated (outbox, correlationId 贯穿)
        ↓
HR05-01 待报到 → Portal invite
```

`correlationId/causationId` 从 HR04 handoff 事件一路传递到 HR05 激活、HR03 生效、HR07 合同（00 §17）。

---

## 2. 字段映射表（HR04 → HR05 staging → HR03 Authority）

> 禁止“字段名一样就自动映射”（05 §21）。每个字段必须：来源 → transform → 校验 → 冲突策略 → 审核人。

| HR04 字段 | HR05 Staging/权威字段 | HR03 权威字段 | Transform | Required? | Reviewer | Conflict Policy |
|---|---|---|---|---|---|---|
| `HrRecruitmentCandidate.legal_name` | `HrPrehireProfile.legal_name` | `HrPerson.legal_name` | 原名直迁；空值阻断 | ✅ | HR | Portal 自填 vs HR04 值不同 → `HrOnboardingDataConflict` |
| `HrRecruitmentCandidate.preferred_name` | `HrPrehireProfile.preferred_name` | `HrPerson.preferred_name` | 原名直迁 | ❌ | HR | 同上 |
| `HrRecruitmentCandidate.primary_email` | `HrPrehireProfile.contact[WORK_EMAIL/PERSONAL_EMAIL]` | `HrPersonContact`（**不是 Person 唯一键**） | 邮箱仅是联系字段，禁止据此合并 Person | ✅(审核) | HR | 不得用 email 自动合并 Person（00 §92/05 §23） |
| `HrRecruitmentCandidate.primary_mobile` | `HrPrehireProfile.contact[PERSONAL_MOBILE]` | `HrPersonContact`（masked） | 同上，手机号遮罩 | ❌ | HR | 跨学校禁止通过手机号识别同一人 |
| `HrRecruitmentCandidate.national_id_cipher/hash` | `HrPrehireProfile.identity_document` | `HrPersonIdentityDocument`（cipher + tenant-scoped fingerprint） | 证件只作 tenant 内 HARD_MATCH；LIKELY_MATCH 进人工去重 | 学校政策 | HR/材料核验 | HARD → 返回既有 Person；LIKELY → `PERSON_MATCH_REQUIRED` 人工确认；绝不自动合并 |
| `HrRecruitmentPosition.organization_id` | `HrOnboardingCase.planned_organization_id` | `HrStaffAssignment.organization_id`（经 HR02 as-of 校验） | HR02 stable org id；不映射名称 | ✅ | HR | 组织在生效日必须 ACTIVE（HR02 provider） |
| `HrRecruitmentPosition.post_catalog_id / position_id / position_pool_id` | `HrOnboardingCase.planned_post_catalog_id / planned_position_id / position_reservation_id` | `HrStaffAssignment.post_catalog_id / position_id` | HR02 `HrPositionReservation` 继承；**HR02 HELD→COMMITTED 只在 Activation 提交** | ✅ | HR | HR05 不新建岗位；`POSITION_RESERVATION_INVALID` 阻断激活 |
| `HrRecruitmentOffer.employment_type`（如 HR04 有） | `HrOnboardingCase.employment_type` | `HrEmploymentRelationship.employment_type` | 用工性质字典映射；按学校 policy 补全 | ✅ | HR | Portal 自填与 HR04 冲突 → DataConflict |
| `HrProposedHire` 的人员类别（来自岗位/计划） | `HrOnboardingCase.staff_category` | `HrStaffMaster.staff_category_code` | 从招聘岗位/计划解析，需 HR 确认 | ✅ | HR | 不自动猜 |
| `HrProposedHire` 录用批次/来源 | `HrOnboardingCase.source_type / source_id / hr04_application_id` | （溯源审计） | 原样保留，不重新解释 | ✅ | SYSTEM | source unique 防止重复 case |
| `HrRecruitmentOffer` 约定到岗日（如 HR04 采集） | `HrOnboardingCase.expected_report_date` | `HrEmploymentRelationship.effective_from`（Activation 时） | 日期经学校时区校验；延期走 `HrReportDelay` 保留历史 | ✅ | HR | 延期不覆盖原日期 |
| HR04 已核验材料（`HrApplicationMaterial` 状态） | `HrOnboardingMaterial(source=HR04, reuse_as_evidence)` | `HrStaffMaterial`（HR03 长期档案） | 按 `HrOnboardingMaterialRequirement.reuse_policy`：`TRUST_SOURCE / REVERIFY / REQUIRE_ORIGINAL` | 按需 | MATERIAL_VERIFIER | **HR05 不无条件继承“已验证”**（05 §12.6） |
| `HrPositionReservation.id`（HR04 已预占） | `HrOnboardingCase.position_reservation_id` | （HR03 assignment 生效引用） | 继承；延期可续期；放弃必须 release | ✅ | HR | 预占未提交不算占岗成功（05 §0） |
| 工号 | **HR05 不产生** | `HrStaffMaster.staff_no`（HR03 `StaffNumberService`） | 由 HR03 服务分配；HR05 只读取 | ✅ | SYSTEM | HR05 禁止“当前最大值+1”（00 §24）；依赖 HR03 序号化修复 |

---

## 3. 数据冲突处理（05 §22）

| 冲突字段 | 场景示例 | 处理 | 阻断级别 |
|---|---|---|---|
| 学历/学位 | Portal 填“博士”，HR04 已核验“硕士” | 生成 `HrOnboardingDataConflict(field, source_a, source_b, values, resolution)`，HR 裁决 | 可配置（默认不阻断报到，阻断激活前必须解决） |
| 姓名 | Portal 自填与 HR04 不一致 | DataConflict + HR 核对 | 阻断激活 |
| 组织/岗位 | HR04 与 HR05 计划组织不一致 | 以 HR04 录用时冻结岗位为准；变更需 HR02 校验 | 阻断激活 |
| 工号/人员类别 | 重复或冲突 | 抛 `STAFF_NUMBER_CONFLICT` / `PERSON_MATCH_CONFLICT` | 阻断激活 |

**禁止静默覆盖任何一方。**

---

## 4. 错误码（HR05 侧接收 handoff 时使用）

| 错误码 | 含义 |
|---|---|
| `ONBOARDING_CASE_INVALID_SOURCE` | source_type 非法/无来源创建被拒 |
| `ONBOARDING_CASE_DUPLICATE` | 同一 HR04 ProposedHire 已存在 case |
| `PERSON_MATCH_REQUIRED` | LIKELY/INSUFFICIENT_DATA，需人工去重确认 |
| `PERSON_MATCH_CONFLICT` | 去重冲突未解决 |
| `POSITION_RESERVATION_INVALID` | 预占失效/已释放/超期 |
| `BLOCKING_MATERIAL_MISSING` / `MATERIAL_NOT_VERIFIED` | 激活前材料不齐 |
| `VERSION_CONFLICT` | case 被并发修改 |
| `PORTAL_TOKEN_EXPIRED/REVOKED` | Portal 访问失败 |

---

## 5. 对账与验收（Recruit-to-Hire 闭环）

### 5.1 DUAL_READ_COMPARE 维度
- HR04 `HANDOFF_TO_HR05` 数量 vs HR05 case 数量；
- proposed_hire → case 一一对应，**重复 case = 0**；
- reservation 状态一致（HELD 在 HR04 与 HR05 引用一致）；
- Offer 状态（ACCEPTED）与 case 来源一致；
- 历史已 handoff 但 HR05 无 case → discrepancy 清单（可审）。

### 5.2 验收（05 §53 相关）
- HR04 handoff 自动建 case ✅；
- 重复 handoff 不重复建 case ✅；
- 未公示完成时禁止 handoff（HR04 侧拒绝）✅；
- 放弃/No-show 后 reservation 释放并通知 HR04 ✅；
- 审计链：HR04 handoff_id ↔ HR05 case_id ↔ HR03 staff 全程可追溯 ✅。

---

## 6. HR04 侧当前真实就绪度（S0 核实）

| 能力 | 真实状态 | 影响 |
|---|---|---|
| `ApplicationCanonicalStatus.HANDOFF_TO_HR05` | ✅ 已冻结（hr_recruitment/constants.py L40） | HR05 枚举/状态机可对齐 |
| `hr04.handoff_hr05` 权限码 | ✅ 已冻结（hr_recruitment/permissions.py L41） | HR05 权限命名可对齐 |
| `HrRecruitmentOffer`/`HrProposedHire` 模型 | ❌ 未建（HR04 仅 S1 契约层） | handoff 生产侧由 HR04-S8 实现；HR05 现在按契约预留消费端 + mock 测试 |
| `handoff-to-hr05` API | ❌ 未实现 | HR05-S3 以 Provider 契约 + 幂等 mock 先行，HR04-S8 完成后回填联调 |
