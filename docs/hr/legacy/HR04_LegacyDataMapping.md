# HR04 LegacyDataMapping（S0 基线复审版 · 依据真实仓库核对）

> 文档性质：HR04-S0 前置交付；依据 `renshi` 仓库真实 `recruitment/` 模型/视图核对后物化。
> 核对基线：`feature/hr01-control-center` 分支（HEAD `32a88ac` 之后；工作树含未提交 HR02 `hr_structure/`）
> 物化时间：2026-08-09
> 状态：`DRAFT_V1` —— HR04 编码期以最终权威模型核对后升级
> 依据总册：《04_HR04_招聘与人才引进_施工总册_终极版》第 28/29/30/53 节

---

## 1. 结论先行

- Horilla `Recruitment/Stage/Candidate` **不具备**高校招聘权威能力：无年度用人计划、无 HR02 编制/岗位额度/预占、无招聘公告版本、无资格条件版本、无公示、无 Offer/拟录用分层、无 HR05 handoff。
- HR04 采用 `ADAPT`：复用 Horilla 的**交互骨架**（Pipeline 看板、stage 拖拽、面试排期、survey、材料上传、公开报名），重建**高校招聘事实链**为新权威；Horilla 旧模型降级为**单向投影（projection）**，Authority 切换后旧写入口关闭。
- **禁止推断**：不把 `Stage.stage_type` 当权威状态机；不把 `Candidate.hired=True` 当最终录用真相；不把 `Recruitment.vacancy` 当岗位额度权威；不把 `Candidate` 一条记录当「自然人 + 全部应聘历史」；不根据 email 自动合并候选自然人。

## 2. 引用盘点（S0 输出）

### Horilla recruitment 模型/视图被引用的范围
- **后端模型**：`recruitment/models.py`（Recruitment/Stage/Candidate/RejectedCandidate/InterviewSchedule/RecruitmentSurvey/CandidateDocument 等）；`onboarding/models.py`（OnboardingStage/OnboardingTask/CandidateStage/CandidateTask 以 `Candidate`/`Recruitment` 为锚）；`employee/models.py`（Employee 被 recruitment 作 manager/referral/评级引用）。
- **视图**：`recruitment/views/views.py`（约 4200 行，单文件堆叠）、`recruitment/views/surveys.py`（含公开报名 `application_form`）、`recruitment/views/dashboard.py`、`recruitment/cbv/*`（Pipeline/Kanban/Stage/Candidate 等）、`recruitment/dashboard.py`（现代 dashboard + ApexCharts）。
- **模板**：`recruitment/templates/**`（173 个文件，pipeline/candidates/stage/interview/survey/skill_zone/settings 等）。
- **认证**：`recruitment/auth.py`（`CandidateAuthenticationBackend`：email+手机号末 10 位登录，返回 Candidate 实例）。
- **公开报名**：`recruitment/views/surveys.py: application_form`（GET `?recruitmentId=`，POST 建 Candidate，session 序列化 JSON 存 `candidate`）、`candidate_survey`（survey 问卷 + 附件，max 5MB，裸 default_storage 落盘 `recruitment_attachment/<filename>`）。

### 接管裁决

