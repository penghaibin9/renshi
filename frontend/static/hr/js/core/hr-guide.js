/*
 * hr-guide.js — 高校人事办理助手（规则型，不伪装成 AI）
 *
 * 设计边界：
 * 1. 只提供入口搜索、上下文流程说明、表单完成度与提示词模板；
 * 2. 不读取人员姓名、身份证、联系方式、工资、附件正文等敏感业务数据；
 * 3. 不在浏览器端决定审批/核验/正式状态，所有权威状态仍以后端为准；
 * 4. 未来接入 AI 时，可复用 buildSafePrompt() 生成的脱敏上下文。
 */
(() => {
  "use strict";

  const root = document.querySelector(".hr-v2-page[data-module], [data-module^='HR'][data-section]");
  if (!root) return;

  const STORAGE = {
    welcomed: "yueke.hr.guide.welcomed.v1",
    recent: "yueke.hr.guide.recent.v1",
    lifecycle: "yueke.hr.guide.lifecycle.v1",
  };

  const MEMORY_STORAGE = new Map();

  const MODULES = {
    HR01: {
      name: "人事工作台",
      purpose: "把今天最该处理的待办、风险和数据异常放在一起，先办事，再找模块。",
      prepare: ["确认当前学校和数据范围是否正确", "先看逾期待办和高风险预警", "不确定入口时直接搜索要办的事"],
      steps: ["先处理“我的待办”里的逾期和今日事项", "再查看人事预警，确认是否有到期/异常风险", "最后按具体任务进入 HR02-HR18 工作区办理"],
      pitfalls: ["首页数字是摘要，不要在首页直接推断正式业务状态", "遇到“暂不可用/部分可用”先查数据来源，不把它当成 0"],
      next: { label: "查看我的全部待办", route: "/hr/todos" },
      prompts: ["我今天应该先处理什么？", "我第一次使用系统，从哪里开始？", "某项业务应该进入哪个模块？", "为什么首页有数据不可用提示？"],
    },
    HR02: {
      name: "组织岗位",
      purpose: "维护组织、岗位、编制和历史生效关系，为后续人员业务提供统一组织岗位事实。",
      prepare: ["确认组织生效日期和上级组织", "准备岗位类别、编制/额度和归属组织", "涉及调整时先确认是否已有在岗人员或下游业务引用"],
      steps: ["先维护或核对组织机构", "再维护岗位目录、编制方案和岗位台账", "变更前做生效预览，确认影响后再提交正式调整"],
      pitfalls: ["不要为了修人员数据直接改历史组织事实", "未来生效调整和当前生效状态要分开看"],
      next: { label: "进入组织机构", route: "/hr/structure/organizations" },
      prompts: ["新建一个学院前要准备什么？", "岗位为什么显示容量不足？", "组织调整会影响哪些人员？", "如何查看某个历史时点的组织结构？"],
    },
    HR03: {
      name: "教职工主档",
      purpose: "维护教职工身份、任职关系、履历和材料，是其他 HR 模块引用人员事实的权威入口。",
      prepare: ["确认人员身份是否已存在，避免重复建档", "准备基本身份、组织岗位和任职关系信息", "历史纠错要保留原事实与纠正依据"],
      steps: ["先在教职工名册搜索人员，确认不是重复人员", "进入个人主档核对任职、履历和材料", "发现历史错误时走正式更正流程，不直接覆盖历史"],
      pitfalls: ["不要用同名人员猜测身份", "主档更正可能影响合同、考核、薪酬等下游口径"],
      next: { label: "进入教职工名册", route: "/hr/staff/" },
      prompts: ["新增教职工前要检查什么？", "为什么人员组织和岗位信息不一致？", "历史更正会影响哪些业务？", "我怎么确认这是不是重复人员？"],
    },
    HR04: {
      name: "招聘管理",
      purpose: "从年度用人计划、招聘项目、候选人到资格审查、考察和录用形成完整招聘链。",
      prepare: ["先有批准的年度用人计划和正式岗位", "明确招聘项目编号、岗位和报名时间", "准备资格条件、材料要求和评审规则"],
      steps: ["从年度用人计划确认可招聘岗位", "创建招聘项目并绑定正式岗位后发布", "按人才库→资格审查→考试考察→拟录用依次推进"],
      pitfalls: ["未绑定 HR02 正式岗位不能开放报名", "不要跳过资格审查直接形成录用结论"],
      next: { label: "进入招聘项目与岗位", route: "/hr/recruitment/campaigns" },
      prompts: ["第一次发起招聘应该先做什么？", "岗位为什么不能开放报名？", "候选人资格审查要看哪些材料？", "拟录用后下一步怎么转入职？"],
    },
    HR05: {
      name: "入职管理",
      purpose: "把拟录用人员从待报到、身份材料核验、协同任务推进到正式入职和试用转正。",
      prepare: ["确认拟录用来源和人员身份匹配", "准备入职材料清单与原件核验要求", "确认组织岗位、到岗日期及需协同的账号/资产任务"],
      steps: ["先处理待报到人员并核对身份", "完成报到登记和必需材料核验", "完成跨部门协同后再正式激活，随后进入试用/转正"],
      pitfalls: ["材料缺失或身份冲突时不要强行激活", "协同任务完成不等于人员主档已正式生效"],
      next: { label: "进入待报到人员", route: "/hr/onboarding/prehires" },
      prompts: ["新员工报到前还有哪些阻断项？", "哪些材料必须核验后才能激活？", "报到后需要哪些部门协同？", "入职完成后怎么进入试用转正？"],
    },
    HR06: {
      name: "人事异动",
      purpose: "办理校内调动、岗位身份变更、借调挂职，并保留生效前后完整事实链。",
      prepare: ["确认当前人员、组织、岗位和任职状态", "明确异动类型、生效日期和目标组织岗位", "核对编制/岗位容量及在途业务冲突"],
      steps: ["新建异动申请并选定人员与异动类型", "完成目标组织岗位、原因和生效日期校验", "审批通过后执行生效，再到异动台账复核结果"],
      pitfalls: ["生效日期和审批完成日期不是同一概念", "不要直接修改 HR03 当前任职来绕过异动流程"],
      next: { label: "进入异动申请中心", route: "/hr/changes/" },
      prompts: ["调动一个教师前要检查什么？", "为什么目标岗位不能选择？", "异动生效后会更新哪些事实？", "借调挂职和正式调动有什么区别？"],
    },
    HR07: {
      name: "合同管理",
      purpose: "管理合同签订、续签、变更解除和到期风险，保留合同版本与正式生效依据。",
      prepare: ["确认人员当前聘用关系和合同状态", "准备适用模板、期限、岗位/聘期信息", "续签或变更前先处理到期风险和冲突"],
      steps: ["先核对合同台账和到期风险", "按模板发起签订/续签或变更流程", "完成签署与核验后形成新版本，不覆盖旧合同"],
      pitfalls: ["不要直接修改已生效合同正文", "续签、变更、解除应保留独立的生效链"],
      next: { label: "查看聘期与到期预警", route: "/hr/contracts/risks/" },
      prompts: ["哪些合同快到期需要先处理？", "续签前要核对哪些条件？", "合同变更为什么不能直接改原记录？", "解除合同后还要做哪些下游处理？"],
    },
    HR08: {
      name: "外聘人员",
      purpose: "管理外聘教师、产业教授等外部人员的准入、聘用、任务、续聘和退出。",
      prepare: ["确认外聘身份和合作来源", "准备准入资质、聘期和任务范围", "明确可访问的数据和系统权限边界"],
      steps: ["先建立或核对外聘人员档案", "完成聘用审批并绑定任务/协议", "聘期内跟踪任务，期满后续聘或退出并清理权限"],
      pitfalls: ["外聘身份不能替代 HR03 正式在编/在岗身份", "合作单位人员不得默认获得完整教职工数据"],
      next: { label: "进入外聘教师库", route: "/hr/external-teachers/" },
      prompts: ["新建外聘教师要准备哪些资料？", "外聘人员可以看到哪些数据？", "续聘前要检查哪些任务和资质？", "退出后哪些权限需要清理？"],
    },
    HR09: {
      name: "资格资质",
      purpose: "维护教师资格、职业资格和双师认定等可核验资质及其有效期、复核和历史证据。",
      prepare: ["准备证书类别、编号、发证机构和有效期", "附件需与本人和业务对象绑定", "历史已用于考核/认定的证据不得静默覆盖"],
      steps: ["先录入或导入资质并上传证据", "完成核验/认定后形成正式资质事实", "持续处理到期风险、续证和复核"],
      pitfalls: ["普通培训结业证不能直接当作法定资格", "续证应形成新代际/版本，不覆盖旧证据"],
      next: { label: "查看教师资格台账", route: "/hr/qualifications/credentials/" },
      prompts: ["哪些教师资质快到期？", "新增资质需要哪些字段和附件？", "续证后旧证书怎么保留？", "双师认定和普通培训证书有什么区别？"],
    },
    HR10: {
      name: "教师发展",
      purpose: "把发展计划、培训项目、个人申请、企业实践、成果核验和成长档案串成一条可追溯发展链。",
      prepare: ["先确定学校/学院/个人发展目标和周期", "培训/实践项目要有明确主办方、时间、名额与规则", "历史导入先预览再确认，不直接生成未经核验的正式事实"],
      steps: ["先建立发展计划和可参加的发展项目", "教师提交申请并完成审批、培训/实践过程", "完成成果核验后写入教师发展档案"],
      pitfalls: ["报名不等于完成，证书不等于正式资格", "企业实践不能只记录天数，还要有过程和评价证据"],
      next: { label: "进入教师发展计划", route: "/hr/development/plans" },
      prompts: ["第一次建立教师发展计划怎么做？", "培训申请为什么不能直接算完成？", "企业实践需要哪些过程证据？", "哪些结果才能进入教师成长档案？"],
    },
    HR11: {
      name: "考勤时间",
      purpose: "管理排班、考勤、请假、加班和月结，以正式时间事实服务薪酬和其他业务。",
      prepare: ["确认人员在岗状态和适用排班", "准备请假/加班类型及必要证明", "月结前先处理异常打卡和未审批事项"],
      steps: ["先核对排班和考勤异常", "处理请假、加班及必要补正", "月结前完成复核，封板后再向薪酬提供正式时间事实"],
      pitfalls: ["未审批请假不能当作正式缺勤结论", "月结后更正要走更正链，不能直接覆盖封板结果"],
      next: { label: "进入考勤工作区", route: "/hr/time/attendance/" },
      prompts: ["这个月结前还有哪些异常要处理？", "请假为什么没有影响考勤结果？", "排班冲突要怎么处理？", "月结后发现错误怎么更正？"],
    },
    HR12: {
      name: "考核管理",
      purpose: "从制度指标、目标、数据采集到教师确认、分级审核、异议和归档形成可解释考核链。",
      prepare: ["先冻结考核周期、指标、权重和规则版本", "确认考核数据来源可用且口径一致", "准备教师确认、教研室/学院/学校各级处理人"],
      steps: ["配置并发布本周期规则", "采集数据并自动计算，允许教师核对/异议", "完成逐级确认和学校审核后归档形成快照"],
      pitfalls: ["规则变更不能静默改写已归档历史结果", "人工调整必须记录前后值、原因和依据"],
      next: { label: "进入考核制度与指标", route: "/hr/assessments/policies/" },
      prompts: ["新考核周期怎么从上一周期复制？", "教师对得分有异议怎么处理？", "某个指标分数是怎么计算出来的？", "归档后发现错误还能怎么更正？"],
    },
    HR13: {
      name: "职称评审",
      purpose: "管理职称申报批次、资格、材料、专家评审、公示异议和正式结果。",
      prepare: ["确定本批次制度、职称层级和申报条件", "准备申报材料清单与代表性成果规则", "专家回避和评审组织规则需提前配置"],
      steps: ["发布申报批次并受理申请", "完成资格审查、材料核验和专家评审", "完成表决、公示及异议处理后形成正式结果"],
      pitfalls: ["公示结果不等于正式职称事实", "专家回避、评分和表决过程必须留痕"],
      next: { label: "进入申报批次与资格审查", route: "/hr/titles/applications/" },
      prompts: ["职称申报批次要先配置什么？", "资格审查不通过常见原因有哪些？", "专家评审怎么处理回避？", "公示后异议怎么进入正式结果？"],
    },
    HR14: {
      name: "岗位聘任",
      purpose: "从岗位额度、聘任批次、竞聘资格到排序、公示和正式聘任形成可审计聘任链。",
      prepare: ["先确认岗位等级、额度和聘期规则", "准备竞聘条件、资格和评议规则", "正式聘任前核对 HR02 岗位容量与人员当前聘任"],
      steps: ["建立聘任批次和岗位额度", "受理竞聘并完成资格、评议与排序", "公示无异议后形成正式聘任，再管理聘期变更"],
      pitfalls: ["拟聘公示不等于正式聘任", "不能绕过岗位额度直接写人员聘任结果"],
      next: { label: "进入岗位额度与聘任批次", route: "/hr/appointments/quota/" },
      prompts: ["新一轮岗位聘任先做什么？", "为什么某岗位没有可用额度？", "竞聘排序结果能直接生效吗？", "聘期中途变更怎么留痕？"],
    },
    HR15: {
      name: "薪酬福利",
      purpose: "管理薪酬档案、规则、月度核算、调资津补贴、社保公积金和支付对账。",
      prepare: ["确认薪酬期间和人员薪酬档案完整", "核对考勤/聘任等正式来源是否已封板", "计算前冻结本期规则版本和必要参数"],
      steps: ["先处理薪酬档案和规则配置", "创建工资期间并执行计算、复核异常", "封板后生成工资条/支付数据并完成财务对账"],
      pitfalls: ["不要把未封板考勤直接作为最终扣款依据", "工资结果封板后更正应通过调整/重算链而非直接改值"],
      next: { label: "进入月度工资核算", route: "/hr/payroll/calculations/" },
      prompts: ["本月工资核算前要先检查什么？", "为什么某教师工资没有算出来？", "封板后发现错误怎么纠正？", "工资条和财务支付如何对账？"],
    },
    HR16: {
      name: "退休与离校",
      purpose: "办理辞职调出、退休预审、离校交接、结算关系转移和离退档案。",
      prepare: ["确认离校/退休类型、预计生效日期和人员当前关系", "准备审批依据、交接清单及资产/权限责任方", "结算前核对薪酬、合同、社保等下游事项"],
      steps: ["发起离校或退休预审并完成审批", "执行交接、资产权限清退和必要结算", "正式生效后形成离退事实、证明和归档记录"],
      pitfalls: ["审批通过不等于已经完成离校清退", "退休事实、返聘和原聘用关系要明确分开"],
      next: { label: "进入离校/退休办理", route: "/hr/exit/cases/" },
      prompts: ["教师离校前必须完成哪些交接？", "退休预审主要检查什么？", "为什么已经审批还不能正式离校？", "退休后返聘应该走哪条流程？"],
    },
    HR17: {
      name: "教职工服务",
      purpose: "给教职工一个统一入口查看本人档案、薪酬合同、申请待办、办理进度和退休关怀服务。",
      prepare: ["先确认本人身份已正确关联 HR03 主档", "只提交本人业务所需材料，不上传无关敏感信息", "发现档案错误走更正申请，不直接要求后台改库"],
      steps: ["从服务首页选择要办理的本人事项", "按要求提交信息/材料并跟踪待办", "在办理进度查看退回、补件和最终结果"],
      pitfalls: ["本人服务不能通过 URL 参数切换成他人身份", "工资/合同等高敏文件只在授权范围内查看下载"],
      next: { label: "进入我的申请与办理", route: "/hr/self/todos/" },
      prompts: ["我想更正个人档案怎么申请？", "我的申请被退回后怎么补件？", "在哪里看工资条和合同？", "我的办理现在卡在哪一步？"],
    },
    HR18: {
      name: "人事数据中心",
      purpose: "统一指标口径、历史时点、数据质量、交换共享和正式报送，不另建第二套业务事实。",
      prepare: ["先明确指标/报表的数据来源和统计口径", "接口同步前确认字段映射、鉴权和幂等键", "正式报送前处理数据质量问题并冻结证据"],
      steps: ["先看数据质量和同步状态", "按指标/专题进行分析或生成标准报表", "对外交换/上报时走任务、回执、重试和对账闭环"],
      pitfalls: ["数据中心只能消费权威业务事实，不能反向篡改业务结果", "报文发送成功不等于对方已接收对账成功"],
      next: { label: "查看数据质量与治理", route: "/hr/data/quality/" },
      prompts: ["某个指标口径从哪里来的？", "为什么接口显示发送成功但任务还没完成？", "同步失败如何单条重试？", "正式报送前要通过哪些数据质量检查？"],
    },
  };

  const TASKS = [
    ["查看今天待办", "HR01", "/hr/todos", "待办 审批 今天 逾期", "先看今天和逾期事项，直接进入对应业务处理。"],
    ["查看人事风险预警", "HR01", "/hr/alerts", "预警 风险 到期 异常", "集中查看合同、资质、数据等风险入口。"],
    ["查组织机构", "HR02", "/hr/structure/organizations", "学院 部门 组织 架构", "查询或维护学院、部门等组织关系。"],
    ["查岗位和编制", "HR02", "/hr/structure/positions", "岗位 编制 容量 空岗", "查看岗位台账、占用和容量。"],
    ["查教职工档案", "HR03", "/hr/staff/", "教师 员工 人员 档案 名册 主档", "按姓名/编号定位教职工正式主档。"],
    ["检查人员数据质量", "HR03", "/hr/staff/data-quality/", "数据质量 缺失 重复 异常", "查看人员主档缺失、冲突和治理问题。"],
    ["建立年度用人计划", "HR04", "/hr/recruitment/plans", "招聘 用人 计划 年度", "从年度需求开始建立招聘来源。"],
    ["新建招聘项目", "HR04", "/hr/recruitment/campaigns", "招聘 项目 发布 岗位", "创建招聘项目并绑定正式岗位。"],
    ["处理候选人资格审查", "HR04", "/hr/recruitment/qualification", "候选人 资格 审查 材料", "核对候选人资格和材料。"],
    ["办理新教职工入职", "HR05", "/hr/onboarding/prehires", "入职 报到 新员工 新教师 待报到", "从待报到人员进入身份、材料和正式激活流程。"],
    ["做入职材料核验", "HR05", "/hr/onboarding/materials", "入职 材料 证件 核验", "统一核验入职必需材料。"],
    ["处理试用与转正", "HR05", "/hr/onboarding/probations", "试用 转正 新员工", "跟踪试用期和转正决策。"],
    ["发起校内调动/转岗", "HR06", "/hr/changes/transfers", "调动 转岗 异动 部门 岗位", "办理校内组织/岗位变更。"],
    ["查看异动台账", "HR06", "/hr/changes/ledger", "异动 台账 历史 生效", "核对已生效及历史异动记录。"],
    ["办理合同续签", "HR07", "/hr/contracts/signing/", "合同 续签 签订 聘期", "从合同台账进入签订或续签。"],
    ["查看合同到期风险", "HR07", "/hr/contracts/risks/", "合同 到期 风险 预警", "优先处理临近到期和异常合同。"],
    ["建立外聘教师", "HR08", "/hr/external-teachers/", "外聘 兼职 产业教授 技能大师", "维护外聘人员准入和基本档案。"],
    ["办理外聘续聘/退出", "HR08", "/hr/external-teachers/renewals/", "外聘 续聘 退出", "处理聘期到期后的续聘或退出。"],
    ["登记教师资格/证书", "HR09", "/hr/qualifications/credentials/", "教师资格 证书 资质 登记", "录入并核验教师资格和相关证书。"],
    ["查看资质到期风险", "HR09", "/hr/qualifications/risks/", "资质 到期 续证 风险", "查看到期、续证和复核事项。"],
    ["建立教师发展计划", "HR10", "/hr/development/plans", "教师发展 培训 计划 培养", "建立学校/学院/个人发展计划。"],
    ["处理培训申请", "HR10", "/hr/development/requests", "培训 申请 审批 进修", "处理教师培训和发展申请。"],
    ["管理企业实践", "HR10", "/hr/development/practice", "企业实践 实习 研修", "管理企业实践项目、过程和人员。"],
    ["处理请假/加班", "HR11", "/hr/time/", "请假 加班 考勤 时间", "进入时间工作区处理请假、加班和异常。"],
    ["查看考勤异常", "HR11", "/hr/time/attendance/", "考勤 异常 打卡 排班", "先处理异常再进行月结。"],
    ["建立年度考核周期", "HR12", "/hr/assessments/policies/", "考核 年度 指标 权重 规则", "配置考核制度、周期、指标和权重。"],
    ["处理考核确认/异议", "HR12", "/hr/assessments/review/", "考核 异议 确认 复核", "处理教师核对、分级确认和异议。"],
    ["发起职称申报", "HR13", "/hr/titles/applications/", "职称 申报 资格 评审", "进入批次、申报和资格审查。"],
    ["处理职称公示异议", "HR13", "/hr/titles/appeals/", "职称 公示 异议 复核", "办理结果公示后的异议复核。"],
    ["发起岗位聘任", "HR14", "/hr/appointments/quota/", "岗位聘任 竞聘 额度 聘期", "先确认岗位额度，再推进竞聘。"],
    ["做月度工资核算", "HR15", "/hr/payroll/calculations/", "工资 薪酬 核算 月度", "创建工资期间并执行计算复核。"],
    ["查看工资支付对账", "HR15", "/hr/payroll/payments/", "工资 支付 财务 对账 工资条", "核对工资结果、支付和财务回执。"],
    ["办理辞职/调出离校", "HR16", "/hr/exit/cases/", "离校 辞职 调出 解除", "发起离校并推进交接、结算。"],
    ["办理退休", "HR16", "/hr/exit/retirement-precheck/", "退休 离退 预审", "从退休预审进入正式退休办理。"],
    ["查看我的申请进度", "HR17", "/hr/self/todos/", "本人 申请 进度 待办 补件", "查看本人申请、退回补件和办理状态。"],
    ["申请个人档案更正", "HR17", "/hr/self/files/", "本人 档案 更正 纠错", "由本人发起档案补件或更正。"],
    ["查看工资条/合同", "HR17", "/hr/self/payslips/", "本人 工资条 合同 文件", "查看本人授权范围内的薪酬权益文件。"],
    ["检查人事数据质量", "HR18", "/hr/data/quality/", "数据质量 治理 缺失 重复", "在报表/交换前处理数据质量问题。"],
    ["查看接口同步失败", "HR18", "/hr/data/exchange/", "接口 同步 失败 重试 映射", "查看最近同步、失败原因并按规则重试。"],
    ["做人事报表/专题分析", "HR18", "/hr/data/population/", "报表 统计 分析 人员 结构", "使用标准报表和自助分析。"],
    ["做正式数据上报", "HR18", "/hr/data/submissions/", "报送 上报 数据交换", "从质量检查进入正式上报和回执对账。"],
  ].map(([title, module, route, keywords, description]) => ({ title, module, route, keywords, description }));

  // Cross-module "journeys" reduce learning cost for work that spans multiple HR domains.
  // These are guidance-only routes: they never infer completion or mutate business state.
  const JOURNEYS = [
    {
      id: "employee-lifecycle-full",
      title: "教职工全生命周期：从招聘到数据中心",
      keywords: "全流程 全生命周期 招聘 入职 主档 合同 异动 资质 培训 考勤 考核 聘任 薪酬 离退 本人服务 数据中心",
      summary: "按学校人事经办顺序把 14 个核心环节串成一条路线。路线只记录导航进度，不替代任何审批、核验或正式生效。",
      steps: [
        ["HR04", "招聘：确认用人计划、项目与拟录用", "/hr/recruitment/campaigns"],
        ["HR05", "入职：报到、材料核验与正式激活", "/hr/onboarding/prehires"],
        ["HR03", "主档：复核身份、组织岗位与任职关系", "/hr/staff/"],
        ["HR07", "合同：签订、续签与聘期风险", "/hr/contracts/"],
        ["HR06", "异动：调动、转岗与身份变更", "/hr/changes/transfers"],
        ["HR09", "资质：资格证书、有效期与核验", "/hr/qualifications/credentials/"],
        ["HR10", "培训：发展计划、培训与企业实践", "/hr/development/plans"],
        ["HR11", "考勤：排班、考勤、请假与月结", "/hr/time/attendance/"],
        ["HR12", "考核：年度考核、异议与归档", "/hr/assessments/annual/"],
        ["HR14", "聘任：岗位额度、竞聘与正式聘任", "/hr/appointments/appointments/"],
        ["HR15", "薪酬：月度核算、结果与对账", "/hr/payroll/calculations/"],
        ["HR16", "离退：离校、退休、交接与结算", "/hr/exit/cases/"],
        ["HR17", "教职工本人服务：本人申请、补件与进度", "/hr/self/services/"],
        ["HR18", "数据中心：质量、统计、交换与正式报送", "/hr/data/quality/"],
      ],
    },
    {
      id: "new-hire",
      title: "新教职工从录用到正常发薪",
      keywords: "新员工 新教师 录用 入职 合同 考勤 工资 发薪",
      summary: "把招聘录用、报到建档、合同、考勤和首月薪酬串成一条办理路线。",
      steps: [
        ["HR04", "确认拟录用结果", "/hr/recruitment/proposed-hires"],
        ["HR05", "办理报到与材料核验", "/hr/onboarding/prehires"],
        ["HR03", "复核正式教职工主档", "/hr/staff/"],
        ["HR07", "签订/核验聘用合同", "/hr/contracts/signing/"],
        ["HR11", "确认排班与考勤入口", "/hr/time/attendance/"],
        ["HR15", "进入首月工资核算", "/hr/payroll/calculations/"],
      ],
    },
    {
      id: "transfer",
      title: "教师校内调动/转岗",
      keywords: "调动 转岗 换部门 换学院 换岗位 异动",
      summary: "先核目标岗位，再走异动，最后复核主档、考勤和薪酬影响。",
      steps: [
        ["HR02", "核对目标岗位与容量", "/hr/structure/positions"],
        ["HR06", "发起校内调动/转岗", "/hr/changes/transfers"],
        ["HR03", "复核任职关系更新", "/hr/staff/"],
        ["HR11", "检查排班/考勤影响", "/hr/time/attendance/"],
        ["HR15", "检查薪酬影响", "/hr/payroll/calculations/"],
      ],
    },
    {
      id: "renewal",
      title: "合同到期续签",
      keywords: "合同 续签 到期 聘期 延期",
      summary: "从到期风险进入续签，不直接覆盖旧合同，并复核人员聘用关系。",
      steps: [
        ["HR07", "先看合同到期风险", "/hr/contracts/risks/"],
        ["HR07", "发起签订/续签", "/hr/contracts/signing/"],
        ["HR03", "复核聘用关系与主档", "/hr/staff/"],
      ],
    },
    {
      id: "title-appointment",
      title: "职称评审到岗位聘任",
      keywords: "职称 评审 聘任 岗位 竞聘 晋升",
      summary: "职称正式结果与岗位聘任分开办理，再检查任职和薪酬影响。",
      steps: [
        ["HR13", "发起职称申报/评审", "/hr/titles/applications/"],
        ["HR14", "进入岗位额度与聘任", "/hr/appointments/quota/"],
        ["HR03", "复核任职事实", "/hr/staff/"],
        ["HR15", "核对薪酬影响", "/hr/payroll/calculations/"],
      ],
    },
    {
      id: "retirement",
      title: "退休/离校完整办理",
      keywords: "退休 离校 离职 辞职 调出 清退 结算",
      summary: "从退休/离校预审开始，完成合同、权限资产、薪酬结算和人事归档。",
      steps: [
        ["HR16", "发起退休预审或离校", "/hr/exit/retirement-precheck/"],
        ["HR07", "核对合同与解除/终止", "/hr/contracts/risks/"],
        ["HR15", "完成薪酬结算核对", "/hr/payroll/calculations/"],
        ["HR03", "复核离退后人员事实", "/hr/staff/"],
      ],
    },
    {
      id: "development-review",
      title: "教师发展到年度考核",
      keywords: "培训 发展 实践 资质 考核 年度 双师",
      summary: "把发展活动和已核验资质作为正式来源，再进入年度考核。",
      steps: [
        ["HR10", "查看教师发展计划与事实", "/hr/development/plans"],
        ["HR09", "核对正式资质与有效期", "/hr/qualifications/credentials/"],
        ["HR12", "进入年度考核", "/hr/assessments/policies/"],
      ],
    },
  ].map((journey) => ({
    ...journey,
    steps: journey.steps.map(([module, label, route]) => ({ module, label, route })),
  }));

  const FULL_LIFECYCLE_ID = "employee-lifecycle-full";
  const MODULE_EXTRA_PROMPTS = Object.freeze({
    HR01: ["今天最少只处理哪些待办？", "不知道入口时怎么按事情直接找到页面？", "数据异常时先查什么再处理？"],
    HR02: ["新建岗位最少要填哪些？", "岗位类别和等级哪些可以直接从学校方案带入？", "岗位方案不生效时先检查什么？"],
    HR03: ["入职完成后哪些资料可以自动进入主档？", "档案更正时哪些没有变化的字段不用重填？", "发现重复人员时先怎么处理？"],
    HR04: ["新建招聘项目最少要填哪些？", "招聘岗位哪些信息可以从 HR02 自动带入？", "拟录用后下一步怎么进入入职？"],
    HR05: ["办理报到最少需要补哪些现场信息？", "招聘阶段哪些信息可以直接带入入职？", "入职材料被退回后只需要改哪些？"],
    HR06: ["办理调动最少需要填哪些变化项？", "当前组织岗位哪些可以自动带入？", "异动失败或退回后只改哪些内容？"],
    HR07: ["续签合同最少需要重新确认哪些？", "原合同哪些稳定信息可以沿用？", "合同到期后下一步怎么处理？"],
    HR08: ["外聘续聘最少需要重新填什么？", "已有外聘身份哪些资料可以沿用？", "外聘退出时还缺哪些清退材料？"],
    HR09: ["资质续证最少需要补哪些新信息？", "旧证哪些稳定信息可以自动带入？", "资质材料被退回后只需要改哪些？"],
    HR10: ["培训报名最少需要填哪些？", "选择培训项目后哪些信息可以自动带入？", "导入失败后只需要处理哪些错误行？"],
    HR11: ["请假或加班最少需要填哪些？", "人员排班和组织哪些可以自动带入？", "考勤异常时先检查什么？"],
    HR12: ["新考核周期最少需要重新配置哪些？", "哪些考核数据可以从其他 HR 模块自动取数？", "考核退回或异议时只需要处理哪些项？"],
    HR13: ["职称申报最少需要本人补哪些材料？", "哪些任职和成果信息可以从主档带入？", "材料被退回后只需要补哪些？"],
    HR14: ["正式聘任最少需要确认哪些？", "岗位额度和资格信息哪些可以自动带入？", "聘任生效后下一步会影响哪些模块？"],
    HR15: ["月度工资核算最少需要人工处理什么？", "考勤和聘任哪些数据会自动进入核算？", "工资异常时先查什么再重算？"],
    HR16: ["退休或离校最少需要补哪些变化信息？", "合同主档薪酬哪些信息可以自动带入？", "离退事项被退回后只需要改哪些？"],
    HR17: ["本人申请最少需要填写哪些变化项？", "我的主档合同工资条哪些不用重复填？", "申请被退回后只需要补哪些内容？"],
    HR18: ["常用报表最少需要选择哪些筛选条件？", "指标口径和组织范围哪些可以自动带入？", "接口同步失败后只需要重试哪些数据？"],
  });

  const GENERIC_PROMPTS = [
    "这个页面最少必须填什么？",
    "哪些信息可以从前一环节或主档自动带入？",
    "哪些字段可以先不填，后面再补？",
    "我只想完成最小必需步骤，怎么做？",
    "这个环节办完后下一步去哪里？",
    "有没有可以沿用上一笔或上一周期的内容？",
    "这个状态是什么意思，我现在还能继续吗？",
    "如果被退回或失败，我只需要改哪些内容？",
    "提交前帮我核对一下还缺什么？",
    "哪些已有值不需要我重复填写？",
    "哪些字段必须人工确认，不能自动填？",
    "我只想改一项，最短怎么操作？",
    "我不确定的选填项可以先不填吗？",
    "这个字段为什么要填？",
    "提交以后通常还要谁处理？",
    "系统已经帮我带入了什么？",
  ];

  const WORKFLOW_AUTOFILL = Object.freeze({
    HR01: ["无需先记菜单：直接按要办的事搜索", "最近办理和全生命周期路线会保留导航进度", "首页摘要只做入口，不要求重复填写业务数据"],
    HR02: ["岗位类别使用系统已内置的管理岗、专业技术岗、工勤技能岗等目录", "岗位等级从当前学校有效等级方案选择，不手输代码", "组织、岗位和编制一经维护，后续人员流程直接引用"],
    HR03: ["从正式入职单带入已经核验的身份引用、组织、岗位和任职起始信息", "已有人员再次办理时只改变化项，不重复建立第二份人员", "历史错误走更正链，不要求用户重新抄整份档案"],
    HR04: ["招聘岗位直接引用 HR02 正式岗位和容量", "项目编号可以一键生成，避免手工编流水号", "拟录用结果进入 HR05 后复用候选人已核验信息"],
    HR05: ["从拟录用结果带入人员、岗位、组织和录用来源", "报到环节只补实际到校时间、地点、核验结果等现场事实", "正式激活后把已核验信息交给 HR03，不再让经办人二次抄录"],
    HR06: ["选定教职工后沿用当前组织、岗位和任职事实作为变更前值", "经办人重点只填异动类型、目标组织/岗位、生效日和原因", "生效后由 HR03 接收正式任职事实，不手工回写主档"],
    HR07: ["选择教职工后自动加载当前有效聘用关系", "续签应复制原合同人员、合同类型和模板，只填新期限与必要说明", "项目/合同/业务单编号可一键生成，减少手工流水号"],
    HR08: ["外聘人员已有身份时直接复用，不重复建档", "续聘沿用原聘用范围和已核验资料，只确认新聘期与变化项", "退出时从现有任务和权限生成清退清单"],
    HR09: ["人员身份从 HR03 主档选择，不重复填写姓名、组织和岗位", "续证沿用资质类别、发证机构等稳定信息，只补新证号、有效期和新附件", "已用于历史考核的材料保留版本，不让用户重新上传覆盖"],
    HR10: ["培训申请选择项目后带入主办方、班次、时间和规则", "人员及学院从 HR03 主档引用，不重复填个人基础信息", "历史 Excel 使用模板、字典和预览确认，避免逐行重复录入"],
    HR11: ["人员和组织从 HR03 当前有效任职获取", "当前有效排班直接显示；请假/加班只填时间、类型、原因和必要附件", "月结后下游薪酬读取封板事实，不再重复录考勤结果"],
    HR12: ["新周期优先复制上一周期规则，再调整变化项", "组织、岗位、资质、培训、考勤等从权威模块自动取数", "经办人重点处理异常、异议和人工调整，而不是逐个教师抄数据"],
    HR13: ["申报人身份和任职信息从 HR03 引用", "代表性成果尽量引用已有正式成果/附件，不重复上传同一材料", "新批次可复用上一批次材料清单和规则后再调整"],
    HR14: ["岗位额度直接引用 HR02，人员资格引用正式任职/职称结果", "正式聘任重点确认岗位等级、生效日和聘期，不重复填写个人档案", "聘任生效后由下游薪酬读取正式结果"],
    HR15: ["人员薪酬档案、考勤封板、岗位聘任和规则自动取数", "经办人优先处理异常项和需要人工确认的调整", "封板后支付/工资条/对账沿用同一结果，不重复造数"],
    HR16: ["从主档、合同和薪酬状态生成离退办理上下文", "交接按学校模板生成任务清单，经办人只确认完成情况和证据", "正式离退后同步本人服务和数据中心，不重复维护第二份离退休档案"],
    HR17: ["本人身份自动锁定为当前登录教职工，禁止手工切换他人", "已有主档、合同、工资条直接展示；申请只填写变化项、诉求和补件", "退回时直接定位缺什么，不要求重新提交整份申请"],
    HR18: ["指标口径、组织范围和接口映射从已配置规则带入", "常用报表使用预设筛选，用户只调整时间/组织等少量条件", "交换重试沿用原业务主键和映射，不重新录一遍业务数据"],
  });

  const moduleCode = root.dataset.module || "HR01";
  const moduleInfo = MODULES[moduleCode] || MODULES.HR01;
  const currentPath = window.location.pathname;

  function textEl(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = text;
    return el;
  }

  function safeJsonParse(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    try {
      const parsed = JSON.parse(value);
      return parsed === null || parsed === undefined ? fallback : parsed;
    } catch (_) { return fallback; }
  }

  function storageGet(key) {
    try {
      if (window.localStorage) {
        const value = window.localStorage.getItem(key);
        if (value !== null) return value;
      }
    } catch (_) { /* storage may be unavailable in hardened/private contexts */ }
    return MEMORY_STORAGE.has(key) ? MEMORY_STORAGE.get(key) : null;
  }

  function storageSet(key, value) {
    MEMORY_STORAGE.set(key, value);
    try { if (window.localStorage) window.localStorage.setItem(key, value); } catch (_) { /* keep in-memory fallback */ }
  }

  function findCurrentTask() {
    return TASKS
      .filter((task) => currentPath === task.route || currentPath.startsWith(task.route.endsWith("/") ? task.route : `${task.route}/`))
      .sort((a, b) => b.route.length - a.route.length)[0] || null;
  }

  function recordRecent(task) {
    const current = safeJsonParse(storageGet(STORAGE.recent), []);
    const next = [task, ...current.filter((item) => item.route !== task.route)].slice(0, 6);
    storageSet(STORAGE.recent, JSON.stringify(next));
  }

  function recentTasks() {
    const raw = safeJsonParse(storageGet(STORAGE.recent), []);
    if (!Array.isArray(raw)) return [];
    return raw
      .map((item) => TASKS.find((task) => task.route === item.route))
      .filter(Boolean)
      .slice(0, 6);
  }

  function clearRecent() {
    storageSet(STORAGE.recent, "[]");
  }

  const QUERY_ALIASES = new Map([
    ["换部门", "调动"], ["换学院", "调动"], ["换岗位", "转岗"], ["转部门", "调动"],
    ["新员工", "入职"], ["新教师", "入职"], ["报到", "入职"], ["转正", "试用转正"],
    ["续合同", "合同续签"], ["合同快到期", "合同到期"], ["合同过期", "合同到期"],
    ["证书过期", "资质到期"], ["证书快到期", "资质到期"], ["教师证", "教师资格"],
    ["评职称", "职称"], ["升职称", "职称"], ["竞聘", "岗位聘任"],
    ["工资单", "工资条"], ["工资明细", "工资条"], ["算工资", "工资核算"], ["涨工资", "薪酬"],
    ["离职", "离校"], ["辞职", "离校"], ["离岗", "离校"], ["退下来", "退休"],
    ["请假", "请假考勤"], ["加班", "加班考勤"], ["打卡异常", "考勤异常"],
    ["数据上报", "正式数据上报"], ["接口报错", "接口同步失败"], ["同步失败", "接口同步失败"],
    ["改档案", "档案更正"], ["档案错了", "档案更正"], ["我的申请", "申请进度"],
    ["新入职怎么办", "入职"], ["员工报到", "入职"], ["老师报到", "入职"],
    ["换科室", "调动"], ["调学院", "调动"], ["岗位调整", "转岗"],
    ["证书续期", "资质续证"], ["资格证续期", "资质续证"], ["证书到期怎么办", "资质到期"],
    ["培训报名", "培训申请"], ["进修", "培训"], ["企业实践", "企业实践"],
    ["年度考核", "考核"], ["考核退回", "考核"], ["考核有异议", "考核异议"],
    ["聘岗", "岗位聘任"], ["上岗", "岗位聘任"],
    ["退休怎么办", "退休"], ["退休手续", "退休"], ["离校手续", "离校"],
    ["我想改信息", "本人更正"], ["补材料", "补件"], ["数据不对", "数据核对"],
  ]);

  // 高频人事术语用大白话解释，避免用户必须先学习系统术语再办事。
  const GLOSSARY = Object.freeze({
    "草稿": "还没有提交给下一环节，通常只有本人或有权限的经办人可继续修改。",
    "提交": "把当前填写内容送入正式业务流程；提交成功不等于审批通过或业务生效。",
    "退回": "当前环节没有通过，但通常允许补充或修改后再次提交；先看退回原因再处理。",
    "审批": "由有权限的责任人对申请作出同意、退回或拒绝等流程决定。",
    "核验": "检查材料、身份或数据是否真实、完整、符合规则；核验通过也不一定等于最终生效。",
    "生效": "业务结果已经按规则进入正式有效状态，下游模块才应把它当作当前事实使用。",
    "待生效": "流程可能已通过，但还没到生效日期或还缺正式执行动作，当前事实尚未切换。",
    "封板": "把一个周期的正式结果冻结下来，后续不能直接改原值；发现错误要走更正或调整流程。",
    "归档": "把本周期或本事项的正式结果和依据固定保存，供以后查询、审计和历史还原。",
    "快照": "保存某个时间点当时的正式数据和规则，避免以后数据变化后看不出当时为什么得出这个结果。",
    "更正": "不直接抹掉历史记录，而是留下纠错依据和前后关系，形成可追溯的新事实。",
    "冲销": "用一条反向或调整记录抵消原结果，原记录仍保留，常用于薪酬、积分等正式台账。",
    "版本": "同一规则、合同、材料或结果的不同历史阶段；新版本启用后旧版本仍要保留。",
    "历史时点": "按过去某一天当时已经生效的数据看结果，而不是拿今天的数据倒推过去。",
    "权威事实": "系统认可的正式来源。其他模块只能引用它，不能在自己模块里再造一份同类正式数据。",
    "数据范围": "当前账号被允许查看和处理的数据边界，例如本人、本教研室、本学院或全校。",
    "部分可用": "只有一部分来源或范围的数据可靠，不能把当前数字当成完整全量结果。",
    "暂不可用": "当前没有足够可靠的数据返回；它不等于 0，也不等于没有业务记录。",
    "回执": "对方系统或下游环节返回的处理结果，用来证明数据不仅发出去了，而且被怎样接收和处理。",
    "对账": "把两边的正式记录逐项核对，确认数量、金额、状态或业务结果一致，并处理差异。",
    "幂等": "同一个业务请求重复发送时，不应重复创建或重复扣减数据；常用于接口、导入和支付类动作。",
    "预览": "正式写入或生效前先看将发生什么变化；预览本身不会自动成为正式结果。",
    "数据质量": "检查缺失、重复、冲突、格式错误、组织归属异常等问题，先保证数据可信再做统计或业务决策。",
    "正式结果": "已经完成规定流程并由权威模块确认的结果，不是页面颜色、草稿、上传成功或前端提示。",
    "在途": "业务已经发起但还没有走完，例如待审批、待补件、待核验或待生效。",
    "继任记录": "对旧正式记录的后续更正或新版本；通过前后关联保留完整历史，不直接覆盖旧记录。",
  });

  const MODULE_GLOSSARY = Object.freeze({
    HR01: ["数据范围", "部分可用", "暂不可用", "在途", "正式结果", "数据质量"],
    HR02: ["生效", "待生效", "历史时点", "权威事实", "版本", "预览"],
    HR03: ["权威事实", "更正", "历史时点", "快照", "数据范围", "继任记录"],
    HR04: ["草稿", "提交", "核验", "审批", "在途", "正式结果"],
    HR05: ["核验", "审批", "生效", "在途", "正式结果", "数据范围"],
    HR06: ["审批", "预览", "生效", "待生效", "更正", "历史时点"],
    HR07: ["版本", "生效", "待生效", "归档", "更正", "正式结果"],
    HR08: ["核验", "审批", "数据范围", "生效", "归档", "正式结果"],
    HR09: ["核验", "版本", "快照", "归档", "更正", "正式结果"],
    HR10: ["预览", "核验", "幂等", "归档", "权威事实", "正式结果"],
    HR11: ["封板", "更正", "快照", "在途", "正式结果", "历史时点"],
    HR12: ["封板", "快照", "归档", "更正", "版本", "正式结果"],
    HR13: ["核验", "审批", "归档", "更正", "正式结果", "在途"],
    HR14: ["审批", "生效", "待生效", "归档", "正式结果", "版本"],
    HR15: ["封板", "冲销", "对账", "更正", "快照", "正式结果"],
    HR16: ["审批", "生效", "归档", "更正", "正式结果", "在途"],
    HR17: ["提交", "退回", "在途", "数据范围", "正式结果", "核验"],
    HR18: ["回执", "对账", "幂等", "数据质量", "历史时点", "权威事实"],
  });

  function normalize(value) {
    return String(value || "").toLowerCase().replace(/\s+/g, "");
  }

  function glossaryQuery(value) {
    return normalize(value)
      .replace(/是什么意思|什么意思|什么叫|含义|怎么理解|解释一下|解释/g, "");
  }

  function glossaryMatches(query, limit = 4) {
    const q = glossaryQuery(query);
    if (!q) return [];
    return Object.entries(GLOSSARY)
      .map(([term, description]) => ({ term, description, score: normalize(term) === q ? 100 : normalize(term).includes(q) || q.includes(normalize(term)) ? 70 : normalize(description).includes(q) ? 25 : 0 }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || a.term.localeCompare(b.term, "zh-CN"))
      .slice(0, limit);
  }

  function queryVariants(query) {
    const raw = String(query || "").trim();
    if (!raw) return [""];
    const normalized = normalize(raw);
    const variants = new Set([raw]);
    QUERY_ALIASES.forEach((canonical, alias) => {
      if (normalized.includes(normalize(alias))) variants.add(canonical);
    });
    return Array.from(variants);
  }

  function scoreTaskOne(task, query) {
    const q = normalize(query);
    if (!q) return task.module === moduleCode ? 20 : 0;
    const title = normalize(task.title);
    const keywords = normalize(task.keywords);
    const moduleName = normalize((MODULES[task.module] || {}).name);
    let score = 0;
    if (title === q) score += 100;
    if (title.includes(q)) score += 70;
    if (keywords.includes(q)) score += 55;
    if (moduleName.includes(q) || normalize(task.module).includes(q)) score += 35;
    for (const token of String(query).trim().split(/\s+/).filter(Boolean)) {
      const t = normalize(token);
      if (title.includes(t)) score += 20;
      if (keywords.includes(t)) score += 12;
    }
    if (score > 0 && task.module === moduleCode) score += 5;
    return score;
  }

  function scoreTask(task, query) {
    return Math.max(...queryVariants(query).map((variant) => scoreTaskOne(task, variant)));
  }

  function scoreJourneyOne(journey, query) {
    const q = normalize(query);
    if (!q) return journey.steps.some((step) => step.module === moduleCode) ? 12 : 0;
    const title = normalize(journey.title);
    const keywords = normalize(journey.keywords);
    const summary = normalize(journey.summary);
    let score = 0;
    if (title === q) score += 100;
    if (title.includes(q)) score += 70;
    if (keywords.includes(q)) score += 55;
    if (summary.includes(q)) score += 25;
    for (const token of String(query).trim().split(/\s+/).filter(Boolean)) {
      const t = normalize(token);
      if (title.includes(t)) score += 18;
      if (keywords.includes(t)) score += 12;
      if (summary.includes(t)) score += 6;
    }
    return score;
  }

  function scoreJourney(journey, query) {
    return Math.max(...queryVariants(query).map((variant) => scoreJourneyOne(journey, variant)));
  }

  function rankedJourneys(query, limit = 3) {
    return JOURNEYS
      .map((journey) => ({ journey, score: scoreJourney(journey, query) }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || a.journey.title.localeCompare(b.journey.title, "zh-CN"))
      .slice(0, limit)
      .map((item) => item.journey);
  }

  function modulePrompts() {
    return Array.from(new Set([...(moduleInfo.prompts || []), ...(MODULE_EXTRA_PROMPTS[moduleCode] || []), ...GENERIC_PROMPTS]));
  }

  function autofillNotes() {
    return WORKFLOW_AUTOFILL[moduleCode] || ["只填写当前环节真正发生变化的内容；稳定信息应从权威主档或上一环节引用。"];
  }

  function currentFormState() {
    const forms = Array.from(root.querySelectorAll("form")).filter((form) => form.offsetParent !== null || !form.hidden);
    const form = forms.find((item) => item.querySelector("input, select, textarea"));
    if (!form) return null;
    const required = Array.from(form.querySelectorAll("input[required], select[required], textarea[required]")).filter((el) => el.type !== "hidden" && !el.disabled);
    const missing = required.filter((el) => {
      if (el.type === "checkbox" || el.type === "radio") return !el.checked;
      return String(el.value || "").trim() === "";
    });
    const label = (el) => {
      const node = el.closest("label") || (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null);
      return String(node?.textContent || el.getAttribute("aria-label") || el.name || "字段").replace(/必填|已有值|已带入|可选/g, "").trim();
    };
    return {
      requiredCount: required.length,
      completedCount: required.length - missing.length,
      missingLabels: Array.from(new Set(missing.map(label))).slice(0, 8),
    };
  }

  function buildSafePrompt(question) {
    // Explicitly exclude employee/person/case identifiers and all visible page text.
    const formState = currentFormState();
    const formLine = formState
      ? `当前表单只提供完成度元数据：必填 ${formState.completedCount}/${formState.requiredCount}${formState.missingLabels.length ? `；尚缺字段：${formState.missingLabels.join("、")}` : "；必填已齐"}。不包含任何字段值。`
      : "当前页面没有可识别的办理表单。";
    return [
      "你是高校人事系统办理助手。",
      `当前模块：${moduleCode} ${moduleInfo.name}。`,
      `当前页面路径类别：${currentPath.replace(/[0-9a-f]{8,}|\d{4,}/gi, ":id") }。`,
      formLine,
      `用户问题：${question}`,
      "请只解释办理步骤、前置条件、材料、状态含义和下一步；不得替代审批、资格认定、考核结论、薪酬结论或正式人事决定。",
      "如需查看个人敏感数据，请让用户回到系统对应业务页面，不要要求其把身份证号、工资、联系方式或附件正文复制到对话中。",
    ].join("\n");
  }

  function answerFor(question) {
    const q = String(question || "");
    let lines = [];
    const formState = currentFormState();
    if (/提交前|核对|还缺|必填/.test(q) && formState) {
      lines = [
        `当前表单必填完成度：${formState.completedCount}/${formState.requiredCount}。`,
        ...(formState.missingLabels.length ? [`还缺：${formState.missingLabels.join("、")}。`] : ["必填项已经齐全。"]),
        "可以直接点击表单顶部的“提交前核对”，系统只显示字段名称、缺项和本次改动数量，不展示敏感值。",
        "提交前仍需人工核对生效日期、期限、金额、审批依据等正式事实。",
      ];
    } else if (/为什么.*填|字段为什么|为什么要填/.test(q)) {
      lines = [
        "只保留办理当前事项真正需要的信息；系统不会为了凑字段要求你重复抄主档。",
        `当前模块目的：${moduleInfo.purpose}`,
        "如果字段标记为“可选”，且本次事项没有对应事实，可以先不填；如果是必填但你不确定，应先核对业务依据，不要猜。",
      ];
    } else if (/谁处理|谁审批|提交以后|提交后/.test(q)) {
      lines = [
        "提交只代表进入下一处理环节，不等于审批通过或正式生效。",
        "具体下一处理人以后端工作流、当前角色和组织数据范围为准。",
        moduleInfo.next ? `办理结束后常用入口：${moduleInfo.next.label}。` : "可回到当前模块工作台查看下一待办。",
      ];
    } else if (/只想改一项|只改一项|只修改/.test(q)) {
      lines = [
        "优先使用“只看必填/简洁模式”，只修改本次真正变化的字段。",
        "已有值、系统带入值不会在简洁模式里隐藏，提交前可点“提交前核对”查看本次改动字段。",
        "已核验且没有变化的历史事实不要重复填写或覆盖。",
      ];
    } else if (/最少|少填|自动带入|带入|沿用|复制上一|不用填|先不填/.test(q)) {
      lines = ["尽量少填的原则：", ...autofillNotes().map((item) => `• ${item}`), "• 页面里的正式必填校验仍以后端规则为准；系统不会为省事自动编造审批依据、资格结论、薪酬结果或学校专属政策。"];
    } else if (/第一次|从哪里|开始/.test(q)) {
      lines = ["建议按这个顺序：", ...moduleInfo.steps.map((item, i) => `${i + 1}. ${item}`)];
    } else if (/退回|失败|补件|被拒/.test(q)) {
      lines = ["先只改导致当前事项未通过的内容：", ...moduleInfo.pitfalls.map((item) => `• ${item}`), "• 优先查看退回/失败原因和缺项提示；已核验且没有变化的字段不要重复填写。", "• 如果系统提供‘沿用/带入’值，先核对再提交，不要为省事编造原因、日期或正式结论。"];
    } else if (/不能|为什么|卡|异常/.test(q)) {
      lines = ["先排查这几项：", ...moduleInfo.pitfalls.map((item) => `• ${item}`), "• 再确认当前账号权限、业务状态和前置数据是否满足；正式状态以后端返回为准。"];
    } else if (/材料|准备|字段|附件/.test(q)) {
      lines = ["办理前建议准备：", ...moduleInfo.prepare.map((item) => `• ${item}`)];
    } else if (/下一步|之后|然后/.test(q)) {
      lines = [moduleInfo.next ? `建议下一步：${moduleInfo.next.label}` : "建议回到当前模块工作台查看待办和状态。", "如果当前业务仍显示待审批/待核验，请先完成当前环节，不要跳过状态机。"];
    } else if (/影响|正式|生效/.test(q)) {
      lines = ["系统中的正式结果只由对应业务状态机和后端权限确认。", "页面提示、颜色、草稿、预览、上传成功或提交成功都不等于正式生效。", ...moduleInfo.pitfalls.map((item) => `• ${item}`)];
    } else {
      lines = [moduleInfo.purpose, "建议顺序：", ...moduleInfo.steps.slice(0, 3).map((item, i) => `${i + 1}. ${item}`)];
    }
    return lines.join("\n");
  }

  const launcher = document.createElement("button");
  launcher.type = "button";
  launcher.className = "hr-guide-launcher";
  launcher.setAttribute("aria-haspopup", "dialog");
  launcher.setAttribute("aria-controls", "hr-guide-drawer");
  launcher.innerHTML = '<span aria-hidden="true">⌕</span><span>办理助手</span><span class="hr-guide-launcher__key">Alt K</span>';

  const backdrop = document.createElement("div");
  backdrop.className = "hr-guide-backdrop";
  backdrop.hidden = true;

  const drawer = document.createElement("aside");
  drawer.id = "hr-guide-drawer";
  drawer.className = "hr-guide-drawer";
  drawer.hidden = true;
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-modal", "true");
  drawer.setAttribute("aria-labelledby", "hr-guide-title");

  const head = document.createElement("div");
  head.className = "hr-guide-drawer__head";
  const headCopy = document.createElement("div");
  headCopy.append(textEl("span", "hr-guide-drawer__eyebrow", `${moduleCode} · 办理助手`));
  const title = textEl("h2", "hr-guide-drawer__title", moduleInfo.name);
  title.id = "hr-guide-title";
  headCopy.append(title);
  const currentTask = findCurrentTask();
  if (currentTask) recordRecent(currentTask);
  headCopy.append(textEl("p", "hr-guide-drawer__page", currentTask ? `当前：${currentTask.title}` : `当前路径：${currentPath}`));
  const close = textEl("button", "hr-guide-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "关闭办理助手");
  head.append(headCopy, close);

  const body = document.createElement("div");
  body.className = "hr-guide-drawer__body";

  const searchWrap = document.createElement("div");
  searchWrap.className = "hr-guide-search-wrap";
  const search = document.createElement("input");
  search.className = "hr-guide-search";
  search.type = "search";
  search.autocomplete = "off";
  search.placeholder = "我要办什么？如：入职、续签、退休、工资、资质…";
  search.setAttribute("aria-label", "搜索人事业务任务");
  searchWrap.append(search);
  body.append(searchWrap);

  const tipline = document.createElement("div");
  tipline.className = "hr-guide-tipline";
  tipline.innerHTML = '<span>直接搜“要办的事”，不用记 HR 编号</span><span><kbd>Alt K</kbd> 打开</span>';
  body.append(tipline);

  const results = document.createElement("div");
  results.className = "hr-guide-search-results";
  results.setAttribute("aria-live", "polite");
  body.append(results);

  const journeyResults = document.createElement("div");
  journeyResults.className = "hr-guide-search-journeys";
  journeyResults.hidden = true;
  body.append(journeyResults);

  const glossaryResults = document.createElement("div");
  glossaryResults.className = "hr-guide-glossary-results";
  glossaryResults.hidden = true;
  body.append(glossaryResults);
  mountRecentTasks(body, true);

  function glossaryCard(term, description, compact = false) {
    const card = document.createElement("article");
    card.className = compact ? "hr-guide-glossary-card hr-guide-glossary-card--compact" : "hr-guide-glossary-card";
    card.append(textEl("strong", "", term), textEl("p", "", description));
    return card;
  }

  function renderGlossaryResults(query = "") {
    glossaryResults.replaceChildren();
    const matches = glossaryMatches(query);
    if (!matches.length) { glossaryResults.hidden = true; return; }
    glossaryResults.hidden = false;
    glossaryResults.append(textEl("div", "hr-guide-search-journeys__title", "术语大白话"));
    matches.forEach(({ term, description }) => glossaryResults.append(glossaryCard(term, description, true)));
  }

  function renderJourneyResults(query = "") {
    journeyResults.replaceChildren();
    const journeys = rankedJourneys(query, query ? 2 : 1);
    if (!journeys.length) {
      journeyResults.hidden = true;
      return;
    }
    journeyResults.hidden = false;
    journeyResults.append(textEl("div", "hr-guide-search-journeys__title", "这件事可能要跨模块办理"));
    journeys.forEach((journey) => journeyResults.append(createJourneyCard(journey, true)));
  }

  function renderResults(query = "") {
    const ranked = TASKS
      .map((task) => ({ task, score: scoreTask(task, query) }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || a.task.title.localeCompare(b.task.title, "zh-CN"))
      .slice(0, query ? 8 : 5);
    results.replaceChildren();
    if (!ranked.length) {
      results.append(textEl("div", "hr-guide-no-result", "没有找到直接入口。换成业务动作试试，例如“入职”“续签”“退休”“工资核算”“数据上报”。"));
      return;
    }
    for (const { task } of ranked) {
      const a = document.createElement("a");
      a.className = "hr-guide-result";
      a.href = task.route;
      const left = document.createElement("span");
      left.append(textEl("strong", "", task.title), textEl("small", "", task.description));
      const mod = textEl("span", "hr-guide-result__module", `${task.module} ${(MODULES[task.module] || {}).name || ""}`);
      a.append(left, mod);
      a.addEventListener("click", () => recordRecent(task));
      results.append(a);
    }
  }
  renderResults("");
  renderJourneyResults("");
  renderGlossaryResults("");
  search.addEventListener("input", () => {
    renderResults(search.value);
    renderJourneyResults(search.value);
    renderGlossaryResults(search.value);
  });

  function rankedTasks(query, limit = 8) {
    return TASKS
      .map((task) => ({ task, score: scoreTask(task, query) }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || a.task.title.localeCompare(b.task.title, "zh-CN"))
      .slice(0, limit)
      .map((item) => item.task);
  }

  function createTaskLink(task, compact = false) {
    const link = document.createElement("a");
    link.className = compact ? "hr-guide-home__result" : "hr-guide-result";
    link.href = task.route;
    const copy = document.createElement("span");
    copy.append(textEl("strong", "", task.title));
    if (!compact) copy.append(textEl("small", "", task.description));
    const meta = textEl("span", compact ? "hr-guide-home__module" : "hr-guide-result__module", `${task.module} ${(MODULES[task.module] || {}).name || ""}`);
    link.append(copy, meta);
    link.addEventListener("click", () => recordRecent(task));
    return link;
  }

  function createJourneyCard(journey, compact = false) {
    const card = document.createElement("article");
    card.className = compact ? "hr-guide-journey hr-guide-journey--compact" : "hr-guide-journey";
    const head = document.createElement("div");
    head.className = "hr-guide-journey__head";
    const copy = document.createElement("div");
    copy.append(textEl("strong", "", journey.title), textEl("p", "", journey.summary));
    const badge = textEl("span", "hr-guide-journey__badge", `${journey.steps.length} 步`);
    head.append(copy, badge);
    const steps = document.createElement("ol");
    steps.className = "hr-guide-journey__steps";
    journey.steps.forEach((step, index) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = step.route;
      a.append(
        textEl("span", "hr-guide-journey__index", String(index + 1)),
        textEl("span", "hr-guide-journey__label", step.label),
        textEl("span", "hr-guide-journey__module", `${step.module} ${(MODULES[step.module] || {}).name || ""}`),
      );
      a.addEventListener("click", () => {
        const task = TASKS.find((item) => item.route === step.route);
        if (task) recordRecent(task);
      });
      li.append(a);
      steps.append(li);
    });
    const note = textEl("div", "hr-guide-journey__note", "这是建议办理路线，不代表任何步骤已完成；正式状态以业务页面和后端结果为准。");
    card.append(head, steps, note);
    return card;
  }

  function mountRecentTasks(container, compact = false) {
    const items = recentTasks();
    if (!items.length) return null;
    const block = document.createElement("section");
    block.className = compact ? "hr-guide-recent hr-guide-recent--compact" : "hr-guide-recent";
    const head = document.createElement("div");
    head.className = "hr-guide-recent__head";
    head.append(textEl("strong", "", "最近办理"));
    const clear = textEl("button", "hr-guide-recent__clear", "清除");
    clear.type = "button";
    clear.addEventListener("click", () => { clearRecent(); block.remove(); });
    head.append(clear);
    const list = document.createElement("div");
    list.className = "hr-guide-recent__list";
    items.slice(0, compact ? 4 : 6).forEach((task) => list.append(createTaskLink(task, true)));
    block.append(head, list);
    container.append(block);
    return block;
  }

  function mountHomeTaskFinder() {
    if (moduleCode !== "HR01" || root.dataset.hrPage !== "overview") return;
    if (root.querySelector(".hr-guide-home")) return;

    const section = document.createElement("section");
    section.className = "hr-guide-home";
    section.setAttribute("aria-labelledby", "hr-guide-home-title");

    const head = document.createElement("div");
    head.className = "hr-guide-home__head";
    const headCopy = document.createElement("div");
    const title = textEl("h2", "", "我要办什么？");
    title.id = "hr-guide-home-title";
    headCopy.append(title, textEl("p", "", "不用先学 HR01～HR18，也不用记菜单。直接输入要办的事，系统带你到正确入口。"));
    const helper = textEl("button", "hr-guide-home__helper", "本页怎么用");
    helper.type = "button";
    helper.addEventListener("click", () => openDrawer({ focusSearch: false }));
    head.append(headCopy, helper);

    const input = document.createElement("input");
    input.type = "search";
    input.className = "hr-guide-home__search";
    input.autocomplete = "off";
    input.placeholder = "例如：新教师入职、合同续签、调动、资质到期、考核、工资、退休…";
    input.setAttribute("aria-label", "按要办理的事情搜索人事入口");

    const quick = document.createElement("div");
    quick.className = "hr-guide-home__quick";
    quick.setAttribute("aria-label", "常用业务");
    const quickQueries = ["入职", "合同续签", "调动", "资质到期", "考核", "工资核算", "退休", "接口同步"];
    quickQueries.forEach((query) => {
      const chip = textEl("button", "hr-guide-home__chip", query);
      chip.type = "button";
      chip.addEventListener("click", () => { input.value = query; renderHome(query); input.focus(); });
      quick.append(chip);
    });

    const output = document.createElement("div");
    output.className = "hr-guide-home__results";
    output.setAttribute("aria-live", "polite");

    const homeJourneys = document.createElement("div");
    homeJourneys.className = "hr-guide-home__journeys";
    homeJourneys.hidden = true;

    function renderHome(query = "") {
      output.replaceChildren();
      homeJourneys.replaceChildren();
      const matches = rankedTasks(query, query ? 6 : 5);
      if (!matches.length) {
        output.append(textEl("div", "hr-guide-home__empty", "暂时没有直接入口。换成动作试试，例如“入职”“续签”“退休”“工资核算”。"));
      } else {
        matches.forEach((task) => output.append(createTaskLink(task, true)));
      }
      const journeys = query ? rankedJourneys(query, 2) : [];
      if (journeys.length) {
        homeJourneys.hidden = false;
        homeJourneys.append(textEl("h3", "", "完整办理路线"));
        journeys.forEach((journey) => homeJourneys.append(createJourneyCard(journey, false)));
      } else {
        homeJourneys.hidden = true;
      }
    }

    input.addEventListener("input", () => renderHome(input.value));
    section.append(head, input, quick, output, homeJourneys);
    mountRecentTasks(section, true);
    const conclusions = root.querySelector(".hr-v2-conclusions");
    if (conclusions) conclusions.after(section);
    else root.prepend(section);
    renderHome("");
  }

  function section(titleText) {
    const s = document.createElement("section");
    s.className = "hr-guide-section";
    s.append(textEl("h3", "", titleText));
    body.append(s);
    return s;
  }

  const purposeSection = section("这页先搞清楚什么");
  purposeSection.append(textEl("p", "", moduleInfo.purpose));

  const stepsSection = section("建议按这个顺序办理");
  const stepsList = document.createElement("ol");
  stepsList.className = "hr-guide-list";
  moduleInfo.steps.forEach((item, index) => {
    const li = textEl("li", "", item);
    li.dataset.index = String(index + 1);
    stepsList.append(li);
  });
  stepsSection.append(stepsList);

  const prepareSection = section("办理前准备");
  const prepareList = document.createElement("ul");
  prepareList.className = "hr-guide-list hr-guide-list--plain";
  moduleInfo.prepare.forEach((item) => {
    const li = textEl("li", "", item);
    li.dataset.index = "•";
    prepareList.append(li);
  });
  prepareSection.append(prepareList);

  const autofillSection = section("少填一点：系统应该替你带什么");
  autofillSection.append(textEl("p", "hr-guide-section__hint", "稳定信息不重复抄；只填写当前环节的新事实或变化项。"));
  const autofillList = document.createElement("ul");
  autofillList.className = "hr-guide-list hr-guide-list--plain";
  autofillNotes().forEach((item) => {
    const li = textEl("li", "", item);
    li.dataset.index = "✓";
    autofillList.append(li);
  });
  autofillSection.append(autofillList);

  const glossarySection = section("看懂系统里的词");
  glossarySection.append(textEl("p", "hr-guide-section__hint", "这些词会影响你判断业务是否真的完成。点术语看大白话解释。"));
  const glossaryChips = document.createElement("div");
  glossaryChips.className = "hr-guide-glossary-chips";
  const glossaryAnswer = document.createElement("div");
  glossaryAnswer.className = "hr-guide-glossary-answer";
  glossaryAnswer.hidden = true;
  (MODULE_GLOSSARY[moduleCode] || MODULE_GLOSSARY.HR01).forEach((term) => {
    const btn = textEl("button", "hr-guide-glossary-chip", term);
    btn.type = "button";
    btn.addEventListener("click", () => {
      glossaryAnswer.replaceChildren(glossaryCard(term, GLOSSARY[term] || "暂无解释。"));
      glossaryAnswer.hidden = false;
    });
    glossaryChips.append(btn);
  });
  glossarySection.append(glossaryChips, glossaryAnswer);

  const promptSection = section("快捷问法");
  promptSection.append(textEl("p", "", "点一下先看系统内置说明；也可以复制成脱敏提问，后续接校内 AI/大模型时直接复用。"));
  const promptWrap = document.createElement("div");
  promptWrap.className = "hr-guide-prompts";
  promptWrap.style.marginTop = "10px";
  const answer = document.createElement("div");
  answer.className = "hr-guide-answer";
  answer.hidden = true;
  const answerText = document.createElement("div");
  const answerActions = document.createElement("div");
  answerActions.className = "hr-guide-answer__actions";
  const copyBtn = textEl("button", "hr-guide-copy", "复制脱敏提问");
  copyBtn.type = "button";
  answerActions.append(copyBtn);
  answer.append(answerText, answerActions);
  let activeQuestion = "";
  modulePrompts().forEach((prompt) => {
    const btn = textEl("button", "hr-guide-prompt", prompt);
    btn.type = "button";
    btn.addEventListener("click", () => {
      activeQuestion = prompt;
      answerText.textContent = answerFor(prompt);
      answer.hidden = false;
      answer.scrollIntoView({ block: "nearest" });
    });
    promptWrap.append(btn);
  });
  copyBtn.addEventListener("click", async () => {
    const text = buildSafePrompt(activeQuestion || modulePrompts()[0]);
    try {
      await navigator.clipboard.writeText(text);
      copyBtn.textContent = "已复制";
      window.setTimeout(() => { copyBtn.textContent = "复制脱敏提问"; }, 1400);
    } catch (_) {
      copyBtn.textContent = "复制失败，请手动选择";
    }
  });
  promptSection.append(promptWrap, answer);

  const riskSection = section("常见卡点");
  const riskList = document.createElement("ul");
  riskList.className = "hr-guide-list hr-guide-list--plain";
  moduleInfo.pitfalls.forEach((item) => {
    const li = textEl("li", "", item);
    li.dataset.index = "•";
    riskList.append(li);
  });
  riskSection.append(riskList);

  if (moduleInfo.next) {
    const nextSection = section("下一步入口");
    const next = textEl("a", "hr-guide-next", `${moduleInfo.next.label} →`);
    next.href = moduleInfo.next.route;
    nextSection.append(next);
  }

  const privacy = textEl(
    "div",
    "hr-guide-privacy",
    "隐私边界：办理助手不会读取或拼接人员姓名、身份证号、联系方式、工资、附件正文等敏感业务内容；它只使用当前 HR 模块和页面类型提供操作说明。正式审批、认定、考核、薪酬和人事结论仍由后端业务规则确认。"
  );
  body.append(privacy);

  drawer.append(head, body);
  document.body.append(launcher, backdrop, drawer);

  let lastFocused = null;
  function focusables() {
    return Array.from(drawer.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'));
  }
  function openDrawer({ focusSearch = false } = {}) {
    lastFocused = document.activeElement;
    drawer.hidden = false;
    backdrop.hidden = false;
    document.body.classList.add("hr-guide-body-lock");
    requestAnimationFrame(() => {
      drawer.classList.add("is-open");
      launcher.setAttribute("aria-expanded", "true");
      (focusSearch ? search : close).focus();
    });
  }
  function closeDrawer() {
    drawer.classList.remove("is-open");
    launcher.setAttribute("aria-expanded", "false");
    document.body.classList.remove("hr-guide-body-lock");
    window.setTimeout(() => {
      drawer.hidden = true;
      backdrop.hidden = true;
      if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
    }, 190);
  }
  launcher.addEventListener("click", () => openDrawer({ focusSearch: true }));
  close.addEventListener("click", closeDrawer);
  backdrop.addEventListener("click", closeDrawer);
  function lifecycleJourney() {
    return JOURNEYS.find((item) => item.id === FULL_LIFECYCLE_ID) || null;
  }

  function loadLifecycleState() {
    const state = safeJsonParse(storageGet(STORAGE.lifecycle), {});
    return state && typeof state === "object" ? state : {};
  }

  function saveLifecycleState(state) {
    storageSet(STORAGE.lifecycle, JSON.stringify(state || {}));
  }

  function lifecyclePathMatches(route) {
    const clean = String(route || "").replace(/\/+$/, "");
    const current = String(currentPath || "").replace(/\/+$/, "");
    return current === clean || (clean && current.startsWith(`${clean}/`));
  }

  function currentLifecycleIndex(journey) {
    if (!journey) return -1;
    return journey.steps.findIndex((step) => lifecyclePathMatches(step.route));
  }

  function mountLifecycleCoach() {
    const journey = lifecycleJourney();
    if (!journey || root.querySelector('.hr-guide-lifecycle')) return;
    let state = loadLifecycleState();
    const routeIndex = currentLifecycleIndex(journey);
    if (state.active && routeIndex >= 0 && routeIndex !== state.index) {
      state = { ...state, index: routeIndex, updatedAt: new Date().toISOString() };
      saveLifecycleState(state);
    }

    const coach = document.createElement('section');
    coach.className = 'hr-guide-lifecycle';
    coach.setAttribute('aria-label', '教职工全生命周期办理路线');

    const head = document.createElement('div');
    head.className = 'hr-guide-lifecycle__head';
    const copy = document.createElement('div');
    copy.append(textEl('span', 'hr-guide-lifecycle__eyebrow', '一条线办完 · 14 个核心环节'));
    copy.append(textEl('strong', 'hr-guide-lifecycle__title', '招聘 → 入职 → 主档 → 合同 → 异动 → 资质 → 培训 → 考勤 → 考核 → 聘任 → 薪酬 → 离退 → 本人服务 → 数据中心'));
    copy.append(textEl('p', 'hr-guide-lifecycle__desc', '只记录导航和核对进度，不代表任何审批、核验、发薪或人事结果已经完成。'));
    head.append(copy);

    const progress = document.createElement('div');
    progress.className = 'hr-guide-lifecycle__progress';
    const stepLabel = textEl('strong', '', '');
    const bar = document.createElement('div');
    bar.className = 'hr-guide-lifecycle__bar';
    const barFill = document.createElement('span');
    bar.append(barFill);
    progress.append(stepLabel, bar);

    const current = document.createElement('div');
    current.className = 'hr-guide-lifecycle__current';
    const actions = document.createElement('div');
    actions.className = 'hr-guide-lifecycle__actions';
    const primary = textEl('a', 'hr-guide-lifecycle__primary', '开始全流程');
    primary.href = journey.steps[0].route;
    const pause = textEl('button', 'hr-guide-lifecycle__secondary', '暂停');
    pause.type = 'button';
    const reset = textEl('button', 'hr-guide-lifecycle__secondary', '重新开始');
    reset.type = 'button';
    actions.append(primary, pause, reset);

    function render() {
      state = loadLifecycleState();
      const active = Boolean(state.active);
      const index = Math.min(Math.max(Number.isInteger(state.index) ? state.index : 0, 0), journey.steps.length - 1);
      const step = journey.steps[index];
      const pct = active ? Math.round(((index + 1) / journey.steps.length) * 100) : 0;
      barFill.style.width = `${pct}%`;
      stepLabel.textContent = active ? `第 ${index + 1}/${journey.steps.length} 步 · ${step.module}` : `共 ${journey.steps.length} 步 · 尚未开始`;
      current.replaceChildren();
      if (!active) {
        current.append(textEl('strong', '', '从招聘开始，系统每一步只让你确认当前环节真正需要的信息。'));
        current.append(textEl('span', '', '能从上一环节或权威主档带入的信息，不要求重复填写。'));
        primary.textContent = '开始 14 步全流程';
        primary.href = journey.steps[0].route;
        pause.hidden = true;
        reset.hidden = true;
        return;
      }
      current.append(textEl('strong', '', step.label));
      const notes = WORKFLOW_AUTOFILL[step.module] || [];
      if (notes[0]) current.append(textEl('span', '', `少填原则：${notes[0]}`));
      primary.textContent = index >= journey.steps.length - 1 ? '完成路线核对' : '本步骤已核对，去下一步';
      primary.href = index >= journey.steps.length - 1 ? '#' : journey.steps[index + 1].route;
      pause.hidden = false;
      reset.hidden = false;
    }

    primary.addEventListener('click', (event) => {
      state = loadLifecycleState();
      if (!state.active) {
        const start = { active: true, index: 0, startedAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
        saveLifecycleState(start);
        render();
        const first = journey.steps[0];
        if (lifecyclePathMatches(first.route)) event.preventDefault();
        return;
      }
      const index = Math.min(Math.max(Number.isInteger(state.index) ? state.index : 0, 0), journey.steps.length - 1);
      if (index >= journey.steps.length - 1) {
        event.preventDefault();
        saveLifecycleState({ ...state, active: false, completedAt: new Date().toISOString(), index });
        render();
        return;
      }
      const nextIndex = index + 1;
      saveLifecycleState({ ...state, active: true, index: nextIndex, updatedAt: new Date().toISOString() });
      render();
      // The anchor href performs the real navigation. Tests can prevent default and still verify the sequence.
    });
    pause.addEventListener('click', () => {
      state = loadLifecycleState();
      saveLifecycleState({ ...state, active: false, pausedAt: new Date().toISOString() });
      render();
    });
    reset.addEventListener('click', () => {
      saveLifecycleState({ active: true, index: 0, startedAt: new Date().toISOString(), updatedAt: new Date().toISOString() });
      if (!lifecyclePathMatches(journey.steps[0].route)) window.location.assign(journey.steps[0].route);
      else render();
    });

    coach.append(head, progress, current, actions);
    const pageHead = root.querySelector('.hr-v2-pagehead, .hr-home__hero, header');
    if (pageHead && pageHead.parentNode === root) pageHead.after(coach);
    else root.prepend(coach);
    render();
  }

  mountHomeTaskFinder();
  mountLifecycleCoach();
  drawer.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); closeDrawer(); return; }
    if (event.key !== "Tab") return;
    const items = focusables();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  document.addEventListener("keydown", (event) => {
    if (event.altKey && String(event.key).toLowerCase() === "k") {
      event.preventDefault();
      if (drawer.hidden) openDrawer({ focusSearch: true });
      else closeDrawer();
      return;
    }
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const tag = (document.activeElement && document.activeElement.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag) || document.activeElement?.isContentEditable) return;
      event.preventDefault();
      openDrawer({ focusSearch: true });
    }
  });

  function labelFor(control) {
    const wrapping = control.closest("label");
    if (wrapping) {
      const span = wrapping.querySelector(":scope > span");
      const raw = (span ? span.textContent : wrapping.textContent || "").trim();
      if (raw) return raw.replace(/必填/g, "").trim();
    }
    if (control.id) {
      const external = document.querySelector(`label[for="${CSS.escape(control.id)}"]`);
      if (external) return (external.textContent || "").replace(/必填/g, "").trim();
    }
    return control.getAttribute("aria-label") || control.name || "未命名字段";
  }

  function enhanceForm(form) {
    if (form.dataset.hrGuideEnhanced === "true") return;
    form.dataset.hrGuideEnhanced = "true";
    const required = Array.from(form.querySelectorAll("input[required], select[required], textarea[required]"))
      .filter((control) => control.type !== "hidden" && !control.disabled);
    if (!required.length) return;

    required.forEach((control) => {
      const label = control.closest("label") || (control.id ? document.querySelector(`label[for="${CSS.escape(control.id)}"]`) : null);
      if (label && !label.querySelector(".hr-guide-required")) label.append(textEl("span", "hr-guide-required", "必填"));
    });

    const summary = document.createElement("div");
    summary.className = "hr-guide-invalid-summary";
    summary.hidden = true;
    form.prepend(summary);

    let progress = null;
    let progressText = null;
    let progressBar = null;
    if (required.length >= 3) {
      progress = document.createElement("div");
      progress.className = "hr-guide-form-progress";
      const copy = document.createElement("div");
      copy.className = "hr-guide-form-progress__copy";
      progressText = textEl("span", "", "");
      copy.append(textEl("strong", "", "表单完成度"), progressText);
      const bar = document.createElement("div");
      bar.className = "hr-guide-form-progress__bar";
      progressBar = document.createElement("span");
      bar.append(progressBar);
      progress.append(copy, bar);
      summary.after(progress);
    }

    function hasValue(control) {
      if (control.type === "checkbox" || control.type === "radio") return control.checked;
      return String(control.value || "").trim() !== "";
    }
    function updateProgress() {
      if (!progress) return;
      const done = required.filter(hasValue).length;
      progressText.textContent = `${done}/${required.length} 项必填已完成`;
      progressBar.style.width = `${Math.round((done / required.length) * 100)}%`;
    }
    function renderInvalid() {
      const invalid = required.filter((control) => !control.checkValidity());
      if (!invalid.length) { summary.hidden = true; summary.replaceChildren(); return; }
      summary.replaceChildren();
      summary.append(textEl("strong", "", `还有 ${invalid.length} 项需要补充`));
      invalid.slice(0, 6).forEach((control) => {
        const btn = textEl("button", "", `→ ${labelFor(control)}`);
        btn.type = "button";
        btn.addEventListener("click", () => { control.scrollIntoView({ behavior: "smooth", block: "center" }); control.focus(); });
        summary.append(btn);
      });
      summary.hidden = false;
    }
    form.addEventListener("input", () => { updateProgress(); if (!summary.hidden) renderInvalid(); });
    form.addEventListener("change", () => { updateProgress(); if (!summary.hidden) renderInvalid(); });
    form.addEventListener("invalid", () => window.setTimeout(renderInvalid, 0), true);
    updateProgress();
  }

  function enhanceForms(scope = document) {
    scope.querySelectorAll(".hr-v2-page form, [data-module^='HR'] form").forEach(enhanceForm);
  }
  enhanceForms();
  document.body.addEventListener("htmx:afterSwap", (event) => enhanceForms(event.target || document));

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href^='/hr/']");
    if (!link) return;
    const task = TASKS.find((item) => item.route === link.getAttribute("href"));
    if (task) recordRecent(task);
  });

  if (!storageGet(STORAGE.welcomed)) {
    const toast = document.createElement("div");
    toast.className = "hr-guide-toast";
    toast.innerHTML = '<strong>第一次使用？不用记菜单。</strong><br>点“办理助手”，直接输入“入职、续签、退休、工资核算”等要办的事。';
    const actions = document.createElement("div");
    actions.className = "hr-guide-toast__actions";
    const tryBtn = textEl("button", "", "试一下");
    tryBtn.type = "button";
    const dismiss = textEl("button", "secondary", "知道了");
    dismiss.type = "button";
    actions.append(tryBtn, dismiss);
    toast.append(actions);
    document.body.append(toast);
    const dismissToast = () => { storageSet(STORAGE.welcomed, "1"); toast.remove(); };
    tryBtn.addEventListener("click", () => { dismissToast(); openDrawer({ focusSearch: true }); });
    dismiss.addEventListener("click", dismissToast);
  }

  // Test/extension hook. Deliberately exposes only non-sensitive catalog/context.
  window.YuekeHRGuide = Object.freeze({
    version: "1.5.0",
    module: moduleCode,
    moduleName: moduleInfo.name,
    tasks: TASKS.map(({ title, module, route }) => ({ title, module, route })),
    journeys: JOURNEYS.map(({ id, title, steps }) => ({ id, title, steps: steps.map(({ module, label, route }) => ({ module, label, route })) })),
    glossary: Object.entries(GLOSSARY).map(([term, description]) => ({ term, description })),
    prompts: modulePrompts(),
    autofillNotes: autofillNotes(),
    fullLifecycle: JOURNEYS.find((item) => item.id === FULL_LIFECYCLE_ID),
    buildSafePrompt,
    open: () => openDrawer({ focusSearch: true }),
  });
})();
