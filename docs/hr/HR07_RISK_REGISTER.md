# HR07 RISK REGISTER（S0 物化 · P0/P1 优先）

> 物化时间：2026-08-09 · 状态：`DRAFT_V1`
> 等级：P0=跨租户/正式事实严重错误/法律证据破坏；P1=核心链阻塞/对账失败（00 §151）。

---

## P0 风险（必须处理）

| ID | 风险 | 现状证据 | 缓解 |
|---|---|---|---|
| R-01 | **合同历史被覆盖**：旧 `contract_update` 可直接编辑 active/签署合同；`save()` 自动改 status | payroll/views/views.py:114；models.py:459-460 | 新 authority 强不可变：SIGNED 后禁 update/delete（模型级 raise）；旧页面 authority 后 redirect；HR07 §12/§58 |
| R-02 | **Payroll 副作用**：Contract.save 回写 `EmployeeWorkInformation.basic_salary`；`expire_contract` 静默改状态 | models.py:487-503；scheduler.py:20 | 冻结 S4 回写；lifecycle 幂等接管；HR07 §16/§126 |
| R-03 | **多合同语义缺失**：旧模型"一个 employee 一个 active"，无法表达主合同+补充协议+人才协议并存 | models.py:461-485 | HrAgreementFamily + overlap_policy 参数化（HR07 §8） |
| R-04 | **日期/effective 冲突**：旧模型无 effective/signed/review/terminated 区分，单一 status 推断 | HR07 §14 | 显式状态机 + 日期语义分离 + Future conflict 检测（HR07 §44/§89） |
| R-05 | **签署文件安全**：`contract_document` 为 public FileField（裸 `/media/` URL），无 hash/私存/审计 | models.py:273；HR07 §20 | `HrAgreementDocument` private storage + short-lived ticket + hash + 下载审计（00 §34） |
| R-06 | **权限缺口**：旧 `payroll.*` 全局权限无 field/scope 细粒度 | cbv/contracts.py:28 | `hr.contract.*` 权限集 + scope 裁剪 + SoD（HR07 §19/§68/§69） |
| R-07 | **电子签伪造风险**：无 provider；若直接宣称电子签成功会破坏法律证据 | 无电子签代码 | V1 仅 OFFLINE + Adapter 契约；webhook signature/timestamp/replay/providerEventId（HR07 §38/§92） |
| R-08 | **Legacy 迁移不确定性**：active 多份/重叠/状态矛盾需人工裁决 | HR07 §95 | CLEAR/AMBIGUOUS/INVALID 分类；`LegacyContractMigrationReport`；不自动猜 |

## P1 风险

| ID | 风险 | 缓解 |
|---|---|---|
| R-11 | 到期预警刷屏：同一合同多 offset 生成 20+ 通知 | RiskCase 去重键（agreement+risk_type+status OPEN 唯一）；更新同一 case（HR07 §65） |
| R-12 | review 误当自动续签 | review 只产出决策，续签必须新版本签署（HR07 §40-41） |
| R-13 | 已生效不可原地改：correction 与 amendment 混淆 | correction 需审批+证据；已签署 PDF 走 void→重签（HR07 §56） |
| R-14 | HR03 关系 vs HR07 合同对账漂移 | `EffectiveDatedQueryService` 只读引用 + reconciliation（00 §47） |
| R-15 | 模板/规则改动污染历史 | 模板/规则/条款全版本化；Agreement 绑定 template_version（HR07 §21/§28/§33） |
| R-16 | 合同到期 ≠ 离职：系统不能自动把员工置为离职 | end-of-term policy（END_AGREEMENT_ONLY/REQUIRES_EMPLOYMENT_TERMINATION/CREATE_RENEWAL_DECISION/MANUAL_REVIEW）（HR07 §55） |
| R-17 | number sequence 并发冲突 | DB sequence/row lock，禁 max+1（HR07 §27/§109） |
| R-18 | outbox 重发重复激活/生效 | eventId 幂等 + aggregateVersion 冲突不覆盖（00 §16） |
| R-19 | 敏感合同查看/下载无审计 | `SensitiveAgreementAccessLog` + 下载 ticket（HR07 §20/§80） |
| R-20 | 本机无法运行 shell：测试/迁移/提交可能被跳过 | 每个阶段交付可执行验证清单；提交由用户在 IDE 执行，禁止假装跑过 |

## 验收红线（HR07 §149 禁止越界）

- 不在 HR07 建第二套 EmploymentRelationship；
- 不把 HR15 Payroll 做进合同；不读金额做统计；
- 不把 HR11 Leave policy 写进 Agreement；
- 不把 HR16 离校流程整体搬进 HR07；
- 不修改已签署版本；不直接编辑 active 合同正文；
- 续签不只改 end_date；不把 correction 当 amendment；
- 不 delete 正式合同；不用 mock 电子签冒充成功；
- 不放宽 tenant；不关 403 解决权限；不自动 fallback legacy；
- 不合并 main。
