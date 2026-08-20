# 当前真实状态基线

> 最后核对：2026-08-19  
> 适用仓库：`penghaibin9/renshi`  
> 发生冲突时统一执行：**当前 Git HEAD + 当前可重复 Gate > 本页 > 设计总册 > 历史 READY / FINAL 报告。**

## 1. 当前 GitHub 真相

| 项 | 当前事实 | 裁决 |
|---|---|---|
| 默认稳定分支 | `main` | 当前唯一稳定基线 |
| main HEAD | `61fc1d0ece15605a3d14fe72d490c3dd0c1fd2e0` | 2026-08-17 合并 PR #2 |
| PR #2 | 已合并 | HR01~HR18 总集成代码已进入 main |
| 开放 PR | 0（2026-08-19 核对） | 后续新施工必须从当前 main 新开最小分支 |
| 开放 Issue | 0（2026-08-19 核对） | 不代表没有技术债，只代表当前没有登记中的开放 Issue |
| 旧接管分支 | `agent/renshi-takeover-cleanup-20260810` | 已完成总集成使命，不再作为“当前开发总线” |

## 2. 数据库 / CI 当前事实

当前默认基线已经不是 2026-08-10 文档描述的 PostgreSQL 状态。

已经可从 main 直接核验：

```text
docker-compose.yml
  db.image = mysql:8.4

horilla/settings/ci_test.py
  ENGINE = django.db.backends.mysql

.github/workflows/
  docker-ci.yml
  patch-base-mysql-fresh-schema.yml
  previous-baseline-upgrade.yml
  quality.yml
  hr-visual-audit.yml
```

因此：

```text
Production / Development / Test / CI / Migration Acceptance = MySQL
```

仍然禁止新增 PostgreSQL 专属 Authority 设计。SQLite 只能用于局部快速反馈，不能替代 MySQL 验收。

## 3. HR01~HR18 当前状态怎么理解

PR #2 的合并说明 **HR01~HR18 已经进入同一个 main 集成基线**。这推翻了旧状态页中“部分模块尚未交付到 GitHub / 尚未进入总集成”的描述。

但统一采用以下状态语义：

| 状态 | 含义 |
|---|---|
| `IN MAIN BASELINE` | 代码已进入 main，不代表生产验收完成 |
| `CODE COMPLETE` | 主体实现完成 |
| `MODULE TEST GREEN` | 对应模块精准测试绿 |
| `MYSQL GREEN` | 当前 HEAD 的 MySQL migration + 模块测试绿 |
| `INTEGRATION GREEN` | 当前 HEAD 上下游真实联调绿 |
| `READY FOR ACCEPTANCE` | 模块要求的全部 Gate 可重复通过 |
| `PRODUCTION READY` | 全系统生产 Gate 全绿 |

因此当前默认判断是：

```text
HR01~HR18 = IN MAIN BASELINE
PRODUCTION READY = 必须重新以当前 main / 后续 exact-head Gate 证明
```

任何旧报告里的 READY/FINAL，只要没有对应当前 HEAD 的证据，不自动继承。

## 4. 已经失效的旧阻断描述

以下 2026-08-10 状态不得再直接引用为当前事实：

- “compose / CI 仍是 PostgreSQL”——已失效；当前 compose 与 CI settings 已是 MySQL。
- “CI 仍只围绕 Horilla 2.0 / dev-v2.0”——已失效；当前工作流已经包含 main / PR→main 与 MySQL Gate。
- “HR07 GitHub 代码交付断层”——总集成已经包含 HR07 后续完整施工；若要判断 HR07 是否 READY，应重新审当前 main，而不是继续引用旧断层结论。
- “HR09 / HR10 / HR12 尚未进入总集成”——已失效；这些模块已经随 PR #2 进入 main。
- “当前统一施工线仍是 agent/renshi-takeover-cleanup-20260810”——已失效；该分支已经合并。

旧文档可保留用于追溯，但不得继续充当当前 Gate。

## 5. 当前真正的下一阶段

由于大规模总集成已经完成，后续不再按“哪个目录有没有代码”来判断进度，而按 **合并后生产复审** 推进。

推荐顺序：

```text
P1  Tenant / Permission / fail-closed exact-head 复审
→ P2 Canonical API / Event / Legacy formal write 复审
→ P3 MySQL fresh migrate / previous-baseline upgrade / schema conflict 复审
→ P4 HR01~HR18 关键纵向主链与跨域 E2E
→ P5 并发 / 幂等 / failure injection
→ P6 备份恢复 / production security / readiness
→ P7 再决定下一批业务增强
```

### P1 的首要检查对象

优先检查：

- request / job / event / provider 是否都有显式 tenant context；
- 无 tenant 是否 fail-closed；
- 是否仍存在“默认第一所学校”“all scope 兜底”；
- permission cache 切学校后是否立即失效；
- 平台账号是否可能越权获得学校人事数据；
- Dashboard / Report / Legacy 是否绕过 Authority 直接写正式事实。

只有找到真实缺口再改，不为了“继续开发”制造重复代码。

## 6. 当前开发纪律

```text
1. 从当前 main 新开最小施工分支
2. 一次只解决一个可说明、可回滚的问题
3. 不使用 git add -A
4. 不跨域直接写别人的 Authority
5. 精准测试优先，避免无意义全量回归
6. exact-head Gate 通过后才更新 READY 状态
7. 不直接把旧 FINAL/READY 报告当新 HEAD 证据
```

## 7. 历史状态页

`CURRENT_STATE_2026-08-10.md` 仅保留为接管初期历史快照。继续开发时不要再从它读取当前阻断。

下一步统一从本页与 [`开发顺序_接管版.md`](开发顺序_接管版.md) 开始。
