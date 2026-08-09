# HR09_RISK_REGISTER —— 教师资格与双师型风险登记册

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §179.11

---

## 风险分级

| 级别 | 定义 | 计数 |
|---|---|---|
| P0 | 阻断封板 — 业务正确性/安全/法律合规致命缺陷 | 8 |
| P1 | 严重 — 核心流程阻塞/对账失败/数据完整性受损 | 12 |
| P2 | 中等 — 功能降级/体验差/运维风险 | 8 |
| P3 | 低 — 未来扩展/文档/非功能性 | 5 |

---

## P0 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P0-01 | 教师资格与双师混淆 | 一个 `qualification` 字段无法区分法定资格与职业认定；KPI 计算错误 | 分层模型：TeacherQualification ≠ DoubleTeacherRecognition |
| P0-02 | 规则版本污染历史 | 修改学校规则后旧认定结果语义被污染；无法回答"2024年批次的认定依据是什么" | Batch 绑 Frozen RuleVersion；RuleVersion ACTIVE 后 immutable |
| P0-03 | 证据伪造 | 自报证书未经核验进入正式事实；自述"去过企业"冒充企业实践 | Source+Verification 分层；MANUAL_SUBMITTED ≠ VERIFIED |
| P0-04 | Provider 失败假 0 | 教务/HR10 不可用时企业实践=0 → 误判 FAIL_HARD_RULE | SOURCE_UNAVAILABLE ≠ 0；Provider 状态信封 |
| P0-05 | 证书撤销无影响链 | REVOKED 证书对应的双师认定继续有效 | HrEvidenceUsage 反向图 + 自动开 RecheckCase |
| P0-06 | 专家越权 | 专家可以评自己/直属上下级；冲突无人知晓 | HrPanelConflict 检测（CLEAR/DECLARED/DETECTED/RECUSED） |
| P0-07 | 跨租户泄露 | A 校管理员看到 B 校证书号/证照 | tenant_id 强制 fail-closed；证号 exact search 权限 |
| P0-08 | Legacy free-text 当权威 | Employee.qualification 字符串被视作正式资格 | LegacyQualificationMapping 明确策略：READONLY_PROJECTION |

---

## P1 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P1-01 | 正式 EFFECTIVE 后原地改 | 错误覆盖已生效认定 | 状态机 PROTECTED；amend 走 Recheck/Upgrade/Revoke |
| P1-02 | 续证覆盖旧记录 | 丢失证书完整代际 | HrCredentialRenewal 外键链；old→new 不可更新 |
| P1-03 | 复核失败覆盖历史 | 丢失原认定记录 | SUPERSEDED/REVOKED 不删除；History Timeline 完整 |
| P1-04 | 高级认定删除初级历史 | 丢失晋升路径约束 | 初/中/高级各自独立 Recognition record |
| P1-05 | 认定编号并发冲突 | recognition_no 重复 | tenant sequence + 乐观锁；禁止 max+1 |
| P1-06 | 重复提交同一批次 | 同人重复申报 | (batch_id, person_id, target_level) unique constraint |
| P1-07 | Final Decision 重复 | 双写最终认定 | version optimistic lock + unique constraint |
| P1-08 | Score 被直接修改 | 评审人提交后管理员改分 | LOCKED 后 reopen 需要审批并保留 revision |
| P1-09 | Rule Pack 发布后修改 | 规则语义漂移 | ACTIVE 后 immutable；新版本独立 |
| P1-10 | 学校规则弱化国家 HARD | 低于国家基本标准 | Rule Inheritance Validation：发布前 compare parent |
| P1-11 | Job 无 tenant context | 后台 Job 跨租户写 | 显式 tenant_id + service principal |
| P1-12 | 高敏字段泄露 | 身份证/银行卡/家庭信息进专家视图 | 服务端裁剪；Panel 默认 minimal view |

---

## P2 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P2-01 | 资格统计数据 stale | Dashboard 双师率过期 | sourceUpdatedAt/calculatedAt/maxStale 设置 |
| P2-02 | 双师率口径错误 | 分母≠合格专业课教师 | HR18 MetricDefinition 统一；numerator/denominator 可配置 |
| P2-03 | 证书到期阈值冲突 | EXPIRES_SOON 与 EXPIRED 边界模糊 | 风险派生 view，不占用主状态；90 天可配置 |
| P2-04 | Evidence Snapshot hash 缺失 | 无法验证证据未被篡改 | EvidencePackage.checksum + freeze 机制 |
| P2-05 | 预检延迟高 | 多源聚合慢 → 影响用户体验 | async PrecheckJob + 增量刷新 |
| P2-06 | 文件安全 | 长期 URL / 无病毒扫描 | private storage + signed URL + MIME validation + SHA-256 |
| P2-07 | 证书号明文日志 | 高敏信息泄露 | certificate_no_cipher + hash；日志仅 hash |
| P2-08 | 通知过量 | 风险/到期通知轰炸 | dedupe + 合并通知 + 邮件摘要 |

---

## P3 风险

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| P3-01 | 第三方核验接口不可用 | Provider 无法调外部 | MANUAL_ORIGINAL_REVIEW 降级通道 |
| P3-02 | 认定结果文件生成格式 | 电子证明/名单格式不一致 | template versioned |
| P3-03 | 电子签章未接入 | 无合法签章 | 不伪造"电子签章成功" |
| P3-04 | Rule Pack 无 policy 文档 | 规则无依据 | 发布前必需 policy_document_ids |
| P3-05 | Mobile 375px 复杂评审 | 评审操作困难 | 移动端只读/轻量；PC 优先 |

---

## 监控指标

| 指标 | 阈值 | 告警 |
|---|---|---|
| hr09_credentials_unverified | > 5% | WARN |
| hr09_credentials_expiring_30d | — | INFO |
| hr09_applications_pending | > batch deadline | WARN |
| hr09_precheck_source_unavailable | > 0 | CRITICAL |
| hr09_panel_conflict_total | > 0 | WARN |
| hr09_recheck_overdue | > 0 | WARN |
| hr09_evidence_invalidated | > 0 | INFO |
| hr09_legacy_drift | > 0 | WARN |

---

**文件状态：S0_BASELINE 冻结。**
