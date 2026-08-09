# HR07 TASK TREE（S0 物化 · 按总册 #135 顺序）

> 每个阶段一个可验证提交（Draft PR，不合并 main）。Shell 在本机不可用，测试/迁移/提交由用户在 IDE/终端执行；每阶段附验证清单。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`

---

## HR07-S0 基线复审（已完成）

- [x] 审计 payroll Contract（models/forms/cbv/views/urls/scheduler/signals）
- [x] 审计 employee contract_end_date / 导入建 Contract
- [x] 审计 horilla_documents / horilla_audit / notifications
- [x] 读取 HR03 服务契约（HrEmploymentRelationship/Assignment/EffectiveDatedQueryService）
- [x] 物化 HR07_GAP_MATRIX / LegacyContractMapping / PayrollContractDependencyMap / AgreementTypeMatrix
- [x] 物化 HR07_TASK_TREE / HR07_RISK_REGISTER
- [ ] 验证：6 文档评审通过、无业务代码改动

## HR07-S1 基础契约（✅ 已施工）

- [x] `hr_contracts` app 骨架（apps.py 注册 + INSTALLED_APPS）
- [x] `constants.py`：LifecycleStatus / AgreementFamily / TermMode / VersionType / DocumentType / SignatureMode / EventType / TerminationStatus / RenewalDecision / RiskType / RiskSeverity / RiskStatus / AuthorityMode
- [x] `permissions.py`：`hr.contract.*` 权限集 + `HrContractPermissionMeta` + `require_hr_contract_permission`
- [x] `api/exceptions.py`：HR07 错误码（HR07 §88）
- [x] `api/base.py`：envelope + ok/error + context 解析（复用 hr_control_center.context）
- [x] `context.py`：`Hr07RequestContext` + `build_hr07_context` + scope + as_of + authority_mode
- [x] `display_labels.py`/templatetags：状态中文徽标映射（ACTIVE→履行中、EXPIRING→即将到期、SIGNED_WAITING_EFFECTIVE→已签待生效…）
- [x] tests/test_s1_contracts.py
- 验证（待用户在终端执行）：`python manage.py check hr_contracts`；`python manage.py migrate` 后权限注册

## HR07-S2 Authority Models + migrations（✅ 已施工）

- [x] `models/type.py`：HrAgreementType（family/term_mode/overlap_policy/编号规则引用）
- [x] `models/template.py`：HrAgreementTemplate / HrAgreementTemplateVersion（ACTIVE 不可改正文）/ HrAgreementClauseDefinition
- [x] `models/rule.py`：HrAgreementRuleSet（DRAFT/PUBLISHED/RETIRED）/ HrAgreementNumberRule（行锁序列）
- [x] `models/agreement.py`：HrAgreement（agreement_no 签署后 immutable / 显式状态机 / 日期语义 / signing_context_snapshot / compensation_reference）
- [x] `models/version.py`：HrAgreementVersion（内容不可变 + 仅状态流转 / hash / 版本唯一）
- [x] `models/term.py`：HrAgreementTerm（条款唯一 / 敏感分级）
- [x] `models/document.py`：HrAgreementDocument（SIGNED_FINAL 不可变 + hash 必填 / private 路径）
- [x] `models/event.py`：HrAgreementEvent / HrAgreementEventReason
- [x] `models/signing.py`：HrAgreementSigningCase / HrSignatureEnvelope / HrSignatureParticipant（provider event 唯一）
- [x] `models/renewal.py`：HrAgreementRenewalReview（同周期唯一）
- [x] `models/risk.py`：HrAgreementAlertPolicy / HrAgreementRiskCase（open_key 去重）
- [x] `models/outbox.py`：HrContractOutboxEvent
- [x] `models/audit.py`：HrAgreementAuditEvent / SensitiveAgreementAccessLog
- [x] `models/authority.py`：HrContractAuthorityMode
- [x] `migrations/0001_initial.py`（手工编写，MySQL 兼容；无 PostgreSQL 专属设计）
- [x] `admin.py`：正式合同只读（00 §141）
- [x] tests/test_models_s2.py
- 验证（待执行）：`python manage.py makemigrations --check --dry-run`；`python manage.py migrate`

## HR07-S3 合同台账（HR07-01）（✅ 已施工）

- [x] selectors：list（WHERE→COUNT→ORDER→PAGE）/ detail / versions / timeline / documents / staff contracts
- [x] `api/ledger.py`：`GET /api/hr/v1/contracts`、`/{id}`、`/{id}/versions`、`/{id}/timeline`、`/{id}/documents`、`/staff/{staffId}/contracts`
- [x] scope 裁剪（SCHOOL/COLLEGE/DEPARTMENT/SELF）+ 权限（hr.contract.agreement.view）
- [x] 台账前端页面（全中文，独立 HTML 遵循 HR03 模式）+ KPI + 筛选 + 空态/错误态
- [x] tests/test_ledger_s3.py

## HR07-S4 签订（HR07-03 前半）（✅ 已施工）

- [x] `services/number_service.py`：DB 行锁分配 agreement_no；作废不回收
- [x] `services/rule_service.py`：RuleEngine 输出 PASS/WARNING/BLOCKER/MANUAL_REVIEW + rule_code/message/evidence/recommended_action
- [x] `services/template_service.py`：变量白名单渲染（禁止任意 Jinja 表达式）
- [x] `services/signing_service.py`：create case（HR03 关系校验/overlap/future 冲突/幂等）→ submit → approve → generate（Agreement+V1+编号+条款+文档记录）
- [x] `services/signature_service.py`：OFFLINE（envelope + 双方签署 + SIGNED_FINAL 归档）+ SignatureProvider adapter 契约
- [x] `services/lifecycle_service.py`：SIGNED_WAITING_EFFECTIVE →（到生效日）→ ACTIVE（幂等 + 日期校验）
- [x] `services/outbox_service.py` / `services/audit_service.py`
- [x] API：signing-cases / preview / submit / approve / generate / send-signature / complete-signature / activate
- [x] tests/test_signing_s4.py

## HR07-S5 续签与变更（HR07-03 后半 + HR07-04 前半）（✅ 已施工）

- [x] `services/renewal_service.py`：RenewalReview（PENDING→RENEW/RENEW_WITH_CHANGES/DO_NOT_RENEW/TERMINATE/NEEDS_REVIEW）；日期连续性 [start,end) 半开
- [x] `services/event_service.py`：AMEND（新版本取代旧版本）/ SUSPEND / RESUME / VOID；事件状态机 DRAFT→UNDER_APPROVAL→APPROVED_WAITING_EFFECTIVE→EFFECTIVE
- [x] Future conflict 检测（409 FUTURE_AGREEMENT_CONFLICT）
- [x] API：renewal-reviews / decide / events / submit / approve / apply
- [x] tests/test_renewal_amend_s5.py

## HR07-S6 解除与终止（HR07-04 后半）（✅ 已施工）

- [x] `services/termination_service.py`：TERMINATE（原因/未来生效/状态机/重复解除冲突/不 delete）
- [x] `services/correction_service.py`：CORRECT（元数据可更正；签署正文拒绝直接更正 → void 重签）
- [x] API：events create（按 eventType 权限）/ approve / apply
- [x] tests/test_termination_s6.py

## HR07-S7 到期预警（HR07-05）（✅ 已施工）

- [x] `services/risk_service.py`：AlertPolicy → RiskCase（open_key 去重：同合同同类型仅一个 OPEN；跨日不刷屏）
- [x] `jobs/lifecycle.py`：激活 + 风险同步（幂等）
- [x] `jobs/outbox_dispatcher.py` + management commands（hr07_lifecycle / hr07_dispatch_outbox）
- [x] API：risks / acknowledge / resolve / waive / reviews
- [x] tests/test_risk_s7.py

## HR07-S8 联动（✅ 已施工）

- [x] `integrations/hr03.py`：关系/任职 as-of Provider（只读引用，不建第二套关系）
- [x] `integrations/hr05.py`：合同签署状态 Provider（NOT_REQUIRED…ACTIVE）
- [x] `integrations/hr06.py`：ContractImpactEvaluator（NO_IMPACT/REVIEW_REQUIRED/AMENDMENT_REQUIRED/NEW_AGREEMENT_REQUIRED）
- [x] `integrations/hr15.py`：薪酬引用 Provider（不读金额做统计）
- [x] `integrations/hr16.py`：ExitGate（全部必管合同已结束）
- [x] tests/test_integrations_s8.py

## HR07-S9/S10 Legacy Projection + 迁移 + 切换（✅ 已施工）

- [x] `projections/horilla_contract.py`：HR07 → legacy Contract 投影（仅当前 PRIMARY_EMPLOYMENT）
- [x] `jobs/migration.py`：CLEAR/AMBIGUOUS/INVALID 分类 + CLEAR 迁移（dry-run 支持）
- [x] `services/authority_service.py`：LEGACY→DUAL→HR07_AUTHORITY（须对账报告；禁止回退）
- [x] `management/commands/hr07_reconcile_legacy.py` / `hr07_switch_authority.py`
- [x] tests/test_legacy_s9.py

## HR07-S11 安全/并发/幂等验收（✅ 已施工）

- [x] tests/test_security_s11.py（IDOR / 编号序列 / scheduler 幂等）
- [x] tests/test_i18n_labels.py（中文徽标契约）

## HR07-S12/S13 Authority 切换演练与封板（⏳ 待终端验证）

- [ ] 用户在终端执行：migrate + 全部 tests + `hr07_reconcile_legacy --tenant 1` + `hr07_switch_authority`
- [ ] 全绿后更新 docs/hr/HR07_S13_封板评估.md → `HR07 READY FOR ACCEPTANCE`
