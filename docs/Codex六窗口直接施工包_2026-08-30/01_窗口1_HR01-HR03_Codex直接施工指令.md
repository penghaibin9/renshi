# 窗口 1：HR01～HR03 Codex 直接施工指令

## 你是谁

你是 Renshi 六窗口并行施工的窗口 1，独立负责：

- HR01 人事工作台：`hr_control_center`
- HR02 组织机构与编制岗位：`hr_structure`
- HR03 教职工主档：`hr_staff`

用户是新手，不让用户承担项目总控。你必须自行完成审计、拆任务、编码、测试、提交和进度记录。不要只给建议，不要停在文档，不要把技术选择题抛给用户。只有真实外部凭据或不可逆生产操作需要用户授权时才询问。

## 用户零操作协议

- 禁止要求用户安装 MySQL、执行命令、创建数据库、处理 migration、解决冲突或配置环境。
- 你自行使用 Docker/Compose 建立隔离开发环境；项目名使用 `renshi_w1`，避免与其他窗口容器、网络和 volume 冲突。
- `.env` 缺失时自行从 `.env.dist` 生成仅限本地的安全开发配置，不提交密钥，不读取或覆盖生产配置。
- 自行安装/修复容器内依赖、创建并授权测试库、运行 migration 和测试。不要依赖用户本机 Python 已装 `mysqlclient`。
- 浏览器服务需要端口时使用窗口专属端口 `8101`；先检查占用，不终止不属于本窗口的进程。
- 只允许清理 `renshi_w1` 自己创建的容器/临时数据；禁止删除用户现有数据库、volume 或其他窗口资源。

## 终止条件

持续施工，直到 HR01、HR02、HR03 分别达到本文件的 100 分标准。一次做不完时，保留清晰提交和下一步清单后继续下一轮，不得用“骨架完成”“页面完成”“测试文件存在”冒充 100 分。

## 第一步：建立隔离施工区

源仓库：`F:\高校人事系统\renshi-ui-v2`
建议 worktree：`F:\renshi-w1-hr01-03`
分支：`codex/w1-hr01-03`

先 `git fetch origin`，以当时最新且已推送的 UI 集成分支为基线。若 worktree/分支已存在，检查后复用，禁止删除已有目录、重置用户改动或触碰源工作树的未提交文件。

只允许主动修改：

- `hr_control_center/**`
- `hr_structure/**`
- `hr_staff/**`
- 三模块专属模板/JS/CSS/测试
- 三模块 `public.py`、Provider、migration

禁止主动修改：`horilla/settings/**`、根 URL、共享 V2 shell、`.github/workflows/**`、其他 HR 模块。确需共享修改时，在本分支增加兼容适配或记录精确接口需求，留给窗口 6 集成，不跨区顺手修改。

## 已知审计事实

- HR01 待办聚合目前主要只有 Recruitment Provider；overview 的 `todoSummary`、`alertSummary`、`quickActions` 仍不完整。
- HR02 是较成熟上游 Authority，但容量、并发预占、结构历史和 HR04/05 消费必须按真实 MySQL 再封板。
- HR03 的 `correction_service.py` 对未登记字段仍会 `NotImplementedError`；高敏更正、as-of 和 Legacy 真冻结未完全闭环。
- 新旧系统仍存在双主写风险；不能只切换读源而不阻止旧 writer。

## HR01 施工队列

1. 盘点工作台五个页面和所有 API，建立“页面动作→API→Provider→Authority”矩阵。
2. 为 HR04～HR16 建立待办 Provider 注册机制，至少先接真实可用域；单域失败不得拖垮其他域。
3. 实现统一待办分页、逾期/今日/本周口径、来源健康、稳定深链接和权限裁剪。
4. 完成 alert summary、quick actions、workforce drilldown；任何不可用来源返回 `UNAVAILABLE`，禁止 fake zero。
5. 所有聚合结果带 `asOf`、freshness、source domain、requestId；历史日期不能静默使用当前快照。
6. 补租户、权限、跨 tenant UUID、Provider 超时/异常/部分可用测试。
7. 把 UI 上每个卡片、待办和快捷动作接到真实后端；失败不能显示成功。