| Horilla 对象 | HR04 决策 | 终局用途 |
|---|---|---|
| `Recruitment` | ADAPT → LEGACY_PROJECTION | 投影为 `HrRecruitmentCampaign` 兼容视图；不再承载额度/权威状态 |
| `Recruitment.vacancy` | COMPAT_ONLY | 只作兼容展示，额度权威在 `HrRecruitmentPosition` + HR02 Reservation |
| `Recruitment.open_positions` / `job_position_id` | LEGACY_PROJECTION | 投影到 `HrRecruitmentPosition`（不直接绑 Horilla JobPosition） |
| `Recruitment.start_date/end_date` | ADAPT | 映射 `HrRecruitmentCampaign.application_open_at/close_at`（时区化） |
| `Recruitment.is_published/closed` | ADAPT | 投影 Campaign status 的 PUBLISHED/CLOSED 展示 |
| `Recruitment.recruitment_managers` | ADAPT | 映射 Campaign manager 集（按 HR04 角色收敛） |
| `Stage` | LEGACY_PROJECTION | 投影为 `WorkflowStage`；**不再作权威 canonical status** |
| `Stage.stage_type` | REMOVE_AS_AUTHORITY | 权威状态机使用 `HrJobApplication.canonical_status`（总册 14.1 冻结枚举） |
| `Candidate` | LEGACY_PROJECTION → 拆分 | 拆为 `HrRecruitmentCandidate` + `HrJobApplication[]`（候选自然人与应聘申请分离） |
| `Candidate.stage_id` | PROJECT | 投影为 `HrJobApplication.workflow_stage_id`（展示阶段，非权威状态） |
| `Candidate.hired/canceled/converted` | REMOVE_AS_AUTHORITY | 分别投影为拟录用/撤回/HR05 状态；不直接改 |
| `Candidate.recruitment_id/job_position_id` | PROJECT | 投影到 Application 的 position 引用 |
| `RejectedCandidate` | ADAPT → 重构 | 不再把终止态统称 rejected；按 `decision_type`（RETURNED/DISQUALIFIED/FAILED_ASSESSMENT/WITHDRAWN）迁移 |
| `RecruitmentSurvey` | ADAPT | 补充问卷保留；正式资格条件用 `HrQualificationRuleSet`，报名字段用 `ApplicationFormSchema` |
| `RecruitmentSurveyAnswer` | ADAPT | 投影到 Application 提交数据快照 |
| `InterviewSchedule` | ADAPT → 升级 | 升级为 `HrAssessmentEvent` + `HrEvaluatorAssignment` + 评分/盲评/回避/锁定 |
| `CandidateDocument` | ADAPT | 升级为 `HrApplicationMaterial`（类型/版本/SHA-256/验证状态/敏感级/retention） |
| `SkillZone` | ADAPT | 人才库标签语义弱化，保留人才标签投影 |
| `LinkedInAccount` | OPTIONAL/DISABLED | V1 默认关闭，不阻塞高校主链路 |
| `CandidateAuthenticationBackend` | ADAPT | 升级为 tenant-scoped public candidate 账号体系（与员工账号隔离） |

## 3. 字段级映射

### `Recruitment` → `HrRecruitmentCampaign`（projection 语义，非权威迁移）

| Horilla 字段 | 新 HR04 权威模型 | 迁移/投影判定 |
|---|---|---|
| `id` | `HrLegacyObjectLink(legacy_pk)` + `HrRecruitmentCampaign.legacy_recruitment_id`(nullable) | MIGRATE（建立链接，禁止改名冒充） |
| `title` | `HrRecruitmentCampaign.title` | MIGRATE |
| `description` | `HrRecruitmentCampaign.description` | MIGRATE |
| `company_id` | `tenant_id`（HR02 Company→tenant 边界；迁移前校验） | MIGRATE（校验归属） |
| `is_event_based` | `HrRecruitmentCampaign.campaign_type`（SINGLE_POSITION/MULTI_POSITION） | MIGRATE（映射） |
| `vacancy` | **不映射**；仅投影展示 | COMPAT_ONLY（额度权威在 position+reservation） |
| `open_positions` / `job_position_id` | `HrRecruitmentPosition`（通过 `post_catalog_id`/`position_id` 引用 HR02，不直接 FK Horilla JobPosition） | PROJECT（S4 接 HR02；未就绪走 LEGACY_CURRENT_SNAPSHOT） |
| `start_date` / `end_date` | `HrRecruitmentCampaign.application_open_at/close_at` | MIGRATE（时区化） |
| `is_published` | `HrRecruitmentCampaign.status ∈ {PUBLISHED, OPEN}` | MIGRATE（投影状态） |
| `closed` | `HrRecruitmentCampaign.status ∈ {CLOSED, COMPLETED}` | MIGRATE（投影状态） |
| `recruitment_managers` | `HrRecruitmentCampaign.manager_ids` | MIGRATE |
| `survey_templates` | `HrRecruitmentCampaign.survey` 补充问卷投影 | ADAPT |
| `skills` | `HrRecruitmentPosition` 任职条件投影（非权威） | ADAPT |
| `linkedin_*` | 默认不迁移 | OPTIONAL |

