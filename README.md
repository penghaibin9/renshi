# 跃科高校人事管理与教师发展系统

> 仓库：`penghaibin9/renshi`  
> 底座：Horilla HRMS 2.0（作为 Legacy 底座逐域接管）  
> 默认稳定分支：`main`  
> 当前 main 基线：`61fc1d0ece15605a3d14fe72d490c3dd0c1fd2e0`（2026-08-17，PR #2 已合并）

## 先看这一段

这是一个面向高校/职业院校的人事管理与教师发展系统。仓库最初基于 Horilla 2.0，目前 HR01~HR18 已经通过总集成 PR #2 进入 `main`。

**注意：进入 main 只表示形成了新的集成基线，不等于可以跳过当前 HEAD 的生产复验。** 以后继续施工时，一律以当前代码、当前测试/CI 和 [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) 为准，不再使用已经合并关闭的旧施工分支状态做判断。

第一次打开仓库请按下面顺序：

1. 先读 [`docs/README_新手入口.md`](docs/README_新手入口.md)
2. 再读 [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md)
3. 再读 [`docs/开发顺序_接管版.md`](docs/开发顺序_接管版.md)
4. 需要看业务设计时，再进入 [`docs/00_文档总索引.md`](docs/00_文档总索引.md)

## 当前最重要的事实

### 1. PR #2 已经合并，旧“接管分支进行中”描述全部失效

2026-08-17，HR01~HR18 总集成 PR #2 已合并到 `main`，合并提交为：

```text
61fc1d0ece15605a3d14fe72d490c3dd0c1fd2e0
```

因此旧文档中以下表述不再是当前事实：

- “当前统一施工线仍是 `agent/renshi-takeover-cleanup-20260810`”
- “HR07 GitHub 代码交付断层仍未恢复”
- “docker-compose / CI 仍以 PostgreSQL 为默认基线”
- “HR09 / HR10 / HR12 尚未进入总集成基线”

这些内容只能作为历史施工记录。

### 2. MySQL-only 已经进入默认开发/CI 基线

当前仓库可直接核验到：

```text
docker-compose.yml           -> mysql:8.4
horilla/settings/ci_test.py  -> django.db.backends.mysql
.github/workflows/           -> MySQL fresh schema / upgrade / Docker smoke 等门禁
```

生产、开发、测试、迁移、验收仍统一执行 MySQL-only；禁止新增 PostgreSQL 专属 Authority 设计。

### 3. “已集成”不等于“已生产封板”

继续开发前仍然只认当前 HEAD 的可重复证据：

```text
当前 Git HEAD
+ Django system check
+ makemigrations --check
+ MySQL fresh migrate / upgrade
+ 对应模块测试
+ tenant / permission 负测试
+ 跨域 E2E
+ failure injection / backup-restore（进入生产封板时）
```

任何历史 `READY` / `FINAL` / `ProductionAcceptance` 报告，如果没有当前 HEAD 对应证据，都只能当历史记录。

### 4. 当前优先级是“合并后生产复审”，不是重新铺第二套模块

PR #2 已经把 HR01~HR18 放到同一 main 基线上。下一阶段优先做：

```text
仓库真相收口
→ tenant / permission / fail-closed 复审
→ canonical API / event / legacy write 复审
→ MySQL exact-head migration / regression
→ 跨域 E2E / failure injection / backup-restore
→ 再决定下一批业务增强
```

不要因为模块已经存在，就绕过生产 Gate 继续无限加页面或第二套 Authority。

## 目录怎么认

```text
horilla/                 Django 全局设置、URL、启动配置
base/                    Horilla 基础能力与多学校/权限底座
employee/                Horilla 旧员工域（Legacy，逐步退出正式写）
hr_* / hr10_development/ 高校人事 Authority 代码

docs/                    系统设计、总控、模块施工册、验收资料
.github/workflows/        GitHub Actions / MySQL 生产门禁
```

## HR01~HR12 对应代码目录

| 模块 | 业务 | 代码目录 |
|---|---|---|
| HR01 | 人事工作台 | `hr_control_center/` |
| HR02 | 组织机构与编制岗位 | `hr_structure/` |
| HR03 | 教职工主档 | `hr_staff/` |
| HR04 | 招聘与人才引进 | `hr_recruitment/` |
| HR05 | 入职管理 | `hr_onboarding/` |
| HR06 | 人事异动 | `hr_changes/` |
| HR07 | 合同与聘用 | `hr_contracts/` |
| HR08 | 兼职外聘教师 | `hr_external/` |
| HR09 | 教师资格与双师型 | `hr_qualification/` |
| HR10 | 培训进修与企业实践 | `hr10_development/` |
| HR11 | 考勤与请假 | `hr_time/` |
| HR12 | 年度与聘期考核 | `hr_assessment/` |

HR13~HR18 已进入总集成基线，具体目录和 Authority 定义以 `docs/00_文档总索引.md` 与各模块施工总册为准。

## 每次施工只做这 6 步

```bash
# 1. 确认当前分支和 HEAD
git branch --show-current
git rev-parse HEAD

# 2. 确认没有混入无关改动
git status

# 3. 先读 docs/CURRENT_STATE.md

# 4. 一次只改一个阶段/一个 Authority
# 不跨域直接写别人的正式模型

# 5. 跑该阶段的精准 Gate，再看 diff

# 6. 通过后再提交；没有生产证据不宣称 READY
```

## 绝对不要做

- 不要为了“测试绿”关闭 tenant / permission / audit
- 不要默认第一所学校或 `all` scope
- 不要让 Dashboard / Report / Legacy 页面直接改 Authority
- 不要跨域 import 对方正式模型后 `.save()`
- 不要把 SQLite/PostgreSQL 测试通过当成 MySQL 已验收
- 不要看到旧文档写 READY 就直接跳关
- 不要重新制造第二套 API / Permission / Event 正式合同
- 不要一次性大范围重写旧 Horilla；必须按 Authority Cutover 逐域退出

## 当前阅读顺序

```text
README_新手入口
→ CURRENT_STATE
→ 开发顺序_接管版
→ 00 全局架构合同
→ 对应 HRxx 施工总册
→ 真实代码与当前 Gate
```

## License

本仓库继续遵守原项目的 LGPL-2.1 许可证要求，详见 [`LICENSE`](LICENSE)。