## HR02 施工队列

1. 复核组织、部门、岗位、编制、容量、关系与 effective-dated 历史的 Authority 所有权。
2. 封板岗位容量：预占、提交、释放、过期、重复请求、并发超卖和异常恢复。
3. 所有写服务强制 tenant/context、permission、actor、idempotency；不能依赖 API 层已过滤。
4. 完成组织/岗位 as-of 查询、结构变更历史和不可变生效版本。
5. 冻结 `hr_structure.public`：组织证据、岗位证据、容量 Provider，建立向后兼容测试。
6. 验证 HR04/HR05 消费只走公共合同，不直接写 HR02 表。
7. 完成 Legacy 投影/对账，投影失败可重放，不反向污染 Authority。

## HR03 施工队列

1. 枚举所有 correction field code，建立显式注册表、校验器和应用器，消除生产路径 `NotImplementedError`。
2. 高敏更正必须具备独立 permission、原因、证据、前后快照、双人复核和不可变审计。
3. 封 Person→Staff→Employment→Assignment 的状态机、唯一性、有效期、主兼职和历史 as-of。
4. 所有通过 ID 调用的 service 强制 tenant/context 二次约束。
5. 文件/材料使用受控引用，不把任意路径或用户输入当正式凭证。
6. 冻结 `hr_staff.public` 与 SELF 身份映射，覆盖错误 person/staff 对、跨 tenant 和历史身份。
7. 实现 Legacy writer 真冻结：冻结后旧 employee 写入被可测试地拒绝或只作为受控投影。
8. 完成导入、导出、断点重放、错误下载、敏感字段裁剪与大批量测试。

## 跨模块合同

- HR02/03 是上游，窗口 2～6 只能通过 `public.py`、Provider 或事件消费。
- 公共合同先兼容新增，禁止无迁移方案地删除字段或改变语义。
- 不直接 import 下游内部模型；HR01 只聚合，不拥有 HR02/03 真值。

## 每轮执行顺序

```text
审计当前代码与测试
→ 选择第一个 P0/P1 缺口
→ 先写失败测试
→ 实现最小完整业务链
→ 跑模块 MySQL 测试
→ 跑跨域合同测试
→ 接真实页面动作
→ 跑浏览器/安全测试
→ 原子提交
→ 更新三模块评分
→ 继续下一个缺口
```

## 每模块 100 分标准

| 项目 | 分值 | 满分证据 |
|---|---:|---|
| Authority/模型 | 15 | 真值归属、唯一约束、有效期、不可变事实完整 |
| 写服务/状态机 | 15 | 合法转换、事务、并发、幂等、回滚/重放 |
| 查询/API | 10 | current/as-of/分页/错误合同真实可用 |
| tenant/权限/SELF | 10 | wrong-tenant、IDOR、敏感字段全部 fail-closed |
| 跨模块合同 | 10 | public/Provider/Event 稳定且有兼容测试 |
| UI 真实动作 | 10 | loading/empty/partial/unavailable/error/success 全覆盖 |
| Migration/Legacy | 10 | fresh、upgrade、对账、真冻结通过 |
| 自动化证据 | 15 | MySQL 单元/集成/E2E/浏览器，无跳过红灯 |
| 可观测与文档 | 5 | requestId、审计、运行说明、无过期完成声明 |

三个模块都必须各自达到 100/100。外部系统尚无凭据时，满分要求是：生产 Provider 已实现、配置与安全路径完整、sandbox/contract 测试通过、缺凭据显式 `UNAVAILABLE`；不要求伪造外部成功。

## 提交与汇报

- 一个提交只完成一个可验收任务，提交信息带 `HR01/HR02/HR03`。
- 不使用 `git add .`，不修改或删除别的窗口文件。
- 每次汇报只给：完成任务、提交 SHA、测试命令与结果、当前三模块分数、剩余最高风险。
- 不宣称 100，除非评分表每项都有当前 HEAD 的证据。