### `Stage` → `WorkflowStage` projection

| Horilla 字段 | 新 HR04 权威模型 | 判定 |
|---|---|---|
| `id` | `HrWorkflowStage`（legacy_stage_id 链接） | PROJECT |
| `stage`（名称） | `HrWorkflowStage.name`（可配置展示阶段） | ADAPT |
| `stage_type` | **不迁移为权威**；仅 legacy 兼容标签 | REMOVE_AS_AUTHORITY |
| `sequence` | `HrWorkflowStage.sequence` | MIGRATE |
| `stage_managers` | `HrWorkflowStage.owner_scope`（按权限收敛） | ADAPT |
| `recruitment_id` | `HrWorkflowStage.campaign_id` | PROJECT |

**状态映射表（迁移前必须覆盖所有 active stage）**：

| Legacy Stage.stage_type | Legacy stage 名称示例 | 权威 canonical_status（总册 14.1） | 说明 |
|---|---|---|---|
| `initial` | 初筛 | `UNDER_REVIEW` / `ASSESSMENT_PENDING` | 视招聘流程位置 |
| `applied` | 已报名 | `SUBMITTED` | 已提交 |
| `test` | 测试/笔试 | `ASSESSING` / `ASSESSMENT_PENDING` | 进入选拔组件 |
| `interview` | 面试 | `ASSESSING` | 面试组件 |
| `cancelled` | 已取消 | `WITHDRAWN` / `CANCELLED` | 需人工裁决，不自动归因 |
| `hired` | 已录用 | `PROPOSED_HIRE` / `PUBLIC_NOTICE` / `OFFERED` | 绝不映射为最终权威「已录用」 |

> 禁止：把 RETURNED/REJECTED/DISQUALIFIED/WITHDRAWN 全塞进 legacy `cancelled`。

### `Candidate` → `HrRecruitmentCandidate` + `HrJobApplication`（核心拆分）

| Horilla 字段 | 新 HR04 权威模型 | 判定 |
|---|---|---|
| `id` | `HrRecruitmentCandidate.legacy_candidate_id` + `HrJobApplication.legacy_candidate_id` | SPLIT-MIGRATE |
| `name` | `HrRecruitmentCandidate.legal_name` | MIGRATE |
| `email` | `HrRecruitmentCandidate.primary_email` | MIGRATE（**不当作唯一身份键**） |
| `mobile` | `HrRecruitmentCandidate.primary_mobile` | MIGRATE（敏感字段，日志遮罩） |
| `profile` | `HrRecruitmentCandidate.avatar` | MIGRATE |
| `dob` | `HrRecruitmentCandidate.date_of_birth` | MIGRATE |
| `gender` | `HrRecruitmentCandidate.gender` | MIGRATE |
| `address/country/state/city/zip` | `HrRecruitmentCandidate` 联系地址 | MIGRATE |
| `resume` | `HrApplicationMaterial`（类型=RESUME，版本化+SHA-256） | ADAPT |
| `portfolio` | 材料/经历投影 | ADAPT |
| `recruitment_id` | `HrJobApplication.recruitment_position_id`（经 campaign→position 投影） | SPLIT |
| `job_position_id` | `HrJobApplication.recruitment_position_id` | SPLIT |
| `stage_id` | `HrJobApplication.workflow_stage_id`（展示） | PROJECT |
| `hired` | 不迁移；由 `HrProposedHire`/`HrRecruitmentOffer`/handoff 派生 | REMOVE_AS_AUTHORITY |
| `canceled` | 不迁移；`WITHDRAWN`/`CANCELLED` 走 `HrApplicationTransition` | REMOVE_AS_AUTHORITY |
| `converted` | 不迁移；HR05 handoff 后才由 HR03 建 Person/StaffMaster | REMOVE_AS_AUTHORITY |
| `converted_employee_id` | 投影；**禁止 HR04 Hired → Employee.save()** | PROJECT-ONLY |
| `offer_letter_status` | `HrRecruitmentOffer.status` 投影 | PROJECT |
| `source` | `HrRecruitmentCandidate.source` / `HrJobApplication.source_channel` | MIGRATE |
| `joining_date` | HR05 领域；HR04 仅只读投影 | PROJECT-ONLY |
| `start_onboard` | 不迁移 | REMOVE_AS_AUTHORITY |

