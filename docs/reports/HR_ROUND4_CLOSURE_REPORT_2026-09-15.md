# 跃科高校人事系统第四轮核心流程与生产验收收口报告

日期：2026-09-15  
唯一输入基线：`Yueke_University_HR_Round3_20260915.zip`  
施工边界：云端沙箱源码副本；未连接 GitHub；未连接或修改生产服务器、生产 MySQL、真实学校数据。  
当前发布裁决：**NOT_RELEASED，但源码收口程度较第三轮进一步提高。**

## 1. 本轮为什么没有平均改 HR01～HR18

第三轮后的高价值缺口已经不是“18 个模块都缺页面”。源码复核显示：HR17 本人更正/补件在 Round2 已经有 SELF-safe 写链；HR02～HR15 多数模块也已有权威模型和真实 Service。继续平均铺功能反而容易破坏既有 Authority 边界。

第四轮因此只修仍会直接影响正式业务结论的三类问题：

1. HR16 审批材料虽然已有文件证据，但用途分类不足，存在“一份 OTHER_HR 材料重复顶多个审批槽位”的语义风险；
2. HR18 历史指标仍缺 HR07 正式合同事实；
3. 生产验收虽然有手册，但缺一条能自动证明 release → MySQL → 全量 HR 测试 → 备份恢复 → readiness 的隔离执行链。

## 2. HR16：弹性退休审批证据分类与不可变版本核验

### 2.1 原风险

Round3 的弹性退休已具备书面告知、审批依据、缴费核验、协议等字段，但底层人员材料分类仍可统一落成 `OTHER_HR`。这意味着审批页面“看起来四份材料都有”，却无法在数据层证明每一份是什么用途，也难以阻止同一文件被重复引用。

### 2.2 第四轮修复

新增四类材料 Authority code：

- `RETIREMENT_NOTICE`
- `RETIREMENT_APPROVAL`
- `RETIREMENT_CONTRIBUTION`
- `RETIREMENT_AGREEMENT`

并新增 `hr_staff 0022_retirement_evidence_categories` migration。

`FlexRetirementService` 现在：

- SELF 提交必须引用 `RETIREMENT_NOTICE`；
- APPROVE 必须分别引用 approval / contribution / agreement 对应分类；
- EARLY 无 agreement 时仍按规则处理，DELAY / END_DELAY 必须有协议证据；
- 同一 material 或 version 在多个槽位复用时 fail-closed；
- 审批通过前，对**选中的具体 HrStaffMaterialVersion**写核验人/核验时间；
- 被选版本后来变为 REPLACED 仍可作为已经封存的历史证据，不会自动跳到 current version；
- 审批 hash 的 review snapshot 在核验后重新获取，封存 `categoryCode / verificationStatus / verifiedBy / verifiedAt / sha256 / sizeBytes / versionId`。

UI 同步限制本人/管理端的材料选择范围，避免前端继续把所有人事材料混在一个下拉框。

### 2.3 新增/修正测试源码

- `backend/hr_exit/tests/test_round2_flex_workflow.py`
- `backend/hr_exit/tests/test_round3_flex_replan.py`
- `tests/round4/test_round4_closure_contracts.py`

Django TestCase 因本执行器没有 Django/MySQL 不能在此运行；纯契约测试已运行通过。

## 3. HR18：HR07 正式合同历史指标

### 3.1 只读取 Authority，不读取合同办理草稿

新增 HR07 `FormalDomainSpec`：

- Source model：`hr_contracts.HrContractVersion`
- Grain：`STAFF`
- Identity：`agreement__staff_id`
- Active historical statuses：`EFFECTIVE / SUPERSEDED / TERMINATED / EXPIRED`
- Evaluator version：`hr07-contract-staff-count-v1`

可过滤正式合同人员、聘用关系、合同类型、主体类型、版本类型、生效区间与正式状态。

### 3.2 重叠正式版本必须报错

对 as-of 日期先筛正式有效区间，再按 agreement 分组；同一 agreement 如果出现两个以上正式版本覆盖同一日期，返回：

`ASOF_EVALUATION_SOURCE_CONFLICT`

没有使用 `order_by(...).first()` 掩盖数据冲突。

### 3.3 冻结证据与数据质量

`hr07-contract-facts-v1` Provider 的证据哈希纳入：版本 id、agreement id、staff、employment relationship、subject/agreement/version type、version no、有效期、状态、`supersedes_version_id`、`content_hash`，并包含 VOID。这样后续作废/更正会让历史证据重建结果变化，而不是继续复用旧 hash。

新增 HR07 质量规则 Provider：

`HR07_CONTRACT_VERSION_INTEGRITY`

检查：

- version 与 agreement 跨租户挂接；
- 正式状态缺 `signed_at` 或签署文档引用；
- content hash 非 64 位 hex；
- 生效区间非法；
- predecessor 缺失或跨 agreement；
- successor version_no 未递增；
- 同一 agreement 正式版本时间区间重叠。

### 3.4 为什么 HR04/05/06/12/15 仍不直接接入

这些域已有撤销、更正、继任或重算语义。直接对 workflow/current-state 表 COUNT 会产生历史错数。第四轮保留 `ASOF_EVALUATION_SOURCE_UNSUPPORTED`，等每个域建立 chain-aware formal-fact adapter 后再开放。这个“不支持”比错误地返回一个数字更符合生产要求。

## 4. 隔离生产验收门禁

新增 `scripts/run_hr_acceptance_gate.py` 与 `docker-compose.acceptance.yml`，Makefile 暴露：

```text
make acceptance-plan
make acceptance-qa
```

