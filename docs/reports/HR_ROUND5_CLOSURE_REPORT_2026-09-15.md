# 跃科高校人事系统 Round5 核心流程与生产验收收口报告

日期：2026-09-15  
唯一基线：`Yueke_University_HR_Round4_20260915.zip`  
施工边界：仅云端沙箱源码；未连接 GitHub；未访问生产服务器或生产数据库。  
当前裁决：**NOT_RELEASED**。

## 1. 本轮为什么优先 HR06 / HR12

Round4 的 HR18 已支持 HR03、HR07、HR13、HR14、HR16。HR06 与 HR12 之前故意保持 `ASOF_EVALUATION_SOURCE_UNSUPPORTED`，原因不是“没菜单”，而是两者都有 append-only 更正/撤销语义：

- HR06 原始异动生效后还可能发生 HR03 正式纠错、HR06 orchestration rescind；
- HR12 正式考核结果封板后还允许 append-only correction / revocation。

如果 HR18 直接 COUNT 当前 case/result 状态，会把“今天的纠正”错误地带回到昨天，历史值会被重写。因此第五轮只接受 Authority chain-aware 方案。

## 2. HR06：异动历史 Authority 链

### 2.1 权威来源

历史事件基线：`HrChangeEffectiveSnapshot`。

后续 Authority 边界：`HrChangeAuthorityReceipt`：

- `CORRECTION`：记录真正发生在 HR03 Authority 的正式纠错回执；
- `ORCHESTRATION_RESCIND`：只撤销 HR06 orchestration 事件，不谎称已经反向删除 HR03 人员事实。

### 2.2 历史求值语义

`hr06-change-staff-count-v1` 使用 STAFF grain：

- snapshot `effective_at <= as_of_date` 才进入候选；
- 同租户 case/staff lineage 必须成立；
- 若目标日期前已有 `ORCHESTRATION_RESCIND`，该 HR06 事件从撤销生效日起排除；
- 目标日期以后出现的纠错或撤销，不影响更早日期的历史人口口径；
- 支持 staff、action/reason、source/target org、source/target position、effectiveDate 条件。

### 2.3 冻结证据

`hr06-change-chain-v1` 的 evidence hash 分两段：

1. sealed execution snapshot；
2. 目标日期前已生效的 authority receipts。

没有把可变的当前 case status 当作历史真相，因此未来 workflow 状态变化不会无故让过去快照失效；真正新增的 Authority receipt 会只影响其生效日期之后的证据。

### 2.4 数据质量从“格式检查”升级到“内容重算”

新增 `HR06_CHANGE_CHAIN_INTEGRITY`，检查：

- execution case / staff 跨租户；
- canonical execution Provider code；
- execution Provider receipt hash **重新计算**；
- execution content hash **按 snapshot canonical payload 重新计算**；
- receipt tenant/snapshot lineage；
- receipt sequence gap；
- receipt content hash **重新计算**；
- correction 必须声明 `HR03_FORMAL_CORRECTION` 且有 authority effect；
- rescind 必须是 `HR06_ORCHESTRATION_ONLY` 且不能伪造 HR03 Authority effect；
- rescind 后禁止继续追加 receipt；
- receipt 不得脱离 execution snapshot。

这修正了最初实现中“只判断 hash 是否为 64 位 hex”的不足。

### 2.5 HR18 双层 fail-closed

HR06 现在不是“质量中心报警、报表照算”。

- 创建 as-of evidence 时，Provider 先跑 Authority quality；有 findings 就返回 ERROR；
- historical evaluator 真正 COUNT 前再次跑 Authority quality；有 findings 就抛 `ASOF_EVALUATION_SOURCE_CONFLICT`。

因此破损 Authority 链无法被冻成 COMPLETE evidence，也无法继续产出历史数字。

## 3. HR12：考核正式结果历史修订链

### 3.1 权威来源

- base：`HrFinalAssessmentResult`（正式封板结果）；
- append-only：`HrResultRevision`（CORRECTION / REVOCATION）。

当前 `HrFinalAssessmentResult` 不因修订而被覆盖，HR18 必须按目标日期重建 canonical state。

### 3.2 as-of 重建规则

`hr12-assessment-staff-count-v1`：

1. 仅读取 `finalized_at <= as_of_date` 的正式结果；
2. 只 prefetch `effective_at <= as_of_date` 的 revision；
3. 每个 revision 必须满足 `previous_version == current_version` 且 `new_version == current_version + 1`；
4. `before_snapshot_json` 必须精确等于前一 canonical state；
5. CORRECTION 的 after.status 必须是 `CORRECTED`；
6. REVOCATION 的 after.status 必须是 `REVOKED`；
7. result/revision content hash 必须与 sealed payload 一致；
8. calculation hash 必须与 calculation snapshot 一致；
9. case staff identity、assessment type、cycle 必须与 final result 一致；
10. 撤销后的结果不再计数；撤销后继续修订直接 source conflict。

### 3.3 证据冻结

`hr12-result-chain-v1` 的 evidence hash 覆盖：

- final result；
- 目标日期前已生效 revisions；
- assessment case identity（staff / assessment type / cycle）。

因此：

- 2 月 1 日发生更正，不会让 1 月 31 日证据哈希变化；
- 3 月 1 日发生撤销，只从 3 月 1 日开始把该结果从 population 中排除。

### 3.4 数据质量

新增 `HR12_RESULT_REVISION_CHAIN_INTEGRITY`，覆盖：

- case missing / cross-tenant；
- staff identity 缺失；
- type/cycle lineage 不一致；
- result seal/content/calculation hash；
- revision version chain；
- before-snapshot；
- after version/status；
- correction/revocation 类型；
- effective time 单调性；
- revision content hash；
- revocation 后继续修订。

