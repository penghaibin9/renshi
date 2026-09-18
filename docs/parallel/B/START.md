# B_招聘入职与聘用异动 · 仓库接手施工单

分支：`feat/hr-deep-b-lifecycle-20260909`。先读根 `AGENTS.md`、`../README.md` 和本组原施工包 `00_施工说明.md` 的0–6节。不要从main新建，不创建额外施工线；开工、提交前都重新核对本分支远端HEAD。

先复核HR05试用详情的已知契约红灯；再从B-HR04-01进入招聘→入职激活→合同与异动。试用详情GET须另做租户、对象范围、评价/决定回读合同，不能只改限制文案声称功能已完成。

## 本组逐项任务

| 任务 | 模块/目标 | 首读来源 |
|---|---|---|
| B-HR04-01 | HR04 计划、招聘项目、岗位三级对象 | `backend/hr_recruitment/api/plan.py:200` |
| B-HR04-02 | HR04 候选人资料与资格补正 | `frontend/static/hr/js/pages/recruitment-qualification.js:2` |
| B-HR04-03 | HR04 评分、公示、Offer与正式交接 | `backend/hr_recruitment/api/assessment.py:363` |
| B-HR04-04 | HR04 公开招聘与导入导出 | `frontend/templates/hr/recruitment/portal/campaign.html:60` |
| B-HR05-01 | HR05 协同任务真实开始/完成/豁免 | `frontend/templates/hr/onboarding/collaboration/center.html:24` |
| B-HR05-02 | HR05 试用详情GET、评价与决定 | `frontend/static/hr/js/pages/hr05-probation-detail.js:8` |
| B-HR05-03 | HR05 材料与报到—激活闭环 | `backend/hr_onboarding/api/views.py:182` |
| B-HR05-04 | HR05 试用旧断言与同链附件回归 | `backend/hr_onboarding/tests/test_v2_workspace_contract.py:101` |
| B-HR06-01 | HR06 按真实异动类型组织三级办理 | `backend/hr_changes/views.py:133` |
| B-HR06-02 | HR06 影响预览不是正式生效 | `backend/hr_changes/services/impact_service.py:22` |
| B-HR06-03 | HR06 定时生效、失败重试与回退 | `backend/hr_changes/services/apply_service.py:55` |
| B-HR06-04 | HR06 异动台账与批量办理 | `backend/hr_changes/services/bulk_service.py:24` |
| B-HR07-01 | HR07 合同对象与正文版本导航 | `backend/hr_contracts/templates/hr_contracts/workspace.html:14` |
| B-HR07-02 | HR07 签订与回执一致性 | `backend/hr_contracts/services/agreement_service.py:4` |
| B-HR07-03 | HR07 变更、解除、续签与修订 | `backend/hr_contracts/services/lifecycle_service.py:31` |
| B-HR07-04 | HR07 合同文件与授权xlsx | `backend/hr_contracts/services/document_ticket.py:17` |
| B-HR08-01 | HR08 外聘对象三级导航归一 | `backend/hr_external/views.py:120` |
| B-HR08-02 | HR08 审批与HR07协议确认 | `backend/hr_external/api/wb_agreement.py:15` |
| B-HR08-03 | HR08 任务履约与结算交付 | `backend/hr_external/api/urls.py:16` |
| B-HR08-04 | HR08 续聘与退出 | `backend/hr_external/templates/hr_external/renewals_home.html:1` |

## 每项交付

原任务ID保持不变。进入当前任务时只读对应源码、上下游与原测试；追到三级对象/状态而不是反复全仓扫描。详情字段、权限、请求样例先核实，未知项保留。前端、后端、MySQL、权限、审计、xlsx、异常恢复、刷新与下一角色回读一起完成；未适用项写原因。

任务台账分别记录源码修改、隔离测试、真实页面打开、真实业务办理四种状态，不能互相代替。每次只在本组目录更新一份进度；公共合同请求交A。严禁修改其他组文件以绕过跨组问题。

原四包中的API/菜单/动作均为静态来源索引，不是全部已实装的功能合同；一级/二级/三级/页签/动作/兼容路由分开计数。设计模板仅约束视觉与便捷性。

初始状态：本表不宣称任何任务已完成。原PR53及main保持不变；不合并、不部署。
