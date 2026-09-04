# HR10_RISK_REGISTER — 风险登记册

> 全局合同：`00_高校人事系统全局架构与旧系统接管合同.md`
> 业务事实源：`10_HR10_培训进修与企业实践_施工总册_终极版.md`
> 基线复审：`HR10_GAP_MATRIX.md`
> 版本：`S0_V1`
> 日期：2026-08-09

**风险严重度：**
- **CRITICAL**：可能导致数据污染、跨租户泄露、正式事实不可逆损坏、合规失败（需 0 容忍）
- **HIGH**：可能导致核心业务链阻塞、并发数据不一致、下游消费错误事实
- **MEDIUM**：可降级使用但有容忍不完美的风险
- **LOW**：可接受的技术债务，施工中解决

**状态：**
- `OPEN` — 未处理
- `MITIGATED_BY_DESIGN` — 总册设计已覆盖
- `TO_BE_ADDRESSED_IN` — 指定施工阶段解决
- `MONITORING` — 持续观察中
- `CLOSED` — 已消除

---

## 1. 数据正确性风险

| ID | 风险 | 代码证据 | 影响 | 缓解策略 | 严重度 | 状态 |
|---|---|---|---|---|---|---|
| R-D-01 | Employee.qualification 自由文本被误当培训事实 | `employee/models.py:108` CharField | 历史数据无法作为双师证据，可能虚假通过 | S10 staging→人工核验；MIGRATED_FREE_TEXT 标记 | HIGH | TO_BE_ADDRESSED_IN S10 |
| R-D-02 | 报名成功被误当培训完成 | 零代码但零约束 | 不完整的培训事实进入 HR09 双师证据链 | 总册 §2 显式禁止；Enrollment≠Completion≠VERIFIED three gates | CRITICAL | MITIGATED_BY_DESIGN |
| R-D-03 | 培训证书被误当职业资格 | 零代码但边界模糊 | 错误证书类型写入 HR09 credential | 总册 §68 证书分层：COMPLETION_CERTIFICATE→HR10 document; PROFESSIONAL_CREDENTIAL→HR09 | CRITICAL | MITIGATED_BY_DESIGN |
| R-D-04 | 进修学历在 HR10 自建第二套 EducationHistory | 零约束 | 与 HR03 形成双主学历 | 总册 §118: 通过 Provider Contract 提交 HR03 核验 | CRITICAL | MITIGATED_BY_DESIGN |
| R-D-05 | 企业实践只记录天数，无岗位/场景/评价/成果 | 零代码 | 无法区分参观 1 天 vs 真实岗位实践 1 天 | 总册 §72-94: PositionScene/Activity/Evidence/Evaluation/Output 全模型 | CRITICAL | MITIGATED_BY_DESIGN |
| R-D-06 | VERIFIED completion/final evaluation 被原地 UPDATE | 零代码 guard | 正式事实被污染，下游引用失效 | Immutable content_hash + revision_no + supersedes_id; model/service-level guard | CRITICAL | TO_BE_ADDRESSED_IN S5/S7 |
| R-D-07 | Program 发布后静默修改总学时/评价标准 | 零版本冻结 | 已完成历史被新规则重新解释 | PlanVersion/ProgramVersion/ProjectVersion PUBLISHED→immutable | CRITICAL | TO_BE_ADDRESSED_IN S2/S3/S6 |
| R-D-08 | 培训学时/学分/企业实践天数错误混为一个 total | 零分账 | 不同单位统计混淆，HR09 证据失真 | MetricLedger 分账：hours/credits/days 独立粒度 | CRITICAL | MITIGATED_BY_DESIGN |
| R-D-09 | 成果重复计数（同一成果被多个项目引用） | 零去重 | 双师证据膨胀 | duplicate_group_id + content_hash + duplicate detection | HIGH | TO_BE_ADDRESSED_IN S7 |
| R-D-10 | Provider 不可用被当作完成/Pass | 零区分 | 外部接口故障→假通过 | SOURCE_UNAVAILABLE 显式状态；禁止 fallback to legacy/complete | CRITICAL | MITIGATED_BY_DESIGN |
| R-D-11 | 历史规则修改后回溯覆盖旧事实 | 零 immutable 保护 | as-of 查询不可复现 | ComplianceRule effective_from/effective_to; old evaluations not recomputed | HIGH | TO_BE_ADDRESSED_IN S8 |
| R-D-12 | Excel 导入直接生成 VERIFIED completion | 零 staging pipeline | 批量错误事实进入 authority | staging→validation→error workbook→confirm→async pipeline | CRITICAL | MITIGATED_BY_DESIGN |

