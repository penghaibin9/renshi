# 跃科高校人事系统：第五轮接手入口（2026-09-15）

第五轮只以 `Yueke_University_HR_Round4_20260915.zip` 为唯一基线继续施工，没有回退 Round2/Round3，没有连接 GitHub，没有访问生产服务器或生产数据库。

## 本轮主目标

第四轮已经把 HR07 正式合同历史事实接入 HR18。第五轮继续处理此前故意 fail-closed 的两个复杂 Authority 域：

1. **HR06 人事异动**：以不可变 `HrChangeEffectiveSnapshot` + append-only `HrChangeAuthorityReceipt` 重建历史；
2. **HR12 年度/聘期考核**：以封板 `HrFinalAssessmentResult` + append-only `HrResultRevision` 重建历史。

这两个域都没有直接 COUNT 当前 workflow 状态，而是先还原目标日期当时已经生效的 Authority 链。

## HR06 本轮完成

- HR18 新增 `HR06` chain-aware STAFF COUNT；
- 历史基础事实只读取 `HrChangeEffectiveSnapshot`；
- `ORCHESTRATION_RESCIND` 只从该撤销回执的实际 `effective_at` 日期开始排除原异动事件；
- 目标日期之后发生的纠错/撤销不会改写更早日期的冻结证据哈希；
- 历史证据哈希纳入执行快照和目标日期前已生效的 AuthorityReceipt；
- 数据质量规则 `HR06_CHANGE_CHAIN_INTEGRITY` 检查跨租户、回执序号断链、撤销后续写、Provider 边界、快照挂接；
- **执行快照 content hash、Provider receipt hash、AuthorityReceipt content hash 现在都会重新计算核对，不再只检查是否为 64 位字符串**；
- HR18 创建历史证据、以及真正计算历史值时都会先跑链完整性检查；发现问题直接 `ERROR / UNAVAILABLE / ASOF_EVALUATION_SOURCE_CONFLICT`，不能继续给出“看起来正常”的数字。

## HR12 本轮完成

- HR18 新增 `HR12` chain-aware STAFF COUNT；
- 基线为封板 `HrFinalAssessmentResult`；
- 只应用目标日期前已经 `effective_at` 的 `HrResultRevision`；
- CORRECTION 必须逐版本衔接，且 `before_snapshot_json` 必须精确等于前一版本；
- REVOCATION 从实际生效日期开始把结果排除；撤销后仍有修订直接报 Authority 冲突；
- result/revision 的 content hash、calculation hash、sealed/effective 时间、case staff/type/cycle lineage 都进入校验；
- 冻结证据哈希同时覆盖 final result、目标日期前 revision、case identity；
- 数据质量规则 `HR12_RESULT_REVISION_CHAIN_INTEGRITY` 对版本跳号、前置快照不一致、撤销后续写、跨租户/缺 case、hash 异常等 fail-closed。

## HR18 当前历史求值能力

第五轮结束后，chain/formal Authority 历史求值支持：

- HR03：人员主档历史事实；
- **HR06：异动执行/纠错/撤销链（本轮新增）**；
- HR07：正式合同版本；
- **HR12：正式考核结果/修订/撤销链（本轮新增）**；
- HR13：职称结果链；
- HR14：岗位聘任事实链；
- HR16：退休/离校事实链。

HR04、HR05、HR15 仍保持显式 fail-closed；没有为了“支持更多模块”对招聘、入职或薪酬当前态表直接假算历史。

## 生产验收门禁继续收口

`scripts/run_hr_acceptance_gate.py` 的运行证据目录从带版本号的 `round4_evidence` 改成长期稳定的 `docs/reports/acceptance_evidence/`，避免后续 Round6/Round7 继续覆盖“第四轮证据”语义。

本轮实际执行一次隔离门禁：

- 项目：`yueke_hr_round5_acceptance`；
- 第一阶段执行 `docker compose version --short`；
- 当前云执行器没有 Docker，0.001 秒内 fail-closed；
- 证据明确：`productionTouched=false`、`gitHubTouched=false`；
- 临时 acceptance runtime 自动清理；
- 没有读取正式 `.env`、没有启动/修改生产数据库。

## 当前已执行验证

- Round2 纯契约：66/66 PASS
- Round3 纯契约：6/6 PASS
- Round4 纯契约：16/16 PASS
- Round5 纯契约：20/20 PASS
- 新增 Django 测试源码：`backend/hr_data/tests/test_round5_change_assessment_history.py`
- 当前执行器缺 Django/MySQL，不能声称该 Django TestCase 已运行
- acceptance `--plan`：PASS
- acceptance 真执行：BLOCKED / fail-closed at compose-version（Docker unavailable）

详细裁决见：

`docs/reports/HR_ROUND5_CLOSURE_REPORT_2026-09-15.md`

当前仍是 **NOT_RELEASED**。代码侧已把 HR06/HR12 历史假算风险进一步消除；真正 RELEASED 仍必须在可信 Docker/MySQL QA 主机执行 `make acceptance-qa`，再做目标学校外部接口和四角色真实浏览器验收。
