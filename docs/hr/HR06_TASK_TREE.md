# HR06 TASK TREE（S0 基线复审 · S1-S12 文件级施工任务树）

> 依据：《06_HR06_人事异动_施工总册_终极版》§80（AI 施工顺序）+ GAP_MATRIX。
> 命名约定：新 app `hr_changes`（Django app name），页面前缀 `/hr/changes/*`，API 前缀 `/api/hr/v1/changes/*`（00 §28.1 冻结）。
> 每阶段产出独立可验证提交；全程 Draft PR；不合并 main。

---

## S0 基线复审（已完成 · 只读）

- [x] 读取 00 合同、06 总册 §80、HR03 服务契约（`docs/hr/HR03_服务契约_生效事实_v1.md`）
- [x] 读取 `employee/models.py`（EmployeeWorkInformation 受管字段）、`employee/forms.py`、`employee/views.py`、`employee/cbv/*`、`employee/methods/methods.py`
- [x] 读取 HR02（hr_structure）组织/岗位/预占/重组/scope、HR03（hr_staff）模型/AssignmentService/EffectiveDatedQueryService/权限/API 模式
- [x] 物化：`docs/hr/legacy/HR06_LegacyChangeMapping.md`、`docs/hr/HR06_GAP_MATRIX.md`、`docs/hr/HR06_CHANGE_ACTION_MATRIX.md`、`docs/hr/HR06_TASK_TREE.md`、`docs/hr/HR06_RISK_REGISTER.md`
- [x] S0 清点：20 个直接修改 EmployeeWorkInformation 受管字段的入口（见 LegacyChangeMapping §2）

---

## S1 ChangeAction / Reason / enums / permissions / API contract / 公共 UI

### 脚手架
- [ ] `renshi/hr_changes/__init__.py`
- [ ] `renshi/hr_changes/apps.py`（ready() 注册页面路由 `/hr/changes/` + API `/api/hr/v1/changes/`）
- [ ] `renshi/hr_changes/constants.py`（CaseStatus / ChangeActionCode / ChangeReason / ScopeType / ImpactLevel / 错误码 `HR06_ERROR_CODES` / 权限码 `HR_CHANGE_PERMISSIONS` / 事件类型）
- [ ] 注册 INSTALLED_APPS（`horilla/settings/base.py`）

### 模型（迁移 0001）
- [ ] `models/action.py`：`HrChangeAction`（code/name/domain/允许的 reason 集/enablement/workflow_key/followup_policy_json/effective_date_rule/reporting_manager_policy/version/tenant_id）
- [ ] `models/reason.py`：`HrChangeReason`（code/name/action_code/description/active/requires_document/requires_approval/default_workflow_key/effective_date_rule/allowed_source_scope/allowed_target_scope/version）
- [ ] `models/__init__.py` 导出
- [ ] `migrations/0001_initial.py`
- [ ] `models/field_definition.py`：`HrChangeFieldDefinition`（受管字段字典：domain/field_code/编辑策略）

### 权限
- [ ] `permissions.py`：`require_hr_change_permission`（照抄 hr_staff.permissions 模式）+ 权限常量注册

### API 契约
- [ ] `context.py`：`HrChangeRequestContext` + `build_hr_change_context` + `resolve_tenant_from_request`（复用 hr_control_center.context）
- [ ] `api/base.py`：`api_root/json_response/error_response/make_change_context`（对齐 hr_staff.api.base）
- [ ] `api/urls.py`：`/api/hr/v1/changes/contract` 探针 + bootstrap（actions/reasons/fieldDefinitions/statusMeta）
- [ ] `api/bootstrap.py`：GET `/api/hr/v1/changes/bootstrap`
- [ ] `api/views.py`：contract_probe

### 公共 UI 组件（模板/静态）
- [ ] `templates/hr_changes/components/change_status_badge.html`（状态徽章，含 future 警示）
- [ ] `templates/hr_changes/components/change_action_badge.html`
- [ ] `templates/hr_changes/components/before_after_panel.html`
- [ ] `templates/hr_changes/components/impact_panel.html`
- [ ] `templates/hr_changes/components/change_timeline.html`
- [ ] `urls.py` + `views.py` 占位（重定向到 S3 中心页）

### 测试
- [ ] `tests/test_s1_constants.py`（枚举/权限/错误码/事件集）
- [ ] `tests/test_s1_bootstrap.py`（API envelope + actions/reasons）

