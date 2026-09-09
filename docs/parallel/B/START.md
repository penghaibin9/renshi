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

下一切片：核对试用模型/权限/正式服务/评价历史，设计受租户、对象范围保护的单条详情读取，再联接页面与真实正负用例；在新能力实际完成时同步修订限制说明与相应契约，不保留失真的“无入口”提示。原PR53、main、A组文件、后端、状态机、数据库和CI均未修改。


## 2026-09-09 第二切片：试用对象只读详情与四分区

接续本分支 `67c3614aca3fda2536ab2c10f9c03ed674ea622c`，推进 B-HR05-02 的读取半段；不是整项完成，也不修改其他三组、集成母线或 main。采用选定学院蓝的清晰对象、少说明和分区布局；不复制设计稿中的样例业务数据。

**实际调用链**：现有 `hr05-probation-detail` 页面 → 生效模板 `frontend/templates/hr/onboarding/probations/detail.html` → `hr05-probation-detail.js` → 命名 GET `hr05-api-probation-detail` → 模块原 URLconf / 既有 canonical adapter → 新 `api/probation_detail.py` → 现有 `make_hr05_context` / `hr05.probation.manage` → `HrProbationCase` 及其 Goal、Review、Extension。对外唯一新接口为 `/api/v1/hr/onboarding/probations/<uuid>`；原适配器内部的 `api/hr/v1/` 声明保持原注册约定，不增全局路由实现。

**本次能力**：摘要、试用目标、评价记录、延期历史四个只读分区；摘要只取一条对象，其他分区每页20条、最多读取21条判断下一页。父记录和子记录均限定服务端选定学校及对象，异常跨校父关联拒绝；不存在和异校对象统一404。沿用原管理权限与学校成员校验，对非学校级查询范围明确拒绝而非静默扩大；没有增加本人/学院读取授权。没有新状态机、模型、迁移或正式写入。关联入职单入口另需原 `hr05.case.view`。

**前端一致性**：不再下载全量试用列表寻找单条记录；命名地址由Django提供。切分区立即清除旧对象内容，迟到成功/失败不覆盖当前分区；分页与刷新保留当前条件和焦点。真实空记录、读取失败、403、404和格式不匹配分开。动态内容转义；旧意见不冒充正式决定，目标的证据要求不冒充已完成。保留返回列表、原模块导航，手机长文本换行，键盘手动激活页签。

**实际验证**：15项Python组件隔离检查、15项Chromium隔离检查通过；JS与三个Python文件语法检查通过。Python隔离检查使用查询替身，不是Django ORM。浏览器使用实际模板适配/实际页面JS及API客户端、内存DOM和合成fetch/空cookie；无网络、登录或数据库验收。六种宽度320/390/540/768/1024/1440通过边界检查。初次本地HTTP导航被浏览器策略拒绝，未放宽策略；内存检查初次发现320px根节点6px溢出，已修复作用域内box-sizing。重复读取测试改用原生键盘Enter触发正在忙的按钮，保留请求次数断言，未强制点击或改产品门禁。所有失败与最终日志保留在会话增量证据包。

**保留的阻断**：新增 `tests/test_probation_detail_read.py` 含13项待运行Django/MySQL用例（实际ORM、权限前置、双租户、成员拒绝、分页和只读）；当前环境缺Django/MySQL，运行尝试在导入阶段失败，不能记PASS。该测试中请求用户/成员解析为明确的测试替身，仍不代替真实多角色与会话验收。原 `test_v2_workspace_contract.py` 字节未改；其“尚无单条详情查询入口”静态断言与新增能力冲突，原方法独立源码复跑确实失败，**作为B-HR05-04未通过保留**。没有藏入失真的旧文案或删除/放宽断言制造全绿。须先取得新能力真实运行证据，再由正常契约评审处理该历史断言。

**下一切片**：使用锁定Python3.12、依赖及隔离MySQL运行新增读取用例和原HR05回归；真实管理员/无权用户/异校用户验证刷新、分页及历史。随后核对评价提交和正式决定的角色、对象范围、乐观锁、幂等及审计，再接原服务的写表单。当前页面明确只读，评价提交、转正、延期、不通过均未签收；本次无xlsx与附件写入，原导入导出与下载链未改、尚待同链回归。子PR目标非main导致现有Quality不触发的缺口仍在，未改CI、未转main、未合并或部署。
