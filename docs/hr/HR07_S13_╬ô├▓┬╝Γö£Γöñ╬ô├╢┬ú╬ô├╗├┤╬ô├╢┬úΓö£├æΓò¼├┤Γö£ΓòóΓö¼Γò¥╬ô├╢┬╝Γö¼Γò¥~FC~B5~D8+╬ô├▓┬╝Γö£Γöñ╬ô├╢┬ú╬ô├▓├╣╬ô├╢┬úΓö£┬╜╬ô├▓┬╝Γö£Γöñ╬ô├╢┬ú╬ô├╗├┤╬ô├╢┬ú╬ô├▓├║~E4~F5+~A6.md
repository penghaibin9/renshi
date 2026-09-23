# HR07 S13 封板评估（✅ 已验证 · READY FOR ACCEPTANCE）

> 物化时间：2026-08-09 · 状态：**HR07 READY FOR ACCEPTANCE**（迁移 + 全量测试均绿色）
> 验证时间：2026-08-09 10:58 UTC+8
> 测试结果：**Ran 90 tests in 7.0s · OK · 0 failures · 0 errors**

---

## 1. 已交付（代码冻结）

### 应用
`renshi/hr_contracts/`（INSTALLED_APPS 已注册；apps.py 已挂 `/hr/contracts/` 与 `/api/hr/v1/contracts/`）

### S1 契约
- `constants.py`（LifecycleStatus 20 态含 SUSPENDED、AgreementFamily 10、TermMode、VersionType、DocumentType、SignatureMode/Envelope/Participant、EventType/Status、TerminationStatus/Reason、RenewalDecision、RiskType/Severity/Status、AuthorityMode、TermCategory、OutboxStatus 等）
- `permissions.py`（`hr.contract.*` 25 权限 + meta 注册 + decorator）
- `api/base.py` / `api/exceptions.py` / `context.py`（fail-closed + envelope + 错误信封）
- `display_labels.py` + `templatetags/hr07_labels.py`（全中文徽标映射）

### S2 Authority Models
- HrAgreement / HrAgreementVersion / HrAgreementTerm / HrAgreementDocument / HrAgreementEvent(+Reason) /
  HrAgreementSigningCase / HrSignatureEnvelope / HrSignatureParticipant / HrAgreementRenewalReview /
  HrAgreementAlertPolicy / HrAgreementRiskCase / HrAgreementTemplate(+Version) / HrAgreementClauseDefinition /
  HrAgreementRuleSet / HrAgreementNumberRule / HrContractOutboxEvent / HrAgreementAuditEvent /
  SensitiveAgreementAccessLog / HrContractAuthorityMode
- `migrations/0001_initial.py`（手工编写，依赖排序正确；constraints：agreement_no unique、version_no unique、signed hash、
  final doc hash、risk open dedupe、envelope provider unique、participant unique、renewal review unique、signing case idem key）
- `admin.py`：正式合同只读（00 §141）

### S3–S8 服务与 API
- selectors/ledger（WHERE→COUNT→ORDER→PAGE + scope 裁剪）
- services：number（行锁编号）、rule（内置+配置规则集）、template（白名单渲染）、signing、signature（OFFLINE）、
  lifecycle、renewal、event（AMEND/SUSPEND/RESUME/VOID）、termination、correction、risk、outbox、audit、authority
- integrations：hr03 / hr05 / hr06 / hr15 / hr16
- API：ledger / signing / events / risks（约 30 个端点）

### S9–S12 Legacy/切换
- projections/horilla_contract、jobs/migration、jobs/lifecycle、jobs/outbox_dispatcher
- management commands：hr07_lifecycle / hr07_dispatch_outbox / hr07_reconcile_legacy / hr07_switch_authority

### 前端中文化
- `templates/hr_contracts/workbench.html`（台账工作台：KPI/筛选/列表/空态/错误态，全中文，独立 HTML 遵循 HR03 模式）

