# 当前真实状态基线（2026-08-10）

> 这是接管分支的“仓库真相页”。  
> 它描述的是当前 GitHub HEAD 的可验证状态，不复述历史报告的 READY 宣言。  
> 发生冲突时：**当前代码/CI 事实 > 本页 > 历史验收报告。**

## 全局状态

| 项 | 当前状态 | 结论 |
|---|---|---|
| 默认稳定分支 | `main` | 未经全绿 Gate 不合并 |
| 接管分支 | `agent/renshi-takeover-cleanup-20260810` | 当前统一收口施工线 |
| 接管基线来源 | `feature/hr06-changes` | 包含当前最多 HR01~12 代码 |
| H0/A0 | 独立 Draft PR/分支，尚未成为当前统一底座 | P0：必须先吸收并复验 |
| 目标数据库 | MySQL-only | 已由 00 合同冻结 |
| 当前 compose/部分 CI | PostgreSQL | P0：与目标冲突 |
| 当前 Quality/Docker CI | 仍沿用 Horilla 上游分支触发思路 | P0：需改为 main/PR→main |
| HR13~HR18 | 暂停新增功能 | 等 HR01~12 baseline sealed |

## HR01~HR12 真相矩阵

| 模块 | 目录 | 当前判断 | 下一动作 |
|---|---|---|---|
| HR01 人事工作台 | `hr_control_center/` | 主体代码存在，聚合层思路正确；API/Metric/全局合同待统一 | C7 最后收口 |
| HR02 组织机构与编制岗位 | `hr_structure/` | 基础 Authority 主体已存在，测试与分层较好 | C4 首先封板 |
| HR03 教职工主档 | `hr_staff/` | 当前最成熟范本之一 | C4 与 HR02 一起封板 |
| HR04 招聘 | `hr_recruitment/` | 主体代码完整度较高，欠统一 CI/MySQL/E2E | C5 |
| HR05 入职 | `hr_onboarding/` | 主体代码完整度较高，欠统一 CI/MySQL/E2E | C5 |
| HR06 人事异动 | `hr_changes/` | 当前最成熟范本之一，有并发/outbox/reconcile 思路 | C6 补全局 Gate |
| HR07 合同 | `hr_contracts/` | **GitHub 代码交付断层**：历史报告与当前目录不一致 | C5 先恢复完整 app |
| HR08 外聘 | `hr_external/` | 主体已施工，欠 Provider/CI/全局合同 | C6 |
| HR09 资格/双师 | `hr_qualification/` | 代码存在，但未完整进入默认运行接管 | C6：先注册/迁移/测试 |
| HR10 培训发展 | `hr10_development/` | 代码面很宽，测试/接管深度不足以证明整体 READY | C6：按纵向业务链重新验 |
| HR11 考勤请假 | `hr_time/` | 当前最成熟范本之一 | C6 补 Legacy/MySQL/跨域 |
| HR12 考核 | `hr_assessment/` | 代码量大，但未完整进入默认运行接管 | C6：先正式注册再验收 |

## 当前三个金标准模块

后续重构/新模块优先参考：

```text
HR03 hr_staff
HR06 hr_changes
HR11 hr_time
```

参考的是它们的“分层方式”，不是盲目复制全部实现。

推荐结构：

```text
context.py
permissions.py
models/
selectors/
services/
providers/ or integrations/
events/ / outbox
jobs/
tests/
```

## 当前五个系统级阻断

### P0-01 H0/A0 尚未统一

业务模块施工在租户底座完全签发之前已经展开。先统一 tenant foundation，再接受各模块安全测试结果。

### P0-02 MySQL-only 与 PostgreSQL 运行/CI 冲突

当前 PostgreSQL/SQLite 测试只能作为开发反馈，不能作为最终数据库 Gate。

### P0-03 API / Permission / Event 合同漂移

最终必须收成单一 canonical contract：

```text
/api/v1/hr/...
hr.<domain>.<resource>.<action>
Global Event Registry
```

### P0-04 HR07 仓库交付不完整

历史 HR07 交付报告不能作为当前 GitHub READY 证据。必须以当前目录恢复完整 app、migration、test、URL 后重新验收。

### P0-05 CI 没有真正覆盖当前开发方式

必须建立针对 `main` / PR→`main` 的真实 Gate，并执行 MySQL + HR 模块测试，而不是只做 Horilla settings/urls 轻量检查。

## 状态词重新定义

从本接管分支起，统一使用：

| 状态 | 含义 |
|---|---|
| `CODE COMPLETE` | 主体代码写完，不代表能合并 |
| `MODULE TEST GREEN` | 模块测试绿，不代表数据库/联调绿 |
| `MYSQL GREEN` | MySQL fresh migrate + 对应测试绿 |
| `INTEGRATION GREEN` | 上下游真实联调绿 |
| `READY FOR ACCEPTANCE` | 模块所有要求 Gate 绿 |
| `PRODUCTION READY` | 全系统生产 Gate 绿 |

历史文档中的 `READY` 如果没有对应当前 HEAD Gate，统一降级为“历史施工记录”。

## 下一步

严格按：

[`开发顺序_接管版.md`](开发顺序_接管版.md)

从 C0 → C1 开始，不跨阶段。