同 HR06，evidence creation 与 evaluator 都 fail-closed。

## 4. 新增生产级测试源码

新增：

`backend/hr_data/tests/test_round5_change_assessment_history.py`

它在真实 Django 环境中会验证：

- quality bridge 的 OK / findings / UNAVAILABLE 行为；
- corrupt HR06 chain 不能生成 OK frozen evidence；
- clean HR06 chain 才能产出 evidence hash；
- HR12 correction 在不修改 base result 的情况下重建新 canonical state；
- revocation 是 revision terminal；
- before snapshot 不一致必须 source conflict；
- HR06 sealed snapshot / receipt 的关键载荷变化会改变 hash。

当前云执行器没有 Django，所以只完成 Python/AST 源码校验；**没有把未运行的 Django TestCase 写成 PASS**。

## 5. acceptance 门禁的版本无关证据目录

Round4 的 `scripts/run_hr_acceptance_gate.py` 把运行证据固定写在：

`docs/reports/round4_evidence/acceptance-latest.json`

这对长期迭代不合理。第五轮改为：

`docs/reports/acceptance_evidence/acceptance-latest.json`

以后 Round6/Round7 仍使用同一个“当前 QA runtime evidence”语义，不会把运行证据错误归类成 Round4。

## 6. 本轮真实运行结果

### 6.1 纯测试

| 门禁 | 结果 |
|---|---:|
| Round2 | 66 / 66 PASS |
| Round3 | 6 / 6 PASS |
| Round4 | 16 / 16 PASS |
| Round5 | 20 / 20 PASS |

Round5 纯契约覆盖 HR06/HR12 end-to-end registry、as-of receipt cutoff、rescind/revocation semantics、hash 重算、quality fail-closed、unsupported domains、acceptance evidence path 和 Python source parse。

### 6.2 源码静态校验

全仓 Python 文件使用 `utf-8-sig` 读取后 AST 检查；这是因为基线包中的 `backend/hr_time/models/leave.py` 原本就带 UTF-8 BOM。该文件与 Round4 基线字节完全一致，并且 `python -m py_compile` 正常通过，不是第五轮引入的语法错误。

生产 Compose 使用 Docker Compose 合法的 `!override` tag，普通 `yaml.safe_load` 不支持该 tag，因此不再用通用 PyYAML 结果冒充 Compose 验证；生产 overlay 继续由项目 `scripts/check_prod_compose.py` + Compose >= 2.24.4 门禁负责。

### 6.3 acceptance 实执行

执行：

`python scripts/run_hr_acceptance_gate.py --project yueke_hr_round5_acceptance`

真实结果：

- `compose-version`：FAILED（当前执行器没有 Docker）；
- 耗时：0.001 秒；
- `productionTouched=false`；
- `gitHubTouched=false`；
- 临时 runtime 自动清理；
- 未进入 MySQL/release/restore 阶段。

证据：`docs/reports/acceptance_evidence/acceptance-latest.json`。

## 7. HR01～HR18 当前判断

| 模块 | Round5 判断 |
|---|---|
| HR01/02/03 | 控制、组织、主档 Authority 保持；HR03 历史能力已存在。 |
| HR04/05 | 招聘/入职核心流程存在；历史 HR18 仍 fail-closed，等待 Authority chain 适配。 |
| **HR06** | **本轮新增 execution + correction/rescind chain-aware 历史 STAFF COUNT、证据冻结、完整性规则。** |
| HR07 | 正式合同版本历史 STAFF COUNT 与质量门禁保持。 |
| HR08～HR11 | 业务代码保留；目标学校外部边界仍需真实环境。 |
| **HR12** | **本轮新增 final result + correction/revocation chain-aware 历史 STAFF COUNT、证据冻结、完整性规则。** |
| HR13/14 | formal fact 历史链保持。 |
| HR15 | 薪酬历史仍不假算；真实支付/财税边界和 chain-aware historical adapter 待后续。 |
| HR16 | 退休/离校事实链、弹性退休与证据分类保持。 |
| HR17 | 本人服务、更正/补件、弹性退休本人提交保持。 |
| HR18 | 当前正式支持 HR03 + HR06 + HR07 + HR12 + HR13 + HR14 + HR16 历史 Authority 求值。 |

## 8. 剩余真正的上线阻断

源码继续改 mock 不能替代：

1. 可信 Docker Compose >= 2.24.4 + MySQL 8.4 环境完整执行 `make acceptance-qa`；
2. HR01～HR18 Django/MySQL 全量测试、trigger、migration drift；
3. 备份 → 解密验证 → 独立库恢复 → schema/migration 检查；
4. 人事管理员、二级单位负责人、普通教职工、评委/审定角色真实浏览器黄金流程；
5. SMTP、学校 IAM/教务、银行/财税、电子签章等实际接入；
6. 跨租户/越权/MFA、并发与大数据量性能；
7. HR04/HR05/HR15 的 chain-aware historical adapter。

## 9. 裁决与下一轮建议

第五轮不是扩菜单，而是把两个此前高风险的“历史会算错”域升级为可追溯 Authority 链，并把损坏链阻断提前到证据创建阶段。

**当前仍为 NOT_RELEASED。**

如果下一轮仍在当前无 Docker 的云执行器施工，最高价值是继续处理 **HR04 招聘 → HR05 入职的跨域 Authority handoff 与历史事实**，而不是再堆 UI；若能切到可信 Docker/MySQL QA 环境，则优先直接跑 `make acceptance-qa`，根据真实失败项修到绿。
