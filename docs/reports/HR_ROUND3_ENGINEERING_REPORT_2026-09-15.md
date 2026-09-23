# 跃科高校人事系统第三轮工程整改报告

日期：2026-09-15  
输入基线：`Yueke_University_HR_Round2_20260914.zip`  
基线 SHA256：`3538843133d0a4565f86bf30dce14dfcc3323d797d5ec8bf7539a634ecd440fa`  
交付裁决：**完整第三轮源码包可交付；生产状态仍为 NOT_RELEASED。**

## 1. 本轮施工边界

只在云端沙箱中的基线副本施工；未连接 GitHub，未连接用户电脑，未连接或修改生产服务器、正式 MySQL、真实学校账号或数据。没有用 SQLite 代替 MySQL 验收。

本轮优先处理用户指定的三类问题：生产 `release`、首次部署初始化、核心业务流程。没有重建系统架构，没有删除 HR01～HR18 原业务，也没有把说明文件代替源码修改。

## 2. 生产 release 与部署链修复

### 2.1 release 不再绕过镜像入口

原生产 overlay 对 `release` 使用 Compose `entrypoint: ["/bin/bash", "-lc"]` 加字符串 command。这会直接替换 Dockerfile 的 `/entrypoint.sh`，导致 release 与 web 不是同一启动门禁：数据库等待、生产密钥等入口检查可能被 release 绕过。

本轮改为：

- `release` 与 web 共用 `renshi-web:latest`；
- 不再覆盖 entrypoint；
- 禁止 entrypoint 自己自动 migrate/collect/check，避免重复执行；
- Compose command 使用精确 argv：`["python", "manage.py", "prepare_runtime", "--migrate", "--collectstatic"]`；
- web/worker 继续 `service_completed_successfully` 等待 release。

这样 schema/static 的唯一所有者仍是 release，但其启动前置门禁与正式应用一致。

### 2.2 Compose 版本和配置 fail-fast

生产 overlay 使用 `!override`，新增 `scripts/check_prod_compose.py`：

- 拒绝 Docker Compose < 2.24.4；
- 执行基础文件 + 生产 overlay 的 `config --quiet`；
- Makefile 新增 `prod-preflight`，`make prod` 先依赖该预检。

当前云执行器没有 Docker，所以真实 `docker compose config` 的本轮结果是 **BLOCKED**，而不是假绿。脚本自身的版本判断/调用契约由 Round3 纯 Python 测试验证。

## 3. 首次部署初始化安全收口

### 3.1 修复生产初始化 URL 可直达风险

Round2 基线虽然 `initialize_database` 主入口在 `DEBUG=False` 时返回 404，但多个子步骤只依赖 `HX-Request` 检查，攻击者可以伪造该请求头直达首管/学校初始化函数；`load_demo_database` 也缺同级生产关闭条件。

本轮改为：

- 所有初始化子步骤均先调用 `_require_database_initialization_access()`；
- 仅 DEBUG 环境允许，并要求从初始化口令主入口获取 15 分钟短期 session grant；
- grant 时轮换 session key；过期、未来时间或缺失均 404；
- `load_demo_database` 在非 DEBUG 环境直接 404；
- 初始化和演示加载的口令比较使用 `constant_time_compare`。

### 3.2 新增生产一次性首管 CLI

新增 `bootstrap_production_admin`，避免为了新库开通而重新暴露网页初始化：

- 默认仅 `IS_PRODUCTION=True` 可运行；
- 密码只读 `HR_BOOTSTRAP_ADMIN_PASSWORD`，不提供密码 CLI 参数；
- 使用 Django 密码强度验证；
- 一个事务内创建 HQ 学校、superuser、Employee、EmployeeWorkInformation 绑定；
- `Horilla Bot` 使用不可登录密码；
- 数据库已有业务数据且不等于完全一致的历史成功结果时拒绝继续；
- 完全一致的重复执行只返回 `PRODUCTION_BOOTSTRAP_ALREADY_COMPLETE`，不会重复创建。

生产运行手册已加入首次建校/首管步骤，并明确执行后立即清除临时密码环境变量。

## 4. HR16 核心流程：终止延迟退休后的受控改期