### 4.1 安全边界

- 不读取/覆盖正式 `.env`；
- 自动生成 0600 权限的一次性 env；
- project 名必须包含 `acceptance` 或 `qa`；
- project 名出现 `prod` / `production` / `live` 直接拒绝；
- Compose volume/project namespace 独立；
- restore 只允许单独数据库；
- 日志输出对 password/secret/token/连接串凭据做遮蔽；
- acceptance 首管密码不写入共享 env，只在 `bootstrap_production_admin` 单次容器临时注入；
- 默认执行结束 `down -v --remove-orphans`；
- `make prod` 的 Compose 文件列表没有加入 acceptance overlay。

### 4.2 自动门禁阶段

1. Compose >= 2.24.4；
2. 三份 Compose 合并解析；
3. 以当前源码 build `renshi-web:latest`；
4. MySQL 8.4、Redis、ClamAV healthy；
5. release migration + collectstatic；
6. Django `check --deploy`；
7. `makemigrations --check --dry-run`；
8. `migrate --check`；
9. HR01～HR18 Django/MySQL tests；
10. 全新库首管 bootstrap；
11. MySQL + media 加密 backup；
12. backup checksum + authenticated decryption verify；
13. 创建单独 restore database；
14. restore；
15. restored database `migrate --check`；
16. 原库/恢复库 schema table count 一致；
17. web 启动；
18. 容器内 `/ready/` HTTP 200；
19. 自动销毁验收环境。

### 4.3 当前沙箱的真实执行结果

当前执行器重新检查：

- `docker`：不存在；
- `django`：`ModuleNotFoundError`。

因此实际执行 `python scripts/run_hr_acceptance_gate.py` 时在 `docker compose version --short` 立即返回 `HR_ACCEPTANCE_GATE_FAILED: compose-version failed`。这是预期的 fail-closed；没有循环等待，没有假装 release/MySQL 已验收。

## 5. 本轮实际跑过的测试

| 门禁 | 当前结果 |
|---|---:|
| Round2 纯契约 | 66 / 66 PASS |
| Round3 纯契约 | 6 / 6 PASS |
| Round4 纯契约/安全门禁 | 16 / 16 PASS |
| acceptance `--plan` | PASS |
| acceptance 真实 Docker 执行 | BLOCKED：Docker unavailable，第一阶段 fail-closed |
| Django/MySQL TestCase | BLOCKED：django/MySQL unavailable |

第四轮纯测试同时覆盖：HR16 四类证据、材料不可复用、exact-version verify、HR17/HR16 UI 分类、HR07 as-of 注册、STAFF grain、VOID/hash/supersedes 证据、HR07 数据质量、危险域继续 fail-closed、acceptance 项目命名隔离、临时 env、日志凭据遮蔽、`make prod` 不引用 acceptance overlay。

## 6. HR01～HR18 当前收口判断

| 范围 | 第四轮判断 |
|---|---|
| HR01/02/03 | 主控、组织、主档 Authority 基础稳定；HR03 历史 COUNT 已有。 |
| HR04/05 | 招聘→入职真实主链已存在；历史 HR18 evaluator 暂保持 fail-closed。 |
| HR06 | 异动正式事实存在；因更正/撤销链，历史 evaluator 暂保持 fail-closed。 |
| HR07 | 正式合同 Authority + 历史 STAFF COUNT + overlap fail-closed + 质量规则，本轮增强。 |
| HR08～HR11 | 核心业务代码保留；目标学校 IAM/教务等真实边界仍需目标环境联调。 |
| HR12 | 年度/聘期考核前轮已补权威链；历史 evaluator 暂保持 fail-closed。 |
| HR13/14 | formal fact 历史 PERSON COUNT + 质量/证据链已有。 |
| HR15 | 薪酬支付未配置时 fail-closed；真实银行/财税适配器必须目标学校验收；历史 evaluator 暂不假算。 |
| HR16 | 法定退休预审、弹性退休、受控 END_DELAY 改期、材料用途分类与 exact-version 审批证据进一步闭环。 |
| HR17 | SELF 读取、本人更正/补件写链、弹性退休本人提交均已有；旧审计“SELF 写操作缺失”不再是当前缺口。 |
| HR18 | HR03 + HR07 + HR13 + HR14 + HR16 历史求值能力；其他域继续显式 UNSUPPORTED。 |

## 7. 仍然不能在源码包里伪造完成的项目

以下是目标环境验收，不应通过继续写 mock 代码来“消灭”：

1. Docker/MySQL 8.4 真实执行第四轮 acceptance gate；
2. HR01～HR18 Django/MySQL 全量测试与 triggers；
3. 四角色真实浏览器：人事管理员、二级单位负责人、普通教职工、评委/审定角色；
4. 跨租户、越权、MFA、真实 SMTP；
5. 目标学校实际需要的 IAM/教务/银行/财税/电子签章等外部边界；
6. 大数据量性能、并发、任务队列、备份恢复 RPO/RTO；
7. HR04/05/06/12/15 历史指标只有在各自 chain-aware adapter 完成后才能从 UNSUPPORTED 升级。

## 8. 裁决

第四轮不是文档收口。源码已经实际增加/修改 HR16 材料 Authority、HR18 HR07 历史与数据质量、生产形态自动验收 harness，并为这些改变增加测试。

**当前仍应保持 NOT_RELEASED。** 下一次有 Docker/MySQL 的可信 QA 执行环境时，不需要重新讨论“怎么验收”，直接运行 `make acceptance-qa`；只有它通过，再进入真实 SMTP/外部接口和四角色浏览器签字。
