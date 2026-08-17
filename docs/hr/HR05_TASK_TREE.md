# HR05 Task Tree（S1–S12 · 文件级任务树）

> 依据：《05_HR05_入职管理_施工总册_终极版》第 67 节 AI 施工顺序 + HR05_S0 审计。
> 原则：一个阶段一个可验证提交；全程 Draft PR；未经授权不合并 main；不做越界改造（不重写 HR02/03/04）。
> 约定：新增 app 建议名 `hr_onboarding`（总册 §32）；旧 `onboarding/` 保持运行逐步成为 legacy adapter/projection。
> 依赖现状（S0 核实）：`hr_structure`（HR02）✅ 已注册+migrated+reservation 服务可用；`hr_staff`（HR03）⏳ S2 完成（Person/StaffMaster 可用，Employment/Assignment 未建）；`hr_recruitment`（HR04）⏳ S1 契约层（handoff 未实现）。

---

## 依赖图

```
S1 契约/枚举/权限/API envelope/公共组件 ──────────────┐
S2 权威模型（Template/Case/Task/Material/Probation）   │
  + migrations + DB 约束 ───────────────────────────┼──── S3 HR05-01 待报到+Portal ─┐
                                                    │                                 ▼
                                                    ├──── S4 HR05-02 报到登记+Activation Gate
                                                    │         （HR02 reservation ✅ / HR03 Employment⏳ → mock 先行回填）
                                                    │                                 ▼
                                                    ├──── S5 HR05-03 材料核验
                                                    │                                 ▼
                                                    ├──── S6 HR05-04 协同任务+Provisioning
                                                    │                                 ▼
                                                    └──── S7 HR05-05 试用与转正
                                                                                     ▼
S8 Legacy Projection → S9 迁移+DUAL_READ_COMPARE → S10 全量验收 → S11 Authority 切换演练 → S12 封板
```

- S3–S7 依赖 S1（权限/enum/envelope/UI）+ S2（模型/migrations/约束）。
- S4 依赖 HR02 `PositionService`（已就绪）与 HR03 激活服务（Employment/Assignment 未就绪 → Provider 契约 + mock + 回填）。
- S3 依赖 HR04 handoff 消费契约（HR04-S8 未就绪 → 幂等 mock 先行）。
- S9/S10 横切，任何阶段后可逐步叠投影。

---

## HR05-S1 契约 / 枚举 / 权限 / API envelope / 公共组件

