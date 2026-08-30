# 窗口 2：HR04～HR06 Codex 直接施工指令

## 你是谁

你是 Renshi 六窗口并行施工的窗口 2，独立负责：

- HR04 招聘与人才引进：`hr_recruitment`
- HR05 入职管理：`hr_onboarding`
- HR06 人事异动：`hr_changes`

用户是新手。你自行审计、编码、测试、提交和追踪进度，不要求用户分配子任务、处理冲突或判断接口。不要只输出计划；立即从 P0 开始施工，并持续到三个模块各 100 分。

## 用户零操作协议

- 不得让用户安装/操作数据库、运行命令、处理 migration、Git 或冲突。
- 自行用 Docker/Compose 建隔离 MySQL；项目名 `renshi_w2`，不得复用或删除其他窗口资源。
- 自行生成未提交的本地开发 `.env`、安装容器依赖、创建测试库并执行 migration；绝不接触生产数据库。
- 浏览器验收使用专属端口 `8102`，先检查占用，不终止其他窗口进程。
- 环境失败由你诊断和修复；只有真实外部凭据或不可逆生产操作才向用户请求授权。

## 隔离施工区

源仓库：`F:\高校人事系统\renshi-ui-v2`
建议 worktree：`F:\renshi-w2-hr04-06`
分支：`codex/w2-hr04-06`

若路径/分支已存在则安全复用，禁止删除、reset 或覆盖源工作树。只主动修改 `hr_recruitment/**`、`hr_onboarding/**`、`hr_changes/**` 及三模块专属模板/静态文件/测试。不得修改上游 HR02/03/07 内部模型，不改 shared shell、settings、根 URL 和 CI；通过其 `public.py`/Provider 消费。

## 必须先修的 P0

`hr_recruitment/api/urls.py` 有 6 组同路径、不同 callback：proposed-hires、medical、background、candidates、campaigns、plans。Django 只命中第一条，部分 GET/POST 在真实 resolver 下不可达。

第一批提交必须：

1. 将同一路径收敛为单一 callback/类视图，按 HTTP method 明确分派。
2. 用 Django `resolve()` 证明每个 canonical URL 唯一可达。
3. 用 Client 覆盖 GET/POST、CSRF、permission、tenant、400/403/404/409/422。
4. 覆盖 legacy `/api/hr/v1` 到 canonical 的兼容跳转，不制造第二套写入口。
5. 建全模块重复路由回归测试，确保同类问题不再出现。

## HR04 施工队列

1. 打通年度计划、招聘项目、候选人创建入口，移除因后端不可达而禁用的按钮。
2. 封计划→岗位容量→项目→申请→资格→评审→拟录用→Offer→HR05 交接。
3. HR02 容量 `UNAVAILABLE/STALE/ERROR` 时 fail-closed，不得超批。
4. 医疗/背调读写分别可达，高敏结果按最小字段和专门权限返回。
5. 拟录用和交接支持幂等；重复点击不能生成第二个 HR05 Case。
6. 恢复被跳过的 tenant/IDOR 安全测试，不以 skip 解决约束问题。
7. 全部页面动作显示真实 409/422/403 与 requestId。

## HR05 施工队列

1. 为试用期、入职 Case、材料和任务补 tenant/scope 下单条 GET，禁止全表拉取后前端找详情。
2. 封预入职→材料→报到→协同→激活→试用→转正/终止状态机。
3. 报到时间、激活时间等正式时间由服务端规则控制，客户端只提交允许字段。
4. 交接与激活严格幂等，同 tenant 同来源不造第二人；失败恢复不复用其他 tenant 缓存。
5. HR02 容量只在 HR03 正式人员事实成功后提交；失败时保留可恢复状态。
6. 文件材料使用受控存储引用、病毒/类型/大小策略和审计。
7. 实现 Legacy onboarding writer 真冻结，并做旧数据迁移/对账。

## HR06 施工队列

1. 封创建草稿→预览→提交→审批→生效→回执→历史查询。
2. 覆盖调岗、组织变更、岗位身份、主兼职、借调/挂职、管理职务等真实动作。
3. primary switch、secondary assignment 和 manager change 不破坏原有正式事实。
4. HR02 岗位容量必须在服务层校验；并发请求不能超卖。
5. HR03 Assignment/Employment 只能经正式公共服务生效，禁止直接 update。
6. HR07 合同不被静默篡改；需要复核时形成明确回执/待办。
7. 状态机、驳回、撤回、重复 apply、下游失败重放和 wrong-tenant 全测试。

## 三模块联合 E2E

至少证明以下真实链：

```text
HR02 可用岗位
→ HR04 计划/项目/候选/评审/拟录用
→ HR05 入职 Case/报到/材料/激活
→ HR03 正式人员与任职
→ HR07 合同
→ HR06 异动生效与合同复核回执
```

必须同 tenant、同一人、容量不超卖、重放不重复、跨 tenant 全拒绝。

## 每轮执行协议

从第一个红灯开始：写失败测试→实现→模块测试→联合 E2E→真实浏览器→原子提交→重新评分。完成一个缺口立即继续下一个，不等待用户总控。

## 每模块 100 分标准

| 项目 | 分值 |
|---|---:|
| Authority/状态模型 | 15 |
| 写服务/事务/幂等/并发 | 15 |
| 查询与 HTTP API | 10 |
| tenant/权限/IDOR/高敏 | 10 |
| HR02/03/07 公共合同 | 10 |
| UI 全动作与失败状态 | 10 |
| migration/legacy/cutover | 10 |
| MySQL/E2E/浏览器证据 | 15 |
| 审计/可观测/文档 | 5 |

三个模块逐项有当前 HEAD 证据才是 100。不得以大量模型、漂亮 UI、mock-only 测试或 skip 计分。

## 提交纪律

- 分别用 `fix(hr04)`、`feat(hr05)`、`test(hr06)` 等原子提交。
- 只暂存本窗口文件，不改用户未提交 UI/shared 文件。
- 汇报：SHA、通过的命令、三模块分数、剩余 P0/P1；不把选择题交回用户。
