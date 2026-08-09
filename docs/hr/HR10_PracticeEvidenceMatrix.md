# HR10_PracticeEvidenceMatrix — 实践证据类型与可信等级矩阵

> 业务事实源：总册 §87–108 + §67
> 版本：`S0_V1`
> 日期：2026-08-09

---

## 0. 证据分层哲学

**不是所有证据是等价的。**
同一项实践可以有多源异构证据：企业系统记录（高可信）、导师确认（中高可信）、学校检查（中可信）、教师自拍（低可信）、历史迁移文本（未知可信）。

HR10 通过 `source` + `trust_level` + `verification_status` 三元组管理证据可信等级。

---

## 1. 证据来源分类

| 来源代码 | 来源 | 默认可信度 | 需要二次核验 | 示例 |
|---|---|---|---|---|
| `ENTERPRISE_SYSTEM` | 企业系统直连 | HIGH | N (除非异常) | E-HR 打卡、企业 OA 工作记录 |
| `ENTERPRISE_SIGNED_DOCUMENT` | 企业签字/盖章文档 | HIGH | N (除非伪造疑点) | 盖章的实践出勤表、企业证明 |
| `PROVIDER_API` | 培训/外部 Provider 回调 | HIGH | Y (Provider 核验) | 在线学习平台完成回调 |
| `MENTOR_DIRECT` | 企业导师直接提交 | MEDIUM-HIGH | Y (学校交叉核验) | 导师通过 portal 提交反馈 |
| `SCHOOL_CHECK` | 学校管理人员抽检 | MEDIUM-HIGH | N | 抽查记录、现场走访 |
| `MANUAL_COMMITTEE` | 专家委员会核验 | HIGH | N | 委员会对实践成果评审 |
| `SELF_SIGNED_LEDGER` | 教师手签日志 + 现场照片 | MEDIUM | Y | 教师手机拍照 + 时间戳 |
| `SELF_NARRATIVE` | 教师文字自述 | LOW | Y | 纯文本日志 |
| `IMPORT_STRUCTURED` | 批量导入的结构化数据 | MEDIUM | Y | Excel 导入的历史数据 |
| `IMPORT_FREE_TEXT` | 批量导入的自由文本 | LOW | Y | 旧系统备注字段 |
| `MIGRATED_DOCUMENT` | 迁移的历史文档 | UNKNOWN | Y | 旧附件迁移 |
| `EXTERNAL_REF` | 外部系统引用 | VARIES | Y | 教务系统的教学改革记录引用 |

---

## 2. 可信等级

| 级别 | 代码 | 含义 | 可进入正式事实 |
|---|---|---|---|
| 5 | `AUTHORITY_VERIFIED` | 被权威 Authority 验证 | Y |
| 4 | `PROVIDER_VERIFIED` | 被可信 Provider 验证 | Y |
| 3 | `DOCUMENT_VERIFIED` | 有签字/盖章/权威文档支持 | Y |
| 2 | `MANUAL_VERIFIED` | 被人工核验通过 | Y |
| 1 | `SELF_REPORTED` | 教师自报 | N (进入 staging) |
| 0 | `MIGRATED_UNVERIFIED` | 迁移未核验 | N (进入 staging) |
| -\ | `UNKNOWN` | 来源不可知 | N |

---

## 3. 证据类型矩阵

### 3.1 企业实践证据

| 证据类型 | 最小可信度要求 | 可进入 Evaluation | 可进入 DevelopmentFact | 来源代码 |
|---|---|---|---|---|
| 企业官方签章出勤表 | DOCUMENT_VERIFIED (3) | Y | Y | ENTERPRISE_SIGNED_DOCUMENT |
| 企业系统出勤数据 | PROVIDER_VERIFIED (4) | Y | Y | ENTERPRISE_SYSTEM |
| 导师评价反馈 | DOCUMENT_VERIFIED (3) | Y (必需) | Y | MENTOR_DIRECT |
| 学校评价结论 | MANUAL_VERIFIED (2) | Y (必需) | Y | SCHOOL_CHECK |
| 实践总结报告 | DOCUMENT_VERIFIED (3) | Y (推荐) | — | SELF_SIGNED_LEDGER + SIGNATURE |
| 活动现场照片 | DOCUMENT_VERIFIED (3) | Y (辅助) | — | SELF_SIGNED_LEDGER + PHOTO |
| 教学转化成果 | DOCUMENT_VERIFIED (3) | — | Y | EXTERNAL_REF (教务) |
| 专利/标准引用 | PROVIDER_VERIFIED (4) | — | Y | EXTERNAL_REF (科研) |
| 教师自报日志 | SELF_REPORTED (1) | — | — (进入 Risk if no other evidence) | SELF_NARRATIVE |
| 历史迁移记录 | MIGRATED_UNVERIFIED (0) | — | — | IMPORT_FREE_TEXT |