Round2 已能创建和批准 `END_DELAY`，但原 ExitCase 一旦进入 SUBMITTED/APPROVED/HANDOVER 后不能更新日期。本轮没有采用“数据库强改日期”。

新增 `ExitCaseService.revise_retirement_plan_for_successor()`，由已批准 END_DELAY 继任申请调用：

- 只允许退休 ExitCase；
- DRAFT/RETURNED 可更新计划；
- SUBMITTED/APPROVED 先受控退回 RETURNED，再写入新计划；
- HANDOVER 仅在尚未建立任何交接事项时可退回；
- 已存在交接事项时返回 `EXIT_RETIREMENT_HANDOVER_REVISION_REQUIRED`；
- SETTLEMENT、EFFECT_PENDING、EFFECTIVE 或任何 ExitEffect 已存在时返回 `EXIT_RETIREMENT_REVISION_TOO_LATE`；
- 改期时清除可能基于旧日期生成的 `planned_access_end_at`，要求后续流程重新确认；
- END_DELAY application 复用原 case id，并写 `EXIT_CASE_REPLANNED` 不可变事件，事件中保存 previousPlan、newPlanDate、reopenedStatus。

该边界的目的不是“一键覆盖全部阶段”，而是把最常见的“原计划已经审批，但尚未产生不可逆交接/结算/生效事实”真正接回原审批链。已经产生下游事实时继续 fail-closed，需要专门的后段更正/撤销业务，而不是静默改写。

## 5. 本轮测试与证据

实际在本云执行器完成：

| 检查 | 结果 |
|---|---|
| 最小文件写入/读回 | PASSED |
| Round2 纯规则/契约测试 | 66/66 PASSED |
| Round3 新增源码契约测试 | 6/6 PASSED |
| 后端 AST | 3076 Python 文件 PASSED |
| Compose YAML 语法解析 | PASSED |
| entrypoint Bash 语法 | PASSED |
| backend/scripts/tests compileall | PASSED |
| Round3 新增 Django/MySQL 测试文件 py_compile | PASSED |
| Docker Compose 实际解析 | BLOCKED：当前执行器无 Docker |
| Django/MySQL 集成运行 | BLOCKED：缺 django、DRF、MySQLdb、MySQL/Docker |

新增但尚未运行的真实 ORM 测试共 8 项：

- `base.test_round3_production_bootstrap`：6 项，覆盖空库原子创建、HQ 关联、不可登录 Bot、幂等重跑、已有数据 fail-closed、密码环境变量和生产环境限制；
- `hr_exit.tests.test_round3_flex_replan`：2 项，覆盖 APPROVED ExitCase 受控重开、旧计划事件证据、END_DELAY 成为当前批准计划，以及已有交接事项时拒绝自动改期。

没有安装另一套数据库、没有篡改门禁、没有删测试来换取绿灯。

证据目录：`docs/reports/round3_evidence/`。

## 6. 仍需目标环境完成的放行门

本包已经把第三轮发现的源码问题修入，但以下属于**运行验收**，当前沙箱客观无法完成：

1. Docker Compose v2.24.4+ 真正执行 `make prod-preflight`，确认 overlay 合并后的最终配置；
2. 以 MySQL 8.4 独立 QA 库执行全 migration（含 triggers）和 `makemigrations --check --dry-run`；
3. 执行新增 8 项、Round2 26 项以及 HR01～HR18 全量 Django/MySQL 回归；
4. 干净库实际跑 release → bootstrap_production_admin → 登录 MFA → `/ready/`；
5. 多角色真实浏览器验证组织机构→教职工主档→招聘入职→异动合同→考核职称聘任→薪酬离退→自助→数据中心；
6. HR16 真实验证 DELAY → ExitCase APPROVED → END_DELAY → RETURNED → 重新提交/批准，以及已有 handover item 时的阻断；
7. 备份、恢复、并发、外部接口、容量、安全扫描与升级/回滚演练。

这些未完成前不得把 `NOT_RELEASED` 改成生产已验收。

## 7. 本轮结论

本轮不是“旧 ZIP 改名”。生产 release 执行链、首次部署首管机制、初始化入口风险和 HR16 已批准计划的受控改期均有真实源码变更和新增测试。当前剩余阻断主要是目标 Docker/MySQL/浏览器运行环境验收，而不是把业务开发继续留成空白说明。
