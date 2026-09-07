# HR01 人事工作台

这是 HR01 的模块入口。HR01 只做聚合、待办和风险展示，不成为人员、组织、合同、考勤等业务事实的最终权威。

## 小白先看这里

- `api/`：对外 API。
- `services/`：工作台业务编排，不直接改其他模块事实。
- `selectors/`：查询和聚合数据。
- `providers/`：从其他 HR 模块读取标准化数据。
- `models.py`：仅保存 HR01 自己的投影/配置数据。
- `permissions.py`：HR01 权限。
- `templates/` / `views/`：管理端页面。
- `tests/`：模块验收测试。

## 重构硬规则

1. 正式 API 使用 `/api/v1/hr/...`。
2. 跨模块数据只通过 Provider / Service / 事件读取或驱动，不直接写其他模块表。
3. 所有学校数据必须 tenant fail-closed。
4. Dashboard 展示结果可以重算，不能反向成为业务事实。
5. 旧入口保留兼容适配时必须明确标注 Legacy。

## 队伍结构：从加载态到可核对结果（PR #53）

适用 HRP-01 / HRP-06 / HRP-12，入口 `/hr/workforce`。本页只读已有正式接口：
`/api/v1/hr/home/workforce/summary` 与 `/api/v1/hr/home/workforce/distribution`。
调用链为 `workforce.html → workforce.js → 现有 API views → WorkforceService → WorkforceSelector → 原有 Provider`。
不新增路由、权限、人员表或统计口径，不修改任何业务事实。

在基线 `25c8c0acbd180acb47d0c63051beca959fb69cc6` 的实际 Chromium 产物中，
桌面与手机均停留在分布图加载态。原因是页面以 `loading` 引入的图表组件不输出
脚本目标容器，空 tabs 参数也不输出维度导航；脚本找不到节点后静默返回。
基线工件为 Run `34159665429` / artifact `10032793165`，检出 SHA
`3df7c7ce834089409c3bddccdb9c80b4b1125fd8`。不能将该运行的绿色结果解释为逐页完工。

本次以页面自有的稳定挂载容器解决加载死角；保留三个规模指标、全部来源与缺项说明，
五种分布均可独立读取、切换和重试。响应晚到不能覆盖新维度；切换后不保留旧分布冒充新结果。
表格与相对人数条形同时呈现，小样本 `<5` 不转换成零、不绘制推断条形、不推算隐藏占比。
服务端标签与错误说明按文本转义，缺失、过期和读取异常有明确状态，不补成假零。

页面样式仅作用于 `.hr-workforce`，沿用既有共享主题；手机继续使用既有窄栏导航，
标题、三个指标、维度按钮和表格各自可读。没有新增导入导出，xlsx 业务功能本切片为 N/A。

验证命令：

```bash
python tests/visual/hr_workforce_ui_contract_tests.py -v
HR_VISUAL_AUDIT=1 python manage.py test tests.visual.hr_workforce_visual_audit_tests.HrWorkforceVisualAuditTests --keepdb --noinput --verbosity 2
```

前者是生产 HTML/CSS/JS 的隔离 DOM、Cookie 与 HTTP 回归，不证明权限或 MySQL；
后者使用真实登录表单、真实服务和 MySQL，按响应逐项回读五维分布、刷新、桌面/手机布局，
并以普通无权限账号验证页面与两个接口均拒绝。均已添加至原视觉工作流，原门禁保留。
截图与逐次请求记录在 `HR01-WORKFORCE/`；合成身份仅用于隔离验收。
本切片不能替代全生命周期、多角色办结和全部详情页验收，最终证据以新提交运行结果为准。
