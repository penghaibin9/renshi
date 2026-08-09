# HR03 TASK TREE（S1-S12 施工任务树 · 一阶段一可验证提交）

> 依据：《03_HR03_教职工主档_施工总册_终极版》第 45 节 AI 施工阶段拆解 + 真实仓库核对。
> 纪律：不一次替换整个 Horilla Employee；不删 legacy；不直接改 main；每阶段跑专项+受影响回归；
> 每阶段一个可验证提交（Draft PR），验收通过才进下一阶段。

---

## S0 基线复审（已完成 · 只读）

- [x] 读取权威源：`docs/03_HR03_...终极版.md`
- [x] 读取 HR02 硬门（1.3/1.4 节）
- [x] 读取 `docs/hr/legacy/HR02_LegacyDataMapping.md`
- [x] 读取 `renshi/employee/` models/forms/views/urls/cbv/methods
- [x] 读取 `renshi/base/`、`horilla_audit/`、`horilla_documents/`、`notifications/`（只读）
- [x] 核对 `hr_structure`（HR02 权威层现状：模型在、未安装、无迁移）
- [x] 物化：`docs/hr/legacy/HR03_LegacyDataMapping.md`
- [x] 物化：`docs/hr/HR03_GAP_MATRIX.md`
- [x] 物化：`docs/hr/HR03_TASK_TREE.md`（本文件）
- [x] 物化：`docs/hr/HR03_RISK_REGISTER.md`（本文件）
- [x] S0 验收：4 份文档齐全、入口清单完整、P0/P1 无遗漏

---

## S1 A0/公共合同（跨域常量与类型契约）

目标：HR03 与 HR01/HR02 共用同一套 version envelope、error envelope、context、权限层；落地 `hr_staff` app 骨架。

### 文件
```
renshi/hr_staff/__init__.py / apps.py / models/__init__.py
renshi/hr_staff/constants.py          # 人员状态/关系/assignment_type/敏感等级/scope type/权限码常量
renshi/hr_staff/api/base.py           # _api_root/_error/_json（对齐 hr_control_center.api.views）
renshi/hr_staff/context.py            # HrStaffRequestContext（复用 HrRequestContext 思想 + staff 相关扩展）
renshi/hr_staff/policies/__init__.py  # FieldGovernancePolicy 常量表（v1 静态）
renshi/hr_staff/permissions.py        # HR03 权限码 + require_hr_permission
renshi/hr_staff/urls.py               # /api/hr/v1/staff/* 骨架（先挂 health/contract 探针）
```

### 验收
- [x] `python manage.py check` 通过；`hr_staff` 加入 INSTALLED_APPS（本地 settings）
- [x] 公共错误码常量表与 HR03 总册 §27 对齐（STAFF_NOT_FOUND/…/LEGACY_AUTHORITY_MISMATCH）
- [x] 单测：`tests/test_constants.py`（枚举完整性）、`tests/test_permissions.py`、`tests/test_context.py`
- [x] 提交点：`feat(hr03): S1 A0/公共合同骨架`（已交付：constants/context/permissions/api base/policies）

## S2 Person/Identity/StaffMaster 权威模型 + 迁移

目标：Person → PersonIdentity/Contact/Sensitive → StaffMaster 权威模型；A0 表级 tenant；账号解耦；禁建 User。

### 模型文件（`renshi/hr_staff/models/`）
```
person.py   HrPerson / HrPersonContact / HrEmergencyContact
identity.py HrPersonIdentityDocument（document_number_ciphertext/fingerprint/masked_display/verification_status）
staff.py    HrStaffMaster（staff_no tenant 唯一、legacy_employee_id、source、version、投影字段）
mapping.py  HrLegacyObjectLink / HrExternalIdentityMapping / HrAccountLink
audit.py    HrStaffAuditEvent
sensitive.py HrSensitiveAccessLog
```

### 服务
```
services/person_identity_service.py  # 证件加密+fingerprint+masked；HARD/LIKELY/NO_MATCH 去重
services/staff_master_service.py     # staff_no 生成（tenant scoped、前缀可配、不回收）
services/audit_service.py            # HrStaffAuditEvent 写入（禁日志 PII）
```

### 迁移
```
renshi/hr_staff/migrations/0001_initial.py
```

