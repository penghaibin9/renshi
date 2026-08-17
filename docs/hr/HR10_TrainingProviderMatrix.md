# HR10_TrainingProviderMatrix — 培训/实践提供机构矩阵

> 全局合同：`00_高校人事系统全局架构与Horilla接管合同.md`
> 业务事实源：总册 §25 + §44 + §71
> 版本：`S0_V1`
> 日期：2026-08-09

---

## 0. 模型基础

HR10 使用统一的 `HrDevelopmentProviderOrganization` 模型管理所有培训机构/企业/实践基地。
不与 HR03 Organization 或 HR02 Department 混用（内部主办培训可通过 `owner_org_id` 引用 HR02 组织）。

---

## 1. Provider 机构类型

| 代码 | 类型 | 示例 | 需要核验 |
|---|---|---|---|
| `SCHOOL` | 其他学校/高校 | 合作院校、进修接受学校 | Y |
| `UNIVERSITY` | 大学 | 学历提升、访学接受大学 | Y |
| `ENTERPRISE` | 企业 | 企业实践基地、合作企业 | Y |
| `GOVERNMENT` | 政府机构 | 教育主管部门、人事厅 | — |
| `ASSOCIATION` | 行业协会 | 专业协会、学会 | Y |
| `TRAINING_ORG` | 培训机构 | 社会培训公司、在线教育平台 | Y |
| `RESEARCH_INST` | 科研院所 | 研究院、技术转移中心 | Y |
| `INTERNATIONAL_ORG` | 国际组织/机构 | 国外合作院校、国际认证机构 | Y |
| `OTHER` | 其他 | — | Y |

---

## 2. Provider 关键字段

```text
HrDevelopmentProviderOrganization
├─ Basic
│  ├─ provider_code        (tenant-scoped unique)
│  ├─ provider_kind        (9 类)
│  ├─ legal_name           (法人全称)
│  ├─ short_name           (简称)
│  └─ unified_social_credit_code_hash   (统一社会信用代码 SHA256，PII 保护)
├─ Verification
│  ├─ verification_status  (PENDING / VERIFIED / EXPIRED / REVOKED / BLACKLISTED)
│  ├─ verified_at
│  ├─ valid_from / valid_to (有效期)
│  ├─ verification_document_ref (核验材料引用)
│  └─ verification_notes
├─ Practice Base Extension
│  ├─ practice_base_level  (NATIONAL_PROVINCIAL / SCHOOL_LEVEL / OTHER / NONE)
│  ├─ official_reference   (官方批准文号/备案号)
│  └─ specialty_scope_json (适用专业类群)
├─ Service Scope
│  ├─ service_scope_json   (可提供服务的类型列表)
│  ├─ specialty_scope_json
│  └─ capacity_summary     (承载能力描述)
├─ Risk
│  ├─ risk_status          (LOW / MEDIUM / HIGH / CLOSED / SUSPENDED)
│  ├─ risk_notes
│  └─ last_risk_review
├─ Contact
│  ├─ contact_person_display (联系人显示名，不存完整 PII)
│  ├─ contact_ref          (联系方式引用，实际 PII 存 Document/加密)
│  ├─ address_summary      (地址摘要)
│  ├─ emergency_contact
│  └─ safety_contact
├─ Metadata
│  ├─ source               (MANUAL / IMPORT / EXTERNAL_PROVIDER_API)
│  ├─ version              (乐观锁)
│  ├─ created_by
│  ├─ created_at
│  └─ updated_at
```

---

## 3. Provider 生命周期与状态机

```text
DRAFT
└→ UNDER_VERIFICATION
   ├→ VERIFIED
   │  ├→ RISK_NEEDS_REVIEW (自动/人工)
   │  │  ├→ VERIFIED (风险解除)
   │  │  ├→ RESTRICTED (部分服务受限)
   │  │  └→ BLACKLISTED
   │  ├→ EXPIRED (有效期过)
   │  │  ├→ RENEWAL_VERIFICATION → VERIFIED
   │  │  └→ DEREGISTERED
   │  └→ DEREGISTERED (主动退出)
   ├→ REJECTED
   └→ BLACKLISTED (直接拉黑，跳过 VERIFIED)

状态转换：
VERIFIED ↔ RISK_NEEDS_REVIEW
VERIFIED → RESTRICTED
VERIFIED → BLACKLISTED
BLACKLISTED → 不可逆转（需新建 Provider 记录）
```

---

## 4. Provider 与项目的关系

- 项目（HrLearningProgram / HrEnterprisePracticeProject）发布时保存 provider **快照**
- 快照包括：legal_name, practice_base_level, specialty_scope, risk_status, contact 摘要
- Provider 后续变更（如被拉黑）不影响已发布/已完成项目
- 新班次/新批次如仍引用该 provider → check risk_status → 可能 block creation

---

## 5. Provider 核验策略

| 核验项 | 必填级别 | 核验方式 |
|---|---|---|
| 统一社会信用代码 | 企业必填；学校/政府可选 | hash→政府公开查询 API（或人工录入核验结果） |
| 营业执照/组织证书 | 企业/培训组织必填 | 文件上传→人工审核 |
| 实践基地官方认定 | 国家级/省级基地必填 | 备案号→主管部门文件引用 |
| 法人代表/联系人信息 | 所有 provider 必填 | 不存完整身份证号 |
| 专业服务范围 | 企业/培训组织/科研院所推荐 | 自申报+人工审核 |
| 安全资质（企业实践） | 企业实践 provider 必填 | 安全培训记录/保险证明 |
| 合作历史/投诉记录 | 所有 provider 推荐 | 系统内关联项目回顾 |

---

## 6. 旧代码 Provider 残留

| 旧引用 | 位置 | 策略 |
|---|---|---|
| `hr_external.constants.*PROVIDER*` | 无单独 PROVIDER 枚举 | 不冲突；HR08 管人，HR10 管机构 |
| `base.models.Company` (作为企业) | `base/models.py` | `Company` 是租户主体（学校），不是培训机构。不用于 HR10 |
| `employee.models.Department` 合作企业备注 | free-text | 搬运到 staging |
| `document` 中以企业名字存储的协议 | `horilla_documents` | 引用为 evidence |

---

## 7. Tenant 隔离策略

- `tenant_id` 列在 ProviderOrganization 上
- 学校 A 创建的 Provider 对学校 B 不可见（默认 fail-closed）
- **可选**：平台级 Verified Provider Catalog（跨 tenant 共享）通过 `tenant_id=NULL + verified=true + platform_shared=true` 配置
- 平台共享 Provider 的核验由平台运营负责

---

## 8. Provider 禁止事项

- 禁止因一个项目完成核验就长期标记 Provider 为 VERIFIED 且永不失效
- 禁止从 provider contact 泄露法人身份证/个人手机/家庭地址给无关用户
- 禁止跨 tenant 复用 provider 核验材料
- 禁止 provider 拉黑后仍被用于新项目（需 risk gate 拦截）

---

**文档状态：S0_V1 — Provider 矩阵完成。9 类机构 + full lifecycle + snapshot 策略。**