**目标**：权限码、枚举、API envelope、错误信封、UI 组件、路由骨架、Provider 契约；不建业务表。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `renshi/hr_onboarding/__init__.py` / `apps.py` | 新增 app；`ready()` 注册 urls（前缀 `/api/hr/v1/onboarding/` 与 `/hr/onboarding/`）+ INSTALLED_APPS 追加 |
| 2 | `renshi/hr_onboarding/constants.py` | 冻结枚举：`CaseStatus`（05 §8 全套：CREATED…CONFIRMED + REPORT_DELAYED/DECLINED/NO_SHOW/BLOCKED/ACTIVATION_FAILED/CANCELLED/PROBATION_EXTENDED/PROBATION_FAILED）、`CaseSourceType`（HR04_HIRE/LEGAL_MANUAL_MIGRATION/TRANSFER_IN/POLICY_IMPORT/LEGACY_MIGRATION）、`IntentStatus`、`MaterialStatus`、`MaterialBlockingPhase`、`VerificationResult`、`TaskStatus`（9 值）、`BlockingLevel`、`ProvisioningStatus`、`ProbationStatus/Result`、`PersonMatchStatus`、`PortalTokenStatus`、`RiskCode` |
| 3 | `renshi/hr_onboarding/permissions.py` | HR05 权限码（05 §5：hr05.case.* / report.checkin / material.review / material.sensitive_view / task.manage / task.complete / task.waive / identity.provision / position.commit / probation.* / export / sensitive_export）+ `HrOnboardingPermissionMeta(managed=False)` 注册 |
| 4 | `renshi/hr_onboarding/api/base.py` | `HrApiEnvelope`（apiVersion/schemaVersion/requestId/data/generatedAt）、`HrApiError`（code/message/details/retryable）、幂等键读取、If-Match/version 读取 |
| 5 | `renshi/hr_onboarding/api/exceptions.py` | `TenantContextRequiredError(403)`、`PermissionDeniedError(403)`、`VersionConflict(409)`、`InvalidStateTransition(409)`、`PositionReservationInvalid(409)`、`PersonMatchRequired(409)`、`BlockingMaterialMissing(422)`、`PortalTokenExpired(401)`、`PortalTokenRevoked(401)`、`OnboardingCaseDuplicate(409)`、`ProbationAlreadyFinalized(409)` |
| 6 | `renshi/hr_onboarding/context.py` | `Hr05RequestContext`：复用 `hr_control_center.context.build_hr_context` + `resolve_tenant_from_request`；无 tenant → 403；school_timezone 驱动 expected/due 计算 |
| 7 | `renshi/hr_onboarding/integrations/__init__.py` + `integrations/{hr02,hr03,hr04}.py` | **Provider 契约**：`Hr02PositionProvider`（availability/reserve/commit/release，包 `PositionService`）、`Hr03ActivationProvider`（match_or_create_person/create_staff_master/create_employment/create_assignment 接口，当前 Employment/Assignment 未就绪→`Hr03MockProvider` 标 `mode=MOCK` 仅测试用）、`Hr04HandoffProvider`（消费 HANDOFF_TO_HR05，幂等） |
| 8 | `renshi/hr_onboarding/policies/` | `state_machine.py`（case/task/probation 合法迁移表）、`idempotency.py`、`completion.py`（OnboardingCompletionPolicy 接口）、`person_match.py`（EXACT/POSSIBLE/NO_MATCH/INSUFFICIENT_DATA 决策，tenant-private） |
| 9 | `renshi/templates/hr/onboarding/components/*.html` | 公共组件：`case_header.html`、`readiness_card.html`、`prehire_status_badge.html`、`report_status_badge.html`、`activation_gate.html`、`activation_checklist.html`、`progress.html`、`stage_rail.html`、`task_matrix.html`、`task_status_badge.html`、`blocking_level_badge.html`、`provisioning_status.html`、`material_checklist.html`、`material_verification_panel.html`、`data_conflict_banner.html`、`person_match_panel.html`、`position_reservation_card.html`、`portal_security_status.html`、`probation_timeline.html`、`probation_decision_bar.html`（复用 `static/hr/css/hr-tokens.css`） |
| 10 | `renshi/hr_onboarding/urls.py`（骨架） | 占位 include，系统 check 通过 |
| 11 | `renshi/hr_onboarding/tests/test_contracts.py` | enum 冻结值、权限码、envelope、Provider 接口签名测试 |

**验收**：Django system check 通过；契约测试绿；无业务表。

---

## HR05-S2 权威模型骨架 + migrations

