# 跃科高校人事系统易用性与真实经办路线收口 R2

日期：2026-09-17
基线：`Yueke_University_HR_Usability_Candidate_20260917.zip`
状态：`SOURCE_USABILITY_R2_CLOSURE_COMPLETE / QA_RUNTIME_PENDING_DJANGO_MYSQL`

## 一、本轮为什么继续改

第一轮已经解决“找不到入口、不会填表、看不懂报错、没有上下文帮助”的问题。本轮继续按真实学校经办人的习惯审查，发现仍有三类学习成本：

1. 一件事跨多个模块时，用户仍要自己记“下一站去哪”；
2. 用户会说“换部门、续合同、工资单、离职”，不会严格使用系统术语；
3. 经常处理同一类业务时，重复从菜单找入口仍然浪费时间。

因此本轮没有新增 HR 业务模块，而是继续优化任务导航层。

## 二、互联网对标结论

本轮只吸收公开交互模式，不复制专有实现。

- Oracle HCM Guided Journeys：把教程、政策、最佳实践嵌入具体 HCM 流程。
- Oracle Contextual Journeys：在用户发起调动、请假、晋升等交易时显示前置任务和相关任务；复杂流程应贴着交易本身，而不是要求用户自己记跨模块顺序。
- Oracle Journeys：将业务过程组织为一组由不同执行人完成、可追踪的任务。
- SAP SuccessFactors Joule：按 HR use case 提供 sample prompts，允许用户用自然语言表达要做的事。
- ServiceNow Employee Center：强调从一个入口查答案、发起服务、完成任务。

公开参考：

- https://docs.oracle.com/en/cloud/saas/human-resources/faucf/guided-journeys-in-hcm-flows.html
- https://docs.oracle.com/en/cloud/saas/human-resources/fajqa/what-are-contextual-journeys.html
- https://docs.oracle.com/en/cloud/saas/human-resources/faijh/overview-of-journeys.html
- https://help.sap.com/docs/successfactors-platform/setting-up-and-using-joule-in-sap-successfactors/use-cases-supported-in-joule
- https://www.servicenow.com/products/employee-center.html

## 三、直接落地的整改

### 1. 六条跨模块完整办理路线

新增 guidance-only Contextual Journeys：

- 新教职工从录用到正常发薪：HR04 → HR05 → HR03 → HR07 → HR11 → HR15；
- 教师校内调动/转岗：HR02 → HR06 → HR03 → HR11 → HR15；
- 合同到期续签：HR07 风险 → HR07 续签 → HR03；
- 职称评审到岗位聘任：HR13 → HR14 → HR03 → HR15；
- 退休/离校完整办理：HR16 → HR07 → HR15 → HR03；
- 教师发展到年度考核：HR10 → HR09 → HR12。

这些路线只显示建议顺序和真实业务入口，页面明确提示：**不代表任何步骤已经完成，正式状态以后端状态机和业务页面为准。**

### 2. 口语搜索别名

增加自然表达映射，例如：

- 换部门 / 换学院 / 转部门 → 调动；
- 新员工 / 新教师 / 报到 → 入职；
- 续合同 → 合同续签；
- 证书过期 → 资质到期；
- 评职称 → 职称；
- 工资单 / 工资明细 → 工资条；
- 离职 / 辞职 → 离校；
- 档案错了 → 档案更正；
- 接口报错 / 同步失败 → 接口同步失败。

目的不是做模糊 AI 猜测，而是把一组经过冻结的常用口语映射到已有正式任务入口。

### 3. 最近办理

系统已有本地 recent storage，本轮把它真正显示出来：

- 只保存 `title/module/route` 等入口元数据；
- 不保存姓名、身份证、工资、合同正文、附件等业务数据；
- 最多保留 6 条；
- 支持一键清除。

### 4. 路由防失效门禁

新增源码门：办理助手和完整办理路线中出现的每个 `/hr/...` 路由，都必须能在交付源码的 URL/模板/业务代码中找到对应来源。当前 43 个唯一 HR 引导路由全部可解析到交付源码，避免“帮助文案写了入口，但按钮点过去 404”。

## 四、真实 Chromium 走查

本轮继续使用真实 Chromium + Playwright 执行交付版 CSS/JS。

已验证：

- HR05 办理助手打开/关闭、Alt+K、Escape；
- 任务搜索与跨模块 Journey 同时显示；
- 新教职工 Journey 能一直给到 HR15 首月工资核算入口；
- 表单完成度、缺项汇总、字段跳转；
- 生成的 AI-ready prompt 不读取页面里的测试姓名、身份证和手机号；
- HR01 六类高频用户意图均能给出正确业务入口和对应完整办理路线；
- “换部门”等口语表达能解析到正式 HR06 调动入口；
- Chromium pageerror = 0。

当前 Chromium 沙箱对自定义 HTTP/file URL 有管理员限制，因此“最近办理”的 localStorage 跨页面持久化由源码合同覆盖；该项将在正常 Django QA origin 下由 `hr_real_browser_click.py` 一并验证。

## 五、真实 Django/MySQL 状态

当前执行器仍未安装 Django，实际 `import django` 返回 `ModuleNotFoundError`。Remote Desktop Commander 再次检查时也没有在线设备。

因此本轮没有虚报“招聘→入职→合同→考勤→工资”已经完成真实数据库事务级点击。

但 `scripts/hr_real_browser_click.py` 已继续升级，真实 QA 环境会额外检查：

- HR01 搜索“入职”不仅找到 HR05，还必须显示完整办理路线；
- 口语“换部门”必须落到 HR06；
- HR01～HR18 每页必须有上下文办理助手；
- 继续收集 HTTP、HR API、pageerror、截图、trace。

## 六、回归结果

- HR10 Excel 导入门：20/20 PASS；
- HR10 UUID 身份门：53/53 PASS；
- HR18 采购同步门：24/24 PASS；
- 学校数据移交门：33/33 PASS；
- 最终采购源码门：53/53 PASS；
- 易用性门：56/56 PASS；
- 纯源码回归：187/187 PASS；
- Python AST：3161/3161 PASS；
- JavaScript `node --check`：254/254 PASS；
- 易用性真实 Chromium smoke：PASS。

## 七、下一条唯一主线

源码侧不要再扩菜单。下一步必须在具备 Django + MySQL 的 QA 环境跑真实人事主链：

招聘录用 → 入职报到 → 教职工主档 → 合同 → 异动 → 资质 → 教师发展 → 考勤 → 考核 → 职称 → 聘任 → 薪酬 → 退休离校 → 本人服务 → 数据中心。

每遇到“要返回上一级才能继续、找不到下一步、字段名看不懂、错误提示不知道怎么办”的地方，再做最小改动，不再扩新模块。