---

## S2 Case / Proposal / Transition / Impact / Snapshot 模型 + 迁移

- [ ] `models/case.py`：`HrPersonnelChangeCase`（case_no/tenant/staff_master/employment_relationship/source_assignment/action_code/reason/requested_effective_at/approved_effective_at/status/initiator/owner/source_org/target_org/source_position/target_position/priority/approval_instance_id/base_snapshot_version/base_effective_at/version/时间戳；DB 约束：case_no tenant unique、effective_at not null after submit）
- [ ] `models/proposal.py`：`HrChangeProposal`（case/domain/field_code/old_value_ref/old_value_display/proposed_value_ref/proposed_value_display/effective_at/source_fact_id/validation_status/metadata_json）
- [ ] `models/transition.py`：`HrChangeTransition`（case/from_status/to_status/actor/action/comment/request_id/snapshot_hash）
- [ ] `models/impact.py`：`HrChangeImpactSnapshot`（case/snapshot_version/calculated_at/impacts_json/blockers_json/warnings_json/override_json）
- [ ] `models/snapshot.py`：`HrChangeApprovalSnapshot`（workflow_version/steps_json/generated_at）、`HrChangeEffectiveSnapshot`（applied_at/effective_at/before_json/after_json/source_fact_ids/target_fact_ids/position_changes_json/downstream_plan_version/checksum）
- [ ] `models/downstream.py`：`HrChangeDownstreamEffect`（target_domain/effect_type/status/blocking_level/external_ref/attempts/last_error）
- [ ] `models/temporary.py`：`HrTemporaryAssignmentLink`（S2 建表，S6 用）
- [ ] `models/correction.py`：`HrChangeCorrection`（S2 建表，S7 用）
- [ ] `models/rescind.py`：`HrChangeRescind`（S2 建表，S7 用）
- [ ] `models/bulk.py`：`HrBulkChangeBatch` + `HrBulkChangeItem`（S2 建表，S8 用）
- [ ] `services/state_machine.py`：Case 状态机（合法转移表 + 非法转移抛 `CHANGE_INVALID_STATE`）
- [ ] `services/case_number_service.py`：case_no 生成（照抄 hr_staff HrStaffNumberSequence O(1) 行锁模式）
- [ ] `migrations/0002_case_domain.py`
- [ ] 测试：`tests/test_s2_models.py`、`tests/test_s2_state_machine.py`、`tests/test_s2_case_number.py`

---

## S3 HR06-01 异动申请中心

- [ ] `services/change_service.py`：create_case / update_draft / submit / withdraw / cancel / return / resubmit（版本递增 + 审计）
- [ ] `services/validation_service.py`：action/reason 兼容、effective_date 规则、source/target scope、proposal 校验（BLOCKER/WARNING/INFO）
- [ ] `services/impact_service.py`：Impact Providers（HR02 capacity / HR03 current facts / HR07 / HR11 / HR14 / HR15 / IAM / ACADEMIC 注册表）
- [ ] `services/approval_service.py`：Workflow Resolver（action/reason/scope 生成 steps）+ `HrChangeApprovalSnapshot` 冻结 + approve/reject/return + 并发重检
- [ ] `selectors/case_list.py`：我的发起/我的待办/审批中/待生效/已生效/异常
- [ ] `selectors/bootstrap_data.py`
- [ ] `api/changes.py`：list/create/detail/patch/validate/preview/submit/withdraw/return/approve/reject/cancel/impact/timeline/future
- [ ] `api/urls.py` 挂载 S3 端点
- [ ] `views.py` + `urls.py`：`/hr/changes`（中心首页 + 统计卡）、`/hr/changes/new`（向导）、`/hr/changes/:id`（详情）、`/hr/changes/:id/preview`、`/hr/changes/future`
- [ ] 模板：`change_center.html`、`change_new.html`、`change_detail.html`、`change_preview.html`、`future_changes.html`
- [ ] 前端中文化：`labels.py`（action/status/reason label）+ i18n
- [ ] 测试：`tests/test_s3_center.py`、`tests/test_s3_workflow.py`、`tests/test_s3_target_scope.py`

---

## S4 HR06-02 校内调动

