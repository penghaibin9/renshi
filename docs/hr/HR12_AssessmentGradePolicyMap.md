# HR12_AssessmentGradePolicyMap —— 考核档次政策映射

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §6-8 (年度/聘期/平时硬边界) + §49-51 (RatingScale/Grade)

---

## 1. 年度考核档次

| Grade Code | 中文显示 | 含义 | 正式统计 | 说明 |
|---|---|---|---|---|
| `EXCELLENT` | 优秀 | 表现突出，成绩显著 | ✅ 计入优秀数 | 受 Quota 约束 |
| `QUALIFIED` | 合格 | 完成岗位职责，达到考核要求 | ✅ 计入合格数 | 默认档次 |
| `BASICALLY_QUALIFIED` | 基本合格 | 基本完成岗位职责，但有不足 | ✅ 单独统计 | 需改进计划 |
| `UNQUALIFIED` | 不合格 | 未完成岗位职责，存在问题 | ✅ 单独统计 | 按制度处理 |
| `NO_RATING` | 不确定档次 | 不参加考核/按制度不评定 | ❌ 单独口径统计 | 需要 reason_code |
| `DEFERRED` | 缓定 | 因特殊原因延期确定档次 | ❌ 不参与当期统计 | 见 reason_code |
| `CANCELLED_NOT_RESULT` | 取消无结果 | 取消考核不产生结果 | ❌ 不参与统计 | 程序异常 |

---

## 2. 聘期考核档次

| Grade Code | 中文显示 | 含义 | 说明 |
|---|---|---|---|
| `QUALIFIED` | 合格 | 完成聘期目标任务 | 可能续聘/renewal review |
| `UNQUALIFIED` | 不合格 | 未完成聘期目标任务 | HR07 做 renewal decision |
| `NO_RATING` | 不确定档次 | 按制度不评定 | 需要 reason_code |
| `SPECIAL_POLICY` | 特殊政策 | 按特殊政策/制度处理 | 如返聘/延期等 |

**不是：** `renewable=true` 或 '建议续聘/不续聘'。聘期结论 ≠ 续聘决定。

---

## 3. NO_RATING Reason Codes

| Reason Code | 说明 | 适用场景 |
|---|---|---|
| `NEW_JOINER` | 新入职 | 入职不满 6 月/按 Policy |
| `TRANSFERRED` | 调岗 | 调岗后时间不足 |
| `LONG_LEAVE` | 长期请假 | 病/产/事假等 |
| `RETIRED_DURING` | 周期内退休 | 退休不参加 |
| `LEFT_DURING` | 周期内离校 | 离职不参加 |
| `EXTERNAL` | 外聘/兼职 | 按约不确定档次 |
| `PART_TIME` | 非全职 | 按 Policy |
| `MULTI_ASSIGNMENT` | 多岗人员 | 按特殊处理规则 |
| `DEFERRED_BY_POLICY` | 按政策缓定 | 如未决投诉 |
| `SPECIAL_POLICY` | 特殊政策 | 按具体制度 |
| `CANCELLED` | 取消考核 | 程序性取消 |

**禁止**：NULL、空字符串、`QUALIFIED` 伪装。

---

## 4. 年度考核 Score → Grade 映射（参考，Policy 可配置）

| Score Range | Recommendation | 说明 |
|---|---|---|
| 90-100 | EXCELLENT candidate | 提名优秀 + 需经 Quota+Collective 审定 |
| 70-89 | QUALIFIED | 合格 |
| 60-69 | BASICALLY_QUALIFIED | 基本合格 |
| <60 | UNQUALIFIED | 不合格 |

> ⚠️ Score → Grade 映射由 PolicyVersion.ResultRuleVersion 配置，不可代码写死。

---

## 5. 聘期考核条件（Policy 可配置）

| 条件 | 结论 |
|---|---|
| 聘期内所有年度均 QUALIFIED 及以上 + 聘期目标完成 | QUALIFIED |
| 聘期内有 UNQUALIFIED 年度 或 聘期目标未完成 | UNQUALIFIED (经审定) |
| 聘期内有 NO_RATING 年度 + 按 Policy 不可评估 | NO_RATING or SPECIAL_POLICY |
| 聘期内有 BASED_ON_POLICY 特殊情形 | SPECIAL_POLICY |

---

