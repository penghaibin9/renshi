# HR04 Gap Matrix（S0 基线复审 · 对照总册终极版）

> 依据：《04_HR04_招聘与人才引进_施工总册_终极版》六个三级模块 + H0/A0/HR02/HR03/HR05 硬门。
> 核对对象：`renshi/` 真实代码（recruitment/onboarding/employee/base/horilla_* + hr_structure + hr_control_center）。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`

---

## 0. 顶层裁决

| 层面 | 裁决 | 证据 |
|---|---|---|
| 招聘交互骨架 | **ADAPT** | Pipeline/Kanban、stage 拖拽、面试排期、survey、材料上传、公开报名表单齐全 |
| 业务事实链 | **NEW** | 年度用人计划、招聘公告版本、资格条件版本、评分方案、公示/Offer/handoff 全部缺失 |
| 权威状态机 | **NEW** | `Stage.stage_type` 仅 6 值（initial/applied/test/interview/cancelled/hired），无法承载高校状态机 |
| 岗位额度 | **DEPENDS_HR02（已就绪）** | `hr_structure` 已注册、0001 迁移已建、`HrPositionReservation` 模型就绪；**预占 API 已暴露**（`PositionService.reserve/commit/release` + `/api/hr/v1/structure/position-reservations`，带幂等键+事务锁），S4 经 `integrations/hr02.py` 接入 |
| 数据迁移 | **PROJECT** | Candidate/Application 拆分 + 身份匹配 + 人工队列 |

---

## 1. 硬门核对（H0 / A0 / HR02 / HR03 / HR05）

### H0 基础
| 硬门项 | 现状 | 差距 |
|---|---|---|
| Docker 可构建 | `renshi/Dockerfile`、`docker-compose.yml`、`docker-compose.prod.yml` 存在 | ✅ 文件在位；HR04-S11 需实测 `docker compose build` |
| `/health/` `/ready/` | `horilla/urls.py` 已定义 | ✅ |
| 迁移可执行 | 常规 app 有 migrations；`hr_structure/` 无 | ⚠️ 只影响 HR02 依赖，不阻塞 HR04 自身 migrations |
| CI 真实跑迁移/测试 | GitHub Actions 未在仓库内确认 | ⚠️ S11 验收前需确认 |

### A0 多学校 fail-closed
| 硬门项 | 现状 | 差距 |
|---|---|---|
| 租户由可信上下文解析 | `CompanyMiddleware`（base/middleware.py）+ `set_selected_company`（horilla_middlewares）+ `HorillaCompanyManager` | ✅ 骨架在位 |
| 无 tenant 上下文 fail-closed 403 | HR01 `hr_control_center/api/views.py` 已实现 `TENANT_CONTEXT_REQUIRED → 403` | ✅ 有可复制范式；HR04 内部 admin API 必须照做 |
| 公开入口禁客户端传 tenant_id | **不存在**（现有 `application_form` 用裸 `?recruitmentId=`） | ❌ **HR04-S5 必须用 batch/position 公开 token 解析学校** |
| 上传材料按 tenant 隔离 | 现有 `default_storage` 裸路径 `recruitment_attachment/<filename>` | ❌ 必须改为 tenant+campaign+candidate 隔离 + 短期签名 URL |
| 后台任务显式 tenant | 未见 HR04 领域后台任务（scheduler.py 属 legacy） | ⚠️ S2 起后台任务须显式 tenant |
| 外部候选人数据不进共享池 / 平台运维默认不可查看 PII | 现状 Horilla Candidate 明文 email/mobile/resume | ❌ 需敏感字段分级 + 访问审计 |
| 日志不输出身份证/完整手机号/简历正文 | 现状无身份证字段；手机号明文存在 | ⚠️ S2 起日志规范 + mobile 遮罩 |
| public portal 与员工/HR 账号隔离 | `CandidateAuthenticationBackend` 存在但返回 Candidate 实例、无 tenant 边界、session JSON 存候选人 | ❌ 需重做 tenant-scoped candidate 账号 |

### HR02 依赖硬门（总册 1.2）
| HR02 能力 | 代码现状 | 判定 |
|---|---|---|
| `HrOrganization` | `hr_structure/models/organization.py`（stable_code+版本） | ✅ 就绪 |
| `HrPostCatalog(+Version)` | `hr_structure/models/post_catalog.py` | ✅ 就绪 |
| `HrPosition` | `hr_structure/models/position.py` | ✅ 就绪 |
| `HrPositionPool` | 同上 | ✅ 就绪 |
| `HrPositionReservation` | 同上（HELD/COMMITTED/RELEASED/EXPIRED/CANCELLED + idempotency_key） | ✅ 就绪 |
| `HrStaffingPlan` | `hr_structure/models/staffing.py`（+quota 行） | ✅ 就绪 |
| **app 注册 INSTALLED_APPS** | `horilla/settings/base.py` 已含 `hr_structure` | ✅ 已注册 |
| **migrations** | `hr_structure/migrations/0001_initial.py` 存在 | ✅ 已有 0001 |
| **urls/views/scope/permissions** | `hr_structure/urls.py`/`views.py`/`scope.py`/`permissions.py` 存在；API 前缀 `/api/hr/v1/structure/*`（api/urls.py 存在） | ✅ 基础接口就绪（S4 再核实预占 API 具体实现） |
| **git 纳入** | `hr_structure/` 随 HR02 窗口提交 | ✅ |

> **硬门结论（更新）**：HR02 稳定组织/岗位 ID 已就绪，`hr_structure` 已注册且已有 0001 迁移，**岗位预占 API 已暴露**（`PositionService.reserve/commit/release`，参数含 `source_domain/source_business_type/source_business_id` + `idempotency_key`，事务锁 `select_for_update`，幂等重试命中）。HR04-S4 通过 `integrations/hr02.py` 接入：`source_domain="hr04"`，`source_business_type="recruitment_position"`，`source_business_id=<HrRecruitmentPosition.id>`；`HrRecruitmentPosition.position_id/position_pool_id` 保存 HR02 预占引用；预占失败显式返回 `HR02_POSITION_NOT_AVAILABLE`（UNAVAILABLE ≠ 0）。

### HR03 边界
| 项 | 现状 | 差距 |
|---|---|---|
| `Candidate` 是 HR03 `Person`？ | 否；`Employee` 独立模型，`converted_employee_id` 是 legacy 投影 | ✅ 语义上未混 |
| HR04 Hired → Employee.save() | `recruitment/views/views.py` 存在 `candidate_conversion`（创建 Employee） | ❌ **必须由 HR05 handoff 触发，HR04 不得直接调**；S8 前关闭/收敛 legacy 转换入口 |
| HR03 权威（Person/StaffMaster） | 仓库无 HR03 app（`hr_structure` 之外未见） | ⚠️ handoff 契约按总册 1.3 以接口形式预留 |

### HR05 边界
| 项 | 现状 | 差距 |
|---|---|---|
| onboarding 由 Candidate 锚定 | `onboarding/models.py`（OnboardingStage/OnboardingTask/CandidateStage/CandidateTask） | ✅ 交互骨架可投影 |
| HR05 权威（待报到→入职） | 无 HR05 app | ⚠️ `HANDOFF_TO_HR05` 以幂等领域动作预留，HR04 不实现 HR05 |

---

## 2. HR04-01 年度用人计划

### 现有能力（可 ADAPT）
- 无。Horilla 没有年度用人计划概念。

### 缺口（NEW，S3 施工）
| 能力 | 总册要求 | 现状 | 差距等级 |
|---|---|---|---|
| `HrHiringPlanCycle` | 年度周期/版本 | 无 | P0 NEW |
| `HrHiringPlanRequest` | 学院需求/审批时间线 | 无 | P0 NEW |
| `HrHiringPlanLine` | 岗位目录/need_type/额度/FTE | 无 | P0 NEW |
| 计划状态机 | DRAFT→SUBMITTED→UNDER_HR_REVIEW→RETURNED→...→APPROVED/CLOSED | 无 | P0 NEW |
| HR02 资源校验 | 编制/空岗/已预占/可申请额度 | HR02 模型/注册/迁移就绪；预占 domain 服务待 S4 复核 | P1（S4 复核预占 API；未稳定前走 LEGACY_CURRENT_SNAPSHOT） |
| 批准时并发重检 | 事务重查额度 | 无 | P0 NEW |
| 需求详情三栏 UI | 需求事实/资源校验/审批时间线 | 无 | P0 NEW |
| Excel 批量 | 模板→staging→校验→异步 | `base.methods.export_data` 等有雏形 | P1 NEW |

## 3. HR04-02 招聘项目与岗位

### 现有能力（可 ADAPT）
- `Recruitment`（event-based 多岗位、start/end、publish/close、managers、skills、survey）；
- Pipeline 看板 + stage 拖拽 + kanban；
- 公开 open-recruitments 列表。

### 缺口（NEW/ADAPT，S4 施工）
| 能力 | 总册要求 | 现状 | 差距等级 |
|---|---|---|---|
| `HrRecruitmentCampaign` | code/type/plan_cycle/public_slug/时区/状态 | `Recruitment` 无 code/slug/plan/时区 | P0 NEW |
| `HrRecruitmentPosition` | 岗位粒度/额度/资格方案/评分方案 | `Recruitment.open_positions` M2M，无额度/方案 | P0 NEW |
| HR02 Reservation | 预占/提交/释放/幂等 | 模型在，无接口 | P1（降级 LEGACY_CURRENT_SNAPSHOT） |
| `HrRecruitmentAnnouncementVersion` | 版本/amendment/不可变 | 无 | P0 NEW |
| `HrQualificationRuleSetVersion` | 资格条件版本 | 无（survey 自由题不可作正式条件） | P0 NEW |
| `HrSelectionSchemeVersion` | 评分方案版本 | 无（CandidateRating 是 0-5 手填） | P0 NEW |
| Campaign/Position 状态机 | 总册 9.4/9.5 | 仅 closed/is_published 布尔 | P0 NEW |
| 招聘控制台 5 KPI + 漏斗 | 总册 9.2 | `recruitment/dashboard.py` 有 KPI/漏斗雏形（口径 legacy） | P1 ADAPT |
| Horilla 兼容投影 | Campaign→Recruitment | 无 | P1（S9 施工） |

## 4. HR04-03 人才库与应聘者

### 现有能力（可 ADAPT）
- `Candidate` 列表/卡片/详情/profile-layout、材料、notes、interview 展示、mail log；
- 公开 `application_form` + `candidate_survey`；
- `CandidateAuthenticationBackend`。

### 缺口（NEW/ADAPT，S5 施工）
| 能力 | 总册要求 | 现状 | 差距等级 |
|---|---|---|---|
| `HrRecruitmentCandidate` | 候选自然人/consent/retention/来源/状态 | `Candidate` 绑 recruitment+stage，无法表达"一个自然人多次应聘" | P0 NEW |
| `HrJobApplication` | 一次申请/版本冻结/权威状态 | 无 | P0 NEW |
| Candidate/Application 拆分迁移 | 身份匹配+人工队列 | 无 | P0（S10 施工） |
| 唯一约束 | tenant+candidate+position+active | `unique_together=(email, recruitment_id)` | P0 重定义 |
| 公开门户 | `/recruit/:tenantSlug/:campaignSlug`，token 解析学校 | 裸 `?recruitmentId=` + session JSON | P0 NEW |
| 草稿自动保存/提交幂等 | 总册 49 | 无 | P0 NEW |
| 高敏字段服务端裁剪 | 身份证 cipher/hash、手机号遮罩、exact-match 单独接口 | 无 | P0 NEW |
| 材料版本/SHA-256/验证状态 | 总册 20 | `CandidateDocument` 仅 title/file/status | P1 ADAPT |
| retention/consent | 总册 10.6 | 无 | P1 NEW |
| 候选人页面不泄漏他人 | 总册 22 | legacy 页面凭 manager 权限可见全校 | P0 NEW（新 UI 保证） |

## 5. HR04-04 资格审查

### 现有能力（可 ADAPT）
- `RejectedCandidate`/`RejectReason`（原因目录）；
- `CandidateDocumentRequest`（补材料请求雏形）；
- `CandidateDocument.status`（requested/approved/rejected）。

### 缺口（NEW，S6 施工）
| 能力 | 总册要求 | 现状 | 差距等级 |
|---|---|---|---|
| `HrQualificationRuleSetVersion`/`HrQualificationRule` | 结构化条件/severity/evidence | 无 | P0 NEW |
| `HrQualificationReview` | 逐条系统预检+人工结论 | 无 | P0 NEW |
| `HrQualificationDecision` | decision/reason_code/版本 | `RejectedCandidate` 不区分 RETURNED/DISQUALIFIED | P0 NEW |
| RETURNED 独立 | 材料缺失≠不合格，可补交 | 无 | P0 NEW |
| 规则预检输出 | PASS/FAIL/DATA_MISSING/NEEDS_MANUAL_REVIEW | 无 | P0 NEW |
| 审核工作台三栏 | 队列/条件矩阵/材料决策 | 无 | P0 NEW |
| 批量操作安全 | 低风险一致结论才批量；DISQUALIFIED 逐件 | 无 | P1 NEW |

## 6. HR04-05 考试面试与考察

### 现有能力（可 ADAPT）
- `InterviewSchedule`（日期/时间/interviewer/completed）+ 排期表单 + 冲突检测雏形（请假查重）；
- 面试列表/详情交互、候选 profile tab。

### 缺口（NEW/ADAPT，S7 施工）
| 能力 | 总册要求 | 现状 | 差距等级 |
|---|---|---|---|
| `HrSelectionSchemeVersion`/`HrSelectionComponent` | 组件/权重/门槛/淘汰 | 无 | P0 NEW |
| `HrAssessmentEvent` | 场次/模式/容量/状态 | `InterviewSchedule` 单场无组件语义 | P0 ADAPT |
| `HrEvaluatorAssignment` | 专家分配/回避/盲评 | 无 | P0 NEW |
| 评分表 | `HrScoreSheetTemplate`/`HrCandidateScoreSheet`/`HrCandidateScore`，服务端总分 | `CandidateRating` 0-5 手填 | P0 NEW |
| 分数锁定/解锁审计 | DRAFT→SUBMITTED→LOCKED + reopen | 无 | P0 NEW |
| 利益冲突 | CLEAR/DECLARED/DETECTED/RECUSED/OVERRIDDEN | 无 | P0 NEW |
| 结果快照 | `HrSelectionResultSnapshot` 冻结排名 | 无 | P0 NEW |
| 体检/考察 | `HrMedicalCheck`/`HrBackgroundCheck`，高敏隔离 | 无 | P0 NEW |

## 7. HR04-06 录用与人才引进

### 现有能力（可 ADAPT）
- `Candidate.hired`、`offer_letter_status`（not_sent/sent/accepted/rejected/joined）、`candidate_conversion`；
- onboarding 关联。

### 缺口（NEW，S8 施工）
| 能力 | 总册要求 | 现状 | 差距等级 |
|---|---|---|---|
| `HrProposedHire` | 拟录用/排名/决策/审批/额度校验 | 无（`hired` 布尔） | P0 NEW |
| `HrPublicNotice`/`HrPublicNoticeEntry` | 公示/可发布字段白名单 | 无 | P0 NEW |
| `HrNoticeObjection` | 异议案件/结果版本 | 无 | P0 NEW |
| `HrRecruitmentOffer` | 签发/接受/过期/幂等 | `offer_letter_status` 太粗糙 | P0 NEW |
| `HANDOFF_TO_HR05` | 显式幂等领域动作 + unique | 无 | P0 NEW |
| 录用额度控制 | 事务锁 reservation | 无 | P0 NEW |
| 公示期间禁止入职 | 总册 13.2 | 无状态门 | P0 NEW |

---

## 8. 横切能力缺口

| 能力 | 总册要求 | 现状 | 差距 |
|---|---|---|---|
| 权威状态机 + Transition Ledger | 总册 14 | 仅 stage 布尔/拖拽 | P0 NEW |
| API 信封/错误/Idempotency-Key/If-Match | 总册 17 | HR01 有 envelope 范式可复用；HR04 无 | P0 NEW |
| 通知事件 | 总册 19 | `notifications` app 存在，事件未建模 | P1 |
| 材料安全 | 总册 20 | 裸 storage、无 SHA/malware/签名 URL | P0 |
| Excel 批量 | 总册 21 | 只有 export 雏形 | P1 |
| 数据隐私 | 总册 22 | 明文 PII | P0 |
| 搜索与去重 | 总册 23 | 无身份 exact-match | P1 |
| 事务与并发 | 总册 25 | 无 | P0 |
| 审计 | 总册 26 | `horilla_audit`/`simple_history` 有基础；HR04 专项审计表缺失 | P1 |
| 数据质量 | 总册 27 | 无指标 | P1 |
| 性能 | 总册 31 | `Candidate.options()` 全表 email 拉取等 N+1 隐患 | P1 |
| 可观测性 | 总册 32 | 无 HR04 metrics | P2 |
| 公共组件 | 总册 15 | HR01 有 `templates/hr/components/*` + tokens 可复用 | P0 复用 |

---

## 9. 差距总表（按 S 阶段）

| S | 模块 | 关键缺口 | 依赖硬门 |
|---|---|---|---|
| S1 | 契约/公共组件 | 权限码、enum、API envelope、UI 组件、路由骨架、projection 契约 | 复用 HR01 tokens/components |
| S2 | 权威模型骨架 | 全部权威模型 + migrations + DB 约束 + transition ledger | A0 上下文可复制 |
| S3 | HR04-01 | plan 模型/状态机/审批/并发重检/UI | HR02 快照可读 |
| S4 | HR04-02 | campaign/position/公告版本/reservation(降级) | **HR02 依赖硬门** |
| S5 | HR04-03 | candidate/application 拆分、公开门户、PII 裁剪、幂等提交 | A0 公开入口 token |
| S6 | HR04-04 | 资格规则/审查/决策/RETURNED | 冻结版本模型 |
| S7 | HR04-05 | 评分/回避/盲评/锁定/快照/体检考察 | 服务端算分 |
| S8 | HR04-06 | 拟录用/公示/异议/Offer/handoff | 幂等 + unique |
| S9 | 投影 | Horilla Recruitment/Stage/Candidate projection | 映射文件 |
| S10 | 对账 | 迁移/DUAL_READ_COMPARE/discrepancy | 拆分匹配 |
| S11 | 验收 | 安全/性能/并发/E2E/可访问性/视觉 | Docker + CI |
| S12 | 封板 | 全部绿 → READY FOR ACCEPTANCE | — |

---

## 10. 明确不做 / 越界禁止

- 不重写 HR02 / HR03；不把 HR05 做进 HR04；
- 不删除 Horilla recruitment 旧表（Authority 前）；
- 不 rename tables 冒充迁移；
- 不关闭权限解决 403；不 mock endpoint 冒充完成；
- 不用假数据让 UI 好看；不用 email 自动合并候选；
- 不把 Stage 名称当业务状态；不把 Candidate.hired 当录用真相；
- 不允许 HR04 Hired → Employee.save()；公示期间不进入正式入职。

> 状态：`DRAFT_V1`。编码期逐阶段核对升级。
