# 跃科高校人事管理与教师发展系统

> 仓库：`penghaibin9/renshi`  
> 底座：历史兼容层（正在逐步退出，所有新业务统一进入 HR01～HR18）
> 当前正式集成目标：`main`；本轮唯一施工分支：`fix/production-readiness-20260904`，原 Draft PR #53
> 提交规则：经授权只向原施工分支提交并触发验收；**证据未齐，不合并 main、不部署**

## 开发前必读：已采用的产品原则

先读根目录 [`AGENTS.md`](AGENTS.md)；它将已确认的产品方向落实为 HRP-01～HRP-12 开发与验收要求。业务解释及公开资料依据继续复用 [`docs/UNIVERSITY_HR_PRODUCT_PRIORITIES.md`](docs/UNIVERSITY_HR_PRODUCT_PRIORITIES.md)，不另造产品总册。

目标是：**教师少重复填报，学院少人工催办，人事少反复核对，每一个正式结果都能解释和追溯；学校能自己配置并办事。**人员档案、登录账号和本校权限分别管理；人事与学生系统保持独立，通过明确映射及受控接口协作。

每次施工须写清“原则 → 页面与事件 → API/权限 → 服务/事实 → 测试/证据”；使用现有 [PR 检查表](.github/PULL_REQUEST_TEMPLATE.md)。原则采用不代表功能已实现，检查表不是自动强制执行器；实时进度见 [`docs/CURRENT_STATE_2026-09-04.md`](docs/CURRENT_STATE_2026-09-04.md)。

## 新手只认这三个入口

1. 打开 [`Renshi-18模块.code-workspace`](Renshi-18模块.code-workspace)，它只打开这一份正式主程序。
2. 阅读 [`docs/新手本地开发总控.md`](docs/新手本地开发总控.md)，按固定步骤施工。
3. 进入 [`docs/modules/README.md`](docs/modules/README.md)，一次只选择一个模块。

正式源码已经整理为国内团队常见的前后端结构。Django app 的内部名称保持不变，因此数据库迁移、Python 导入和已有 V2 页面不会丢失。

## 先看这一段

这是一个面向高校/职业院校的人事管理与教师发展系统。现有历史兼容能力正在逐步退出，正式业务统一由 HR01～HR18 高校人事模块承载。

如果你是第一次打开这个仓库，不要先翻几百个源码文件，也不要照历史项目说明操作。请按下面顺序：

1. 先读 [`docs/README_新手入口.md`](docs/README_新手入口.md)
2. 再读 [`docs/开发顺序_接管版.md`](docs/开发顺序_接管版.md)
3. 需要看业务设计时，再进入 [`docs/00_文档总索引.md`](docs/00_文档总索引.md)
4. 只有在修某一个 HR 模块时，才读该模块的施工总册和代码
5. 准备上线或值守时，按 [`docs/PRODUCTION_RUNBOOK.md`](docs/PRODUCTION_RUNBOOK.md) 执行

## 当前最重要的事实

### 1. HR01~HR18 已进入统一施工与收口

18 个模块都已有正式代码目录。当前工作是补齐真实业务链、权限、迁移、MySQL 测试和跨域验收，旧报告里的“完成”不能代替当前代码证据。

### 2. 目标数据库是 MySQL-only

`docs/00_高校人事系统全局架构与旧系统接管合同.md` 已冻结：开发、测试、CI、迁移验收、生产统一以 MySQL 为目标。

`docker-compose.yml`、生产 overlay 和主 CI 都以 MySQL 8.4 为签字数据库；SQLite/PostgreSQL 结果不能替代 MySQL 验收。

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

### 先认识这些目录

```text
backend/                  后端：Django 配置、基础能力、HR01～HR18 业务代码
frontend/                 前端：V2 模板、CSS、JavaScript、图片和本地前端依赖
deploy/                   部署：Docker 启动脚本、Nginx、Gunicorn
docs/                     文档：新手说明、模块施工册、验收报告
tests/                    测试：视觉测试、基线和测试产物
scripts/                  工具：数据准备、检查和浏览器验收脚本
.runtime/                 本机运行数据（数据库、上传文件、静态收集文件，不提交 Git）
.github/workflows/        GitHub Actions 自动验收
```

日常启动仍在仓库根目录运行 `python manage.py ...` 或 Docker 命令，不需要进入 `backend/`。

### HR01~HR18 对应代码目录

| 模块 | 业务 | 代码目录 |
|---|---|---|
| HR01 | 人事工作台 | `backend/hr_control_center/` |
| HR02 | 组织机构与编制岗位 | `backend/hr_structure/` |
| HR03 | 教职工主档 | `backend/hr_staff/` |
| HR04 | 招聘与人才引进 | `backend/hr_recruitment/` |
| HR05 | 入职管理 | `backend/hr_onboarding/` |
| HR06 | 人事异动 | `backend/hr_changes/` |
| HR07 | 合同与聘用 | `backend/hr_contracts/` |
| HR08 | 兼职外聘教师 | `backend/hr_external/` |
| HR09 | 教师资格与双师型 | `backend/hr_qualification/` |
| HR10 | 培训进修与企业实践 | `backend/hr10_development/` |
| HR11 | 考勤与请假 | `backend/hr_time/` |
| HR12 | 年度与聘期考核 | `backend/hr_assessment/` |
| HR13 | 职称评审 | `backend/hr_title/` |
| HR14 | 岗位聘任 | `backend/hr_appointment/` |
| HR15 | 薪酬福利 | `backend/hr_payroll/` |
| HR16 | 退休与离校 | `backend/hr_exit/` |
| HR17 | 教职工服务 | `backend/hr_self/` |
| HR18 | 人事数据中心 | `backend/hr_data/` |

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
- 不要绕过 18 模块统一门禁单独宣称某模块 100%
- 不要一次性大范围重写历史兼容层；必须按 Authority Cutover 逐域退出

## 当前开发顺序

下表保留总体依赖，不等于每轮从 C0 重新施工。当前活动切片以 [`docs/CURRENT_STATE_2026-09-04.md`](docs/CURRENT_STATE_2026-09-04.md) 的最新记录为准；专项绿灯不抵消其他必需门的失败。

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
→ C9 HR13 → HR18 正式 Authority 与 18 模块统一集成
→ 全绿后形成 main 合并候选
```

详细验收条件见 [`docs/开发顺序_接管版.md`](docs/开发顺序_接管版.md)。

## 目前不建议直接使用的旧入口

历史项目说明中的这些内容已经不再作为本仓库开发规则：

- `2.0` / `dev/v2.0` 作为开发目标分支
- PostgreSQL 作为最终生产验收数据库
- 历史模块目录就是最终 Authority

历史兼容层只用于过渡读取与投影；本仓库的最终裁决以 `docs/00_高校人事系统全局架构与旧系统接管合同.md` 和当前代码 Gate 为准。

## License

本仓库继续遵守原项目的 LGPL-2.1 许可证要求，详见 [`LICENSE`](LICENSE)。