- [ ] `policies/transfer_policy.py`：ORG_TRANSFER / POSITION_TRANSFER / ORG_POSITION_TRANSFER 字段定义 + reporting manager policy
- [ ] `services/transfer_service.py`：Transfer Case 专用校验（目标岗位容量、组织有效、同校、非离职/待离职）
- [ ] `integrations/hr02.py`：`PositionGate`（reserve 预占 / commit 生效 / release 释放，幂等 key=case_id）
- [ ] `integrations/hr03.py`：`AssignmentGate`（包装 HR03 AssignmentService，source_business_type=HR06_TRANSFER，source_business_id=case_no）
- [ ] `selectors/transfer_selector.py`：当前任职 ↔ 拟调任对照数据
- [ ] `api/transfers.py` + 路由
- [ ] 页面：`/hr/changes/transfers`、`/hr/changes/transfers/new`、`/hr/changes/transfers/:id` + 模板（左右对照 Before/After）
- [ ] 测试：`tests/test_s4_transfer.py`（容量/预占/释放/未来生效/主岗唯一）

---

## S5 HR06-03 岗位与身份变更

- [ ] `policies/identity_policy.py`：POST_CATEGORY_CHANGE / EMPLOYEE_CATEGORY_CHANGE / EMPLOYMENT_TYPE_CHANGE / MANAGER_CHANGE / LOCATION_CHANGE / ADD-SECONDARY / END-SECONDARY / PRIMARY_SWITCH
- [ ] `services/identity_change_service.py`：各 action 的 proposal 定义与校验
- [ ] `integrations/hr03.py` 扩展：`StaffCategoryGate`（staff_category_code）、`RelationshipGate`（relationship_type / UPDATE_RELATIONSHIP / CLOSE_AND_CREATE）、`ConcurrentGate`（create_assignment CONCURRENT）
- [ ] `api/identity_changes.py` + 路由 + 页面 `/hr/changes/job-identity*` + Change Matrix 模板
- [ ] HR07/HR15 follow-up outbox 事件入队
- [ ] 测试：`tests/test_s5_identity.py`（兼岗不覆盖主岗、主岗切换 one-primary、用工性质策略）

---

## S6 HR06-04 借调挂职

- [ ] `services/temporary_service.py`：start（SECONDMENT/ATTACHMENT 建 temporary assignment + link）、extend、return、overdue 检查
- [ ] `services/return_service.py`：关 temp、恢复/调整 source、原岗有效检查、`RETURN_TARGET_INVALID` exception flow
- [ ] `selectors/temporary_selector.py`：借调中/30 天返岗/已超期/待返岗确认
- [ ] `api/temporary.py` + 路由 + 页面 `/hr/changes/secondments*` + HrTemporaryAssignmentCard 模板
- [ ] 测试：`tests/test_s6_temporary.py`（start/return/延期/原岗撤销 exception）

---

## S7 HR06-05 台账 + Correction + Rescind

- [ ] `selectors/ledger.py`：台账列表 + 全部筛选 + case detail 聚合（tabs 数据）
- [ ] `services/correction_service.py`：`HrChangeCorrection` 受控流程（correction_type/requested_values/reason/approved_by/applied_at/previous+new snapshot hash；高权限）
- [ ] `services/rescind_service.py`：RESCIND_REQUESTED→APPROVED→APPLYING→RESCINDED + 依赖检查（后续事件存在 → `DEPENDENT_CHANGES_EXIST`）
- [ ] `api/ledger.py` / `api/correction.py` / `api/rescind.py` + 路由
- [ ] 页面：`/hr/changes/ledger`、`/hr/changes/ledger/:id`、`/hr/staff/:staffId/change-history` + 模板
- [ ] 测试：`tests/test_s7_ledger.py`、`tests/test_s7_correction.py`、`tests/test_s7_rescind.py`

---

## S8 HR02/HR03 集成（Apply Service + Outbox + 调度）

- [ ] `services/apply_service.py`：核心生效事务
  - 伪代码：lock(case) → ensure APPROVED_WAITING_EFFECTIVE & due → revalidate current facts → rebase if needed → reserve/commit HR02 position → 调 HR03 domain service（switch_primary/create_assignment/close_assignment）→ 更新 occupancy → 写 `HrChangeEffectiveSnapshot`（checksum）→ 写 transition → 写 outbox → mark EFFECTIVE
