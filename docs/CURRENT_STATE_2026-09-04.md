# CURRENT STATE｜2026-09-04

> 仓库：`penghaibin9/renshi`  
> 默认分支：`main`  
> 本轮基线：`main@9b7f877394d0738fd9f49b6286416a71ab640343`  
> 单一施工分支：`fix/production-readiness-20260904`  
> Draft PR：`#53 fix(prod): close HR01–HR18 production gates and documentation truth`  
> 说明：本文冻结“基线与验收口径”；PR 的实时 exact HEAD 和检查结论以 PR #53 页面为准。

## 1. 当前一句话结论

```text
HR01～HR18 正式代码目录、MySQL/生产工作流和多条浏览器验收链已经存在；
但在 PR #53 的必需 Gate 全绿、HM-HR-00～15 与负例全部有 exact-SHA 证据前，
本仓库只能判定为 PRODUCTION CLOSURE IN PROGRESS，不能宣称 PRODUCTION READY。
```

页面可访问、模块测试存在、历史报告写 READY，都不能改变这个结论。

---

## 2. 2026-09-04 重新基线的原因

`main@9b7f877...` 是一次大规模本地同步后的新事实，已经晚于 2026-08-10 的接管快照和 8 月底的阶段报告。旧入口仍在描述：

- 只收 HR01～HR12、暂停 HR13～HR18；
- HR07 代码不完整；
- HR09/10/12 未进入运行态；
- CI 仍以旧数据库/旧分支为主。

这些表述与当前仓库不再一致，因此本轮必须同时做两件事：

1. 按最新 `main` 重新跑真实生产门，而不是继承旧结论；
2. 将 `docs/` 的权威入口改回当前代码事实，旧状态文件保留为历史快照。

---

## 3. 当前已确认的仓库事实

### 3.1 HR01～HR18 均有正式代码目录

| 模块 | 代码目录 | 当前定位 |
|---|---|---|
| HR01 | `backend/hr_control_center/` | 工作台聚合 |
| HR02 | `backend/hr_structure/` | 组织、岗位、编制 Authority |
| HR03 | `backend/hr_staff/` | 人员与任职 Authority |
| HR04 | `backend/hr_recruitment/` | 招聘与 Offer Authority |
| HR05 | `backend/hr_onboarding/` | 入职与激活编排 |
| HR06 | `backend/hr_changes/` | 人事异动 Authority |
| HR07 | `backend/hr_contracts/` | 合同 Authority |
| HR08 | `backend/hr_external/` | 外聘 Authority |
| HR09 | `backend/hr_qualification/` | 资格/双师 Authority |
| HR10 | `backend/hr10_development/` | 培训发展 Authority |
| HR11 | `backend/hr_time/` | 考勤请假 Authority |
| HR12 | `backend/hr_assessment/` | 考核 Authority |
| HR13 | `backend/hr_title/` | 职称 Authority |
| HR14 | `backend/hr_appointment/` | 岗位聘任 Authority |
| HR15 | `backend/hr_payroll/` | 薪酬福利 Authority |
| HR16 | `backend/hr_exit/` | 退休离校 Authority |
| HR17 | `backend/hr_self/` | 教职工本人服务 |
| HR18 | `backend/hr_data/` | 指标、报表、交换与归档 |

“目录存在”只证明代码主体已进入仓库，不自动证明每个业务状态都可由真人完成。

### 3.2 当前主生产工作流

| 工作流 | 主要证明什么 |
|---|---|
| `Quality / MySQL Contract` | 语法、格式、Django 安全检查、迁移漂移、MySQL fresh migrate、Authority 与注册测试 |
| `Previous Baseline / MySQL Upgrade` | 从上一基线升级而非只在空库建表 |
| `Docker / MySQL Smoke` | Compose 构建、release、MySQL、备份恢复、Gunicorn readiness、镜像漏洞门 |
| `HR Real Browser Click Flow` | 真实 MySQL、真实 Django、真实登录、页面与基础操作链 |
| `hr-w-a-handoff-browser.yml` | 岗位/招聘/入职/主档/合同/异动前半核心链 |
| `hr-w-b-browser.yml` | 外聘等 W-B 浏览器链 |
| `hr-w-b-external-contract.yml` | 外部协同合同与回执语义 |
| `hr12-annual-browser.yml` | 年度考核浏览器状态链 |

