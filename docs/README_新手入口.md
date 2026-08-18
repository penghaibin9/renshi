# 新手入口：先把仓库看懂，再开发

> 适用对象：第一次接手本仓库、对 Django/Git/高校人事领域都不熟悉的人。  
> 目标：10 分钟内知道“当前基线是什么、代码放哪、先做什么、什么绝对不能碰”。

## 1. 这个仓库到底是什么

这个仓库不是“原版 Horilla”。

它现在是：

```text
Horilla 2.0 Legacy 底座
        ↓ 逐域接管
跃科高校人事管理与教师发展系统
        ↓
HR01 ~ HR18 高校人事 Authority
```

旧 Horilla 代码仍然大量存在，是为了迁移兼容，不代表这些旧模型永远是正式事实源。

## 2. 当前基线先记住

2026-08-17，HR01~HR18 总集成 PR #2 已经合并到 `main`：

```text
main = 61fc1d0ece15605a3d14fe72d490c3dd0c1fd2e0
```

所以不要再把 `agent/renshi-takeover-cleanup-20260810` 当“当前总开发分支”，也不要继续照 2026-08-10 的旧红灯清单判断现状。

继续开发前先读：

```text
docs/CURRENT_STATE.md
```

## 3. 先记住三个词

### Authority
正式事实源。比如 HR03 才负责正式人员/任职历史，别的模块不能自己再建一套并长期双写。

### Legacy
旧 Horilla 能力。可以读取、迁移、投影、兼容，但最终要明确退出正式写入。

### Gate
验收闸门。没通过当前 HEAD 的 Gate，就算代码很多、文档写 READY，也不能宣称完成。

## 4. 你平时最常看的目录

```text
README.md                       仓库总入口

docs/README_新手入口.md         你现在看的文件
docs/CURRENT_STATE.md           当前 GitHub 真相页
docs/开发顺序_接管版.md          接管架构与 Gate 参考
docs/00_文档总索引.md            深挖业务和历史资料

docs/00_高校人事系统全局架构与Horilla接管合同.md
                                全系统最高设计规则

horilla/settings/               Django 全局配置
.github/workflows/              CI / MySQL / 生产门禁

hr_structure/                   HR02
hr_staff/                       HR03
hr_recruitment/                 HR04
hr_onboarding/                  HR05
hr_changes/                     HR06
hr_contracts/                   HR07
hr_external/                    HR08
hr_qualification/               HR09
hr10_development/               HR10
hr_time/                        HR11
hr_assessment/                  HR12
```

HR13~HR18 已经进入 PR #2 总集成基线，具体目录看文档总索引和对应模块总册。

## 5. 当前数据库事实

当前默认开发/CI 基线已经是 MySQL-only：

```text
docker-compose.yml           -> mysql:8.4
horilla/settings/ci_test.py  -> django.db.backends.mysql
```

因此不要再照旧文档说“当前 compose / CI 还是 PostgreSQL”。

但同样要记住：**文件已经切 MySQL ≠ 当前 HEAD 所有 MySQL Gate 自动通过。** 生产判断仍然要看当前实际执行结果。

## 6. 当前真正要做什么

PR #2 已经解决“代码有没有进入同一基线”的问题。现在继续开发优先做**合并后生产复审**：

```text
Tenant / Permission / fail-closed
→ Canonical API / Event / Legacy write
→ MySQL migration / regression
→ 跨域 E2E
→ 并发 / 幂等 / Failure Injection
→ Backup / Restore / Production Security
→ 再增加业务增强
```

不要为了“继续开发”重新造第二套页面、第二套 Authority 或第二套权限合同。

## 7. Git 最少命令

```bash
# 我在哪个分支
git branch --show-current

# 当前 HEAD
git rev-parse HEAD

# 我改了什么
git status

# 只看某文件差异
git diff -- path/to/file.py

# 只添加明确文件，不用 git add -A
git add path/to/file.py path/to/test_file.py

# 提交
git commit -m "fix(hr03): ..."
```

不要直接：

```bash
git add -A
git push --force
git reset --hard
```

## 8. 每次改业务前的 8 个问题

1. 这个事实到底归哪个 HRxx Authority？
2. 有没有重复建第二套事实表？
3. tenant 不明确时是不是 fail-closed？
4. 有没有跨域直接 `.save()`？
5. 历史查询会不会拿今天的数据改过去？
6. FINAL/EFFECTIVE 后是不是还能普通 UPDATE？
7. 重复请求会不会生成两份正式结果？
8. 当前证据是不是来自 MySQL exact-head，而不是历史报告？

其中任何一个答案不清楚，先停在当前模块解决，不继续铺功能。

## 9. 什么叫“模块完成”

统一使用：

```text
IN MAIN BASELINE        已进入 main，不代表生产验收
CODE COMPLETE           代码主体已完成
MODULE TEST GREEN       模块测试全绿
MYSQL GREEN             MySQL 迁移 + 测试全绿
INTEGRATION GREEN       上下游联调全绿
READY FOR ACCEPTANCE    模块达到验收条件
PRODUCTION READY        全系统 Gate 全绿后才允许
```

## 10. 你现在应该从哪里开始

```text
CURRENT_STATE.md
→ 找本轮唯一缺口
→ 读对应总册/合同
→ 只改最小范围
→ 跑精准 Gate
→ 看 diff
→ 提交
```

核心原则只有一句：**当前代码和当前可重复证据，永远高于旧状态文档。**
