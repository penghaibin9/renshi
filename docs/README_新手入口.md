# 新手入口：先把仓库看懂，再开发

> 适用对象：第一次接手本仓库、对 Django/Git/HR 领域都不熟悉的人。  
> 目标：10 分钟内知道“代码放哪、先看什么、先做什么、什么绝对不能碰”。

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

## 2. 先记住三个词

### Authority
正式事实源。比如 HR03 才负责正式人员/任职历史，别的模块不能自己再建一套并长期双写。

### Legacy
旧 Horilla 能力。可以读取、迁移、投影、兼容，但最终要明确退出正式写入。

### Gate
验收闸门。没通过 Gate，就算代码很多、文档写 READY，也不能进入下一阶段。

## 3. 你平时最常看的目录

```text
README.md                       仓库总入口

docs/README_新手入口.md         你现在看的文件
docs/开发顺序_接管版.md          当前唯一推荐施工顺序
docs/00_文档总索引.md            需要深挖业务时再进去

docs/00_高校人事系统全局架构与Horilla接管合同.md
                                全系统最高规则

horilla/settings/               Django 全局配置
.github/workflows/              CI 门禁

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

## 4. 目前哪些模块最值得当范本

### 第一梯队

- HR03 `hr_staff/`
- HR06 `hr_changes/`
- HR11 `hr_time/`

以后新增模块优先参考它们的这些分层：

```text
context
permissions
models
selectors
services
providers / integrations
events / outbox
jobs
tests
```

不要把全部业务塞进 `views.py`。

## 5. 当前真实风险地图

### 红灯 1：MySQL 合同与现有运行环境不一致

目标已经冻结为 MySQL-only，但当前 `docker-compose.yml` / 部分 CI 仍使用 PostgreSQL。

因此当前 PostgreSQL/SQLite 测试只能用于发现问题，不能作为最终生产验收。

### 红灯 2：HR07 GitHub 代码不完整

HR07 历史交付报告曾宣称完成，但 GitHub 当前目录并没有完整 app 骨架。

因此 HR07 必须重新恢复/核对，不能让下游直接假设它已经 READY。

### 红灯 3：HR09 / HR10 / HR12 代码存在但未完整进入默认运行态

这些模块需要先做 App 注册、迁移、URL、权限、测试和 MySQL 验收，不要继续给它们堆页面。

### 红灯 4：CI 仍是 Horilla 上游规则

现有 Actions 仍主要监听 `2.0/dev-v2.0` 一类旧分支思路，需要改成 `main` 和 PR→`main` 的真实门禁。

## 6. 新手修改代码时只遵守这一条路线

```text
找当前阶段
→ 找唯一责任模块
→ 读该模块总册
→ 找真实代码
→ 只改最小范围
→ 跑测试
→ 看 diff
→ 提交到当前施工分支
→ CI 绿后才能进入下一阶段
```

## 7. Git 最少命令

```bash
# 我在哪个分支
git branch --show-current

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
git checkout main && 直接改
```

## 8. 每次改业务前的 8 个问题

1. 这个事实到底归哪个 HRxx Authority？
2. 有没有重复建第二套事实表？
3. tenant 不明确时是不是 fail-closed？
4. 有没有跨域直接 `.save()`？
5. 历史查询会不会拿今天的数据改过去？
6. FINAL/EFFECTIVE 后是不是还能普通 UPDATE？
7. 重复请求会不会生成两份正式结果？
8. 测试是不是只在 SQLite/PG 绿，MySQL 还没验？

其中任何一个答案不清楚，先停在当前模块解决，不继续铺功能。

## 9. 什么叫“模块完成”

以后不用“代码写完”这个说法，统一使用：

```text
CODE COMPLETE          代码主体已完成
MODULE TEST GREEN      模块测试全绿
MYSQL GREEN            MySQL 迁移+测试全绿
INTEGRATION GREEN      上下游联调全绿
READY FOR ACCEPTANCE   模块达到验收条件
PRODUCTION READY       全系统 Gate 全绿后才允许
```

其中 `READY FOR ACCEPTANCE` 也不等于整个系统能上线。

## 10. 你现在应该做什么

只看 [`开发顺序_接管版.md`](开发顺序_接管版.md)，从 C0 开始按顺序走。

当前阶段原则：

> **不再增加业务面，先把已经写出的 HR01~HR12 收成一套真正能运行、能测试、能上线的系统。**
