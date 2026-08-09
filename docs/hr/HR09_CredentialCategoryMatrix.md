# HR09_CredentialCategoryMatrix —— 资格目录分类矩阵

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §18-19 + 三家 HCM 对标

---

## 1. 证书分类体系

```text
CredentialCategory
├── TEACHER_QUALIFICATION          // 法定教师资格（单独 Category）
│   ├── HIGHER_EDUCATION_TEACHER
│   ├── SECONDARY_VOCATIONAL_TEACHER
│   ├── SECONDARY_VOCATIONAL_PRACTICE_INSTRUCTOR
│   └── OTHER_LEGAL_TEACHER_QUALIFICATION
├── VOCATIONAL_QUALIFICATION       // 国家职业资格
│   ├── LEVEL_1 (高级技师)
│   ├── LEVEL_2 (技师)
│   ├── LEVEL_3 (高级工)
│   ├── LEVEL_4 (中级工)
│   └── LEVEL_5 (初级工)
├── VOCATIONAL_SKILL_LEVEL         // 职业技能等级
│   ├── LEVEL_1 (高级技师)
│   ├── LEVEL_2 (技师)
│   ├── LEVEL_3 (高级)
│   ├── LEVEL_4 (中级)
│   └── LEVEL_5 (初级)
├── NON_TEACHER_PROFESSIONAL_TITLE // 非教师系列职称
│   ├── SENIOR (正高级)
│   ├── DEPUTY_SENIOR (副高级)
│   ├── INTERMEDIATE (中级)
│   └── JUNIOR (初级)
├── PROFESSIONAL_LICENSE           // 专业执业资格
│   └── (如注册会计师/法律职业资格/执业医师等)
├── INDUSTRY_CERTIFICATION         // 行业认证
│   └── (如华为认证/思科认证/AWS认证等)
├── TRAINING_CERTIFICATE           // 培训证书
│   └── (如岗前培训/骨干教师培训等)
└── OTHER                          // 其他
    └── (如语言能力/计算机水平/驾驶证等非专业证书)
```

---

## 2. 字段映射：HrCredentialCatalogItem

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | — |
| tenant_id | FK nullable | NULL=系统级目录，非NULL=租户扩展 |
| code | VARCHAR(64) UNIQUE | 唯一编码 |
| category | VARCHAR(32) | 一级分类（TEACHER_QUALIFICATION/...） |
| name | VARCHAR(200) | 中文名称 |
| issuer_type | VARCHAR(32) | 签发机构类型 |
| issuer_catalog_ref | VARCHAR(64) | 签发机构目录引用（可选） |
| level_schema | JSON | 等级体系定义 |
| validity_policy | JSON | 有效期政策（如：永久有效/5年/3年） |
| requires_document | BOOLEAN | 是否强制上传附件 |
| requires_external_verification | BOOLEAN | 是否需要第三方核验 |
| applicable_professions | JSON | 适用专业/行业 |
| skill_mappings_json | JSON | 技能映射 |
| status | VARCHAR(16) | ACTIVE/INACTIVE/DEPRECATED |
| version | BIGINT | 乐观锁 |

---

## 3. 教师资格扩展字段

TEACHER_QUALIFICATION 类型的 PersonCredential 额外承载：

| 扩展字段 | 类型 | 说明 |
|---|---|---|
| qualification_type | VARCHAR(32) | HIGHER_EDUCATION / SECONDARY_VOCATIONAL / PRACTICE_INSTRUCTOR / OTHER |
| certificate_no | VARCHAR(64) | 教师资格证号 |
| recognition_authority | VARCHAR(200) | 认定机构 |
| recognized_at | DATE | 认定日期 |
| subject_or_discipline | VARCHAR(200) | 任教学科 |
| legal_status | VARCHAR(32) | VALID / REVOKED / LOST / SUSPENDED |

---

## 4. 三家 HCM 对标映射

| Workday | SAP SuccessFactors 1H 2026 | Oracle Fusion | 跃科 HR09 |
|---|---|---|---|
| Certifications | Certificates (Talent Intelligence Hub) | Licenses & Certifications | HrCredentialCatalogItem + HrPersonCredential |
| Skills (self/manager assessment) | Skill Mapping (certificate→skill) | Competencies | skill_mappings_json (目录级) |
| Worker Profile Requirements | — | Job/Position Requirements | HrCredentialRequirement |
| — | Proof Document (required) | Verification | HrCredentialDocument + HrCredentialVerification |
| — | Expiry/Renewal/Notification | Expiry/Missing Risk | validity_policy + HrCredentialRenewal + HrQualificationRiskCase |
| — | Manager Approval Workflow | — | Verification workflow (future) |

---

## 5. Level Schema 定义（JSON 示例）

```json
{
  "levels": [
    {"code": "LEVEL_1", "name": "高级技师", "rank": 5},
    {"code": "LEVEL_2", "name": "技师", "rank": 4},
    {"code": "LEVEL_3", "name": "高级工", "rank": 3},
    {"code": "LEVEL_4", "name": "中级工", "rank": 2},
    {"code": "LEVEL_5", "name": "初级工", "rank": 1}
  ],
  "ordered": true,
  "min_valid_level": "LEVEL_5"
}
```

---

## 6. 种子数据：核心目录项

| code | category | name | issuer_type | validity_policy |
|---|---|---|---|---|
| TQ-HEDU | TEACHER_QUALIFICATION | 高等学校教师资格 | EDUCATION_AUTHORITY | permanent |
| TQ-SVTE | TEACHER_QUALIFICATION | 中等职业学校教师资格 | EDUCATION_AUTHORITY | permanent |
| TQ-SVPI | TEACHER_QUALIFICATION | 中等职业学校实习指导教师资格 | EDUCATION_AUTHORITY | permanent |
| VQ-L1 | VOCATIONAL_QUALIFICATION | 国家职业资格一级（高级技师） | MOHRSS | permanent |
| VQ-L2 | VOCATIONAL_QUALIFICATION | 国家职业资格二级（技师） | MOHRSS | permanent |
| SL-L1 | VOCATIONAL_SKILL_LEVEL | 职业技能等级一级（高级技师） | ASSESSMENT_AGENCY | 3 years |
| SL-L2 | VOCATIONAL_SKILL_LEVEL | 职业技能等级二级（技师） | ASSESSMENT_AGENCY | 3 years |
| NT-SEN | NON_TEACHER_PROFESSIONAL_TITLE | 非教师系列正高级 | TITLE_APPROVAL_AUTHORITY | permanent |
| NT-DEP | NON_TEACHER_PROFESSIONAL_TITLE | 非教师系列副高级 | TITLE_APPROVAL_AUTHORITY | permanent |

---

**文件状态：S0_BASELINE 冻结。**
