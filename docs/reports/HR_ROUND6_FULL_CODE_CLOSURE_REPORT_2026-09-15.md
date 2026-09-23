# 跃科高校人事系统 Round6 一次性源码收口报告

日期：2026-09-15  
唯一基线：`Yueke_University_HR_Round5_20260915.zip`  
基线 SHA256：`7799650cf1d3b9595c940dc7743148548990b0e47daabd444b3d6a233d5aed6a`  
施工边界：仅云端沙箱源码副本；未连接 GitHub；未访问生产服务器或生产数据库。  
当前裁决：**NOT_RELEASED**。

## 1. 本轮范围裁决

用户要求本轮“按照分析一次性都做完”。在 Round5 的遗留清单里，唯一能继续靠当前源码施工直接关闭的明确阻断是：

> HR04 / HR05 / HR15 chain-aware historical adapter。

其余剩余项是目标运行环境、外部系统或真实浏览器验收，不能在没有 Docker/MySQL/学校外部系统的源码沙箱中诚实伪造为完成。因此 Round6 的目标是：**把这个代码级阻断彻底关闭，并把生产验收继续保持 fail-closed；不另造菜单、不假接外部系统。**

## 2. HR04 招聘：正式录用历史链接入 HR18

### 2.1 Authority 来源

使用既有真实 Authority：

- `HrHiringDecisionFact`：录用通知已接受后的不可变事实；
- `HrHiringDecisionRevision`：append-only CORRECTION / REVOCATION。

没有重新造第二套招聘历史表。

### 2.2 as-of 求值

新增 `hr04-hiring-person-count-v1`：

- base fact 仅在 `accepted_at <= as_of_date` 后可见；
- revision 仅应用 `effective_at <= as_of_date` 的节点；
- 逐版本验证 previous/new version；
- `before_snapshot_json` 必须精确等于前态；
- correction 只能修改 rank/finalScore/employmentType/expectedReportDate；
- revocation 不能偷偷修改业务身份；
- revocation 从其实际生效日起排除该录用；
- PERSON grain 按 candidate Authority identity 去重。

### 2.3 质量门

新增 `HR04_HIRING_REVISION_CHAIN_INTEGRITY`，包括：

- offer/proposed hire/application/candidate/position tenant lineage；
- base/revision content hash 重新计算；
- 版本跳号、before snapshot 不一致；
- effective time 倒退；
- correction/revocation payload 越权；
- 身份字段偷换；
- revocation 后继续修订；
- **目标历史日期下出现 revision，但其 parent fact 尚未生效/不存在时直接报错。**

证据冻结和真正 COUNT 前都会先过该质量门。

## 3. HR05 入职：激活事实与 HR04→HR05→HR03 交接闭环

### 3.1 Authority 来源

- `HrOnboardingActivationSnapshot`：正式激活快照；
- `HrOnboardingActivationAmendment`：append-only CORRECTION / REVOCATION。

### 3.2 跨域 lineage

Round6 不只校验 HR05 自己：

- activation snapshot 必须和 onboarding case 的 source/HR04 identity 一致；
- activation person/staff/employment/assignment 必须和 case 中 HR03 正式链接一致；
- `source_type == HR04_HIRE` 时必须能找到对应 `HrRecruitmentHandoff`；
- handoff 的 HR05 case 必须就是当前 case；
- 必须存在目标激活时间之前已 accepted 的 `HrHiringDecisionFact`；
- 如果 HR04 hiring fact 已在激活前被 REVOCATION，则 HR05 历史链质量失败。

### 3.3 历史语义

`hr05-activation-staff-count-v1`：

- snapshot `activated_at <= as_of_date`；
- amendment `effective_at <= as_of_date`；
- sequence/predecessor 必须线性连续；
- before snapshot 精确匹配；
- correction 只允许 activatedAt/staffNo/organizationId/positionId/sourceVersions；
- revocation 只允许 revoked/revocationReason；
- STAFF grain 按 staffMasterId 去重；
- revocation 从实际生效日起排除。

另增加“amendment 已生效但 parent snapshot 仍在未来/不存在”的 fail-closed 检查。