必须注意：单个工作流全绿不等于整个系统 100% 通过；最终要按 [`CORE_BUSINESS_FLOW_ACCEPTANCE.md`](CORE_BUSINESS_FLOW_ACCEPTANCE.md) 汇总。

### 3.3 生产运行文档已具备较完整底座

[`PRODUCTION_RUNBOOK.md`](PRODUCTION_RUNBOOK.md) 已覆盖：

- MySQL 8.4、带密码 Redis、ClamAV、Gunicorn/Nginx；
- 生产配置 fail-closed；
- 外部边界、HTTPS、回执密钥；
- `/health/` 与 `/ready/`；
- 加密备份、校验、异机保存；
- 恢复到不同名称数据库；
- 故障处置、回滚和上线签字。

本轮不再另造第二份生产手册，只让入口、当前状态和核心业务验收与它对齐。

---

## 4. 本轮开始时发现的真实阻断

### P1-CI-01｜Quality 在业务测试前被导入路径阻断

现象：直接执行 production settings gate 时无法导入 `horilla`，后续 Django check、迁移与业务测试被跳过。

处理：PR #53 为 Quality 显式设置 `PYTHONPATH=backend`，不通过删除测试或放宽设置绕过。

### P1-CI-02｜两个生产设置文件未通过锁定格式器

涉及：

```text
backend/horilla/settings/__init__.py
backend/horilla/settings/security.py
```

处理：按 CI 锁定的 Black 版本格式化；不改变安全语义。

### P2-INFRA-01｜Docker Hub 瞬时 502 导致构建未进入应用阶段

处理：Docker build 增加 4 次有限退避重试；四次全部失败仍严格阻断。不得把外部镜像站故障写成产品通过，也不得无限重试掩盖真实失败。

### P1-DOC-01｜权威文档入口整体过期

现象：旧索引、新手入口和开发顺序仍把仓库描述成 8 月 10 日的 HR01～HR12 接管阶段。

处理：本 PR 更新唯一入口、当前状态、生产收口顺序与 100% 验收标准；旧文件只作为历史保留。

---

## 5. 当前能力分层

| 层级 | 当前判断 | 说明 |
|---|---|---|
| HR01～HR18 代码目录 | `PRESENT` | 18 个正式目录均存在 |
| 页面/入口与多条浏览器 smoke | `PRESENT` | 能证明真实登录和基础可访问性，但不等于全生命周期办结 |
| MySQL 生产门 | `RE-RUNNING ON PR #53` | 以当前 exact HEAD 结果为准 |
| 招聘到员工前半合同链 | `CANDIDATE / MUST REPROVE` | 必须在最新 main 基线上重新全绿并补跨角色证据 |
| HR08～HR18 后半生命周期 | `IMPLEMENTED PARTS / MUST PROVE` | 不能只据目录或旧报告写 PASS |
| 核心业务 100% | `NOT YET PROVEN` | HM-HR-00～15 与 N-HR-01～08 尚未形成同一 exact SHA 的完整签字包 |
| 生产部署与恢复 | `RUNBOOK PRESENT / EVIDENCE REQUIRED` | 必须由 Docker、备份恢复和真实环境证据签字 |
| docs 权威入口 | `BEING RETURNED TO TRUTH IN PR #53` | 本轮五个核心文档形成唯一导航和验收口径 |

---

## 6. 核心业务的唯一验收范围

必须围绕同一租户、同一组织、同一岗位/编制、同一候选人/教职工和多个真实角色，连续完成：

