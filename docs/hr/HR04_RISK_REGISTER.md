# HR04 Risk Register（S0 基线复审 · P0 数据/权限/状态机/并发）

> 依据：《04_HR04_招聘与人才引进_施工总册_终极版》第 54/56 节 + 真实代码审计。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`
> 风险分级：P0（封板阻断，施工期必须解决）/ P1（验收前必须解决）/ P2（后续迭代）

---

## 1. P0 风险（封板阻断）

| ID | 类别 | 风险 | 真实代码证据 | 缓解/对策 | 负责阶段 |
|---|---|---|---|---|---|
| R-001 | 数据 | `Candidate`=「一条记录=一次申请」：候选人投多个岗位会被复制成多个人 | `Candidate.unique_together=(email, recruitment_id)`；`recruitment_id` FK PROTECT；`stage_id` FK | 拆 `HrRecruitmentCandidate` + `HrJobApplication[]`；身份匹配 + 人工队列；S2 建模、S10 迁移 | S2/S5/S10 |
| R-002 | 数据 | 用 email 作候选唯一身份 → 同邮箱多人/换邮箱会错误合并或分裂 | `CandidateAuthenticationBackend` 以 email+phone 登录；`unique_together(email, recruitment_id)` | identity 主键 = candidate_uid（immutable）+ verified identity hash；email 只作联系字段 | S2/S5 |
| R-003 | 状态机 | `Stage.stage_type` 只有 6 值（initial/applied/test/interview/cancelled/hired），无法表达 RETURNED/DISQUALIFIED/OFFER/handoff 等 24 态 | `recruitment/models.py` `Stage.stage_types`；`Candidate.save()` 由 stage_type 派生 `hired/canceled` | 新权威 `HrJobApplication.canonical_status` 冻结枚举；WorkflowStage 仅投影展示；禁止新逻辑读 stage_type 作业务状态 | S1/S2/S5 |
| R-004 | 状态机 | 拖拽改 Stage 直接改正式业务状态 | `update_candidate_stage_and_sequence`（views.py）；`Candidate.save()` 改 hired | 拖拽只改 `workflow_stage`（展示），业务推进走 `HrApplicationTransition` + 权限动作 | S5/S9 |
| R-005 | 并发 | 最后一名额被两个招聘项目同时预占/录用 → 超卖 | HR02 `PositionService.reserve` 事务锁 + `HrPositionReservation` 幂等键（已交付）；HR04-S4 接入；正式录用动作绝不依赖缓存 | S4/S8 |
| R-006 | 权限 | 公开报名入口可枚举/直接传 `recruitmentId`，无 token 解析学校 | `application_form` 用 `?recruitmentId=`（surveys.py）；`Recruitment.objects.filter(id=recruitment_id, is_published=True)` | 公开入口用 `:tenantSlug/:campaignSlug/:positionSlug` + applicationToken 解析；禁止客户端传 tenant_id；fail-closed | S5 |
| R-007 | 隐私 | 候选人 PII（email/mobile/resume/地址）明文存储/展示/日志 | `Candidate` 全字段明文；`dashboard.py`、list 模板直接渲染；`logger` 无遮罩约定 | 敏感字段分级；`national_id` cipher+hash；手机号遮罩；日志过滤；SensitiveCandidateAccessLog | S2/S5 |
| R-008 | 材料 | 公开材料裸 `/media/...` URL 长期暴露 + 无 SHA/版本/malware | `Candidate.resume.url` 直接返回；`default_storage` 裸路径 `recruitment_attachment/<filename>` | private storage + 短期签名 URL + SHA-256 + MIME/大小/双扩展名防护 + 版本 + 访问日志 | S5 |
| R-009 | 边界 | HR04 Hired → 直接 `Employee.save()`，绕过 HR03 | `views.py candidate_conversion`（创建 Employee）+ `converted_employee_id` | 收敛 legacy 转换入口；只有 HR05 正式报到后 HR05 调 HR03 `match_or_create Person → StaffMaster → EmploymentRelationship → Assignment`；S8 关旧入口 | S8/S10 |
| R-010 | 公平 | 评分结果可改、无锁定、无审计 | `CandidateRating` 0-5 手填可改；无锁定概念 | `HrCandidateScoreSheet` DRAFT→SUBMITTED→LOCKED；解锁特权+reason+audit；保留旧版本；服务端算分 | S7 |
| R-011 | 公平 | 专家可见敏感 PII/可评利益相关候选人 | 无专家/盲评/回避概念 | `HrEvaluatorAssignment`（conflict/recusal/blind_mode）+ 服务端裁剪（非 CSS） | S7 |
| R-012 | 并发 | 公开报名网络重试双提交 | `application_form` POST 无幂等键；无 unique active constraint | Idempotency-Key + unique(tenant,candidate,position,active) + 提交事务 + application_no 生成 | S5 |
| R-013 | 并发 | Offer 接受/HR05 handoff 重复触发 | 无幂等；无 unique 约束 | 幂等键 + handoff unique proposed_hire；重复调用返回同一 HR05 case | S8 |
| R-014 | 数据 | 公告/资格条件/评分方案发布后直接改字段 → 旧申请被新条件重新解释 | 无版本概念 | 全部版本化 + immutable after publish + amendment（生效时间/原因/影响判定/通知） | S4/S6/S7 |
| R-015 | 隐私 | 候选人页面泄漏其他候选人存在/分数/排序 | legacy 列表按 manager 权限全量展示；无 self scope | candidate self scope 服务端强制；页面只返回本人数据 | S5 |
| R-016 | 数据 | `Candidate.hired`/`offer_letter_status` 被当最终录用真相 | `hired` 布尔；`offer_letter_status` 5 值 | 录用真相 = `HrProposedHire`+`HrPublicNotice`+`HrRecruitmentOffer`+handoff；hired 仅投影 | S8 |

## 2. P1 风险（验收前解决）

| ID | 类别 | 风险 | 对策 | 负责阶段 |
|---|---|---|---|---|
| R-101 | 依赖 | HR02 `hr_structure` 已注册、0001 迁移与 `HrPositionReservation` 模型就绪；**预占 API 已交付**（`PositionService.reserve/commit/release`，幂等键+事务锁） | S4 经 `integrations/hr02.py` 接入（`source_domain="hr04"`）；预占失败显式 `HR02_POSITION_NOT_AVAILABLE`；UNAVAILABLE ≠ 0 | S4 |
| R-102 | 边界 | HR03 权威（Person/StaffMaster）未建，handoff 无接收方 | handoff 以幂等领域动作 + HR05 契约接口预留；HR04 不自行建人 | S8 |
| R-103 | 数据 | 大规模 Candidate 迁移中 POSSIBLE_MATCH 积压 | 身份匹配人工队列 + 门槛控制；禁止自动 merge | S10 |
| R-104 | 性能 | N+1（`Candidate.options()` 全表 email 拉取；列表无预取） | selectors 统一 + `select_related/prefetch_related` + 分页 DB 层过滤 | S5/S11 |
| R-105 | 安全 | 身份证 exact-search 进入普通模糊搜索 | 高敏 exact-match 单独受控接口 + 权限 | S5 |
| R-106 | 数据 | RETURNED/REJECTED/DISQUALIFIED/WITHDRAWN 全塞进 cancelled | 决策类型独立 + transition ledger + reason_code | S6 |
| R-107 | 安全 | 材料/简历下载越权（IDOR） | 下载走签名 URL + 权限 + 审计 | S5/S11 |
| R-108 | 隐私 | 公示直接暴露 Candidate 全字段 | `HrPublicNoticeEntry.public_display_name` + public_fields 白名单 | S8 |
| R-109 | 数据 | 历史结果被重新计算（规则/权重后续变化改变旧排名） | `HrSelectionResultSnapshot` 冻结 + locked scheme | S7 |
| R-110 | 并发 | 两人同时审核同一申请 | optimistic lock/version + 409 VERSION_CONFLICT | S6 |
| R-111 | 安全 | 批量资格审核误淘汰 | 批量仅低风险一致结论；DISQUALIFIED 默认逐件确认 | S6 |
| R-112 | 数据 | Candidate retention/consent 缺失 → 长期保存身份证/简历 | retention_policy + consent_version + anonymization | S5 |
| R-113 | 安全 | 体检/医疗信息被普通招聘管理员看到 | HIGH_SENSITIVE 隔离；普通管理员只看结论 | S7 |
| R-114 | 合规 | 年龄/性别等非必要字段被做成默认筛选项 | 按公告要求配置；最小采集原则 | S5/S6 |

## 3. P2 风险（后续迭代）

| ID | 类别 | 风险 | 对策 |
|---|---|---|---|
| R-201 | 集成 | LinkedIn 外部渠道依赖 | V1 默认关闭 |
| R-202 | 可观测 | 无 HR04 专项 metrics | metrics 名称按总册 32 节 |
| R-203 | 分析 | 招聘分析从 UI Stage 名称反推 | 从规范业务事件/transition 统计 |
| R-204 | AI | 未来 AI 简历筛选黑箱淘汰 | advisory-only 红线（总册 22.3） |

## 4. 硬门追踪（封板依据）

- [ ] H0：Docker 可构建 + health/ready + CI 实测迁移测试（S11）
- [ ] A0：tenant fail-closed 403、公开入口 token 解析、材料 tenant 隔离、后台任务显式 tenant、PII 不进共享池（S2/S5/S11）
- [ ] HR02 依赖：`HrOrganization/HrPostCatalog/HrPosition/HrPositionReservation` 模型就绪、`hr_structure` 已注册+0001 迁移、**预占 API 已暴露**；S4 经 `integrations/hr02.py` 接入（S4）
- [ ] HR03 边界：HR04 不建 Person/StaffMaster；handoff 后 HR05 调 HR03（S8）
- [ ] HR05 边界：handoff 幂等、公示完成前禁 handoff（S8）

> 状态：`DRAFT_V1`。编码期逐阶段更新。
