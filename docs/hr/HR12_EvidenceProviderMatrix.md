# HR12_EvidenceProviderMatrix —— 证据提供者矩阵

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §69-75 (EvidenceRef/MetricSnapshot) + §194-195 (Provider Contracts)

---

## 1. Provider 全景

| Provider | 源域 | 就绪状态 | HR12 消费方式 | 失败策略 |
|---|---|---|---|---|
| **PersonProvider** | HR03 | ✅ OK | as-of 人员/任职/组织 | UNAVAILABLE → 无法启动 Case |
| **OrganizationProvider** | HR02/HR03 | ✅ OK | org hierarchy, position | UNAVAILABLE → 无法分组 |
| **AgreementProvider** | HR07 | ✅ 384 OK | Contract term, duty snapshot, term goals, review due | UNAVAILABLE → TERM_CONTEXT_NOT_FOUND |
| **QualificationProvider** | HR09 | ✅ OK | Qualification status, double-teacher facts (reference only) | UNAVAILABLE → 该项标记 NOT_APPLICABLE |
| **DevelopmentProvider** | HR10 | ⚠️ 待 S6 集成 | VERIFIED Training/EnterprisePractice/DevelopmentOutput | UNAVAILABLE（Provider 契约占位）|
| **TimeSummaryProvider** | HR11 | ✅ 105 OK | Frozen period close: scheduled/worked/absence/late_early | 未月结→ SOURCE_NOT_FROZEN |
| **AcademicProvider** | 教务系统 | ⚠️ 外部 | Teaching assignments, hours, evaluation, quality facts | UNAVAILABLE → 教学指标不可计算 |
| **ResearchProvider** | 科研系统 | ⚠️ 外部 | Projects, publications, patents, roles, contributions | UNAVAILABLE → 科研指标不可计算 |
| **EthicsFactProvider** | 正式师德事实源 | ⚠️ 外部 | Verified formal ethics decisions | UNAVAILABLE → Gate 未决/REVIEW_REQUIRED |
| **DocumentProvider** | horilla_documents | ✅ OK | 证据文件存储/下载 | ERROR → 文件不可获取 |
| **NotificationProvider** | notifications | ✅ OK | 告知/通知发送 | FAILED → 待办通知 |
| **ArchiveProvider** | HR03 档案 | ⚠️ 待建 | 结论性材料存档 | ERROR → 归档失败（非 blocker） |

---

## 2. Provider 可信度映射

| Provider 返回数据类型 | Trust Level | 说明 |
|---|---|---|
| PersonProvider → staff/assignment | AUTHORITATIVE_VERIFIED | HR03 Authority 事实 |
| OrganizationProvider → org/position | AUTHORITATIVE_VERIFIED | HR02 Authority 事实 |
| AgreementProvider → term/contract | AUTHORITATIVE_VERIFIED | HR07 Authority 事实 |
| QualificationProvider → credential | SYSTEM_VERIFIED | HR09 核验事实 |
| DevelopmentProvider → verified training | HR10_VERIFIED | HR10 VERIFIED 事实 |
| TimeSummaryProvider → frozen metric | SYSTEM_VERIFIED | HR11 月结事实 |
| AcademicProvider → teaching data | AUTHORITATIVE_VERIFIED | 教务系统 Authority |
| ResearchProvider → research data | AUTHORITATIVE_VERIFIED | 科研系统 Authority |
| EthicsFactProvider → formal decision | AUTHORITATIVE_VERIFIED | 正式处分/处理记录 |
| SelfAssessment → self claim | SELF_REPORTED | 仅作 reference |
| MultiRaterFeedback → peer feedback | REVIEWER_VERIFIED | 经制度模板采集 |
| Migrated PMS data | MIGRATED_UNVERIFIED | 旧系统迁移，不可信 |
| Self uploaded document | SELF_REPORTED | 待 Reviewer 核验 |

---

## 3. Provider 状态信封

| 状态 | 含义 | 业务影响 |
|---|---|---|
| `OK` | 正常返回 | 正常消费 |
| `STALE` | 数据过期 | Dashboard 可用；正式 FINALIZE 前需刷新 |
| `PARTIAL` | 部分数据可用 | 部分指标可计算；缺失项标记 UNAVAILABLE |
| `UNAVAILABLE` | 源不可用 | **≠ 0**；≠ FAIL；≠ PASS；按 Policy 形成 blocker/人工处理 |
| `CONFLICT` | 数据冲突 | 人工审核 |
| `NOT_APPLICABLE` | 不适用 | 该指标不评价此人 |
| `ERROR` | 系统错误 | 系统级 blocker |