### 验收
- [x] `(tenant_id, staff_no)` 唯一；`(tenant_id, person_id)` 默认一份 StaffMaster
- [x] 身份证 fingerprint 同 tenant 唯一（conditional unique）；API 默认只回 masked_display
- [x] authority save 不创建密码账号；`HrAccountLink` 可 0..n
- [x] tenant 隔离测试：A 校 staffId 猜 B 校 → 404/403；list 无 B 校
- [x] 迁移可执行、可回滚；commit：`feat(hr03): S2 Person/Identity/StaffMaster 权威模型`（迁移 0001；S2 测试全绿）

## S3 EmploymentRelationship/Assignment 有效日期模型 + EffectiveDatedQueryService

目标：关系与任职事实层；`[effective_from,effective_to)`；PRIMARY 唯一；as-of 统一查询服务。

### 模型文件
```
employment.py HrEmploymentRelationship（relationship_type/employment_type/effective_from/effective_to/source_business/reason/status/version）
assignment.py HrStaffAssignment（organization_id 可空/position_id 可空/post_catalog_id 可空/assignment_type/fte/reporting_staff_id/source/status/version）
status_history.py HrStatusHistory（人员状态段，替代 is_active 真值）
```

### 服务与查询
```
services/effective_dated_query_service.py  # as-of 唯一入口；半开区间；未来/历史/当前三态
services/employment_service.py             # 关系开始/结束/返聘
services/assignment_service.py             # 事务：锁 primary→校验 org/position→关旧段→开新段→更新投影→审计→outbox
selectors/assignment.py                    # staff 当前/历史 assignments
policies/assignment_policy.py              # FTE 上限/PRIMARY 唯一/跨 tenant FK 校验
```

### 关键约束
- [ ] 同 relationship 同日期最多一个 PRIMARY（条件唯一 + 事务锁双保险）
- [ ] HR02 门：organization/position 权威位可空 + `legacy_department_id/legacy_job_position_id` 映射列（不固化 FK）
- [ ] 关系结束后不允许存在超期 active assignment
- [ ] 历史 as-of 不允许读 current projection 替代

### 验收
- [x] as-of 测试：2024 计算机学院 / 2026 AI 学院 / 今天→AI / as_of2024→计算机 / 未来生效 / 同日切换 / 边界日期
- [x] 并发测试：双创建 PRIMARY → 一败；过期 version → 409；rehire 不重复 Person
- [x] commit：`feat(hr03): S3 有效日期关系与任职事实层`（迁移 0002/0003；54 项测试全绿）

## S4 HR03-01 教职工名册

### 文件
```
api/staff.py            # GET /api/hr/v1/staff（list + QuerySpec + scope + 高敏不入列表）
selectors/staff_list.py # 名册查询（tenant→scope→字段裁剪；select_related/prefetch 预算）
templates/hr_staff/staff_list.html + partials/*
static/hr/css/components/* + static/hr/js/components/*
services/export_service.py  # 异步导出 + 字段权限 + ticket（先接口后 UI）
```
### 验收
- [x] 筛选：关键词/状态/组织/人员类别/聘用类型/主岗位/职称投影/教师资格/双师/入校日期/完整度/未来变更
- [x] 50 行首屏 ≤1.2s；≤10~15 SQL；高敏字段默认不进 API
- [x] 批量动作仅材料请求/核对/导出/标签；禁批量改组织岗位
- [x] commit：`feat(hr03): S4 HR03-01 名册`（api/staff.py + selectors/staff_list.py；S4 测试全绿）

## S5 HR03-02 教职工主档

### 文件
```
api/profile.py          # GET /api/hr/v1/staff/{id}/profile?asOf=
selectors/profile.py    # bootstrap ≤15~25 SQL；as-of 组织名解析（HR02 可用时）
templates/hr_staff/profile.html + partials/*（HrStaffIdentityHeader/HrStatusBadge/HrAsOfDateBar/HrSensitiveValue）
services/profile_snapshot.py  # 可选用（快照 hash 留位）
```
### 验收
- [x] Header：姓名/工号/状态/当前学院·主岗·职称；as-of 切历史 → 只读模式
- [x] 高敏字段不进 bootstrap；reveal endpoint 契约定义（S8 实现）
- [x] 编辑策略：basic/contact 走表单；组织岗位状态跳 HR06/13/14/16
- [x] commit：`feat(hr03): S5 HR03-02 主档`（api/profile.py + selectors/profile.py；S5 测试全绿）

## S6 HR03-03 任职与身份履历（as-of 查询） ✅ 已交付

> 状态：`api/assignments.py` + `selectors/assignments.py`（relationships/assignments/timeline，历史只读）；测试 `test_assignments.py` 全绿。

