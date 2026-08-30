# 窗口 4：HR10～HR12 Codex 直接施工指令

## 角色

你独立负责：

- HR10 培训进修与企业实践：`hr10_development`
- HR11 考勤与请假：`hr_time`
- HR12 年度与聘期考核：`hr_assessment`

用户是新手，不承担总控。你不得只写分析或路线图；必须持续实现真实后端、页面动作、跨模块合同和测试，直到三个模块各 100 分。

## 用户零操作协议

- 不要求用户安装数据库、创建测试库、执行脚本、处理 migration、Git 或分支冲突。
- 自行使用 Compose 项目 `renshi_w4` 建隔离 MySQL/Redis，准备本地 `.env`、依赖、测试库和迁移。
- 浏览器验收使用专属端口 `8104`；只能清理本窗口资源。
- 环境问题自行诊断；禁止接触生产数据库。只有外部凭据或不可逆生产操作才向用户请求授权。

## 施工隔离

建议 worktree：`F:\renshi-w4-hr10-12`
分支：`codex/w4-hr10-12`

只主动修改 `hr10_development/**`、`hr_time/**`、`hr_assessment/**` 及三模块专属模板/JS/CSS/测试/migration。不得直接写 HR03/07/08/09/15 内部模型，不改 settings、根 URL、shared shell 和 CI。

## 审计起点

- HR10 有 Excel parsing placeholder，并存在 Finance/Academic/Research/Agreement/Document/Notification/EducationWriteback/Assessment/ExternalTeacher 等 Stub Provider。
- HR11 时间与月结基础较强，但必须形成 HR15 可消费的不可变输入快照。
- HR12 年度考核链已绿；聘期、师德、异议/修订、外部证据和 Legacy 真冻结未完成。模型很多不代表 API/交易闭环完整。

## HR10 施工队列

1. 替换 `import_worker.py` placeholder：受控文件存储、真实 Excel 解析、模板版本、逐行校验、错误文件、断点与幂等重放。
2. 逐个替换可由仓内 Authority 接通的 Stub：HR03、HR07、HR08、HR09、HR12；外部学术/科研/财务使用生产 Provider 接口与 sandbox 合同。
3. 封发展计划→项目→班次→报名→审批→过程→完成→证据→正式 Development Fact。
4. 封企业实践项目、岗位场景、派出、过程记录、成果与返校核验。
5. 证据必须有来源、hash、核验状态、有效期、撤销和访问权限。
6. 失败 Provider 显式 `UNAVAILABLE/PARTIAL/STALE`，不得把缺证据当 0。
7. 完成 HR09/HR12 消费合同、通知 outbox、批量性能和浏览器链。

## HR11 施工队列

1. 冻结班次、排班、打卡、请假、调班、加班、异常、补卡和月结的 Authority。
2. Eligibility Resolver 对 HR03 身份/任职不可用时 fail-closed；所有服务强制 tenant/context。
3. 封请假余额、审批、冲销、跨期、时区、夜班和法定规则边界。
4. 月结生成不可变输入快照：规则版本、人员范围、时间事实、异常、hash、as-of、封板 actor。
5. 发布 `hr_time.public` 给 HR12/15/17/18；封板后补卡只能形成调整/重开流程。
6. 覆盖并发月结、重复月结、Provider 故障、跨 tenant、SELF 和敏感位置数据。
7. 打通 HR11→HR15 的真实 E2E，不在 HR15 内重新计算考勤真值。

## HR12 施工队列

1. 保留已绿年度链，扩展聘期考核、师德 Gate、异议、复核、归档、修订和通知。
2. 证据策略驱动：HR09/10/11 等 Provider 独立读取、限时、快照；单源故障不无限等待。
3. 正式结果不可变，修订生成新版本和 parent 链；不得直接覆盖历史档次。
4. 所有 child/service 裸 ID 路径增加 tenant/context 二次校验。
5. 完成学术、科研、师德等生产 Provider 合同；无外部凭据时显式不可用并有 sandbox test。
6. 发布 `hr_assessment.public` 给 HR13/14/17/18，覆盖错误身份和 as-of。
7. 实现 Legacy PMS writer 真冻结；冻结命令必须实际阻止旧写，而不是只设置 cache key。
8. 完成年度+聘期真实浏览器、失败注入、恢复、migration upgrade 和数据对账。

## 三模块联合链

必须证明：

```text
HR10 发展/实践证据
→ HR09 正式资格
→ HR12 年度/聘期证据快照与结果

HR11 不可变月结快照
→ HR12 时间证据
→ HR15 工资输入
```

本窗口不能直接修改 HR09/15；通过公共合同和 consumer contract tests 证明接口。

## 100 分标准

每模块按以下评分：Authority 15；写服务/状态机/幂等 15；查询/API 10；tenant/权限 10；跨模块合同 10；UI 真实动作 10；migration/legacy 10；MySQL/E2E/浏览器 15；审计/文档 5。

任何 placeholder、生产路径 Stub、未收集测试、skip 红灯、假 success、未真实冻结的 Legacy writer 都会阻止 100 分。

## 执行与提交

自主循环：先审计和复现→失败测试→实现→模块 MySQL→合同 E2E→浏览器→原子提交→复评。一次只提交一个模块的一项能力，禁止 `git add .`。不向用户索要日常调度；汇报 SHA、测试结果、三模块分数和剩余最高风险后继续。
