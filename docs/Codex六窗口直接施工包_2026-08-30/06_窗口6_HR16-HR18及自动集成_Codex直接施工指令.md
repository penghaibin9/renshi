# 窗口 6：HR16～HR18与自动集成 Codex 直接施工指令

## 你的双重职责

你负责业务模块：

- HR16 退休与离校：`hr_exit`
- HR17 教职工服务：`hr_self`
- HR18 人事数据中心：`hr_data`

你同时是六窗口的自动集成代理。用户是新手，不承担合并、冲突、CI 或发布总控。你必须在不覆盖其他窗口改动的前提下，自行维护共享运行时、质量门禁和最终集成分支。

## 用户零操作协议

- 用户不负责数据库、Docker、migration、测试、分支、冲突、CI、合并顺序或发布技术判断；禁止把这些工作交回用户。
- 自行使用 Compose 项目 `renshi_w6` 建隔离 MySQL/Redis，准备本地 `.env`、依赖、测试库、migration 与恢复演练。
- 集成浏览器服务使用专属端口 `8106`；只能清理本窗口创建的资源，不得删除其他窗口容器/volume。
- 自行诊断环境和合并失败；禁止接触生产数据库或真实用户数据。只有外部凭据、生产发布和不可逆操作需要用户明确授权。
- 最终只向用户报告业务完成度、已通过证据和必须由业务方提供的外部条件，不要求用户执行技术步骤。

## 施工区与所有权

建议 worktree：`F:\renshi-w6-hr16-18`
分支：`codex/w6-hr16-18-integration`

你可修改：

- `hr_exit/**`、`hr_self/**`、`hr_data/**`
- `horilla/settings/**`、`horilla/config.py`、`horilla_ldap/apps.py`
- 根 URL/canonical 路由注册与共享 registry
- `.github/workflows/**`、`Makefile`、依赖锁定、Docker/Compose、质量脚本
- 共享 V2 shell，但仅在兼容所有 18 模块且有回归时修改

禁止直接改窗口 1～5 模块内部业务代码。发现其红灯时记录精确失败并把修复留在所属分支；集成冲突按 Authority 所有权解决，不要求用户判断。

## 开工先保护现有 UI 收尾

源工作树可能含 HR18、header/index、shared shell 的未提交 UI 改动。先只读检查并保存 diff/文件清单，禁止 reset、checkout 或删除。只吸收明确属于 HR16～18 或共享基座且测试可证明的改动；不确定所有权时保留源文件不动。

## 共享运行时 P0

1. 修 `DB_ENGINE=mysql` 路径遗留 SQLite `OPTIONS.timeout` 的问题；按数据库 engine 重建 OPTIONS，并加 settings 测试。
2. 把 `horilla_ldap` 从 AppConfig.ready() 的数据库查询/动态根 URL 修改改成延迟、显式、失败可观测的加载。
3. 修 GBK/Windows 控制台 Unicode 日志问题，不让警告字符导致管理命令二次失败。
4. 强化 `hr_authority_gate`：逐模块 permission/event/provider/API/migration 检查、重复 URL 检查、真实 cutover 检查；禁止全局有几条记录就 `COMPLETE`。
5. 建 canonical URL 唯一性 Gate，验证窗口 2 的 HR04 路由修复。
6. 统一本地与 CI 的 MySQL test DB provision；修 `Makefile test-hr` 漏 HR07、pytest 未声明/未收集、HR03 E2E 0 tests。
7. 修 workflow/Dependabot 旧分支触发，封存自动写旧分支流程。
8. 把 HR07/HR08 纳入视觉 paths/执行，console error 设为失败，渐进加入 coverage、Ruff、ESLint、Stylelint、axe、Firefox smoke。
9. 在 CI 解析并启动验证 `docker-compose.prod.yml`，清理 PostgreSQL 遗留端口和文档，固定关键依赖版本。

## HR16 施工队列

