# V16 UI A → V15 路由 / 菜单对接矩阵

本文件把上传的“方案 A”离线 UI 设计与 V15 唯一源码基线逐项对照。设计稿中的样例数据和离线交互不作为生产实现；生产页面继续使用 V15 的权限、服务、API、状态机和审计。

- 一级模块：18
- 设计稿登记二级菜单：98
- 设计稿登记页面：138
- 设计审计登记管理路由：154
- V15 当前二级菜单缺后端路由：0
- 非菜单差异：设计审计中的 HR02 `initial-setup` 旧入口在 V15 已不存在，本轮不回加旧路由。
- 公开招聘：`/recruit/<str:token>` 独立保留并同步 UI A 视觉。

| 模块 | 序号 | UI 菜单 | 原菜单名 | 目标地址 | 条件入口 | V15 对接 |
|---|---:|---|---|---|---|---|
| HR01 人事工作台 | 01 | 人事总览 | 人事总览 | `/hr/overview` | 否 | PASS |
| HR01 人事工作台 | 02 | 我的待办 | 我的待办 | `/hr/todos` | 否 | PASS |
| HR01 人事工作台 | 03 | 人事预警 | 人事预警 | `/hr/alerts` | 否 | PASS |
| HR01 人事工作台 | 04 | 队伍结构 | 队伍结构 | `/hr/workforce` | 否 | PASS |
| HR01 人事工作台 | 05 | 快捷办理 | 快捷办理 | `/hr/actions` | 否 | PASS |
| HR02 组织岗位 | 01 | 组织机构 | 组织机构 | `/hr/structure/organizations` | 否 | PASS |
| HR02 组织岗位 | 02 | 党政与业务关系 | 党政与业务关系 | `/hr/structure/relations` | 否 | PASS |
| HR02 组织岗位 | 03 | 编制方案 | 编制方案 | `/hr/structure/staffing-plans` | 否 | PASS |
| HR02 组织岗位 | 04 | 岗位目录 | 岗位目录 | `/hr/structure/post-catalogs` | 否 | PASS |
| HR02 组织岗位 | 05 | 岗位编制台账 | 岗位编制台账 | `/hr/structure/positions` | 否 | PASS |
| HR02 组织岗位 | 06 | 组织岗位历史 | 组织岗位历史 | `/hr/structure/history` | 否 | PASS |
| HR03 教职工主档 | 01 | 教职工名册 | 教职工名册 | `/hr/staff/` | 否 | PASS |
| HR03 教职工主档 | 02 | 数据质量 | 数据质量 | `/hr/staff/data-quality/` | 否 | PASS |
| HR04 招聘管理 | 01 | 年度用人计划 | 年度用人计划 | `/hr/recruitment/plans` | 否 | PASS |
| HR04 招聘管理 | 02 | 招聘项目与岗位 | 招聘项目与岗位 | `/hr/recruitment/campaigns` | 否 | PASS |
| HR04 招聘管理 | 03 | 人才库与应聘者 | 人才库与应聘者 | `/hr/recruitment/candidates` | 否 | PASS |
| HR04 招聘管理 | 04 | 资格审查 | 资格审查 | `/hr/recruitment/qualification` | 否 | PASS |
| HR04 招聘管理 | 05 | 考试面试与考察 | 考试面试与考察 | `/hr/recruitment/assessment` | 否 | PASS |
| HR04 招聘管理 | 06 | 录用与人才引进 | 录用与人才引进 | `/hr/recruitment/proposed-hires` | 否 | PASS |
| HR05 入职管理 | 01 | 待报到人员 | 待报到人员 | `/hr/onboarding/prehires` | 否 | PASS |
| HR05 入职管理 | 02 | 报到登记 | 报到登记 | `/hr/onboarding/reporting` | 否 | PASS |
| HR05 入职管理 | 03 | 材料核验 | 材料核验 | `/hr/onboarding/materials` | 否 | PASS |
| HR05 入职管理 | 04 | 协同任务 | 协同任务 | `/hr/onboarding/collaboration` | 否 | PASS |
| HR05 入职管理 | 05 | 试用与转正 | 试用与转正 | `/hr/onboarding/probations` | 否 | PASS |
| HR06 人事异动 | 01 | 异动申请 | 异动申请中心 | `/hr/changes/` | 否 | PASS |
| HR06 人事异动 | 02 | 校内调动 | 校内调动 | `/hr/changes/transfers` | 否 | PASS |
| HR06 人事异动 | 03 | 岗位与身份变更 | 岗位与身份变更 | `/hr/changes/job-identity` | 否 | PASS |
| HR06 人事异动 | 04 | 借调挂职 | 借调挂职管理 | `/hr/changes/secondments` | 否 | PASS |
| HR06 人事异动 | 05 | 异动台账 | 异动台账 | `/hr/changes/ledger` | 否 | PASS |
| HR07 合同管理 | 01 | 合同台账 | 合同台账 | `/hr/contracts/` | 否 | PASS |
| HR07 合同管理 | 02 | 合同模板与规则 | 合同模板与规则 | `/hr/contracts/rules/` | 否 | PASS |
| HR07 合同管理 | 03 | 签订与续签 | 签订与续签 | `/hr/contracts/signing/` | 否 | PASS |
| HR07 合同管理 | 04 | 变更与解除 | 变更与解除 | `/hr/contracts/changes/` | 否 | PASS |
| HR07 合同管理 | 05 | 合同到期预警 | 聘期与到期预警 | `/hr/contracts/risks/` | 否 | PASS |
| HR08 外聘人员 | 01 | 外聘人员总览 | 外聘教师库 | `/hr/external-teachers/` | 否 | PASS |
| HR08 外聘人员 | 02 | 产业教授与技能大师 | 产业教授与技能大师 | `/hr/external-teachers/industry/` | 否 | PASS |
| HR08 外聘人员 | 03 | 聘用审批 | 聘用审批 | `/hr/external-teachers/hiring/` | 否 | PASS |
| HR08 外聘人员 | 04 | 教学与服务任务 | 教学与服务任务 | `/hr/external-teachers/tasks/` | 否 | PASS |
| HR08 外聘人员 | 05 | 续聘办理 | 续聘与退出 | `/hr/external-teachers/renewals/` | 否 | PASS |
| HR09 资格资质 | 01 | 教师资格台账 | 教师资格台账 | `/hr/qualifications/credentials/` | 否 | PASS |
| HR09 资格资质 | 02 | 双师认定批次 | 双师认定标准 | `/hr/double-teacher/` | 否 | PASS |
| HR09 资格资质 | 03 | 双师申报 | 双师申报 | `/hr/double-teacher/applications/` | 否 | PASS |
| HR09 资格资质 | 04 | 认定结果 | 认定与评审 | `/hr/double-teacher/recognitions/` | 否 | PASS |
| HR09 资格资质 | 05 | 资格复核与到期 | 复核与资格台账 | `/hr/qualifications/risks/` | 否 | PASS |
| HR10 教师发展 | 01 | 教师发展计划 | 教师发展计划 | `/hr/development/plans` | 否 | PASS |
| HR10 教师发展 | 02 | 培训项目 | 培训项目 | `/hr/development/programs` | 否 | PASS |
| HR10 教师发展 | 03 | 报名与审批 | 报名与审批 | `/hr/development/requests` | 否 | PASS |
| HR10 教师发展 | 04 | 企业实践项目 | 企业实践项目 | `/hr/development/enterprise-practice` | 否 | PASS |
| HR10 教师发展 | 05 | 实践过程与成果 | 实践过程与成果 | `/hr/development/enterprise-practice/results` | 否 | PASS |
| HR10 教师发展 | 06 | 个人发展档案 | 教师发展档案 | `{{ record_url }}` | 是 | PASS |
| HR11 考勤时间 | 01 | 工作制度与考勤规则 | 工作制度与考勤规则 | `/hr/time/rules/` | 否 | PASS |
| HR11 考勤时间 | 02 | 工作日历与排班 | 工作日历与排班 | `/hr/time/schedule/` | 否 | PASS |
| HR11 考勤时间 | 03 | 打卡与工时 | 打卡与工时 | `/hr/time/attendance/` | 否 | PASS |
| HR11 考勤时间 | 04 | 加班与调休 | 异常、补卡与加班 | `/hr/time/overtime/` | 否 | PASS |
| HR11 考勤时间 | 05 | 请假与销假 | 请假休假与销假 | `/hr/time/leave/` | 否 | PASS |
| HR11 考勤时间 | 06 | 考勤台账与月结 | 考勤台账与月结 | `/hr/time/close/` | 否 | PASS |
| HR12 考核管理 | 01 | 考核制度与指标 | 考核制度与指标体系 | `/hr/assessments/policies/` | 否 | PASS |
| HR12 考核管理 | 02 | 目标任务与平时考核 | 目标任务与平时考核 | `/hr/assessments/goals/` | 否 | PASS |
| HR12 考核管理 | 03 | 年度考核 | 年度考核 | `/hr/assessments/annual/` | 否 | PASS |
| HR12 考核管理 | 04 | 聘期考核 | 聘期考核 | `/hr/assessments/term/` | 否 | PASS |
| HR12 考核管理 | 05 | 师德与专项考核 | 师德与专项考核 | `/hr/assessments/ethics/` | 否 | PASS |
| HR12 考核管理 | 06 | 评议与审定 | 评议审定与考核档案 | `/hr/assessments/review/` | 否 | PASS |
| HR13 职称评审 | 01 | 职称评审总览 | 职称制度与评审标准 | `/hr/titles/` | 否 | PASS |
| HR13 职称评审 | 02 | 职称申报 | 申报批次与资格审查 | `/hr/titles/applications/` | 否 | PASS |
| HR13 职称评审 | 03 | 材料与代表性成果 | 业绩材料与代表性成果 | `/hr/titles/materials/` | 否 | PASS |
| HR13 职称评审 | 04 | 专家与评委管理 | 专家库与评审组织 | `/hr/titles/experts/` | 否 | PASS |
| HR13 职称评审 | 05 | 评议与表决 | 评议表决与结果公示 | `/hr/titles/deliberation/` | 否 | PASS |
| HR13 职称评审 | 06 | 异议与复核 | 复核监管与职称档案 | `/hr/titles/appeals/` | 否 | PASS |
| HR14 岗位聘任 | 01 | 聘任制度与岗位等级 | 聘任制度与岗位等级 | `/hr/appointments/policies/` | 否 | PASS |
| HR14 岗位聘任 | 02 | 岗位额度 | 岗位额度与聘任批次 | `/hr/appointments/quota/` | 否 | PASS |
| HR14 岗位聘任 | 03 | 竞聘申报 | 申报竞聘与资格审查 | `/hr/appointments/applications/` | 否 | PASS |
| HR14 岗位聘任 | 04 | 评议排序 | 评议评审与择优排序 | `/hr/appointments/ranking/` | 否 | PASS |
| HR14 岗位聘任 | 05 | 拟聘公示 | 拟聘公示与正式聘任 | `/hr/appointments/publicity/` | 否 | PASS |
| HR14 岗位聘任 | 06 | 聘期变更 | 聘期变更与聘任档案 | `/hr/appointments/term-changes/` | 否 | PASS |
| HR15 薪酬福利 | 01 | 薪酬档案 | 薪酬档案 | `/hr/payroll/profiles/` | 否 | PASS |
| HR15 薪酬福利 | 02 | 薪资项目与规则 | 薪资项目与规则 | `/hr/payroll/rules/` | 否 | PASS |
| HR15 薪酬福利 | 03 | 月度工资核算 | 月度工资核算 | `/hr/payroll/calculations/` | 否 | PASS |
| HR15 薪酬福利 | 04 | 津贴与补贴 | 调资与津补贴 | `/hr/payroll/allowances/` | 否 | PASS |
| HR15 薪酬福利 | 05 | 社保公积金与年金 | 社保与公积金 | `/hr/payroll/social-security/` | 否 | PASS |
| HR15 薪酬福利 | 06 | 支付与工资条 | 工资条与财务对接 | `/hr/payroll/payments/` | 否 | PASS |
| HR16 退休离校 | 01 | 退休离校总览 | 离退制度与离校规则 | `/hr/exit/` | 否 | PASS |
| HR16 退休离校 | 02 | 离校审批 | 辞职调出与解除离校 | `/hr/exit/cases/` | 否 | PASS |
| HR16 退休离校 | 03 | 退休预审 | 退休预审与退休办理 | `/hr/exit/retirement-precheck/` | 否 | PASS |
| HR16 退休离校 | 04 | 工作交接 | 离校交接与权限资产清退 | `/hr/exit/handover/` | 否 | PASS |
| HR16 退休离校 | 05 | 最终结算 | 结算证明与关系转移 | `/hr/exit/settlement/` | 否 | PASS |
| HR16 退休离校 | 06 | 正式离校档案 | 离退休档案与返聘衔接 | `/hr/exit/archive/` | 否 | PASS |
| HR17 教职工服务 | 01 | 我的人事服务 | 我的服务首页 | `/hr/self/` | 否 | PASS |
| HR17 教职工服务 | 02 | 我的文件 | 我的档案与更正 | `/hr/self/files/` | 否 | PASS |
| HR17 教职工服务 | 03 | 办理进度 | 我的任职与成长 | `/hr/self/progress/` | 否 | PASS |
| HR17 教职工服务 | 04 | 我的工资条 | 我的薪酬权益与文件 | `/hr/self/payslips/` | 否 | PASS |
| HR17 教职工服务 | 05 | 我的待办 | 我的申请与办理 | `/hr/self/todos/` | 否 | PASS |
| HR17 教职工服务 | 06 | 服务大厅 | 关怀与退休服务 | `/hr/self/services/` | 否 | PASS |
| HR18 人事数据中心 | 01 | 人事数据总览 | 人事数据总览 | `/hr/data/` | 否 | PASS |
| HR18 人事数据中心 | 02 | 指标口径中心 | 指标口径与专题分析 | `/hr/data/metrics/` | 否 | PASS |
| HR18 人事数据中心 | 03 | 标准报表与自助分析 | 标准报表与自助分析 | `/hr/data/population/` | 否 | PASS |
| HR18 人事数据中心 | 04 | 数据质量中心 | 数据质量与治理 | `/hr/data/quality/` | 否 | PASS |
| HR18 人事数据中心 | 05 | 数据交换 | 数据交换与共享 | `/hr/data/exchange/` | 否 | PASS |
| HR18 人事数据中心 | 06 | 正式报送 | 正式上报与报送档案 | `/hr/data/submissions/` | 否 | PASS |