## 6. Hard Gate 清单

| Gate Code | 名称 | 效果 | 来源 |
|---|---|---|---|
| `ETHICS_PASS` | 师德合格 | 通过师德评价 | EthicsAssessmentCase |
| `ETHICS_BLOCKED` | 师德禁止 | HARD_GATE → 正式结果受阻 | EthicsFactProvider |
| `ETHICS_REVIEW_REQUIRED` | 师德待审 | PENDING_FORMAL_REVIEW → 暂缓或人工审定 | EthicsFactProvider |
| `QUALIFICATION_REQUIRED` | 资格前置 | 无资格不评某类考核 | PolicyVersion |
| `DISCIPLINARY_FORMAL` | 正式处分 | 受处分影响 | 制度事实 |
| `POLICY_HARD_GATE` | 制度硬门槛 | 学校制度规定 | PolicyVersion.GateRule |

**ETHICS_BLOCKED** 时：即使 Score=95，Final 仍为 BLOCKED——不能用高分掩盖硬门槛。

---

## 7. 优秀 Quota 政策

```text
HrExcellentQuotaPolicy
├─ policy_version_id
├─ quota_basis_population    → 基数口径（如 eligible ≠ NO_RATING）
├─ max_excellent_ratio       → 最大比例（默认 ≤0.20）
├─ classification_factor     → 岗位分类倾斜系数
├─ special_tilt_policy       → 特殊倾斜政策（JSON）
├─ over_quota_action         → BLOCKER / AUTHORIZED_OVERRIDE / COLLECTIVE_DELIBERATION
├─ rounding_rule             → ROUND_DOWN / ROUND_UP / ROUND_STANDARD
├─ min_eligible_for_quota    → 最小基数（防止小单位虚高中奖）
└─ effective_from / effective_to
```

**核心约束**：
- 不能把 quota 做成"自动降档算法"（自动把后几名从优秀降到合格）
- 超额触发 `OVER_QUOTA_BLOCKER` → 需有权组织逐人审定
- 不能为满足优秀比例偷偷改个人评分

---

## 8. 档次变化历史 (ResultRevision)

| Revision Type | 触发 | 示例 |
|---|---|---|
| `CORRECTION` | 展示/映射/录入错误 | 合格误写为"合格+" |
| `REASSESSMENT` | 新权威证据、Provider 更正、申诉成立、程序问题 | 教务更正教学课时后重新计算 |
| `OBJECTION_UPHELD` | 异议成立 | 原"不合格"改为"合格" |
| `COLLECTIVE_OVERRIDE` | 集体审定调整 | Calibration 后调整 |
| `POLICY_RETROACTIVE` | 制度回溯 | 新政策追认 |

`SUPERSEDED`：有新 ResultVersion；历史保留；不删除。

---

## 9. Calculation Trace 模板

每次计算生成完整链：

```text
input: 教学工作量 320h (AcademicProvider v2.1, 2026-06-30)
     → weight: 0.35 → weighted: 112.0
input: 教学评价 4.2/5 (AcademicProvider v2.1)
     → weight: 0.25 → weighted: 84.0
input: 科研项目 1 (ResearchProvider v1.5)
     → weight: 0.25 → weighted: 25.0
input: 发展 48h (HR10 Provider, VERIFIED)
     → weight: 0.05 → weighted: 4.8
input: 考勤 正常 (HR11 Frozen)
     → weight: 0.10 → weighted: 10.0
────────────────────────────────
calculated_score: 235.8 → 78.6%
calculated_recommendation: QUALIFIED
gate_ethics: PASS
────────────────────────────────
FINAL GRADE (after Collective Decision): QUALIFIED
decision_reason: 一致通过
decision_body: 学院考核工作领导小组
```

---

## 10. 禁止的档次操作

- ❌ `result.final_grade = calculate_score().grade` (自动公式当正式)
- ❌ `if special.status == "failed": annual.grade = "UNQUALIFIED"` (专项失败≠年度不合格)
- ❌ `sort score desc → take N → finalize EXCELLENT` (无审定自动优秀)
- ❌ `NO_RATING` 改为 NULL/空字符串/QUALIFIED
- ❌ FINALIZED → 直接 UPDATE
- ❌ 强制 `excellent = top 20% by score` (无制度依据)
- ❌ AI 自动年度/聘期/师德档次