---

## 4. EvidenceRef 完整字段

```text
HrAssessmentEvidenceRef
├─ case_id          → 所属考核 Case
├─ indicator_id     → 对应指标
├─ provider_type    → ACADEMIC/RESEARCH/HR10/HR11/SELF/REVIEWER
├─ source_object_type → 源对象类型
├─ source_object_id   → 源对象 ID
├─ source_version     → 源对象版本
├─ source_as_of       → 数据 as-of 时间
├─ trust_level        → AUTHORITATIVE_VERIFIED ... SELF_REPORTED
├─ snapshot_hash      → 证据内容哈希
├─ status             → PENDING/VERIFIED/PARTIALLY_VERIFIED/REJECTED/SOURCE_UNAVAILABLE/CONFLICT
├─ verified_by        → 核实人
├─ verified_at        → 核实时间
├─ verification_method → PROVIDER_AUTHORITATIVE/DOCUMENT_VERIFICATION/REVIEWER_VERIFICATION
└─ verification_note  → 核实说明
```

---

## 5. Evidence Period Boundary 策略

| Period 类型 | 适用场景 | 说明 |
|---|---|---|
| `WITHIN_CYCLE` | 年度考核证据 | 只计算本考核周期内成果 |
| `WITHIN_TERM` | 聘期考核证据 | 覆盖整个聘期 |
| `AS_OF_DATE` | 快照型证据 | 师德 Gate / 资格状态 |
| `CUMULATIVE` | 累积型指标 | 累计发表/项目 |
| `ROLLING_WINDOW` | 滑动窗口 | 近N年成果 |
| `LIFETIME_REFERENCE` | 终身参照 | 代表性成果引用 |

---

## 6. Evidence Deduplication 规则

| 去重键 | 适用范围 | 策略 |
|---|---|---|
| `source_object_id` + `source_object_type` | 同一成果 | 单个 authoritative evidence → 多个 indicator links |
| DOI / 项目号 / 课程任务 ID | 科研/教学 | 一次计数；跨 indicator 共享引用 |
| HR10 DevelopmentFact ID | 培训/实践 | 一次计数 |
| File hash | 自上传附件 | 避免重复上传 |

**禁止**：同一成果不同标题变体重复加分；跨周期该算一次却自动累计。

---

## 7. Provider 失败场景处理矩阵

| 场景 | 年度考核 | 聘期考核 | 师德 | 平时考核 |
|---|---|---|---|---|
| Academic unavailable | 教学指标 UNAVAILABLE；按 Policy 人工处理 | — | — | — |
| Research timeout | 科研指标 UNAVAILABLE；不影响非科研岗 | — | — | — |
| HR10 unavailable | 培训/实践 UNAVAILABLE；不影响其他指标 | UNAVAILABLE | — | — |
| HR11 period not closed | 考勤指标 SOURCE_NOT_FROZEN | — | — | — |
| HR07 term missing | — | TERM_CONTEXT_NOT_FOUND → 无法创建 Case | — | — |
| EthicsFact partial | — | — | Gate REVIEW_REQUIRED | — |
| Document failed | 证据文件不可获取 | 同左 | 同左 | — |
| Notification failed | 告知 FAILED → 待办通知 | 同左 | — | — |
| Archive failed | 归档失败（非 blocker） | 同左 | 同左 | — |

---

## 8. Evidence Refresh Gate

| 阶段 | 允许 refresh | 说明 |
|---|---|---|
| DRAFT~SELF_SUMMARY | ✅ | 允许刷新 Provider |
| REVIEWING~ORG_REVIEW | ✅ 按需 | Reviewer 可触发 refresh |
| CALIBRATION | ❌ | 锁定 snapshot |
| COLLECTIVE_REVIEW | ❌ | 锁定 snapshot |
| FINALIZED | ❌ | 不可更改 |
| 源系统权威更正后 | ✅ EvidenceChangeDetected → Reassessment Review | 走正式流程 |

---

## 9. HR10/HR11 未就绪时的 Provider 契约占位

```python
# HR10 Development Provider 占位
class DevelopmentProvider:
    status = "UNAVAILABLE"
    reason = "HR10 not yet integrated; contract placeholder"
    # 等 HR10 S6 完成后替换为真实实现

# HR11 TimeSummary Provider (已就绪)
class TimeSummaryProvider:
    status = "OK"
    # 只消费 closed/frozen 月结指标
    # 不读 raw punch/data
```