**目标**：Template/Case/Task/Material/Probation 权威模型全建 + migrations + DB 约束（05 §62/§63）；本阶段不接 UI/API。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_onboarding/models/template.py` | `HrOnboardingTemplate`（code/name/applicable_*）+ `HrOnboardingTemplateVersion`（version_no/effective/status/snapshot_json）+ `HrOnboardingStageDefinition` + `HrOnboardingTaskDefinition`（category/responsible_role/due_offset/available_offset/blocking_level/prerequisite_codes/completion_type/automation_handler/candidate_visible/sequence） |
| 2 | `hr_onboarding/models/case.py` | `HrOnboardingCase`（05 §7 全字段 + version + status + current_stage_code + activation_status + hr03_*_id）+ `HrOnboardingStageTransition` + `HrReportDelay`（old/new/reason/approval，保留历史）+ `HrReportCheckin` |
| 3 | `hr_onboarding/models/prehire.py` | `HrPrehireProfile`（staging，禁止直写 HR03）+ `HrPrehirePortalAccess`（token_hash/purpose/expires_at/revoked_at/last_used_at/failed_attempts/status；明文只在签发瞬间）+ `HrOnboardingDataConflict` |
| 4 | `hr_onboarding/models/material.py` | `HrOnboardingMaterialRequirement`（material_type/required/blocking_phase/condition_json/allowed_formats/max_size/verification_required/destination_domain/retention_policy/reuse_policy）+ `HrOnboardingMaterial`（source/file_version_id/status/issue/expiry）+ `HrMaterialVerification` + `HrPersonnelFileTransfer` |
| 5 | `hr_onboarding/models/activation.py` | `HrActivationAttempt`（case/effective_at/idempotency_key/status/result_json/snapshot_ref）+ `HrOnboardingActivationSnapshot`（05 §25 全字段 + source_versions_json） |
| 6 | `hr_onboarding/models/task.py` | `HrOnboardingTaskInstance`（case/definition/assignee_type/assignee_id/status/available_at/due_at/started_at/completed_at/completion_payload/failure_code/version） |
| 7 | `hr_onboarding/models/provisioning.py` | `HrProvisioningRequest`（05 §15 全字段：target_system/operation/idempotency_key/status/external_ref/attempt_count/next_retry_at/last_error/completed_at） |
| 8 | `hr_onboarding/models/probation.py` | `HrProbationCase` + `HrProbationGoal` + `HrProbationExtension` + `HrProbationReview`（self/college/hr/decision） |
| 9 | `hr_onboarding/models/audit.py` | `HrOnboardingAuditEvent`（actor/action/before/after/reason/request_id，替代 HorillaAuditLog 作正式审计）+ 敏感访问日志 |
| 10 | migrations | `hr_onboarding/migrations/0001_*`：DB 约束（`UNIQUE(tenant,source_type,source_id)`、case_no tenant unique、staff_no 引用 HR03、one active probation per employment、task instance unique by case+definition+cycle、portal active token unique、activation snapshot one-per-success）、索引（05 §63） |
| 11 | `hr_onboarding/models/__init__.py` | 导出全部模型 |
| 12 | `tests/test_models_s2.py` | 模型不变量：source unique、状态默认值、约束生效、tenant FK 一致 |

**验收**：clean DB migration 通过；约束/索引测试绿；不接业务入口。

---

## HR05-S3 HR05-01 待报到人员 + Portal

**目标**：HR04 handoff 消费 → 建 case → 待报到列表/详情 → 意愿/延期/放弃 → Portal 邀请与自助资料采集（身份隔离）。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `integrations/hr04.py` | `HandleRecruitmentHandoff`（幂等消费；`ONBOARDING_CASE_DUPLICATE` 防重；写 `hr04_proposed_hire_id/hr04_application_id/position_reservation_id`） |
| 2 | `services/case_service.py` | `create_case`、`confirm_intent`、`request_delay`（建 `HrReportDelay` 需审批，不覆盖原日期）、`decline`（release reservation via HR02）、`resolve_person_match`、`auto_risk_evaluation` |
| 3 | `services/portal_service.py` | `issue_portal_access`（token hash + purpose + expiry；明文只返回一次）、`consume_access`（attempt/rate limit/revoke/last_used）、`update_prehire_profile`（staging，冲突→`HrOnboardingDataConflict`） |
| 4 | `api/` | `GET /cases`、`GET /cases/{id}`、`POST /cases/{id}/confirm-intent`、`/request-delay`、`/decline`；Portal：`GET/PATCH /prehire/me/profile`、`POST /prehire/me/materials`、`POST /prehire/me/confirm-intent`（不接受任意 case id，仅本人） |
| 5 | `views.py` / templates | 待报到列表（统计：待确认/已确认/7天内/延期/风险）、case detail tabs、Portal 375px mobile-first |
| 6 | `tests/test_s3.py` | handoff 幂等、token 安全、延期历史、放弃释放 reservation、tenant/scope、Portal 本人数据 |

**验收**：HR04 重复 handoff 不重复建 case；token 有时效不入日志；公共 URL 不可枚举；Portal 与员工账号隔离。

---

## HR05-S4 HR05-02 报到登记 + Activation Gate

**目标**：报到确认（幂等）→ Activation Gate 全项检查 → `ActivateOnboardingCase`（HR03 生效 + HR02 commit + snapshot + outbox）；**Employment/Assignment 未就绪时 mock 先行回填，禁止“报到=正式任职”。**

| # | 文件 | 内容 |
|---|---|---|
| 1 | `services/report_service.py` | `confirm_report`（`HrReportCheckin` 幂等：same case+actual_report_at 重复返回原记录）；`REPORTED` 状态 |
| 2 | `services/activation_service.py` | `ActivateOnboardingCase(case_id, effective_at, idempotency_key)`：`select_for_update` case → 状态复查 → Gate 全项（HR04 valid/REPORTED/person match/材料/HR02 reservation/organization & position as-of/employment type/staff category/无重复 StaffMaster）→ `Hr03ActivationProvider` → HR02 `commit` → `HrOnboardingActivationSnapshot` → outbox `StaffActivated` → ACTIVE |
| 3 | `policies/activation_policy.py` | 可配置追加项：Contract signed/档案到校/体检/无犯罪/教师资格 |
| 4 | `integrations/hr03.py` | `Hr03ActivationProvider`：`match_or_create_person`（HARD 幂等返回，LIKELY 抛 `PERSON_MATCH_REQUIRED`）、`create_staff_master`（staff_no 由 HR03 分配）、`create_employment`/`create_assignment`（**未就绪 → `Hr03MockProvider` mode=MOCK 仅测试；就绪后切换真实现，标 dataBasis）** |
| 5 | `integrations/hr02.py` | `Hr02PositionProvider.commit/reserve/release/availability`（包 `PositionService`） |
| 6 | `api/` | `POST /cases/{id}/report`、`GET /cases/{id}/activation-gate`、`POST /cases/{id}/activate` |
| 7 | `views.py` / templates | 报到登记三栏页 + Activation Gate 面板（只读实时，禁止过期缓存，05 §39） |
| 8 | `tests/test_s4.py` | 报到幂等；Gate 每一项正/负；两 HR 同时激活（row lock + version 409）；重复激活返回原结果；provisioning 失败不回滚 HR 事实；mock 与真实 Provider 契约一致 |

**验收**：确认报到与执行正式生效是两个动作；HR03/HR02 事务正确；外部开通失败 HR 事实仍 ACTIVE + PARTIAL 工作访问。

---

## HR05-S5 HR05-03 入职材料核验

**目标**：材料要求模板 → 上传/退回/重提/核验 → HR04 复用策略 → 高敏受控 → 档案到校。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `services/material_service.py` | `submit_material`（幂等）、`return_material`、`verify_material`（`HrMaterialVerification` 记录 reviewer/evidence_snapshot/reason）、`apply_reuse_policy`（TRUST_SOURCE/REVERIFY/REQUIRE_ORIGINAL） |
| 2 | `services/file_service.py` | 私有存储 + SHA-256 + MIME/双扩展名/大小 + 版本 + 下载 ticket（短时效一次性）+ 高敏水印/访问审计 |
| 3 | `api/` | `GET /cases/{id}/materials`、`POST /materials/{id}/verify`、`/return`、`POST /materials/{id}/download-ticket` |
| 4 | `views.py` / templates | 三栏证据工作台（左材料目录/中预览/右要求与核验动作） |
| 5 | `tests/test_s5.py` | 核验记录完整性；reuse 不无条件继承“已验证”；高敏材料越权拒绝；裸 URL 不可猜 |

---

## HR05-S6 HR05-04 入职协同任务 + Provisioning

**目标**：模板→实例化 → 责任人解析 → 任务 DAG → 手动/自动任务 → 入职完成策略；Provisioning retry/reconciliation。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `services/task_service.py` | `instantiate_tasks`（template version → `HrOnboardingTaskInstance`，assignee 按角色解析）、`start/complete/waive`（waive 需 reason+authority+audit）、prerequisite 防环校验、`TASK_PREREQUISITE_NOT_MET` |
| 2 | `services/provisioning_service.py` | `request_provisioning`（幂等键）、`mark_success/failed_retryable/failed_terminal`、next_retry_at 调度、`reconcile`（external_ref）、自动任务 job（SSO/邮箱/一卡通/工资档案等，`PENDING→RUNNING→SUCCESS/FAILED`，200≠业务成功） |
| 3 | `policies/completion.py` | `OnboardingCompletionPolicy`：case ACTIVE + BLOCKS_ONBOARDING_COMPLETE 全完/waived + 无 critical risk → `ONBOARDING_COMPLETED`；UI 区分“正式生效/协同进度/阻断项/后续事项” |
| 4 | `jobs/` | 自动任务执行器 + 超期提醒 + provisioning retry worker（显式 tenant） |
| 5 | `api/` | `GET /cases/{id}/tasks`、`POST /tasks/{id}/start`、`/complete`、`/waive` |
| 6 | `views.py` / templates | 协同中心（部门+任务矩阵）、我的任务视图 |
| 7 | `tests/test_s6.py` | 责任人解析、DAG 防环、双完成 version 冲突、waive 语义、provisioning 重试/终态/reconcile |

---

## HR05-S7 HR05-05 试用与转正

**目标**：`HrProbationCase` 生命周期 → 目标/评价 → 延长/确认/不通过 → 正式事件。

| # | 文件 | 内容 |
|---|---|---|
| 1 | `services/probation_service.py` | `open_probation`（Activation 后按 policy 创建）、`submit_review`（自评/学院/HR 分角色）、`confirm`（`ProbationConfirmed` outbox + HR03 领域服务更新，不直接改多表）、`extend`（`HrProbationExtension`，不覆盖 planned_end_date）、`fail`（`ProbationFailed` + 交 HR07/HR16 后续处理，不 `is_active=False`） |
| 2 | `jobs/` | 试用到期提醒 job（`PROBATION_DUE`） |
| 3 | `api/` | `GET /probations`、`POST /probations/{id}/submit-review`、`/confirm`、`/extend`、`/fail` |
| 4 | `views.py` / templates | 试用列表 + 详情时间线 + 评价分区 + 决策栏 |
| 5 | `tests/test_s7.py` | 终局不可改、延长历史、双审批 final-state lock、转正失败事件链路 |

---

## HR05-S8 Horilla Legacy Projection

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_onboarding/projections/horilla_onboarding.py` | `HrOnboardingCase → CandidateStage`（current stage 投影）；`HrOnboardingTaskInstance → CandidateTask`（9 值→5 值显式映射）；case 只读投影，禁止反向写 |
| 2 | `hr_onboarding/projections/legacy_routes.py` | 旧 portal 4 路由进入 readonly/redirect；`create_initial_stage` signal 收口（00 §58） |
| 3 | `tests/test_s8.py` | projection 幂等、单向性、路由降级 |