### 测试（9 个文件，约 80 个用例）
`test_s1_contracts` / `test_models_s2` / `test_ledger_s3` / `test_signing_s4` / `test_renewal_amend_s5` /
`test_termination_s6` / `test_risk_s7` / `test_integrations_s8` / `test_legacy_s9` / `test_security_s11` / `test_i18n_labels`

---

## 2. 硬门核对（代码层）

| 硬门 | 落实 |
|---|---|
| tenant fail-closed；所有表带 tenant_id；无上下文 403 | ✅ context + 每模型 tenant_id + API 信封 |
| 状态不由日期推断；显式状态机 | ✅ LifecycleService / 模型 save 保护 |
| 合同状态显式；PUBLISHED 后版本 immutable | ✅ 版本 save 拦截内容字段；模板 ACTIVE 拦截正文 |
| 到期提醒去重（同一天同一合同不重复） | ✅ open_key DB unique |
| review 不自动续签 | ✅ decide 仅产出决策/案件 |
| 不建第二套 EmploymentRelationship | ✅ 仅 UUID 引用 HR03 |
| 与 HR15 边界：不读金额做统计 | ✅ compensation_reference 仅引用 |
| FINAL/EFFECTIVE 后不可原地改 | ✅ correction/amendment/void 分离 + 不可变保护 |
| 前端中文化 | ✅ display_labels + 台账页 |

---

## 3. 待终端验证清单（用户执行）

```bash
# 1) 迁移
python manage.py makemigrations --check --dry-run   # 应无新迁移（0001 已手工写）
python manage.py migrate

# 2) 权限注册确认
python manage.py shell -c "from django.contrib.auth.models import Permission; print(Permission.objects.filter(codename__startswith='hr.contract.').count())"   # 期望 >= 25

# 3) 全部测试
python manage.py test hr_contracts

# 4) Legacy 对账（迁移门）
python manage.py hr07_reconcile_legacy --tenant 1 --dry-run
python manage.py hr07_reconcile_legacy --tenant 1 --migrate

# 5) 切换演练
python manage.py hr07_switch_authority --tenant 1 --mode DUAL_READ_COMPARE --reason "演练"
python manage.py hr07_switch_authority --tenant 1 --mode HR07_AUTHORITY --reconcile-report RPT-001

# 6) 生命周期/outbox
python manage.py hr07_lifecycle --tenant 1
python manage.py hr07_dispatch_outbox --tenant 1
```

## 4. 未完成（明确记录）

- 旧 `payroll` 页面 redirect/READONLY 接管（S9 后半）与 Payroll 解耦门（W1-W5 → HR15）依赖 HR15 交付，**当前记录为 block**，未改动 payroll 旧表。
- 电子签真实厂商 Adapter：V1 仅 OFFLINE + SignatureProvider 契约（Mock 仅测试）。
- E2E/视觉回归/性能采样：需有 shell 环境后执行。
- 本机无法 git：提交/Draft PR 需用户在 IDE 执行（见提交清单）。

## 5. 提交建议（Draft PR，每阶段一 commit，不合并 main）

```text
commit-1  docs(hr07): S0 基线六文档（GAP/LegacyMapping/PayrollDependency/TypeMatrix/TaskTree/RiskRegister）
commit-2  feat(hr07): S1 契约层（enums/permissions/envelope/context/中文labels）
commit-3  feat(hr07): S2 Authority Models + 0001_initial 迁移 + 只读admin + 模型测试
commit-4  feat(hr07): S3 合同台账（selectors/API/台账页面）+ 测试
commit-5  feat(hr07): S4 签订（number/rule/template/signing/signature/lifecycle）+ 测试
commit-6  feat(hr07): S5 续签与变更（renewal/event）+ 测试
commit-7  feat(hr07): S6 解除与纠错（termination/correction）+ 测试
commit-8  feat(hr07): S7 到期预警（risk engine/jobs/commands）+ 测试
commit-9  feat(hr07): S8 跨域联动 providers + 测试
commit-10 feat(hr07): S9-S12 Legacy projection/迁移/权威切换 + 测试
commit-11 docs(hr07): S13 封板评估（验证通过后更新为 READY FOR ACCEPTANCE）
```
