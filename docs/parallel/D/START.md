# D_时间薪酬离校与数据验收 · 仓库接手施工单

分支：`feat/hr-deep-d-operations-20260909`。先读根 `AGENTS.md`、`../README.md` 和本组原施工包 `00_施工说明.md` 的0–6节。不要从main新建，不创建额外施工线；开工、提交前都重新核对本分支远端HEAD。

从D-HR11-01开始，接通校历、排班、异常详情，再完成请假/月结→正式薪酬→离校→数据报送；只消费上游正式事实，不反写HR02/HR03/HR07。

## 本组逐项任务

| 任务 | 模块/目标 | 首读来源 |
|---|---|---|
| D-HR11-01 | HR11 日历、排班与异常详情 | `backend/hr_time/api/workbench.py:640` |
| D-HR11-02 | HR11 请假、证明、销假和余额 | `backend/hr_time/api/workbench.py:428` |
| D-HR11-03 | HR11 加班、调休与正式工时 | `backend/hr_time/api/urls.py:30` |
| D-HR11-04 | HR11 月结、修正与HR15交接 | `backend/hr_time/api/workbench.py:817` |
| D-HR15-01 | HR15 薪酬档案、规则、津补贴与社保 | `backend/hr_payroll/services/compensation_change_service.py:26` |
| D-HR15-02 | HR15 冻结输入、试算与复核 | `backend/hr_payroll/services/calculation_service.py:800` |
| D-HR15-03 | HR15 最终封板、支付回执与工资条 | `backend/hr_payroll/services/payment_service.py:305` |
| D-HR15-04 | HR15 调账、历史接管与可售验收 | `backend/hr_payroll/services/adjustment_service.py:11` |
| D-HR16-01 | HR16 离校类型、申请与退休预审 | `backend/hr_exit/services/retirement_policy_service.py:8` |
| D-HR16-02 | HR16 工作交接、证明材料与结算 | `backend/hr_exit/services/handover_service.py:4` |
| D-HR16-03 | HR16 跨域生效、重试和正式离校 | `backend/hr_exit/services/participant_service.py:14` |
| D-HR16-04 | HR16 退休事实、档案收发与纠错 | `backend/hr_exit/services/archive_transfer_service.py:21` |
| D-HR18-01 | HR18 指标、范围与历史时点对象 | `backend/hr_data/views.py:31` |
| D-HR18-02 | HR18 数据质量问题处置 | `backend/hr_data/services/quality_finding_service.py:14` |
| D-HR18-03 | HR18 交换、报送、回执与更正 | `backend/hr_data/services/submission_service.py:18` |
| D-HR18-04 | HR18 全系统集成与可用性总验收 | `backend/hr_data/services/source_gate.py:11` |

## 每项交付

原任务ID保持不变。进入当前任务时只读对应源码、上下游与原测试；追到三级对象/状态而不是反复全仓扫描。详情字段、权限、请求样例先核实，未知项保留。前端、后端、MySQL、权限、审计、xlsx、异常恢复、刷新与下一角色回读一起完成；未适用项写原因。

任务台账分别记录源码修改、隔离测试、真实页面打开、真实业务办理四种状态，不能互相代替。每次只在本组目录更新一份进度；公共合同请求交A。严禁修改其他组文件以绕过跨组问题。

原四包中的API/菜单/动作均为静态来源索引，不是全部已实装的功能合同；一级/二级/三级/页签/动作/兼容路由分开计数。设计模板仅约束视觉与便捷性。

初始状态：本表不宣称任何任务已完成。原PR53及main保持不变；不合并、不部署。