---

## HR05-S9 Legacy Migration + DUAL_READ_COMPARE

| # | 文件 | 内容 |
|---|---|---|
| 1 | `hr_onboarding/jobs/migration.py` | 按 LegacyOnboardingMapping §3 迁移：case 创建（source=LEGACY_MIGRATION）、stage 映射、任务迁移、joining/probation、已转 Employee 回填 HR03 link + activation snapshot；**不重触发账号/岗位副作用** |
| 2 | `hr_onboarding/jobs/reconcile.py` | candidate count / current stage / required tasks / task status / joining date / portal status / probation end 对账报告（discrepancy 可见，禁止新空读旧） |

---

## HR05-S10 全量验收

- 安全矩阵（05 §52）：tenant、scope、PREHIRE self、token expiry/revoked/brute-force、IDOR、材料 URL 越权、银行卡遮罩、高敏下载 audit、assignee 最小 PII、IT 不可见体检、Activation/probation permission、Excel scope、malicious upload、XSS/CSRF、rate limit。
- 并发（05 §47）：重复 handoff、双 Activate、工号并发、reservation 事务、Portal 重复提交、Task 双完成、转正双审批。
- 性能（05 §51）：case list/detail、Activation Gate、material list、task matrix、portal、Activation 核心事务 < 1.5s、大导出异步、无 N+1。
- E2E（05 §58 二十步）+ 视口 1440/1280/768/375 + Accessibility（05 §60）+ Visual Regression（05 §59）。
- API 契约（05 §61）：apiVersion/schemaVersion/requestId/pagination/envelope/If-Match/idempotency/enum fallback。

