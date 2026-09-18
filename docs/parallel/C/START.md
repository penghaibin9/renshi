# C_教师发展与评价聘任 · 仓库接手施工单

分支：`feat/hr-deep-c-development-20260909`。先读根 `AGENTS.md`、`../README.md` 和本组原施工包 `00_施工说明.md` 的0–6节。不要从main新建，不创建额外施工线；开工、提交前都重新核对本分支远端HEAD。

从C-HR09-01开始，先把证书对象、证据文件、核验历史、有效期完整接通，再完成双师/发展/考核/职称/聘任；HR13创建提交是否缺失须核对最新所有路由与正式服务。

## 本组逐项任务

| 任务 | 模块/目标 | 首读来源 |
|---|---|---|
| C-HR09-01 | HR09 证书台账、版本、核验与下载 | `backend/hr_qualification/services/credential_service.py:29` |
| C-HR09-02 | HR09 双师规则、批次与证据冻结 | `backend/hr_qualification/services/rule_service.py:33` |
| C-HR09-03 | HR09 申请、退回、评审与正式审定 | `backend/hr_qualification/services/final_decision_authority_service.py:8` |
| C-HR09-04 | HR09 到期风险与复核闭环 | `backend/hr_qualification/services/recheck_service.py:27` |
| C-HR10-01 | HR10 导航、对象ID及本人档案映射 | `frontend/templates/hr/development/base.html:33` |
| C-HR10-02 | HR10 培养计划、项目与报名审批 | `frontend/static/hr/js/pages/hr10-actions.js:15` |
| C-HR10-03 | HR10 实践过程、材料与正式成果 | `backend/hr10_development/services/practice_process_service.py:19` |
| C-HR10-04 | HR10 发展事实与下游复用 | `backend/hr10_development/services/development_fact_authority_service.py:14` |
| C-HR12-01 | HR12 制度、周期与人员快照 | `backend/hr_assessment/api/urls.py:10` |
| C-HR12-02 | HR12 年度链保全＋聘期/师德补强 | `frontend/static/hr/js/pages/hr12-actions.js:27` |
| C-HR12-03 | HR12 评议、评分、公示、异议 | `backend/hr_assessment/services/review_service.py:5` |
| C-HR12-04 | HR12 正式结果、修订与归档 | `backend/hr_assessment/services/finalization_service.py:13` |
| C-HR13-01 | HR13 申报源头服务与API缺口 | `backend/hr_title/api_urls.py:6` |
| C-HR13-02 | HR13 材料与资格证据链 | `backend/hr_title/services/material_service.py:13` |
| C-HR13-03 | HR13 专家、回避、票决与公示 | `backend/hr_title/services/panel_service.py:4` |
| C-HR13-04 | HR13 正式职称事实与复核修订 | `backend/hr_title/services/result_service.py:15` |
| C-HR14-01 | HR14 制度、批次、人员范围与额度 | `frontend/static/hr/js/pages/hr14-workflows.js:45` |
| C-HR14-02 | HR14 申报、资格、排序与公示 | `backend/hr_appointment/api_urls.py:95` |
| C-HR14-03 | HR14 集体决定、容量预占和生效 | `backend/hr_appointment/services/effect_service.py:243` |
| C-HR14-04 | HR14 聘期续聘、变更与档案 | `backend/hr_appointment/term_api.py:17` |

## 每项交付

原任务ID保持不变。进入当前任务时只读对应源码、上下游与原测试；追到三级对象/状态而不是反复全仓扫描。详情字段、权限、请求样例先核实，未知项保留。前端、后端、MySQL、权限、审计、xlsx、异常恢复、刷新与下一角色回读一起完成；未适用项写原因。

任务台账分别记录源码修改、隔离测试、真实页面打开、真实业务办理四种状态，不能互相代替。每次只在本组目录更新一份进度；公共合同请求交A。严禁修改其他组文件以绕过跨组问题。

原四包中的API/菜单/动作均为静态来源索引，不是全部已实装的功能合同；一级/二级/三级/页签/动作/兼容路由分开计数。设计模板仅约束视觉与便捷性。

初始状态：本表不宣称任何任务已完成。原PR53及main保持不变；不合并、不部署。
