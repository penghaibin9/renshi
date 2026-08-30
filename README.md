# 跃科高校人事管理与教师发展系统

> 仓库：`penghaibin9/renshi`  
> 底座：Horilla HRMS 2.0（正在逐步接管，不再按 Horilla 上游开发分支规则施工）  
> 当前本地开发总线：`agent/renshi-ui-v2-20260827`
> 默认稳定分支：`main`（**没有全绿验收，不合并 main**）

## 本地开发只认这三个入口

1. 打开 [`Renshi-18模块.code-workspace`](Renshi-18模块.code-workspace)，文件树只显示 HR01～HR18。
2. 阅读 [`docs/新手本地开发总控.md`](docs/新手本地开发总控.md)，按固定步骤施工。
3. 进入 [`modules/README.md`](modules/README.md)，一次只选择一个模块。

`modules/` 是给人看的 18 模块控制面；现有 `hr_*` Django app 暂不移动，避免破坏 Python 导入、migration 历史和测试。前端文件按模块逐步迁回各自 app，不做一次性大搬家。

## 先看这一段

这是一个面向高校/职业院校的人事管理与教师发展系统。仓库最初基于 Horilla 2.0，目前正在把旧 Horilla 能力逐步接管为 HR01~HR18 的高校人事 Authority。

如果你是第一次打开这个仓库，不要先翻几百个源码文件，也不要直接照旧 Horilla README 操作。请按下面顺序：

1. 先读 [`docs/README_新手入口.md`](docs/README_新手入口.md)
2. 再读 [`docs/开发顺序_接管版.md`](docs/开发顺序_接管版.md)
3. 需要看业务设计时，再进入 [`docs/00_文档总索引.md`](docs/00_文档总索引.md)
4. 只有在修某一个 HR 模块时，才读该模块的施工总册和代码

## 当前最重要的事实

### 1. 暂停新增 HR13~HR18 功能

当前优先任务不是继续堆功能，而是把 HR01~HR12 从“模块内完成”收敛成“全系统可运行、可测试、可上线”。

### 2. 目标数据库是 MySQL-only

`docs/00_高校人事系统全局架构与Horilla接管合同.md` 已冻结：开发、测试、CI、迁移验收、生产统一以 MySQL 为目标。

**注意：当前 `docker-compose.yml` 和部分 CI 仍是 PostgreSQL，这是待清理的历史欠账，不代表目标架构。**

### 3. 文档里的 READY 不能代替代码验收

以后只认：

```text
当前 Git HEAD
+ Django system check
+ makemigrations --check
+ MySQL fresh migrate
+ 对应模块测试
+ tenant / permission 负测试
+ 跨域 E2E
+ GitHub Actions 全绿
```

任何旧报告写着 `READY FOR ACCEPTANCE`，如果当前 HEAD 没有通过上面这些 Gate，就仍然视为未封板。

### 4. API / Permission / Event 只保留一套正式合同

新代码最终统一到：

```text
API:        /api/v1/hr/...
Permission: hr.<domain>.<resource>.<action>
Tenant:     fail-closed
History:    effective-dated / as-of
Cross-domain write: Provider / Command API / durable Event
```

旧 `/api/hr/v1/...` 只允许作为迁移期 Legacy Adapter，不再新增业务 handler。

## 目录怎么认

### 先认识 6 类目录

```text
horilla/                 Django 全局设置、URL、启动配置
base/                    Horilla 基础能力与多学校/权限底座
employee/                Horilla 旧员工域（Legacy，逐步被 HR03 等接管）
hr_* / hr10_development/ 新高校人事模块代码

docs/                    系统设计、总控、模块施工册、验收资料
.github/workflows/        GitHub Actions 门禁（当前需要重建为 main + MySQL）
```

### HR01~HR12 对应代码目录

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

## 新手每天只做这 5 步

```bash
# 1. 看自己在哪个分支
git branch --show-current

# 2. 看当前有没有未提交改动
git status

# 3. 一次只改一个阶段/一个模块
# 不要同时改多个 Authority

# 4. 跑该阶段要求的检查/测试
# 以 docs/开发顺序_接管版.md 的 Gate 为准

# 5. 通过后再提交；仍然不直接合并 main
```

## 绝对不要做

- 不要为了“测试绿”关闭 tenant / permission / audit
- 不要默认第一所学校或 `all` scope
- 不要让 Dashboard / Report / Legacy 页面直接改 Authority
- 不要跨域 import 对方正式模型后 `.save()`
- 不要把 PostgreSQL/SQLite 测试通过当成 MySQL 已验收
- 不要看到旧文档写 READY 就继续往后开发
- 不要在 HR01~HR12 系统收口前继续铺 HR13~HR18
- 不要一次性大范围重写旧 Horilla；必须按 Authority Cutover 逐域退出

## 当前开发顺序

简版：

```text
C0 新手化与仓库真相清洗
→ C1 H0/A0 多学校租户底座
→ C2 MySQL-only 开发/CI/迁移基线
→ C3 Django App / URL / API / Permission 全局接管
→ C4 HR02 + HR03 基础 Authority 封板
→ C5 HR04 → HR05 → HR07 入人主链
→ C6 HR06 → HR08 → HR09 → HR10 → HR11 → HR12
→ C7 HR01 聚合收口
→ C8 跨域 E2E / Failure Injection / Backup-Restore / Security
→ 全绿后才开始 HR13
```

详细验收条件见 [`docs/开发顺序_接管版.md`](docs/开发顺序_接管版.md)。

## 目前不建议直接使用的旧入口

旧 Horilla README 中的这些说明已经不再作为本仓库开发规则：

- `2.0` / `dev/v2.0` 作为开发目标分支
- PostgreSQL 作为最终生产验收数据库
- Horilla 原模块目录就是最终 Authority

Horilla 仍然是重要 Legacy 底座，但本仓库的最终裁决以 `docs/00_高校人事系统全局架构与Horilla接管合同.md` 和当前代码 Gate 为准。

## License

本仓库继续遵守原项目的 LGPL-2.1 许可证要求，详见 [`LICENSE`](LICENSE)。