---

## HR05-S11 Authority 切换演练

- 模式 `LEGACY_ONBOARDING_ONLY → DUAL_READ_COMPARE → HR05_AUTHORITY`（05 §44）。
- 进入后：新 case 只写 HR05；Horilla CandidateStage/CandidateTask 为 projection；Portal 不再建 Employee；不自动 fallback legacy；回滚 runbook。
- 切换记录 operator/old_mode/new_mode/reason/reconcile_report_id。

---

## HR05-S12 封板

- clean DB 迁移 + upgrade from legacy snapshot + 全量 CI + Playwright/visual/security/performance + docs/ops。
- 输出条件唯一：`HR05 READY FOR ACCEPTANCE`；否则列 blocker。

---

## 越界红线（05 §68 / 本窗口合同）

- 不重写 HR02/03/04；不把 HR07 合同、HR15 工资引擎做进 HR05；
- 不删除 Horilla onboarding；不用 mock 冒充正式结果（mock 仅限未就绪 Provider，标 mode 且不回填前不得当作生产）；
- Portal 不 `Employee.save()`；不绕过 Activation Service 写 HR03；不建第二份 StaffMaster；
- 多部门协同失败不静默跳过；账号开通失败不显示“完成”；工资档案未就绪不显示“已完成入职”；
- 延期不覆盖原日期；放弃必须释放 reservation；工号不加锁不并发；跨校不自动识别同一人。