## 4. HR15 薪酬：从弱状态链升级为可封存 Authority

### 4.1 PayrollResultFact 封存

新增字段：

- `effective_at`
- `sealed_at`
- `content_hash`
- `authority_reason`
- `authority_evidence_ref`
- `authority_actor_id`

canonical hash 覆盖 payroll period、staff、currency、金额、status、predecessor、Authority 元数据和 effective time。

### 4.2 不可变边界

终态：FINALIZED / ADJUSTED / REVERSED。

代码层：

- persisted terminal instance 禁止原地编辑；
- terminal instance `.delete()` 禁止；
- terminal queryset update/delete/bulk_update 禁止；
- terminal `bulk_create` 禁止绕过 service；
- DRAFT 只能合法跨到 FINALIZED，不能原地变成 ADJUSTED/REVERSED；
- FINALIZED 跨边界时不得同时偷改业务金额/身份。

数据库层（MySQL migration 0013）：

- terminal INSERT 必须带 seal/hash；
- FINALIZED 不能带 predecessor；
- ADJUSTED/REVERSED 必须带 predecessor 和 Authority reason；
- terminal UPDATE/DELETE trigger 阻断；
- `(tenant_id, supersedes_result_id)` 唯一约束，确保每个源结果最多一个后继。

### 4.3 旧数据迁移 fail-closed

0013 backfill 在封存旧 terminal 结果前检查：

- duplicate successor；
- derived result 缺 predecessor；
- predecessor 缺失；
- tenant/period/staff/currency 身份漂移；
- cycle；
- root 不是 FINALIZED；
- **net != gross - deduction 时拒绝封存。**

旧 ADJUSTED/REVERSED 没有 reason 时只用于迁移兼容，明确写入 `MIGRATED_LEGACY_DERIVED_RESULT`，不伪造人工原因。

### 4.4 正式 adjustment / reversal

Adjustment：

- 必须从 FINALIZED/ADJUSTED 最新节点继续；
- source 已有 successor 时拒绝分叉；
- gross/deduction/net delta 恒等式校验；
- API 强制 reason；
- reason/evidence/actor 进入 sealed hash。

Reversal：

- 新增 `/results/<source_result_id>/reversal/` 正式接口；
- 只允许对最新 FINALIZED/ADJUSTED 节点冲销；
- 沿 predecessor 向 root 锁定读取；
- root 必须 FINALIZED；
- period/staff/currency 全链一致；
- reversal 金额 = **整个已生效链累计金额的相反数**；
- resultNo 重试时重新核对 source/period/staff/currency/金额/reason/evidence/actor，避免错误幂等命中。

### 4.5 HR15 历史质量与 HR18

`HR15_PAYROLL_RESULT_CHAIN_INTEGRITY` 检查：

- seal/hash 重算；
- gross/deduction/net 恒等式；
- payroll period tenant/finalized time；
- predecessor 身份与时间；
- 分叉、孤儿、循环；
- REVERSED 后继续写；
- **REVERSED 金额是否精确抵消其前驱累计金额。**

`hr15-payroll-staff-count-v1` 按 as-of date 重放 FINALIZED → ADJUSTED → REVERSED；撤销链不再计入，未撤销链使用累计后的正式金额参与 predicate。

## 5. HR18 当前正式历史能力

Round6 后支持：

| 域 | 历史 Authority 语义 |
|---|---|
| HR03 | 主档历史事实 |
| HR04 | Hiring fact + correction/revocation |
| HR05 | Activation snapshot + correction/revocation + HR04/HR03 lineage |
| HR06 | Effective snapshot + correction/rescind receipt |
| HR07 | 正式合同版本 |
| HR12 | Final assessment result + correction/revocation |
| HR13 | 职称正式结果 |
| HR14 | 岗位聘任事实 |
| HR15 | Finalized payroll + adjustment/reversal |
| HR16 | 退休/离校正式事实 |

HR08～HR11、HR17 不被强行包装成同一种 COUNT historical adapter。它们有自己的业务流程、外部系统或个人服务语义；未来需要指标时必须按具体 metric/population 定义接 Authority，而不是“为了全模块有数字”直接数当前表。