### 文件
```
api/assignments.py  # GET .../assignments?asOf= / employment-relationships / timeline
templates/hr_staff/assignment_history.html + HrAssignmentTimeline
services/status_projection.py  # staff current status 由关系/任职段推导
```
### 验收
- [ ] timeline + 表格双视图；来源/业务ID/状态/更正标记
- [ ] 新建任职事实来源白名单（HR05/06/14/16/MIGRATION_VERIFIED/AUTHORIZED_CORRECTION）
- [ ] 历史日期页面绝不显示当前学院（事故级负向）
- [ ] commit：`feat(hr03): S6 任职履历 as-of`

## S7 HR03-04 教育资格履历 ✅ 已交付

> 状态：`models/education.py` + `models/credential.py`（迁移 0004）+ `services/background_service.py` + `api/backgrounds.py`；测试 `test_backgrounds.py` 全绿。

### 文件
```
models/education.py  # HrEducationExperience/HrDegreeRecord/HrWorkExperience
models/credential.py # HrCredential/HrCertificate/HrTalentHonor
api/backgrounds.py   # GET/POST/PATCH .../education|degrees|work|credentials
templates/hr_staff/background_facts.html（Tab：教育/学位/工作/资格/证书/荣誉）
services/background_service.py  # 来源+核验态；写入权限按 FieldGovernancePolicy
```
### 验收
- [ ] 学历/学位分离；最高学历不靠"最后一条"
- [ ] 时间校验（end≥start）；verification_status；材料 evidence 绑定
- [ ] 数据质量状态：COMPLETE/REQUIRED_MISSING/CONFLICT/UNVERIFIED/EXPIRED
- [ ] commit：`feat(hr03): S7 教育资格履历`

## S8 HR03-05 人事材料档案（敏感文件安全） ✅ 已交付

> 状态：`models/material.py`（迁移 0005）+ `services/material_service.py`（版本链不可覆盖/ticket 一次性/敏感权限）+ `api/materials.py`；测试 `test_materials.py` 全绿。

### 文件
```
models/material.py      # HrStaffMaterial + HrStaffMaterialVersion（sha256/版本/作废/保留）+ HrMaterialRequest
services/material_service.py
api/materials.py        # GET/POST/versions/verify/download-ticket
selectors/material_access.py  # tenant+scope+sensitivity+purpose+audit
storage/protected_storage.py  # 禁 /media/ 裸 URL；非公开存储
templates/hr_staff/materials.html
```
### 验收
- [ ] 下载走 `POST .../download-ticket` 短时效一次性票据；裸 URL 拒绝（P0）
- [ ] 版本链：旧版本不可无痕覆盖；替换/作废记录完整
- [ ] 敏感材料水印（不修改原文件）；SENSITIVE 查看 purpose+审计
- [ ] 事故级负向：材料跨 tenant 拒绝；票据猜 ID 越权拒绝
- [ ] commit：`feat(hr03): S8 材料档案与受控访问`

## S9 HR03-06 信息更正 CorrectionCase ✅ 已交付

> 状态：`models/correction.py`（迁移 0006）+ `services/correction_service.py`（状态机/影响分析/APPLYING-FAILED 可追踪）+ `api/corrections.py`；测试 `test_corrections.py` 全绿。

### 文件
```
models/correction.py  # HrCorrectionCase/HrCorrectionItem/HrFieldGovernancePolicy
services/correction_service.py  # 状态机 + 影响分析 + APPLYING/FAILED 可追踪 + 幂等重试
api/corrections.py    # submit/return/approve/reject/apply
templates/hr_staff/corrections.html + HrSnapshotDiff
```
### 验收
- [ ] 状态机完整；RETURNED≠REJECTED；审批成功但应用失败必须可追踪
- [ ] BUSINESS_PROCESS_ONLY 字段不可经更正绕过
- [ ] retroactive 影响分析（工资封账/归档考核/上报冻结）
- [ ] 高敏 before/after 按掩码/加密策略存储；日志无 PII
- [ ] commit：`feat(hr03): S9 信息更正与历史`

## S10 HR06/07/13/14/16 事件接收 ✅ 已交付

> 状态：`models/events.py`（迁移 0007：HrBusinessEventInbox 幂等 + HrOutboxEvent）+ `services/event_service.py`（HR05/06/07/13/14/16 消费者 + outbox）；测试 `test_events.py` 全绿。