```text
HR01
→ HR02
→ HR04
→ HR05
→ HR03
→ HR07
→ HR06
→ HR08/HR09
→ HR10
→ HR11
→ HR12
→ HR13
→ HR14
→ HR15
→ HR16
→ HR17
→ HR18
```

同时必须通过：

- 跨租户猜 ID 拒绝；
- 最后一个编制并发不超占；
- handoff / activation 重放幂等；
- 错误部门和错误审批人拒绝；
- 调岗后旧 Assignment 仍可按 as-of 查询；
- 已签合同不可被异动静默改写；
- Employee A 不能查看 Employee B；
- HR18 不能反向改写 HR02～HR16 源事实。

详细 Case、证据字段和 100% 公式见 [`CORE_BUSINESS_FLOW_ACCEPTANCE.md`](CORE_BUSINESS_FLOW_ACCEPTANCE.md)。

---

## 7. PR #53 必需 Gate 矩阵

下面全部为合并前必需项；任何 `FAIL / BLOCKED / SKIPPED` 都不能被“其他检查已绿”抵消。

| Gate | 合并要求 |
|---|---|
| Syntax / Ruff / Black / isort | PASS |
| Django check + production deployment check | PASS |
| `makemigrations --check --dry-run` | PASS |
| MySQL fresh migrate | PASS |
| Previous baseline upgrade | PASS |
| HR01～HR18 Authority gate | PASS |
| 全部注册 HR app tests | PASS |
| Docker build / release / collectstatic | PASS |
| MySQL backup + restore smoke | PASS |
| Gunicorn `/health/` / `/ready/` | PASS |
| Trivy High/Critical gate | PASS 或有正式、限期、经批准的例外记录 |
| 前半核心浏览器链 | PASS |
| 后半生命周期浏览器/服务合同 | PASS |
| HM-HR-00～15 | 100% PASS |
| N-HR-01～08 | 100% PASS |
| P0 | 0 |
| 阻断核心链 P1 | 0 |
| docs 当前状态与验收口径 | 与最终 exact SHA 一致 |

---

## 8. 当前禁止事项

- 不直接合并 PR #53；保持 Draft，直到必需证据齐全。
- 不把暂时排队、Runner 噪声或外部镜像站故障误写成业务缺陷；也不因此跳过门禁。
- 不因为某个模块旧报告写 `FINAL` 就跳过当前回归。
- 不通过关闭租户、权限、审计、扫描、生产设置或漏洞门制造绿灯。
- 不在同一时间另开 HRxx 功能分支并行施工。
- 不删除旧历史事实来修“当前状态”。
- 不让 mock、fixture、手工 SQL 替代真人业务前置动作。

---

## 9. 下一步执行顺序

```text
1. 查看 PR #53 当前 exact HEAD 的 Actions
2. 对每个失败 job 读取完整日志，区分产品缺陷、门禁缺陷、外部基础设施故障
3. 只修当前最上游根因，并补精准测试
4. 先跑受影响链，再跑全部必需门
5. 按 CORE_BUSINESS_FLOW_ACCEPTANCE 执行同一黄金员工 HM/N 用例
6. 完成 Docker、备份恢复、readiness 与生产安全签字
7. 更新本文件的 Release Seal
8. 负责人确认后才把 Draft 转为可合并
```

---

## 10. 最终 Release Seal 模板

只有所有 Gate 完成后填写；未填写等于未签字。

| 字段 | 值 |
|---|---|
| Product exact SHA | `PENDING` |
| PR | `#53` |
| Quality / MySQL run | `PENDING` |
| Previous baseline upgrade run | `PENDING` |
| Docker / MySQL run | `PENDING` |
| Browser golden evidence | `PENDING` |
| HM-HR-00～15 | `PENDING` |
| N-HR-01～08 | `PENDING` |
| Backup package / hash | `PENDING` |
| Restore target / result | `PENDING` |
| P0 | `PENDING` |
| Blocking P1 | `PENDING` |
| Reviewer / date | `PENDING` |

在 `PENDING` 全部清零前，统一结论：

```text
NO PRODUCTION RELEASE
```