## 6. 测试与静态验收

### 6.1 当前执行器实际运行的纯门禁

| 门禁 | 结果 |
|---|---:|
| Round2 | 66 / 66 PASS |
| Round3 | 6 / 6 PASS |
| Round4 | 16 / 16 PASS |
| Round5 | 20 / 20 PASS |
| Round6 | 24 / 24 PASS |

Round6 纯门禁锁定：registry、evidence provider、HR04/05/15 as-of 路由、未来 parent 异常、Authority hash/lineage、HR15 single successor、迁移阻断、MySQL trigger、terminal bulk/delete、adjust/reversal、reversal amount/idempotency 等。

### 6.2 新增/加强的 Django 测试源码

- `backend/hr_data/tests/test_round6_recruitment_onboarding_payroll_history.py`
- `backend/hr_payroll/tests/test_reversal_authority_service.py`
- `backend/hr_payroll/tests/test_models.py`
- `backend/hr_payroll/tests/test_adjustment_service.py`
- `backend/hr_payroll/tests/test_adjustment_api.py`
- `backend/hr_payroll/tests/test_finalization_service.py`

它们会在真实 Django/MySQL acceptance 环境中被现有 HR app test suite 执行。

当前云执行器没有 Django，所以本报告**不声称这些 TestCase 已运行 PASS**。

### 6.3 全仓静态结果

最终封包前再次复跑并记录在 delivery metadata：

- 全仓 Python AST：3,122 个文件 PASS；
- `compileall`：PASS；
- migration 数字前缀：444 个 migration 文件，0 冲突；
- JavaScript `node --check`：253 个文件 PASS；
- `deploy/docker/entrypoint.sh`：`bash -n` PASS。

## 7. 隔离生产形态 acceptance

`--plan` 成功输出隔离流程，包括：

Compose 版本 → MySQL/Redis/ClamAV → release/migrate/collectstatic → deploy checks → HR01～HR18 Django/MySQL tests → 首管 bootstrap → 加密备份校验 → 独立恢复库 → restored migration/schema check → web `/ready/`。

实际执行：

`python scripts/run_hr_acceptance_gate.py --project yueke_hr_round6_acceptance`

结果：

- status: FAILED；
- phase: `compose-version`；
- 原因：当前执行器无 Docker；
- 约 0.001 秒即 fail-closed；
- `productionTouched=false`；
- `gitHubTouched=false`；
- 未进入数据库和 web 阶段。

证据：`docs/reports/acceptance_evidence/acceptance-latest.json`。

## 8. “一次性做完”的准确含义

Round5 遗留的第 7 个源码阻断：

> HR04 / HR05 / HR15 chain-aware historical adapter

**Round6 已关闭。**

本轮没有发现另一个能在当前离线源码沙箱中继续施工、并且可以诚实代替目标环境签字的同类明确代码阻断。

仍然不能叫 RELEASED，因为下面这些必须由真实 QA / 学校接入环境给证据：

1. Docker Compose >= 2.24.4 + MySQL 8.4 完整 `make acceptance-qa`；
2. fresh migrate、0013 MySQL trigger、`makemigrations --check` / `migrate --check`；
3. HR01～HR18 Django/MySQL 全量测试；
4. 加密备份 → 解密校验 → 独立库恢复；
5. 人事管理员、二级单位负责人、普通教职工、评委/审定角色真实浏览器黄金流程；
6. SMTP、学校 IAM/教务、银行/财税、电子签章等真实接口；
7. 跨租户、越权、MFA、并发、大数据量和安全/性能验收。

这些不是继续在无 Docker 沙箱写更多模拟代码就能“做完”的事项。

## 9. 最终裁决

**代码级 Round6 收口：完成。**  
**生产发布裁决：NOT_RELEASED。**

以后继续时，应以 Round6 完整包作为唯一新基线。若获得可信 Docker/MySQL QA 环境，第一优先级不是再开发业务，而是实际执行 `make acceptance-qa`，根据真实失败项修到全绿。