1. 封离退申请→审批→交接→结算→生效→退休/离校事实→归档。
2. 完成退休政策、日期预检、特殊情形与可解释决策，不由前端猜测。
3. Saga 参与方覆盖 HR03、HR07、HR14、HR15、IAM、资产、财务、档案；每个都有 lease、idempotency、receipt、retry。
4. 外部调用在事务外；部分成功可见，旧 worker 不能覆盖新 lease。
5. IAM/资产/财务/档案无凭据时实现生产 Provider + sandbox test + 显式 `UNAVAILABLE`。
6. 完成交接文件、豁免证据、最终结算、权限回收、失败重放和浏览器链。

## HR17 施工队列

1. 默认要求 HR03～HR16 共 14 域；补齐缺失 HR04/05/06/08/11 Provider。
2. 实现统一待办、办理进度和本人文件，不再显示“暂未开放”。
3. SELF 身份只由登录用户→Employee→HR03 canonical staff 解析，拒绝任意 person/staff 参数。
4. 工资条、合同、考核、职称、聘任、离退等按来源健康独立聚合，单域失败不拖垮全页。
5. 本人文件使用受控下载、字段裁剪、水印/审计；IDOR 和跨 tenant 全拒绝。
6. 服务目录、收藏、搜索和深链接使用真实 permission/capability，不展示不可执行动作。
7. 完成多角色、手机端、a11y、Provider timeout、partial/stale 和真实浏览器测试。

## HR18 施工队列

1. 完成通用指标表达式引擎：白名单字段/运算、版本、population、dimension、as-of、来源证据和可解释结果。
2. 保留已有 bounded COUNT，扩展时禁止任意 eval/SQL；Provider 不可用不能产生业务值。
3. 完成数据质量规则执行、finding 生命周期、复核、整改证据和重跑对账。
4. 实现异步 exchange：数据集版本、目标映射、任务、传输、重试、回执、对账、失败队列。
5. 实现 correction workflow：保留原快照、创建修订链、审批、重新报送和新回执。
6. 完成 Legacy 报表接管：口径映射、双跑、差异、切换、真冻结和历史 as-of。
7. 报送敏感数据执行字段最小化、加密/签名、权限、审计、留存和删除策略。
8. 接 HR02～HR17 正式 Provider，做来源缺失、错误 tenant、过期、冲突和大数据量测试。

## 自动集成协议

1. 持续检查本地分支 `codex/w1-hr01-03` ～ `codex/w5-hr13-15`，只集成已有原子提交，不读取或提交其他 worktree 的未提交文件。
2. 固定顺序合并：W1→W2→W3→W4→W5；每次合并后跑结构、migration drift、受影响模块测试和跨域合同。
3. 冲突时：模型/服务归 Authority 窗口；共享 registry/CI 归本窗口；消费者使用兼容适配。禁止简单选择 ours/theirs 覆盖业务语义。
4. 任一分支红灯时，不在集成分支替它改业务；保留失败证据，继续集成其他独立绿提交。
5. 每个集成批次完成后运行：fresh MySQL、previous baseline upgrade、全量注册 HR tests、真实浏览器、视觉审计、Docker/恢复、生产 Compose smoke。
6. 只有六窗口全部模块评分满分且所有门禁全绿，才生成候选合并提交；未经用户明确授权不直接合并远程 `main`。

## 每模块 100 分标准

HR16、17、18 分别按：Authority 15、写服务/状态机 15、查询/API 10、安全 10、跨域合同 10、UI 10、migration/legacy 10、MySQL/E2E/浏览器 15、审计/文档 5。

另外集成线必须满足：18 模块结构 100%、逐模块 registry 100%、路由唯一 100%、测试被真实收集 100%、7+ 远程门禁全绿、生产 Compose/恢复通过。任何 P0/P1、placeholder、假绿 Gate、未提交共享改动或跳过测试都会阻止最终 100。

## 自主执行与汇报

优先修共享运行时 P0，同时推进 HR16～18；定期吸收其他窗口绿提交。不要让用户判断冲突或安排顺序。每轮汇报：本窗口 SHA、已集成的其他窗口 SHA、测试结果、HR16～18 分数、全系统剩余阻塞。没有授权不得 push/merge `main`，但本地分支内的正常提交和集成由你自行完成。
