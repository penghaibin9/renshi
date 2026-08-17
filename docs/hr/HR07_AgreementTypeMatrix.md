# HR07 Agreement Type / Family Matrix（S0 物化 · 配置域默认集）

> 默认集可在学校配置；不把全国/某省具体类型硬编码为唯一选择（HR07 §9）。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`

---

## 1. Agreement Family（§8）

| Family Code | 说明 | max_active_per_relationship | overlap_policy | requires_relationship | requires_assignment | affects_employment_end | affects_payroll | requires_signature | requires_approval |
|---|---|---|---|---|---|---|---|---|---|
| `PRIMARY_EMPLOYMENT` | 主聘用合同 | 1 | HARD_OVERLAP 禁止 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `SUPPLEMENTARY` | 补充/变更协议 | many | 允许（绑定 parent） | ✅ | 否 | 依条款 | 依条款 | ✅ | ✅ |
| `TALENT_INTRODUCTION` | 人才引进协议 | 学校可配（默认 1） | 允许与主合同并行 | ✅ | 否 | ✅ | ✅ | ✅ | ✅ |
| `CONFIDENTIALITY` | 保密协议 | many | 允许 | ✅ | 否 | 否 | 否 | ✅ | ✅ |
| `INTELLECTUAL_PROPERTY` | 知识产权协议 | many | 允许 | ✅ | 否 | 否 | 否 | ✅ | ✅ |
| `PART_TIME` | 兼职协议 | many | 允许 | ✅ | 可选 | 否 | ✅ | ✅ | ✅ |
| `EXTERNAL_EXPERT` | 外聘/专家协议 | many | 允许 | ✅（或 HR08 engagement） | 可选 | 否 | ✅ | ✅ | ✅ |
| `SERVICE` | 劳务/服务协议 | many | 允许 | 可选 | 否 | 否 | ✅ | ✅ | ✅ |
| `PROJECT` | 项目协议 | many | 允许 | 可选 | 否 | 否 | ✅ | ✅ | ✅ |
| `OTHER` | 其他 | many | 允许 | 可选 | 否 | 否 | 否 | ✅ | ✅ |

> V1 内置 10 family；`max_active` 为配置字段（school configurable），`PRIMARY_EMPLOYMENT` 冻结为 1。

## 2. Agreement Type（§9）

| Type Code（默认） | 中文名 | family | term_mode | requires_end_date | requires_review_date | 备注 |
|---|---|---|---|---|---|---|
| `PUBLIC_INSTITUTION_EMPLOYMENT` | 事业单位聘用合同 | PRIMARY_EMPLOYMENT | FIXED | 是 | 是 | 默认主合同 |
| `LABOR_CONTRACT` | 劳动合同 | PRIMARY_EMPLOYMENT | FIXED | 是 | 是 | 劳动合同制 |
| `FIXED_TERM` | 固定期限聘用合同 | PRIMARY_EMPLOYMENT | FIXED | 是 | 是 | |
| `OPEN_ENDED` | 无固定期限合同 | PRIMARY_EMPLOYMENT | OPEN_ENDED | 否 | 可选 | |
| `LABOR_DISPATCH` | 劳务协议 | SERVICE | EVENT_BOUND | 可选 | 否 | 劳务/服务 |
| `EXTERNAL_TEACHER` | 外聘教师协议 | EXTERNAL_EXPERT | FIXED | 是 | 是 | HR08 联动 |
| `TALENT_INTRODUCTION` | 人才引进协议 | TALENT_INTRODUCTION | FIXED | 是 | 是 | HR04 联动 |
| `SUPPLEMENTARY` | 补充协议 | SUPPLEMENTARY | EVENT_BOUND | 否 | 否 | parent 绑定 |
| `CONFIDENTIALITY` | 保密协议 | CONFIDENTIALITY | OPEN_ENDED | 否 | 否 | |
| `INTELLECTUAL_PROPERTY` | 知识产权协议 | INTELLECTUAL_PROPERTY | OPEN_ENDED | 否 | 否 | |
| `PROBATION` | 试用期协议 | SUPPLEMENTARY | EVENT_BOUND | 是 | 否 | 试用约定 |
| `OTHER` | 其他 | OTHER | EVENT_BOUND | 否 | 否 | |

## 3. term_mode 语义（§10/§14）

| mode | contract_end_date | review_date | 说明 |
|---|---|---|---|
| `FIXED` | 必填 | 依类型/规则 | 固定期限 |
| `OPEN_ENDED` | NULL（禁止 2099-12-31，00 §7） | 可选 | 无固定期限 |
| `EVENT_BOUND` | 可选 | 否 | 以事件/项目为界 |

## 4. 编号规则默认集（§27）

| 默认 Rule | prefix | year_segment | type_segment | sequence_length | reset_policy | immutable_after_issue |
|---|---|---|---|---|---|---|
| `YK-EMP` | `YK-EMP` | YYYY | 无 | 6 | YEARLY | ✅ |
| `YK-SUP` | `YK-SUP` | YYYY | 无 | 6 | YEARLY | ✅ |
| `YK-EXT` | `YK-EXT` | YYYY | 无 | 6 | YEARLY | ✅ |

分配用 DB sequence / row lock；禁止 `max(no)+1`；作废编号不回收（HR07 §27）。

## 5. 预警默认建议（§61 仅默认建议，学校可配）

```text
180 天：可选早期提示（INFO）
90 天：启动续聘评审（MEDIUM）
60 天：学院意见（MEDIUM）
30 天：HR 高优先（HIGH）
7 天：升级（HIGH）
到期日：critical（CRITICAL）
过期未处理：daily/periodic escalation（CRITICAL）
```
