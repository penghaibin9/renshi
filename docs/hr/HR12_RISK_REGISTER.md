# HR12_RISK_REGISTER —— 年度与聘期考核风险登记册

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §244 自纠错清单 + §260 最终封板条件

---

## 风险分级

| 级别 | 定义 | 计数 |
|---|---|---|
| P0 | 阻断封板 — 业务正确性/安全/法律合规致命缺陷 | 16 |
| P1 | 严重 — 核心流程阻塞/对账失败/数据完整性受损 | 16 |
| P2 | 中等 — 功能降级/体验差/运维风险 | 9 |
| P3 | 低 — 未来扩展/文档/非功能性 | 6 |

---

## P0 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P0-01 | 公式得分自动成为正式档次 | `calculated_score.level → final_grade` 跳过人事审定；违反事业单位考核规定 | Calculation Trace 与 FinalDecision 分离字段/权限/生命周期 |
| P0-02 | 师德为普通 10% 权重 | 严重师德问题被其他高分抵消；违反"师德第一标准" | HARD_GATE 独立评估；GateResolution BLOCKED 不可被 Score 覆盖 |
| P0-03 | NO_RATING 混入 Qualified 统计 | 不参加/不确定档次人员被统计为合格；KPI 严重失真 | `grade_code=NO_RATING + reason_code` 独立统计口径 |
| P0-04 | 强制正态分布 | 无制度依据强制末位淘汰；违反评价改革精神 | Calibration 不提供"自动正态化"；Quota 只做 blocker 不做自动排序淘汰 |
| P0-05 | FINALIZED Result 原地 UPDATE | 正式考核结果被静默修改；所有下游消费者拿到篡改数据；法律后果 | `status=FINALIZED` → immutable；Amendment 走 ResultRevision (CORRECTION/REASSESSMENT) |
| P0-06 | 年度/聘期/平时混淆 | 一个通用表承担所有考核语义；聘期结果独立于年度 | 三个独立 Case 类型 + 独立 Result；ANNUAL≠TERM≠ROUTINE |
| P0-07 | 当前部门/岗位污染历史考核 | 今天调岗导致去年考核模板变化；历史不可解释 | SubjectSnapshot 冻结当时 org/position/classification；as-of query |
| P0-08 | Policy 修改影响历史 Cycle 结果 | "2024年优秀"依据的制度被 2026 修改后的规则解释 | PolicyVersion PUBLISHED→immutable；CycleSnapshot bind specific PolicyVersion |
| P0-09 | 聘期结果自动续聘/解除 | HR12 直接改 HR07 Contract/Autorenew/DisableAccount | TermAssessmentFinalized 事件 → HR07 RenewalPolicy Review；HR12 只输出结论 |
| P0-10 | Provider unavailable 当 0 分 | 教务不可用→教学工作量=0→FAIL；HR10 不可用→企业实践=0→不达标 | UNAVAILABLE ≠ 0；Provider 状态信封 + blocker 策略 |
| P0-11 | 未核实投诉/AI 判定师德 | 匿名评价、舆情、AI sentiment 自动 BLOCKED/BLOCKED | EthicsFactProvider 只返回正式已生效事实；AI 只做 ADVISORY |
| P0-12 | 跨租户泄露考核隐私 | A 校看到 B 校考核结果/评语/分数/师德问题 | tenant_id fail-closed；Reviewer scope + object scope + field policy |
| P0-13 | 同一成果多目标引用重复得分 | 同一篇论文挂 3 个目标各算一次 | EvidenceDeduplication (source_object_id + counting_policy) |
| P0-14 | Excel 直接 FINALIZE 正式结果 | 批量 Excel 导入绕过 Gate/CollectiveDecision/Publicity/Notice | Excel 只能 staging→validate→confirm→async apply；FINALIZE 必须 service gate |
| P0-15 | PMS Dashboard API 暴露员工排名 | `performers/` 和 `at-risk/` 端点公开全校分数排名/末位标签 | S10 必须 DEPRECATE 这 5 个 ranking API；HR18 Analytics 不做个人排名 |
| P0-16 | BonusPoint 信号链未切断 | employee→pms→payroll 的 BonusPoint 通道在新 HR12 下继续运作 | S10 Legacy Cutover 时显式 FREEZE 信号链；不可静默保留 |

