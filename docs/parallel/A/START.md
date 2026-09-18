# A_公共底座与人员服务 · 仓库接手施工单

分支：`feat/hr-deep-a-foundation-20260909`。先读根 `AGENTS.md`、`../README.md` 和本组原施工包 `00_施工说明.md` 的0–6节。不要从main新建，不创建额外施工线；开工、提交前都重新核对本分支远端HEAD。

先复现并处理A-HR01-01及HR17来源健康度/内联样式契约；随后HR02组织岗位→HR03人员与账号→HR17本人回读→HR01待办返回链。

## 本组逐项任务

| 任务 | 模块/目标 | 首读来源 |
|---|---|---|
| A-HR01-01 | HR01 来源异常与原门禁修复 | `backend/hr_control_center/tests/test_canonical_todo_providers.py:82` |
| A-HR01-02 | HR01 待办对象定位与返回链 | `frontend/static/hr/js/pages/todos.js:6` |
| A-HR01-03 | HR01 预警与队伍结构口径 | `frontend/static/hr/js/pages/workforce.js:2` |
| A-HR01-04 | HR01 快捷办理的菜单权责 | `frontend/static/hr/js/pages/quick-actions.js:5` |
| A-HR02-01 | HR02 学校初始化与组织对象工作区 | `backend/hr_structure/services/initialization.py:67` |
| A-HR02-02 | HR02 岗位与编制的真实占用 | `backend/hr_structure/services/position.py:563` |
| A-HR02-03 | HR02 方案、目录、关系三级办理 | `frontend/static/hr/js/structure/workspace.js:1` |
| A-HR02-04 | HR02 组织重组与生效恢复 | `backend/hr_structure/services/reorganization.py:844` |
| A-HR03-01 | HR03 名册与xlsx全流程保持 | `backend/hr_staff/templates/hr_staff/staff_list.html:61` |
| A-HR03-02 | HR03 五个真实对象导航及敏感数据 | `backend/hr_staff/templates/hr_staff/profile.html:57` |
| A-HR03-03 | HR03 更正创建缺口与审批闭环 | `backend/hr_staff/templates/hr_staff/corrections.html:84` |
| A-HR03-04 | HR03 材料档案与本人账号 | `backend/hr_staff/api/materials.py:46` |
| A-HR17-01 | HR17 菜单名称、能力与当前失败 | `backend/hr_self/tests/test_ui_contract.py:52` |
| A-HR17-02 | HR17 身份关联、停用与越权 | `backend/hr_self/services/identity_service.py:57` |
| A-HR17-03 | HR17 目录与跨分支业务进度 | `backend/hr_self/services/provider_gateway.py:89` |
| A-HR17-04 | HR17 工资合同文件的敏感回读 | `backend/hr_self/services/self_records_service.py:134` |

## 每项交付

原任务ID保持不变。进入当前任务时只读对应源码、上下游与原测试；追到三级对象/状态而不是反复全仓扫描。详情字段、权限、请求样例先核实，未知项保留。前端、后端、MySQL、权限、审计、xlsx、异常恢复、刷新与下一角色回读一起完成；未适用项写原因。

任务台账分别记录源码修改、隔离测试、真实页面打开、真实业务办理四种状态，不能互相代替。每次只在本组目录更新一份进度；公共合同请求交A。严禁修改其他组文件以绕过跨组问题。

原四包中的API/菜单/动作均为静态来源索引，不是全部已实装的功能合同；一级/二级/三级/页签/动作/兼容路由分开计数。设计模板仅约束视觉与便捷性。

初始状态：本表不宣称任何任务已完成。原PR53及main保持不变；不合并、不部署。

## 2026-09-09 首批施工记录（任务仍未全部验收）

基于共同F0 `678c96602cf2cc336b90131e5ae23084045d6e07`，本次只提交3个生产文件与1个补充脚本：HR01概览UNAVAILABLE/ERROR使用原契约的显式分支；HR17恢复可见“业务来源健康度”，把原内联CSS逐字迁入既有样式文件，并同步资源版本。

这是 A-HR01-01 / A-HR17-01 的局部契约修复，不是新增详情、身份关联或来源业务能力。HR01异常逻辑原本已经存在，显式条件改写前后16项隔离脚本测试均通过；本次不宣称修复了此前不存在的运行错误。

已执行：`node --test tests/parallel/A/hr01_source_health.cjs`，16/16 PASS；`node --check frontend/static/hr/js/pages/todos.js` PASS。HR17实际工具栏子树的隔离Chromium检查覆盖320/390/768/1440宽度及普通/forced-colors状态，8组前后computed-style一致。原HR01/HR17失败方法涉及的源码条件复核通过，原测试文件保持原blob。首次默认浏览器路径缺失，改用环境既有`/usr/bin/chromium`后通过，未增加项目依赖。

未执行：Django模板/路由运行、真实MySQL、多角色/双租户业务验收、xlsx业务回归及新提交完整CI。本地使用经Git blob核对的相关文件，并非完整最新运行仓库；隔离响应不得作为服务端授权证明。原PR53、main、接口、权限、迁移与CI未修改。

下一切片：先在本分支完成原MySQL定向回归，再推进 A-HR01-02 待办对象定位与返回链；共享壳改造仍须核对生效模板与真实截图。B组试用详情的旧失败不在A分支修复范围内。