### 同 email 多 Candidate 合并规则（禁止仅凭 email 自动合并）

```text
匹配键：tenant + (verified identity hash 优先) + (email/mobile) + (name)
输出：EXACT_MATCH / POSSIBLE_MATCH / NO_MATCH / INSUFFICIENT_DATA
POSSIBLE_MATCH → 人工队列，禁止自动 merge。
```

### 其余 Horilla 对象 → HR04 映射

| Horilla 对象 | HR04 权威 | 判定 |
|---|---|---|
| `InterviewSchedule(candidate/employee/date/time/completed)` | `HrAssessmentEvent` + 参与分配 | ADAPT |
| `CandidateDocumentRequest/Document(status)` | `HrApplicationMaterial`（类型/要求/验证/版本） | ADAPT |
| `RecruitmentSurveyAnswer.answer_json` | `HrJobApplication.form_snapshot` | ADAPT |
| `SkillZoneCandidate` | `HrRecruitmentCandidate.talent_tags` | ADAPT |
| `CandidateRating` | 弃用为权威；评分走 `HrCandidateScoreSheet`（服务端加权） | REMOVE_AS_AUTHORITY |
| `RecruitmentGeneralSetting` | `HrRecruitmentConfig`（tenant 级） | ADAPT |

## 4. 无法迁移的事实（MANUAL_IMPORT_REQUIRED）
- 年度用人计划、计划审批时间线、计划额度消耗；
- 招聘公告版本历史、资格条件版本历史、评分方案版本历史；
- 资格审查逐条结论（含人工审核人/依据/退回原因）；
- 考试/试讲/面试成绩原始分、权重、锁定记录；
- 体检/考察结论与敏感材料；
- 公示/异议案件、Offer 签发/接受记录、HR05 handoff 记录。

以上必须 `UNAVAILABLE / MANUAL_IMPORT_REQUIRED`，禁止根据当前 UI 状态「补历史」。

## 5. 迁移阶段（总册 29/30 节）
```
M0 只盘点 → M1 Campaign 投影（legacy link） → M2 Stage→WorkflowStage 映射（覆盖所有 active stage）
→ M3 Candidate 拆分（identity match → Application） → M4 资格/评分/公告版本人工补录
→ M5 DUAL_READ_COMPARE → M6 Authority Cutover（HR04_AUTHORITY）
```

## 6. 退出合同（总册 29 节）
```
LEGACY_RECRUITING_ONLY → DUAL_READ_COMPARE → HR04_AUTHORITY
```
- Authority 后：新业务只写 HR04；Horilla 只做 projection；Pipeline UI 从 projection 渲染；
- 禁止 provider 故障自动 fallback legacy；回滚走受控 runbook；
- Cutover 硬门：campaign 映射 100%、active stage 映射 100%、Candidate 拆分无 POSSIBLE_MATCH 积压、对账 discrepancy 达门槛、HR02 依赖契约达成。

> 状态：`DRAFT_V1`。HR04 编码期必须以此文件为基线再次核对最终模型，升级到 `REVIEWED`。