---

## P1 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P1-01 | 目标发布后原地修改影响历史 | 目标语义漂移；无法回答"考核时目标是什么" | GoalVersion DRAFT→CONFIRMED；ChangeRequest→APPROVED V2；ReviewLock |
| P1-02 | Reviewer 本人评价自己 | 无自我利益冲突 | ReviewerConflict: CLEAR/DECLARED/DETECTED/RECUSED |
| P1-03 | 申诉复核人=原决策人 | 自审自判；程序无效 | Objection Reviewer conflict check（原 reviewer/calibration owner/collective finalizer/本人） |
| P1-04 | Calibration 无 before/after diff | 校准改分无迹可查；怀疑黑箱操作 | CalibrationRevision (before_rating/after_rating/reason_code/proposed_by/approved_by) |
| P1-05 | 公示不满足最低时长 FINALIZE | 违反公示制度；程序瑕疵 | PublicityBlocker: ASSESSMENT_PUBLICITY_INCOMPLETE |
| P1-06 | Quota 暗改个人分数满足比例 | "优秀人数超标，自动降最后 3 名" | OVER_QUOTA_BLOCKER → require authorized deliberation → per-person decision reason |
| P1-07 | Population 中途调岗静默变化 | Case 的 org 被改成新学院而无历史 | AssignmentChangedDuringAssessment event；KEEP_ORIGINAL_ORG / TRANSFER policy |
| P1-08 | Result Revision 不通知下游 | V2 产生后 HR07/HR13/HR14 仍用 V1 | ResultApplicationLedger + DownstreamAssessmentReviewRequired event |
| P1-09 | 聘期案例无 HR07 Term | 没有合同聘期也能评聘期考核 | TERM_CONTEXT_NOT_FOUND blocker |
| P1-10 | 年度结果缺失时聘期默认"合格" | 缺少某年度结果→TERM_INPUT_INCOMPLETE 被忽略 | TERM_INPUT_INCOMPLETE blocker；不能默认"每年合格" |
| P1-11 | Finalization Gate 跳过验证 | UNKNOWN/UNAVAILABLE 默认 PASS | Final gate checklist (population valid/policy frozen/evidence resolved/reviewers submitted/ethics gate/quota/publicity/collective decision) |
| P1-12 | 集体审定被一个管理员"批量通过"冒充 | DecisionSession 为空 | DecisionSession (body/quorum/participants/agenda/dissent) |
| P1-13 | Objection 删除或忽略 | 异议被丢弃 | Objection lifecycle: SUBMITTED→ACCEPTED→UNDER_REVIEW→UPHELD/MODIFIED/REJECTED→CLOSED |
| P1-14 | 后台 Job 无 tenant context | Job 跨租户写考核结果 | 显式 tenant_id + service principal；fail-closed |
| P1-15 | 通知失败=已告知 | 通知发送失败但系统标记 DELIVERED | delivery_status: PENDING→DELIVERED→VIEWED→FAILED；FAILED 进入待办 |
| P1-16 | Anonymous feedback 身份泄露 | 匿名评价人身份在导出中暴露 | raw answer export 默认不含 identity mapping；admin 调试也需受控审计 |

---