---

## 2. 安全与隐私风险

| ID | 风险 | 代码证据 | 影响 | 缓解策略 | 严重度 | 状态 |
|---|---|---|---|---|---|---|
| R-S-01 | 跨租户访问 fail-open | 零 HR10 tenant 机制 | 学校 A 看到学校 B 培训/实践数据 | All models inherit DevelopmentTenantModel; all API enforce tenant context | CRITICAL | TO_BE_ADDRESSED_IN S1 |
| R-S-02 | 教师通过改 staffId 看他人发展档案 | 零 self-only 保护 | 隐私泄露 | /me/development/* 强制当前用户匹配 staff_master; 不匹配→403 | CRITICAL | TO_BE_ADDRESSED_IN S4/S7/S8 |
| R-S-03 | 企业导师看到教师薪酬/身份证/家庭信息 | 零 field policy | PII 泄露给企业 | scoped access: assignment-link+expiry+field allowed; mentor portal 最小化 | CRITICAL | TO_BE_ADDRESSED_IN S7 |
| R-S-04 | 企业导师 token 永久有效/可复用 | 零 access grant 生命周期 | 长期未授权访问 | AccessGrant: bounded by engagement end_date + expiry + max_uses | HIGH | TO_BE_ADDRESSED_IN S7 |
| R-S-05 | 培训证书附件生成永久裸 URL | HR03 有 signed URL 模式 | 未授权访问敏感文件 | File security: private storage/short signed URL/token+permission before download | HIGH | TO_BE_ADDRESSED_IN S5/S7 |
| R-S-06 | 审批人无 data scope 但有 action permission 可审核 | 零 scope 关联 | 学院 A 审批学院 B 教师 | data scope + action permission 双重校验 | HIGH | TO_BE_ADDRESSED_IN S4 |
| R-S-07 | 敏感搜索关键词暴露 PII 于全文索引 | 零搜索治理 | 敏感信息泄露 | 身份证/薪酬等不进普通搜索索引; permission before ranking | MEDIUM | TO_BE_ADDRESSED_IN S8 |
| R-S-08 | 企业实践定位持续追踪 | 零默认但易被误设为强制 | 教师隐私侵犯 | Feature flag off by default; coarse site check only; no background continuous tracking | MEDIUM | MITIGATED_BY_DESIGN |

---

## 3. 架构与依赖风险

| ID | 风险 | 代码证据 | 影响 | 缓解策略 | 严重度 | 状态 |
|---|---|---|---|---|---|---|
| R-A-01 | HR03 Person/Staff 模型在 S1 时被修改导致 HR10 引用断裂 | HR03 正在施工 | HR10 identity root 不可用 | HR10 仅通过 FK provider 引用; HR03 变更→Provider contract 更新 | HIGH | MONITORING |
| R-A-02 | HR11 schedule/attendance 仍在施工，时间冲突检查接口不稳定 | HR11 在 S0 基线阶段 | 培训/实践时间冲突检查不可用 | HR11 有 abstract DevelopmentTimeProvider; HR10 S4 实现时需等待 HR11 ≥S4 | MEDIUM | TO_BE_ADDRESSED_IN S4/S9 |
| R-A-03 | HR09 双师模块未施工，HR10 evidence Provider 无消费者 | HR09 未创建 | 提供的接口暂时无下游消费 | HR10 S9 实现标准 Provider contract; HR09 施工时直接对接 | LOW | TO_BE_ADDRESSED_IN S9 |
| R-A-04 | HR15/财务模块未施工，预算/报销 Provider 不可用 | HR15 未创建（"budget" 全代码零匹配） | 培训费用只能记录估算，不能获取实际支付状态 | HR10 S4 保留 budget_reservation_ref; payment_status 投影 | LOW | MONITORING |
| R-A-05 | 教务/科研系统未对接 | 无接口 | 教学转化成果/科研产出无法自动认证 | output 存 PENDING_EXTERNAL_LINK; 待对接后通过 router 升级 | LOW | MONITORING |
| R-A-06 | Horilla approval/workflow 基线变更 | base 模块仍在维护 | 审批快照格式不兼容 | S4 审批模块独立于 base approval; 自有 HrDevelopmentApprovalSnapshot | MEDIUM | TO_BE_ADDRESSED_IN S4 |
| R-A-07 | 37+ 新模型依赖 Django ORM 在 MySQL 下全 green | MySQL-only 00 合同 | 约束/锁/索引/JSON 在 MySQL 与 SQLite 有差异 | S0 不创建表; S1/S2 在 MySQL 跑 migration 验证 | HIGH | TO_BE_ADDRESSED_IN S11 |
| R-A-08 | Outbox 事件消费者在 worker 故障时积压 | 零 outbox | 跨域事件丢/延迟→HR09 证据滞后 | Outbox: PENDING→PUBLISHED→FAILED→DEAD; retry + lag monitoring | HIGH | TO_BE_ADDRESSED_IN S9 |

---

## 4. 并发与性能风险

| ID | 风险 | 代码证据 | 影响 | 缓解策略 | 严重度 | 状态 |
|---|---|---|---|---|---|---|
| R-C-01 | 最后一个培训名额并发抢占 | 零控制 | 超名额报名 | SELECT FOR UPDATE / optimistic lock + transaction boundary | CRITICAL | TO_BE_ADDRESSED_IN S3 |
| R-C-02 | 候补转正并发超额 | 零控制 | 多人同时转正 | Atomic: 名额释放→候补队列 FIFO→转正；duplicate prevention | HIGH | TO_BE_ADDRESSED_IN S4 |
| R-C-03 | 预算预留并发超支 | 零控制 | 预算超支 | Reserved_amount: UPDATE WHERE reserved + committed <= planned AND version = current | HIGH | TO_BE_ADDRESSED_IN S4 |
| R-C-04 | 同一申请被重复审批 | 零幂等 | 审核状态污染 | ApprovalSnapshot unique(step_no, case_type, case_id) + idempotency key | HIGH | TO_BE_ADDRESSED_IN S4 |
| R-C-05 | Completion 被重复 finalize | 零幂等 | 多个 DevelopmentFact 对应同一 completion | Completion finalize idempotency: unique completion→fact | HIGH | TO_BE_ADDRESSED_IN S5 |
| R-C-06 | N+1 query 在大列表/档案页 | 零优化 | 大数据量下超时 | select_related/prefetch_related; pagination; EXPLAIN 验证 | MEDIUM | TO_BE_ADDRESSED_IN S11 |
| R-C-07 | 大规模导出阻塞 API | 零 async | 导出请求超时 | Async job: 导出→分页查询→文件生成→下载票据→到期清理 | MEDIUM | TO_BE_ADDRESSED_IN S11 |

---

## 5. 组织与流程风险

| ID | 风险 | 影响 | 缓解策略 | 严重度 | 状态 |
|---|---|---|---|---|---|
| R-P-01 | S0→S13 共 13 阶段，每个阶段 40-80 文件，工期压力大 | 质量下降、P0 未充分覆盖 | 总册 §179 明确施工顺序；S0 产出物化后逐阶段 PR | MEDIUM | OPEN |
| R-P-02 | HR09 作为 HR10 下游消费者同时施工 | 接口契约因双方未冻而频繁变更 | Provider contract 先冻结；变更通过 contract version 发布 | MEDIUM | MONITORING |
| R-P-03 | Tenant/department/position 等基础数据在 HR10 施工时可能因 HR02 变更而漂移 | 引用断裂 | 使用 effective-dated snapshot 而非 current value | LOW | MONITORING |
| R-P-04 | 培训/实践 UI 复杂度（6 模块 × 10+ tabs）导致前端工期超出 | 后端完成但前端不完整 | S2-S8 每个阶段自含 UI 施工 | MEDIUM | OPEN |
| R-P-05 | 施工 AI 自作主张将被禁止行为（如报名=完成）写入代码 | 违反总册红线 | 总册 §2 红线清单 + 每阶段 commit 前自检 | HIGH | OPEN |

---

## 6. 验收/灾难性负结果（对应总册 §55 章节）

| ID | 现象 | 根因 | 拦截措施 |
|---|---|---|---|
| R-N-01 | VERIFIED 培训事实实际只有报名记录 | 审核 AI 绕过 verification gate | Completion→VERIFIED 需要 at least 1 verification source 满足 policy minimum trust |
| R-N-02 | 企业实践看起来 180 天，实际只有 start/end 日期差 | days = end - start | Duration from verified ledger only; start/end dates are informational |
| R-N-03 | HR09 双师认定使用了自报培训记录 | Fact generated from SELF_REPORTED source | DevelopmentFact 只从 VERIFIED source 生成 |
| R-N-04 | 教师发展档案显示"已完成 300 学时"实际 200 学时重复计算 | 同一完成事实被多个 fact 引用 | Unique(completion→fact); duplicate detection on content_hash |
| R-N-05 | 项目发布后改了规则,去年完成记录被重新计算 | 规则未版本化 | Old completion records reference frozen program_version_id |
| R-N-06 | Excel 批量导入把 1000 条 free-text 直接标 VERIFIED | 绕过 staging pipeline | Excel pipeline enforced; no direct INSERT to authority models |
| R-N-07 | 因 Provider 超时 20 人培训/实践全标 Available/0/Pass | SOURCE_UNAVAILABLE→default pass | SOURCE_UNAVAILABLE 不进完成/评估; stays in pending review |
| R-N-08 | 企业导师看到了教师薪酬和家庭信息 | field policy 被绕过 | Mentor portal limited to assignment-scope + field-whitelist only |
| R-N-09 | 调岗/离职后教师仍能看到旧学院培训数据 | data scope 未更新 | scope resolved at request time with OrganizationProvider (HR02) |

---

## 7. P0 风险汇总

以下 12 项为施工全程 P0 风险，需实时跟踪：

| # | P0 风险 | 当前缓解 | 目标阶段解决 |
|---|---|---|---|
| 1 | 报名=完成 污染事实 | DESIGN | S4/S5 → 3 gates enforced |
| 2 | 培训证书=职业资格 | DESIGN | S5 → certificate routing to HR09 |
| 3 | 企业实践=天数 | DESIGN | S6/S7 → full model chain |
| 4 | Tenant fail-open | TO_BE_BUILT | S1 → DevelopmentTenantModel |
| 5 | 名额并发 unsafe | TO_BE_BUILT | S3/S4 → DB-level lock |
| 6 | VERIFIED 事实可原地改 | TO_BE_BUILT | S5/S7 → immutable guard |
| 7 | 项目发布后规则可静默改 | TO_BE_BUILT | S2/S3/S6 → version freeze |
| 8 | Provider UNAVAILABLE→Pass | DESIGN | S9 → explicit error state |
| 9 | Excel→直接 VERIFIED | TO_BE_BUILT | S2/S4/S6 → staging pipeline |
| 10 | 教师自报=已核验 | DESIGN | S4/S5/S7 → trust chain |
| 11 | 学历在 HR10 重复建权威 | DESIGN | S5 → HR03 writeback contract |
| 12 | 企业导师越权读 PII | TO_BE_BUILT | S7 → scoped access |

---

**文档状态：S0_V1 — 风险登记完成。CRITICAL=12, HIGH=20, MEDIUM=12, LOW=6。按施工阶段跟进关闭。**
