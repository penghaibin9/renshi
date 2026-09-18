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

## 2026-09-09 首批施工记录（任务仍未全部验收）

基于共同F0 `678c96602cf2cc336b90131e5ae23084045d6e07`，本次仅修改 `frontend/templates/hr/onboarding/probations/detail.html` 的可见限制说明，把“暂无独立详情查询”恢复为原契约要求的“尚无单条详情查询入口”；其余模板字节不变。

这是 B-HR05-04 的局部文本契约修复。原断言的源码条件复核通过，原测试文件保持blob `08d8d5f11e90d5890ffaa5ac42d43da0e8de753d`；未执行Django/MySQL/真实浏览器。没有新建GET接口、评价读取或决定表单，B-HR05-02仍未完成，不能把限制说明当成三级详情实装。

## 2026-09-09 第二切片：试用对象只读详情与四分区

接续本分支 `67c3614aca3fda2536ab2c10f9c03ed674ea622c`，推进 B-HR05-02 的读取半段。新增受租户和学校级管理范围保护的单条GET，摘要、试用目标、评价记录、延期历史分区读取；子记录每页20条。页面改用命名GET，不再下载列表寻找单条对象。关联入职单另需 `hr05.case.view`。

新增 `tests/test_probation_detail_read.py` 含13项Django/MySQL读取用例，但当前会话没有可运行Django/MySQL，不能记PASS。隔离组件/Chromium结果只证明本地读层行为；旧 `test_v2_workspace_contract.py` 仍保留原断言，未为新增能力修改测试预期。

## 2026-09-09 第三切片：正式决定区与并发保护

从远端 `2247266bf712805f157ede23eaf0e6193a71c33b`继续。B-HR05-02 进一步接通**既有** `confirm / extend / fail` 写服务，不新建第二套状态机或决定写入器。

- 单条GET根据 `hr05.probation.finalize` 与正式状态迁移返回 `decisionCapabilities`；无权限、终局或当前状态不允许的决定不会显示为可操作。
- 详情页新增“正式试用决定”工作区，只包含转正、延期、不通过；评价仍只读。原因必须填写，延期还需新结束日，前端提交使用当前记录版本 `If-Match`。
- 三个写接口在事务内锁定当前租户试用行，再校验 `If-Match/version`；旧页面提交返回 `VERSION_CONFLICT`，不覆盖新状态。统一API客户端发送JSON，因此HR05试用写接口同时兼容JSON和原表单请求。
- 转正依据、延期原因、不通过原因改为服务端必填；每次成功返回新 `version`。延期继续复用既有 `HrProbationExtension` 历史，不覆盖旧日期；转正/不通过继续复用原case联动及outbox。
- 新增 `test_probation_decision_guards.py`，覆盖旧版本拒绝、JSON写入、必填原因、延期历史、finalize权限失败关闭。**该文件已提交但尚未在Django/MySQL环境运行，不能记PASS。**

未解决边界：现有 `submit-review` 管理写接口虽然限定 `SELF/COLLEGE/HR` 三种值，但当前权限只有 `hr05.probation.manage`，无法可靠区分本人、学院、人事三种评价身份。本切片不把一个前端下拉框当作角色授权，因此不开放评价提交。后续需与A组本人身份/学校角色事实对齐后再接三角色评价链；在此之前不得宣布B-HR05-02整项完成。

原PR53、main、A/C/D组业务文件、迁移、依赖和CI仍未修改；没有合并或部署。由于子PR目标不是main，仓库主Quality不会自动覆盖本分支，本记录不把“没有检查”写成绿色。