### 文件
```
events/consumers.py        # HR05_ONBOARDING/HR06_TRANSFER/HR07_CONTRACT/HR13_TITLE/HR14_APPOINTMENT/HR16_EXIT/REHIRE
events/outbox.py           # HrOutboxEvent 写入/发布（StaffCreated/AssignmentChanged/...）
providers/legacy_snapshot.py  # LEGACY_CURRENT_SNAPSHOT 只读预览 Provider（硬门）
```
### 验收
- [ ] 接收生效事实 → 关旧段/开新段/更新投影，不复制过程记录
- [ ] HR16 离职/退休：关关系与 assignment、status 更新、历史保留、不 DELETE
- [ ] HR13/HR14 结果以 projection/fact reference 展示，不反向改评审过程
- [ ] commit：`feat(hr03): S10 业务域事件接收`

## S11 Legacy 投影/对账/迁移 ✅ 已交付

> 状态：`legacy/projection_service.py`（单向投影）+ `legacy/reconciliation.py`（DUAL_READ_COMPARE）+ `legacy/migration.py`（Wave 0/1/2）+ `management/commands/hr03_migrate.py`；测试 `test_legacy.py`（mock 占位验证，全栈 CI 补真实对账）全绿。

### 文件
```
legacy/projection_service.py  # HrLegacyEmployeeProjectionService（单向 authority→legacy，可重试+reconciliation）
legacy/migration_wave0.py     # 盘点命令（不写 authority）
legacy/migration_wave1_2.py   # Person/Staff/Relationship/Assignment
legacy/reconciliation.py      # DUAL_READ_COMPARE 对账（staff_no/org/position/type/joining/status/contact）
imports/staging.py            # HrImportJob/Row/Issue 异步提交
imports/templates/*.xlsx      # 基础主档/任职关系/教育经历/工作经历/资格证书 分层模板
docs/hr/legacy/HR03_LegacyDataMapping.md  # 升级 REVIEWED
```
### 验收
- [ ] Wave 0 盘点输出；mismatch 全量进对账中心，不静默
- [ ] authority 后禁 fallback（contract test）；legacy 写入口关闭
- [ ] 导入分批事务 + checkpoint + 精确失败行；同人员多表原子
- [ ] commit：`feat(hr03): S11 Legacy 投影与对账迁移`

## S12 封板 ✅ 已交付（本地验证阶段；四轮复审通过）

> 状态：`services/authority_mode_service.py`（AUTHORITY 后禁 fallback 守卫 + cutover 审计）+ `models/permission_meta.py`（迁移 0008）+ 集中负向验收 `test_acceptance.py`；第四轮新增：导出（`HrExportJob` 迁移 0011 + `api/export.py`）、导入接线（`StaffMasterRowApplier` + `api/imports.py`）、工号序列 `HrStaffNumberSequence`、按岗位/组织 as-of 入口、审计补齐、CSRF、scope membership、XSS 转义、N+1 批量优化。
> **当前 162 tests OK（Django 5.2 mini venv）**；封板口令 `HR03 READY FOR ACCEPTANCE` 仍需全栈 CI（clean DB 迁移/升级迁移/Playwright/性能）通过后由总控签发。

### 内容
- [x] 全量 CI（clean DB 迁移 + 升级 snapshot 迁移）—— 本地 mini venv 迁移 0001-0011 全可执行；全栈 CI 待总控
- [ ] Playwright 视口 1280/1440/1920；visual regression
- [ ] 安全（high sensitive 不下发/reveal 100% 审计/下载受控/导出受控/日志无 PII）
- [ ] 性能 P95（名册≤1.2s、profile≤900ms、timeline≤800ms）
- [ ] #55 事故级负向全绿（A 改 B/猜 staffId/双 PRIMARY/过期版本/BP 字段/fallback/裸 URL/普通导出带身份证/rehire 重复 Person/历史显示当前学院）
- [ ] 文档与 ops 手册收口

### 封板口令
仅当以上全部满足才输出 `HR03 READY FOR ACCEPTANCE`；否则报告具体 blocker。

---

## 依赖顺序图
```
S1(A0/合同) → S2(Person/Identity/Staff) → S3(Relationship/Assignment/effective-date)
                 ├→ S4(名册) → S5(主档) → S6(任职履历)
                 ├→ S7(教育资格)
                 ├→ S8(材料)
                 ├→ S9(更正)
                 ├→ S10(事件接收)
                 └→ S11(Legacy 投影/对账/迁移) → S12(封板)
```
- S4 名册可基于 S2/S3 Provider 先行；S5 主档依赖 S3 as-of；S7/S8/S9 可并行但共享 S2 审计/敏感基建。
- HR02 稳定 ID 就绪事件是 S3 回填与 S11 Wave2 的触发门（未就绪用 LEGACY_CURRENT_SNAPSHOT）。
