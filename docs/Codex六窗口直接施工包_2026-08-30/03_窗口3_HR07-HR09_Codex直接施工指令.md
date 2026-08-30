# 窗口 3：HR07～HR09 Codex 直接施工指令

## 角色与目标

你负责三个 Authority：

- HR07 合同与聘用：`hr_contracts`
- HR08 兼职外聘教师：`hr_external`
- HR09 教师资格与双师型：`hr_qualification`

用户不承担总控。你必须从真实代码出发持续施工，自己选择最高优先级缺口、写测试、实现、提交和复评，直到三个模块分别 100 分。

## 用户零操作协议

- 禁止把 MySQL、Docker、migration、测试命令、Git 或冲突交给用户。
- 自行使用 Compose 项目 `renshi_w3` 建隔离 MySQL/Redis，生成仅本地 `.env`，安装依赖并创建测试库。
- 浏览器验收使用专属端口 `8103`；不得停止或清理其他窗口资源。
- 不连接生产数据库，不删除用户数据；只有外部系统真实凭据或不可逆生产动作才询问用户。

## 隔离与所有权

建议 worktree：`F:\renshi-w3-hr07-09`
分支：`codex/w3-hr07-09`

只主动修改 `hr_contracts/**`、`hr_external/**`、`hr_qualification/**` 以及三模块专属 UI/测试/migration。不得直接修改 HR02/03/10/12 内部模型，不改 shared shell、settings、根 URL 和 CI。跨域功能通过 `public.py`、Provider、事件和回执完成。

## 已知重点

- HR07 主链存在，但签署文件凭证、版本不可变和多种合同页面仍需统一。
- HR08 协议激活链已通过，但教务/IAM、续聘、到期、终止和资源回收仍需真实 Provider。
- HR09 证据核验和评审骨架较强，必须封 HR10→HR09→HR12、撤销/续期和间接 tenant 的服务层安全。

## HR07 施工队列

1. 冻结合同/协议类型、主体、版本、签署、生效、续签、变更、解除、终止状态机。
2. 已签署/已生效版本不可原地覆盖；变更形成新版本、原因、actor、证据和 parent 链。
3. 实现受控签署文件 Provider：摘要、hash、受控引用、访问权限、留存与撤销。
4. 所有 public evidence 强制 tenant、subject、as-of；错误主体/跨 tenant 显式不可用。
5. HR06、HR08、HR17 只能通过 `hr_contracts.public` 消费，建立消费者兼容测试。
6. 合并散落页面动作与 API，清除仅前端存在、后端无合同的按钮。
7. 补到期预警、续签评审、并发签署、重复生效和 outbox 失败重放。

## HR08 施工队列

1. 封外聘候选→审批→协议要求→签署→激活→派任→续聘/终止/到期。
2. 保持三种 agreement requirement 语义，禁止把 `UNAVAILABLE` 误报为 `NOT_REQUIRED`。
3. 实现教务排课、IAM 身份、文档、通知等可配置 Provider；外部调用不持有数据库长事务。
4. Provider 支持幂等键、lease、receipt、timeout、retry 和明确失败状态。
5. 外聘人员不冒充正式 HR03 Employment；建立 canonical identity 映射和 tenant gate。
6. 到期或终止必须触发派任关闭、权限回收和下游回执，可部分失败并重放。
7. 完成真实浏览器激活/续聘/终止链和 wrong-tenant/IDOR 测试。

## HR09 施工队列

1. 封资格类别、证据、规则版本、申请、预检、评审、认定、续期、撤销、历史。
2. 所有 child model 的 service 方法显式接收 tenant/context，不能依赖 API 先过滤 parent。
3. 接 HR03 身份、HR08 外聘、HR10 发展证据；来源不可用时 fail-closed。
4. 双师认定规则支持有效期、证据版本和国家/学校口径，旧结果保持可追溯。
5. 发布 `hr_qualification.public` 给 HR12/17/18 使用，并覆盖错误 person/staff 映射。
6. 封 HR10 证据撤销/过期对 HR09 当前有效性的影响，不篡改历史快照。
7. 完成批量核验、人工复核、异议、敏感证据权限和审计。

## 必须封板的联合链

```text
HR03/HR08 身份
→ HR10 已核验证据
→ HR09 资格/双师申请与正式认定
→ HR12 证据快照消费
→ HR17 本人安全查询
```

另需证明 HR08→HR07 协议签署→HR08 激活/终止的真实回执链。

## 100 分评分

每模块：Authority 15、状态机与幂等 15、查询/API 10、tenant/权限 10、跨域合同 10、UI 动作 10、migration/legacy 10、MySQL/E2E/浏览器 15、审计/文档 5。三个模块逐项满分才结束。

外部系统没有真实账号时，必须完成生产级 Provider、配置/密钥边界、sandbox/contract test 和显式 `UNAVAILABLE`；禁止 hard-code 假回执。

## 自主施工循环与提交

每轮：审计→锁定最高风险→失败测试→实现→最小测试→模块 MySQL→联合 E2E→浏览器→提交→评分。一个提交只做一件事，只暂存本窗口文件。汇报仅包含 SHA、测试、分数和剩余风险，不要求用户做技术总控。