### 3.2 培训证据

| 证据类型 | 最小可信度要求 | 可进入 Completion | 可进入 DevelopmentFact | 来源代码 |
|---|---|---|---|---|
| 培训 Provider 完成证书 | PROVIDER_VERIFIED (4) | Y | Y | PROVIDER_API |
| 组织方签到表 | DOCUMENT_VERIFIED (3) | Y | Y | SCHOOL_CHECK |
| 线上平台学习记录 | PROVIDER_VERIFIED (4) | Y | Y | PROVIDER_API |
| 培训讲师确认 | MANUAL_VERIFIED (2) | Y | Y | MENTOR_DIRECT |
| HR 人工核验 | MANUAL_VERIFIED (2) | Y | Y | MANUAL_COMMITTEE |
| 自拍证书 | SELF_REPORTED (1) | — | — | SELF_NARRATIVE |
| 历史迁移记录 | MIGRATED_UNVERIFIED (0) | — | — | IMPORT_FREE_TEXT |

### 3.3 进修证据

| 证据类型 | 最小可信度要求 | 里程碑可标记 | 来源代码 |
|---|---|---|---|
| 录取通知书 | DOCUMENT_VERIFIED (3) | ADMITTED | EXTERNAL_REF |
| 注册证明 | DOCUMENT_VERIFIED (3) | REGISTERED | EXTERNAL_REF |
| 成绩单 | DOCUMENT_VERIFIED (3) | COURSE_COMPLETED | EXTERNAL_REF |
| 学位/学历证书 | PROVIDER_VERIFIED (4) → HR03 EducationHistory | GRADUATED → writeback to HR03 | EXTERNAL_REF |
| 回岗报到 | DOCUMENT_VERIFIED (3) | RETURNED_TO_POST | SCHOOL_CHECK |

---

## 4. Completion/Final Evaluation 证据要求

### 培训完成核验

```text
LearningCompletion 进入 VERIFIED 前需要：
├─ 至少 1 项 evidence 满足 policy minimum trust
├─ 若 provider_verification_required → at least 1 provider source
├─ 总学时 ≥ program_version.completion_rule_json.minimum_hours
├─ 无 open risk case 标记此 completion 为 suspicious
└─ 所有 required session attendance 状态非 ABSENT (除非 EXCUSED)
```

### 企业实践最终评价

```text
EnterprisePracticeEvaluation 进入 FINAL 前需要：
├─ Enterprise mentor feedback submitted (at least 1)
├─ School evaluation submitted
├─ Verified duration ≥ project_version.completion_rule_json.minimum_duration
├─ Required task modules all met
├─ Required evidence all submitted + verified
├─ Safety/incident status: no open incidents
├─ Required output submitted (if output_requirements_json not empty)
├─ Prerequisites all confirmed passed
└─ No unresolved risk cases flagged as blocking
```

---

## 5. Evidence → Fact 升级路径

```text
Evidence (any source)
    │
    ▼
Evidence Verification
    │ (trust_level >= policy minimum)
    ▼
VERIFIED Evidence
    │
    ▼
Completion / Evaluation
    │ (all required evidence + rules met)
    ▼
VERIFIED Completion / Finalized Evaluation
    │
    ▼
HrDevelopmentFact (FactType = TRAINING_COMPLETION / ENTERPRISE_PRACTICE / ...)
    │
    ▼
HR09 Evidence Provider
    │
    ▼
HR09 双师证据
```

禁止跳级：
- 禁止 Evidence DRAFT → Fact
- 禁止 Evaluation DRAFT → Fact
- 禁止 SELF_REPORTED evidence → Fact (without explicit manual verification upgrade)
- 禁止 MIGRATED_FREE_TEXT → Fact (without verification)

---

## 6. Evidence 安全与隐私

| 证据内容 | 敏感级别 | 访问控制 |
|---|---|---|
| 企业内部工艺文件 | RESTRICTED | 仅实践负责人+评估委员会（企业导师可见自己提交的） |
| 个人出勤记录 | PERSONAL | 本人+实践负责人+学院管理员 |
| 身份证/证书编号 | SENSITIVE_PERSONAL | 仅 HR 核验人员 |
| 导师评价 | PERSONAL | 评价人+本人+学校评估人员 |
| 医疗证明（安全培训） | SENSITIVE_PERSONAL | 仅必要安全人员 |
| 产线/岗位照片 | INTERNAL | scoped to assignment |

---

**文档状态：S0_V1 — 证据矩阵完成。12 类来源 + 7 级可信度 + 3 类证据类型 + Completion/Evaluation 证据要求 + 升级路径。**
