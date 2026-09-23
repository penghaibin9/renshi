# 高校人事系统易用性研究摘记 R5

日期：2026-09-17

> 用途：只作为交互与提示设计参考，不把互联网内容直接写成学校人事政策、审批结论或业务事实。

## 采用的公开设计依据

1. **GOV.UK Design System – Question pages**
   - https://design-system.service.gov.uk/patterns/question-pages/
   - 核心启发：只询问完成当前服务真正需要的信息；选填项明确标注为 optional；让用户知道为什么要问。
   - 本系统落地：复杂表单默认只隐藏空选填项；所有选填字段显示“可选”；办理助手增加“这个字段为什么要填？”和“哪些可以先不填？”。

2. **Oracle HCM – Guided Journeys**
   - https://docs.oracle.com/en/cloud/saas/readiness/hcm/25c/hure-25c/25C-hr-wn-f38839.htm
   - 核心启发：把分步骤引导直接嵌进具体 HCM 任务，而不是让用户跳到独立手册。
   - 本系统落地：14 段全生命周期路线、HR01～HR18 页面内办理助手、当前环节少填原则和下一步入口。

3. **SAP SuccessFactors Joule – HR use cases / sample prompts**
   - https://help.sap.com/docs/successfactors-platform/setting-up-and-using-joule-in-sap-successfactors/time-tracking-use-cases
   - https://help.sap.com/docs/joule/capabilities-guide/performance-goals-use-cases
   - 核心启发：用用户自然语言描述任务，例如“打卡”“查看评估表”，直接导航或执行对应 HR 事务。
   - 本系统落地：每个 HR 模块至少 23 个上下文问法；支持“我只想改一项”“提交前还缺什么”“谁处理下一步”等自然语言问题。

4. **SAP Performance Preparation Agent 2026**
   - https://help.sap.com/docs/successfactors-release-information/e9989dc2e5b046ec929e2ad5e8305d24/17150fd1e5a54104907f1f4680d2ff29.html
   - 核心启发：给出下一步建议、深链到依据页面；请求缺关键条件时应主动澄清，而不是生成不可靠结论。
   - 本系统落地：助手只发送“模块/路径/必填完成度/缺失字段名称”这类无值上下文，不发送人员敏感字段值；正式结论仍由后端状态机决定。

## 明确不采用的做法

- 不从互联网自动填某校的组织、岗位、工资标准、考核规则、合同条款、退休结论。
- 不从互联网推断人员身份证、联系方式、学历、资格、实际到岗时间。
- 不让 AI 替代录用、审批、资格认定、考核、聘任、薪酬或离退正式决定。
- 不因为“减少填写”而隐藏已有值；已有值必须继续让经办人看到并核对。
