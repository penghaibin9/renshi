# HR11 考勤与时间

这是 HR11 的模块入口。HR11 负责考勤规则、排班/时间事实、异常、补正和统计结果。

## 小白先看这里

- `models/`：考勤、班次、异常、补正和统计模型。
- `services/`：打卡/补正/审批/结算等写操作。
- `selectors/`：考勤明细、异常、统计查询。
- `api/`：正式 API。
- `jobs/`：周期计算、异步统计和导出。
- `policies/` / `permissions.py`：规则和权限。
- `tests/`：并发、幂等、规则边界、租户和越权测试。

## 重构硬规则

1. 原始时间事实与计算结果分离，统计可重算。
2. 补正必须留痕，不能覆盖原始事实。
3. tenant / permission / audit fail-closed。
4. 批量计算必须可重试、幂等并有失败记录。
5. 正式 API 统一 `/api/v1/hr/...`。

## 请假证明下载交互回归

办理入口为 `/hr/time/leave/` 的“审计下载证明”。当前脚本
`frontend/static/hr/js/pages/hr11-actions.js` 使用既有下载地址与
`X-HR-Access-Reason` 请求头；不增加下载接口或修改后端权限、审计和业务状态。

连续下载必须每次填写查阅事由。成功、拒绝、网络错误和响应文件读取失败后，
共用“确认办理”按钮及原下载链接必须恢复。关闭弹窗或按 Esc 只关闭操作视图，
不宣称已经撤销服务器可能记录的访问；原链接在请求完成前仍不可重复提交。
旧请求结束时不得关闭、改写提示或解锁后来打开且仍在处理的弹窗。

仓库根目录执行：

```bash
python tests/visual/hr11_download_lifecycle_tests.py -v
```

该专项加载完整生产脚本，用真实 Chromium 点击控件，覆盖桌面、手机、连续下载、
失败重试、空白事由、处理中禁用、取消/Esc 和晚到响应。HTTP 传输是明确隔离的测试替身，
不连接学校、不写人员数据；**它只证明前端控件生命周期，不能证明 MySQL、权限或审计通关**。
现有 `.github/workflows/hr-visual-audit.yml` 增加该专项步骤，原真实服务浏览器测试全部保留。
默认使用 Playwright 安装的 Chromium；本机已有 Chromium 时可通过
`HR_UI_CHROMIUM_EXECUTABLE` 指定可执行文件。

`tests/visual/hr11_visual_audit_tests.py` 的真实系统验收仍为必要条件；
逐次访问审计、双租户拒绝、文件权限和全生命周期验收不能由本专项替代。
测试截图放在工件中的 `HR11-DOWNLOAD-UI-UNIT/`，明确区别于真实学校页面截图。
本次回归依据为 PR #53 的 `eacb4318bc156b05fca15465825db40ad1b49cca`；
不因此上调全仓库生产发布结论。


## 请假计薪分类与月结证据

新发布的 `HrLeavePolicyVersion` 将假别的明确计薪分类冻结到
`interaction_rules.paidClassification`，纳入既有 `content_hash`。批准请假只从申请
引用的已发布/已退役政策版本读取该分类，随 `HrAbsenceFact.effective_snapshot`
保存版本号与哈希；不能用今天可变的假别目录重解释历史申请。

`PAID` / `UNPAID` 必须有学校已确认的政策依据；默认仍是 `POLICY_DEPENDENT`。
旧政策缺失冻结分类、旧申请无政策引用、已存在的缺勤事实均不自动改写。
分类未决的 ACTIVE 缺勤继续由 `UNRESOLVED_ABSENCE_CLASSIFICATION` 阻止月结。
已批准事实更正仍需原有受控流程，本次没有提供批量 SQL 修补或默认年休假带薪。

定向验收：`python manage.py test hr_time.tests.test_leave_paid_classification --keepdb --noinput`。
覆盖带薪/无薪月结依据、未知分类拦截、旧版本与目录变化、重复批准、跨学校/跨假别、
未发布政策和输入非法值。只以实际 MySQL 运行结果记 PASS，语法检查不是业务通过。

## 办理后刷新与月结回读（PR #53）

基线 `7f0cf53213ec24337cdc434364bcb00bfbfc0e6b` 的视觉 Run `34197073603` /
job `101967079224` 在请假批准后访问加班页时出现 `net::ERR_ABORTED`。
生产 `hr11-actions.js` 在正式写入成功后延迟刷新原页面；旧验收只等待当前文档的
`networkidle`，可能在未来的刷新尚未开始时进入下一页。不能用重复业务提交、
手工 reload、固定延时或吞掉异常来取得绿色。

本次只修验收同步并加强证据，不改生产脚本、政策、计薪分类、权限、租户或月结服务。
每个会刷新的动作，在一次真实点击前同时订阅精确 POST、同页主框架 GET 和 load 事件，
随后核验实际办理区状态。预检不刷新，单独验证 ready 和空 blockers。
调用链仍为 `workspace.html → hr11-actions.js → 原 workbench API → 原服务/事实表`。

原案例的账号、学校、日历、排班、申请与日事实前置及双尺寸页面巡检保持不变。
新增完整 POST 顺序与次数检查，并在浏览器循环停止后独立读取 MySQL：异常解决、
请假批准、加班申请批准、风险接单、月结关闭、单份缺勤/额度使用/预占释放/月结快照/
时间依据。加班申请批准不代表已经核验实际加班；该案例仍是技术管理员定位案例，
不代替跨角色 UAT、真实请假全生命周期、xlsx 或全站美化验收。

```bash
HR_VISUAL_AUDIT=1 python manage.py test tests.visual.hr11_visual_audit_tests.Hr11VisualAuditTests.test_real_browser_completes_time_fact_chain --keepdb --noinput --verbosity 2
```

原视觉工作流保留全部检查和原25项套件，新增同一案例的前置专项及早期证据上传。
专项工件 `hr11-close-*` 使用独立目录，避免后续全套运行覆盖其记录；包括日志、
成功或失败截图、`real-time-chain-seal.json`。PASS只在所有浏览器断言与数据库回读
完成后写入；失败也保存已完成的检查点。证据必须区分产品SHA、测试checkoutSHA及运行。