## P2 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P2-01 | Dashboard 指标 stale | 首页考核完成率过期 | sourceUpdatedAt/calculatedAt/maxStale + status |
| P2-02 | 聘期 Handoff 丢失或重复 | HR07 未收到或收到多次 TermAssessmentFinalized | Idempotency (consumer_event_id + result_id + version)；delivery/retry log |
| P2-03 | 迁移数据信任级错误 | 旧 1~5 feedback score 被当作正式年度结果 | MIGRATED_UNVERIFIED/MIGRATED_PARTIAL trust levels；展示为 legacy_reference |
| P2-04 | DUAL_READ_COMPARE 差异未跟踪 | Legacy vs HR12 差异悄悄累积 | Drift metric + reconciliation report |
| P2-05 | 考核周期学年 vs 自然年模糊 | 不同单位混用导致 period boundary 错误 | Cycle.business_year nullable; academic_year nullable; 由 Policy 配置 |
| P2-06 | 多 Assignment 人员只取第一条 | 兼岗人员的考核分类/Reviewer 错误 | EligibilityResolver 显式处理多 Assignment；禁止 `.first()` |
| P2-07 | 手机端泄露敏感信息 | 移动端展示未脱敏的评审详情 | Mobile self-service 只做高频自助（目标/进度/Check-in/看结果）；不做复杂评审 |
| P2-08 | 搜索索引含 PII | 评语/师德材料进入全局搜索 | 高敏正文不进通用搜索；permission/filter before ranking |
| P2-09 | Policy Simulator 影响正式数据 | Simulator 被误解或误设为正式 Case | Simulator 永远不 write 正式 Case/Result；明确标记 |

---

## P3 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P3-01 | 考核分析报表缺乏小样本保护 | 小学院人数少时档次分布可反推个人 | suppress/aggregate policy |
| P3-02 | 国际化未就绪 | 初始版本仅中文 | 中文优先；UI label via Policy snapshot（非 i18n） |
| P3-03 | 历史数据清理不完整 | 离职人员旧考核占空间 | Retention policy (FinalResult personnel record; Drafts shorter) |
| P3-04 | 旧 PMS routes 访问无 redirect | 收藏夹/书签失效 | /pms/* → /hr/assessments/* compat redirect + deprecation metric |
| P3-05 | 移动端体验不完整 | HR17 ESS 中考核部分缺少交互 | 优先级：看目标→Check-in→看结果→确认意见；复杂评审 Pad/PC |
| P3-06 | 考核公式文档化不足 | 学校无法理解"为什么系统算出这个分" | CalculationTrace (input metric version/value/weight/formula/intermediate/rounding/gate) |

---

## 风险缓解时间线

| 阶段 | 重点缓解风险 |
|---|---|
| S0-S1 | P0-06 (年度/聘期分离), P1-14 (Job tenant) |
| S2 | P0-08 (Policy 不可变), P1-01 (GoalVersion), P0-07 (Snapshot) |
| S3 | P0-01 (公式≠Final), P1-06 (Quota), P1-07 (Population freeze) |
| S4-S5 | P0-10 (Provider unavailable), P0-13 (证据去重), P1-02 (Reviewer conflict) |
| S6 | P0-04 (无正态), P0-03 (NO_RATING), P1-05 (Publicity), P1-04 (Calibration diff) |
| S7 | P0-09 (不自动续聘), P1-08 (Revision impact), P1-09 (Term required) |
| S8 | P0-02 (师德第一), P0-11 (AI 不得判定师德) |
| S9 | P0-05 (Finalized immutable), P1-03 (Objection conflict), P1-12 (CollectiveDecision) |
| S10-S11 | P0-12 (跨租户), P1-16 (匿名泄露), P2-03 (迁移 trust), P0-15 (PMS ranking API), P0-16 (BonusPoint 信号链) |
| S12-S13 | P0-14 (Excel), all P0/P1 residual |

---

## 风险登记结论

```text
HR12 RISK REGISTER COMPLETE (PRODUCTION REVIEW v1.1)
─────────────────────────────────────────────────────
P0 (blocking):  16 risks — 必须全部清零才能封板
P1 (severe):    16 risks — 必须全部缓解到可接受
P2 (medium):     9 risks — 大部分缓解
P3 (low):        6 risks — 记录跟踪

新增 P0-15: PMS Dashboard performers/at-risk 排名 API → S10 DEPRECATE
新增 P0-16: BonusPoint 跨切信号链 (employee→pms→payroll) → S10 FREEZE

最高优先级三条：
1. P0-01 公式≠Final —— 架构红线，不可妥协
2. P0-05 FINALIZED immutable —— 法律合规边界
3. P0-02 师德第一标准 —— 政策红线
```
