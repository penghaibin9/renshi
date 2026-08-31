# HR06–HR18 前端 V2 设计验收

视觉基准：`C:\Users\10850\Downloads\renshi-hr-ui-prototype-18-modules-with-secondary-pages.html` 与用户提供的 1487×1058 人事异动中心截图。

## HR06 人事异动

- 实现范围：异动申请中心、校内调动、岗位与身份变更、借调挂职、异动台账、待生效清单、新建、案件详情、影响预览。
- 数据状态：阶段数量、筛选项、案件、计划生效日、提醒与经办人均来自当前学校真实查询；未使用前端假数据。
- 交互状态：人员检索、类型与原因联动、组织岗位联动、草稿创建约束、列表筛选与分页合同通过。
- 同视口对比：`artifacts/hr06-correction-20260830/12-reference-vs-hr06-final.png`。
- 视觉结论：页面层级、克制蓝白配色、状态导航、筛选区、密集业务表格和提醒区与参考方向一致；全局中文模块侧栏与顶栏已统一。
- 回归结果：`hr_changes.tests.test_v2_workspace_contract` 与租户隔离测试共 14 项通过。
- checkpoint result: passed

## HR07–HR18

- HR07 合同管理：6 项合同生命周期统计、6 段办理阶段、真实合同台账、五个二级工作区；截图 `artifacts/hr06-correction-20260830/14b-hr07-after.png`；合同工作区与接口合同 4 项通过。
- HR08 外聘人员：6 项人才与聘期统计、真实人才速览、待办提醒、人才台账、七个现有业务工作区；截图 `artifacts/hr06-correction-20260830/15b-hr08-after.png`；模板与接口合同 10 项通过。
- HR09 资格资质：6 项资格与双师统计、五段业务链、真实优先事项、资格台账与判断口径；截图 `artifacts/hr06-correction-20260830/16b-hr09-after.png`；工作区与接口安全合同 5 项通过。
- HR07–HR09 checkpoint result: passed

### HR10–HR12 发展与评价

- HR10 教师发展：按年度计划、培养项目、个人申请、企业实践、成果入库、质量复盘形成 6 段业务导航；6 项统计和待办均来自当前学校台账；截图 `artifacts/hr06-correction-20260830/17c-hr10-after.png`。
- HR11 考勤时间：按制度规则、校历排班、日常打卡、异常补卡、审批复核、月结归档形成 6 段业务导航；冲突、异常、月结等状态来自现有模型；截图 `artifacts/hr06-correction-20260830/18b-hr11-after.png`。
- HR12 考核管理：按制度指标、目标任务、年度考核、聘期考核、师德专项、评议档案形成 6 段业务导航；当前周期、参与人数、完成率、待评审、师德异常、待归档均为真实汇总；截图 `artifacts/hr06-correction-20260830/19b-hr12-after.png`。
- HR10–HR12 checkpoint result: passed

### HR13–HR15 评审聘任与薪酬

- HR13 职称评审：6 个原型二级入口、6 项评审统计、6 段业务链和真实办理重点已接通；截图 `artifacts/hr06-correction-20260830/20c-hr13-after.png`。
- HR14 岗位聘任：制度等级、额度批次、申报资格、评议排序、公示聘任、聘期档案 6 个业务入口已与现有页面和接口归并；截图 `artifacts/hr06-correction-20260830/21b-hr14-after.png`。
- HR15 薪酬福利：薪酬档案、薪资规则、月度核算、调资津贴、社保公积金、工资条财务 6 个入口已与真实期间、结果和支付状态对接；截图 `artifacts/hr06-correction-20260830/22b-hr15-after.png`。
- HR13–HR15 checkpoint result: passed

### HR16–HR18 离校、本人服务与数据决策

- HR16 退休离校：离退规则、辞职调出、退休办理、离校交接、结算转移、档案返聘 6 个入口与真实案件、交接、结算和生效协同对接；截图 `artifacts/hr06-correction-20260830/23b-hr16-after.png`。
- HR17 教职工服务：本人首页、档案更正、任职成长、薪酬权益、申请办理、关怀退休 6 个入口已接通登录本人主档和来源健康度；截图 `artifacts/hr06-correction-20260830/24c-hr17-after.png`。
- HR18 人事数据中心：数据总览、指标专题、报表分析、质量治理、交换共享、上报档案 6 个入口与真实治理汇总、质量问题、历史证据和正式报送对接；截图 `artifacts/hr06-correction-20260830/25b-hr18-after.png`。
- HR16–HR18 checkpoint result: passed

## 最终同屏视觉复核

- 同一比较输入：用户参考截图与 HR06–HR18 全部桌面首屏已合成为 `artifacts/hr06-correction-20260830/27-reference-vs-hr06-18-contact-sheet.png`；HR16–HR18 放大对照为 `artifacts/hr06-correction-20260830/26-reference-vs-hr16-18.png`。
- 复核视口：桌面浏览器约 1280×720；检查了全局中文侧栏、页头主操作、6 段业务导航、一体化指标带、业务表格/空状态、右侧办理路径与滚动区域。
- 视觉结论：蓝白灰配色、1px 分隔线、紧凑数字层级、5px 左右圆角和低装饰密度已统一；未发现渐变、横向破版、按钮裁切、明显错位或重复嵌套卡片。
- 业务结论：页面继续使用现有路由、权限、选择器与接口；未开放来源明确显示“暂不可用”，未使用前端示例数字冒充真实业务数据。
- 回归结果：HR06–HR18 目标页面合同、模板、接口与公开身份边界共 91 项测试通过；`git diff --check` 通过（仅工作区既有 CRLF 提示）。
- final result: passed
