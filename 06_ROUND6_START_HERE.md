# 跃科高校人事系统：第六轮一次性源码收口入口（2026-09-15）

本轮只以 `Yueke_University_HR_Round5_20260915.zip` 为唯一基线继续施工。基线 SHA256：

`7799650cf1d3b9595c940dc7743148548990b0e47daabd444b3d6a233d5aed6a`

施工仅发生在当前云端沙箱源码副本：**没有连接 GitHub，没有连接生产服务器，没有连接生产数据库。**

## 这一轮完成了什么

Round5 留下的唯一明确“继续改源码才能关闭”的历史数据阻断是：

> HR04 / HR05 / HR15 的 chain-aware historical adapter。

Round6 已把这一项完整关闭，而不是给 HR18 直接 COUNT 当前 workflow 状态。

### HR04 招聘录用

权威历史来源：

- `HrHiringDecisionFact`：已接受录用的不可变正式事实；
- `HrHiringDecisionRevision`：append-only `CORRECTION / REVOCATION`。

HR18 现在按目标日期重放修订链，支持 PERSON grain 历史 COUNT；目标日期之后的更正/撤销不会污染更早快照。数据质量会校验租户、父链、版本、before/after snapshot、内容哈希、身份字段、撤销后续写，以及“修订已经生效但父事实尚在未来”的异常。

### HR05 入职激活

权威历史来源：

- `HrOnboardingActivationSnapshot`：正式激活事实；
- `HrOnboardingActivationAmendment`：append-only correction/revocation。

HR18 现在按目标日期重建 STAFF grain 历史状态，并把三条身份链同时纳入质量门：

1. HR05 activation snapshot → onboarding case；
2. onboarding case → HR03 person/staff/employment/assignment；
3. 招聘来源 case → HR04 proposed hire/application → recruitment handoff → accepted hiring fact。

因此 HR04→HR05 不是靠字符串“看起来对上”就通过；缺失/跨租户/已撤销招聘事实会 fail-closed。

### HR15 薪酬结果 Authority

Round5 以前 `PayrollResultFact` 虽有 `FINALIZED / ADJUSTED / REVERSED` 状态，但终态证据和冲销业务链还不够强。本轮同时补齐：

- `effective_at`、`sealed_at`、`content_hash`；
- `authority_reason`、`authority_evidence_ref`、`authority_actor_id`；
- 同一结果只允许一个后继，禁止 adjustment/reversal 分叉；
- FINALIZED/ADJUSTED/REVERSED 终态实例删除禁止；
- 终态 `bulk_create` 禁止绕过 Authority service；
- MySQL insert/update/delete trigger 封住终态绕过；
- 迁移对旧终态结果回填封存哈希，遇到分叉、孤儿、循环、身份漂移、金额恒等式错误直接阻断；
- 调整必须从最新结果继续；
- 新增正式 reversal API/service；
- reversal 金额必须等于整个已生效工资链累计金额的相反数；
- idempotency 会重新核对 period/staff/currency/金额/原因/证据/操作者，不只核对单号。

HR18 现在能按目标日期重建 FINALIZED → ADJUSTED → REVERSED 线性链；撤销只从实际生效日起排除该链。

## HR18 当前正式历史求值范围

Round6 后，已接正式 Authority / chain-aware 历史求值的域为：

- HR03：教职工主档历史事实；
- **HR04：招聘录用事实 + correction/revocation；**
- **HR05：入职激活事实 + correction/revocation + HR04/HR03 lineage；**
- HR06：异动执行 + correction/rescind；
- HR07：正式合同版本；
- HR12：正式考核结果 + correction/revocation；
- HR13：职称结果；
- HR14：岗位聘任；
- **HR15：薪酬正式结果 + adjustment/reversal；**
- HR16：退休/离校事实。

HR08～HR11、HR17 并没有被假装成“都适合 COUNT 的历史人口域”。它们保留自己的业务 Authority 和外部边界；需要指标时应按具体指标语义另建正式定义，而不是为了凑 HR01～HR18 全覆盖乱 COUNT。

## 本轮验证

当前云执行器真实完成：

- Round2 纯契约：66/66 PASS；
- Round3：6/6 PASS；
- Round4：16/16 PASS；
- Round5：20/20 PASS；
- Round6：24/24 PASS；
- 全仓 Python AST / compileall；
- 全部 HR/工程 JavaScript `node --check`；
- Django migration 数字前缀冲突检查；
- `deploy/docker/entrypoint.sh` Bash 语法；
- acceptance `--plan`。

另新增 Django 测试源码：

- `backend/hr_data/tests/test_round6_recruitment_onboarding_payroll_history.py`
- `backend/hr_payroll/tests/test_reversal_authority_service.py`
- HR15 既有 model/adjustment/finalization 测试同步加强。

**当前环境没有 Django/MySQL/Docker，所以没有把这些 Django TestCase 或 migration/trigger 真运行结果伪装成 PASS。**

## 当前上线裁决

仍为：**NOT_RELEASED**。

本轮实际触发隔离生产形态验收：

`python scripts/run_hr_acceptance_gate.py --project yueke_hr_round6_acceptance`

它在 `docker compose version --short` 第一阶段立即 fail-closed，因为当前执行器没有 Docker；证据明确记录：

- `productionTouched=false`
- `gitHubTouched=false`
- 未进入 MySQL migration、trigger、backup/restore、web readiness 阶段。

证据文件：`docs/reports/acceptance_evidence/acceptance-latest.json`。

## 以后不要重复开发什么

Round5 报告第 8 节的第 7 项——“HR04/HR05/HR15 chain-aware historical adapter”——已经在 Round6 关闭。下一窗口如果继续接手，**不要重新做 HR04/HR05/HR15 历史适配，也不要再扩菜单来冒充上线收口。**

真正剩余的是目标 QA 环境才能签字的门：Docker Compose >= 2.24.4、MySQL 8.4 fresh migrate / trigger、HR01～HR18 Django 全测、备份恢复、四角色浏览器黄金流程、学校实际 IAM/邮件/银行财税/电子签章接入、安全与性能。

详细证据与裁决见：

`docs/reports/HR_ROUND6_FULL_CODE_CLOSURE_REPORT_2026-09-15.md`