- [ ] `services/rebase_service.py`：base_snapshot_version 冲突重算（NO_CONFLICT/REBASE_REQUIRED/HARD_CONFLICT）
- [ ] `services/bulk_service.py`：`HrBulkChangeBatch/Item` 执行（PREVALIDATE_ALL + ATOMIC_BATCH/ITEMIZED_COMMIT + error workbook）
- [ ] `integrations/outbox.py`：入队事件（PersonnelChangeApproved/Effective/Corrected/Rescinded/TemporaryAssignmentStarted/Ended/…）
- [ ] `jobs/apply_due_cases.py`：Scheduler（find due → lock → revalidate → apply）+ 人工提前生效（reason+审计）
- [ ] `jobs/outbox_dispatcher.py`：投递（照抄 hr_onboarding jobs）
- [ ] `api/bulk.py` + Excel 模板/导入 staging
- [ ] 测试：`tests/test_s8_apply.py`、`tests/test_s8_future_schedule.py`、`tests/test_s8_bulk.py`、`tests/test_s8_hr03_integration.py`、`tests/test_s8_outbox.py`

---

## S9 Legacy Projection + 直接编辑封堵

- [ ] `projections/horilla_work_info.py`：HR03 事实 → `EmployeeWorkInformation` 投影（Apply 事务后段内执行）
- [ ] `projections/__init__.py`
- [ ] 封堵（按 LegacyChangeMapping §6 顺序）：
  - `employee/views.py:1511 save_employee_bulk_update`：受管字段选择移除 + readonly
  - `employee/views.py:2520/2556`：受管字段 disabled + "该字段已由人事异动管理，请发起异动"
  - `employee/forms.py:347/434`：受管字段并入 fields_to_remove
  - `employee/views.py:2642`：delete 拦截（S9 审计，REMOVE_LATER）
  - `employee/methods/methods.py:~896`：导入模板移除受管字段列
  - `employee/cbv/employee_profile.py`：shift/work_type tab 跳 HR11
- [ ] 测试：`tests/test_s9_projection.py`、`tests/test_s9_block_direct_edit.py`

---

## S10 Dual write / compare + 迁移

- [ ] `jobs/reconcile_projection.py`：`HR06_PROJECTION_DRIFT` 检测（记录 DataQualityFinding，不静默修）
- [ ] `management/commands/hr06_reconcile_legacy.py`
- [ ] `management/commands/hr06_switch_authority.py`（LEGACY_ACTIVE→…→NEW_AUTHORITY）
- [ ] `services/authority_mode_service.py`（对照 hr_staff）
- [ ] 迁移数据：legacy WorkInformation ↔ HR03 fact 映射核对
- [ ] 测试：`tests/test_s10_dual_compare.py`

---

## S11 安全 / 并发 / 性能 / E2E / 可视化 / 无障碍

- [ ] `tests/test_security.py`（跨校/跨学院/IDOR/scope/export/批量/未来案件访问）
- [ ] `tests/test_concurrency.py`（抢岗位/同日双调动/future 冲突/双 approve/调度 vs 人工 Apply/rescind vs 后续 change/bulk vs 单人）
- [ ] `tests/test_performance.py`（list p95<500ms/detail<700ms/preview<1s/apply<1.5s；禁 N+1）
- [ ] `tests/test_e2e.py`（申请→source→target→HR→future→生效→投影→台账 + 借调/延期/返岗/兼岗/correction/rescind blocked）
- [ ] `tests/test_i18n_labels.py`（全部可见文案中文）
- [ ] 无障碍/视觉回归核查项清单

---

## S12 Authority 切换与封板

- [ ] 全量测试回归（目标库 MySQL 语义：迁移/FK/唯一/索引 EXPLAIN/锁）
- [ ] `docs/hr/HR06_S12_封板评估.md`（对照总册 §82 最终封板条件逐项核对）
- [ ] 输出 `HR06 READY FOR ACCEPTANCE` 或 `HR06 NOT READY + blocking 清单`
- [ ] Draft PR 更新为 ready-for-review 状态（仍不合并 main）

---

## 跨阶段固定纪律

- 每个阶段：迁移 + 测试真实通过/失败数量；不跳测试；不 mock downstream 冒充完成。
- tenant fail-closed；所有 HR06 表带 tenant_id；禁放宽。
- 不直接批量 UPDATE `EmployeeWorkInformation`；生效只走 HR03 domain service。
- 正式已生效 snapshot 不可原地改；correction/rescind 走受控流程。
- 不 delete effective event；不新建第二份 Position；不把 HR07/HR14/HR15 揉进 HR06。
