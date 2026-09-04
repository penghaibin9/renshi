# HR10_LegacyDevelopmentMapping — 旧代码培训/实践入口审计与接管映射

> 全局合同：`00_高校人事系统全局架构与旧系统接管合同.md`
> 业务事实源：`10_HR10_培训进修与企业实践_施工总册_终极版.md`
> 状态：`S0_V1 — 基线复审完成`
> 复审日期：2026-08-09

---

## 0. 结论先行

**HR10 在仓库当前代码中零实现。**
不存在独立的 training/learning/practice 模型、视图、服务或 API。

旧系统中与 "培训/技能/证书/企业实践" 相关的入口全部位于以下散落代码中，
HR10 施工后这些入口全部接管为只读投影或重定向，禁止再写。

| 旧入口/对象 | 位置 | 内容 | 接管裁决 | Cutover 条件 |
|---|---|---|---|---|
| `Employee.qualification` | `employee/models.py:108` | `CharField(max_length=50)` 自由文本 | **DROP_AFTER_CUTOVER** | 迁移到 HR03 HrCredential + HR10 TrainingCompletion |
| `Skill` 模型 | `recruitment/models.py:112` | 招聘技能标签 (M2M Candidate) | **KEEP** (HR04 资产) | 不接管 |
| `SkillZone` | `recruitment` | 招聘技能管理区 | **KEEP** (HR04 资产) | 不接管 |
| `hr_time.models.attendance.HrTimeSheetEntry.TRAINING` | `hr_time/models/attendance.py:278` | 工时表条目类型 "培训" | **ADAPT** | 改为引用 HR10 HrLearningParticipation |
| `hr_time.models.schedule.HrScheduleException.AUTHORIZED_TRAINING` | `hr_time/models/schedule.py:207` | 排班异常类型 "授权培训" | **ADAPT** | 改为引用 HR10 HrLearningEnrollment |
| `hr_time.models.schedule.HrScheduleException.ENTERPRISE_PRACTICE` | `hr_time/models/schedule.py:208` | 排班异常类型 "企业实践" | **ADAPT** | 改为引用 HR10 HrEnterprisePracticeAssignment |
| `hr_external.constants.SKILL_TRAINING` | `hr_external/constants.py:185` | 外聘分配类型 "技能培训" | **KEEP** (HR08 枚举) | 不接管 |
| `hr_external.constants.PRACTICE_INSTRUCTOR` | `hr_external/constants.py:42` | 外聘人员类别 "实践指导教师" | **KEEP** (HR08 枚举) | 不接管 |
| `hr_external.constants.INDUSTRY_MENTOR` | `hr_external/constants.py:37` | 外聘人员类别 "产业导师" | **KEEP** (HR08 枚举) | HR10 HrEnterprisePracticeMentor 是独立作者模型，不自动转换为 HR08 外聘身份；仅当该产业导师同时存在正式 HR08 engagement 时引用 |
| `hr_external.constants.FACULTY_DEVELOPMENT` | `hr_external/constants.py:186` | 外聘分配类型 "教师发展" | **ADAPT** | HR10 可引用 HR08 engagement 但不自建外聘身份 |
| `EmployeeNote` (notes about training) | `employee/models.py:1069` | 员工备注自由文本 | **STAGING** | S10 迁移时标注 `MIGRATED_FREE_TEXT` |
| Legacy free-text/documents 中提及的培训/实践 | `employee` + `horilla_documents` 的自由文本/附件 | 不可溯源的非结构化历史数据 | **STAGING** | S10 进入 staging→validation→migration trust assignment |
| `hr_external.constants.TRAINING_PROJECT` | `hr_external/constants.py:332` | 外聘贡献类型 "培训项目" | **KEEP** (HR08 枚举) | 不接管 |
| `hr_staff.constants.SKILL_CERTIFICATE` | `hr_staff/constants.py:224` | 技能证书 | **KEEP** (HR03 资产) | 不接管；培训完成可关联 HR10→HR03 credential |

---

## 1. 参考清册

### 1.1 后端模型引用

| 旧模型 | 文件 | 与 HR10 的关系 | 接管裁决 |
|---|---|---|---|
| `Employee` | `employee/models.py` | `qualification` 字段曾用于记录教师最高学历/资格，现 HR03 HrEducationExperience + HrCredential 负责 | **LEGACY_PROJECTION_ONLY** |
| `EmployeeWorkInformation` | `employee/models.py` | 无直接培训/实践字段 | **不涉及** |
| `EmployeeNote` | `employee/models.py` | 可能含有"培训记录""企业实践天数"等管理员手录 | **STAGING + MIGRATED_FREE_TEXT** |
| `Skill` | `recruitment/models.py` | HR04 招聘技能池，与教师发展技能需求可关联但不可覆盖 | **KEEP** |
| `SkillZone` | `recruitment/models.py` | HR04 招聘技能区 | **KEEP** |
| `Document` | `horilla_documents/models.py` | 培训证书/实践协议附件载体 | **ADAPT** (保持文件安全，新增 HR10 evidence 引用) |
| `HrPerson / HrStaffMaster / HrEmploymentRelationship / HrStaffAssignment` | `hr_staff/models/` | HR10 身份根 | **直接复用** |
| `HrCredential / HrEducationExperience` | `hr_staff/models/` | 学历/证书权威 | **引用，不重建** |
| `HrScheduleException` | `hr_time/models/schedule.py` | 培训/企业实践排班异常 | **ADAPT** (改为引用 HR10 assignment) |
| `HrTimeSheetEntry` | `hr_time/models/attendance.py` | TRAINING 条目类型 | **ADAPT** (改为引用 HR10 participation) |
| `HrExternalEngagement` | `hr_external/models/` | 外聘教师发展活动参与 | **ADAPT** (引用，不重复建身份) |

### 1.2 旧路由/视图

| 路由 | 文件 | 接管裁决 |
|---|---|---|
| `/employee/view/{id}/` (qualification 字段) | `employee/views.py` | **READONLY_PROJECTION** |
| `/employee/employee-profile/{id}/` | `employee/cbv/employee_profile.py` | **READONLY_PROJECTION** |
| `/employee/document-request/` | `employee/cbv/document_request.py` | **ADAPT** |
| `/recruitment/skill-zone/` | `recruitment/cbv/skills.py` | **不接管** (HR04 资产) |
| `/hr/time/api/` (schedule exception endpoints - 未全施工) | `hr_time/api/` | **ADAPT** |

---

## 2. 字段级映射

### 2.1 Employee.qualification → HR03 权威事实

| 旧字段 | 新目标 | 策略 | 迁移可信度 |
|---|---|---|---|
| `employee.qualification` (Char) | `HrEducationExperience` + `HrCredential` (HR03) | 由 HR03 教育/证书迁移负责 | `MIGRATED_FREE_TEXT` |
| 培训相关内容 | `HrLearningCompletion` (HR10) | S10 staging → verify | `MIGRATED_FREE_TEXT` |

### 2.2 HrTimeSheetEntry.TRAINING → HR10 LearningParticipation

| 旧字段 | 新目标 | 策略 |
|---|---|---|
| `entry_type = "TRAINING"` | `HrLearningParticipation.enrollment_id` (HR10) | 迁移后旧枚举保留为投影标签，工时累计改为引用 HR10 verified_hours |

### 2.3 HrScheduleException AUTHORIZED_TRAINING / ENTERPRISE_PRACTICE

| 旧类型 | 新目标 | 策略 |
|---|---|---|
| `AUTHORIZED_TRAINING` | `HrLearningEnrollment` (HR10) → schedule exception override | 旧枚举保留，新增 `development_source_ref` 字段 |
| `ENTERPRISE_PRACTICE` | `HrEnterprisePracticeAssignment` (HR10) → schedule exception override | 同上 |

### 2.4 EmployeeNote / Document 自由文本培训记录

| 旧来源 | 新目标 | 迁移可信度 | 策略 |
|---|---|---|---|
| Note text 含关键字 "培训/实践/进修" | `HrDevelopmentFact` (HR10) staging 表 | `MIGRATED_FREE_TEXT` / `MIGRATED_UNVERIFIED` | S10 导入→人工核验→不满足 policy 的保留 staging |
| Document 为培训证书附件 | `HrLearningCompletion.evidence_package_id` | `DOCUMENT_BACKED` | 文件迁移→链接到 staging completion→核验后升级 |

---

## 3. S0 写入口清点

旧系统中**没有**直接创建培训记录/企业实践的专用页面或 API 端点。
所有培训/实践相关数据入口均为：

1. **Employee 编辑页面** (`employee/cbv/employees.py:163`) — `qualification` 字段手填
2. **EmployeeNote** — 管理员手录备注
3. **Document 上传** — 培训证书作为一般文件附件
4. **工时表 TRAINING 条目** — hr_time 自行创建

**接管后写权限变更：**

| 旧入口 | 接管后权限 | 写替代 |
|---|---|---|
| `Employee.qualification` | **只读** (Legacy Projection) | 通过 HR03 correction case 或 HR10 completion → HR03 credential 写回 |
| `EmployeeNote` (培训相关) | **只读** | HR10 authority + migration staging |
| `Document` (培训证书) | **保持上传能力** (文件安全不变) | 培训证书关联到 HR10 evidence |
| 工时表 TRAINING | **保持创建能力** | 工时来源改为引用 HR10 participation |

---

## 4. 迁移波次

| 波次 | 内容 | 阶段 | 回滚策略 |
|---|---|---|---|
| Wave-0 | 基线冻结 (当前所有旧字段快照 + hash) | S0 | 无需回滚 |
| Wave-1 | Staging 表创建 + Employee.qualification/EmployeeNote 文本解析→staging rows | S10 | 删除 staging rows |
| Wave-2 | Document 关联解析 (通过文件名/备注匹配培训/实践相关) → staged evidence | S10 | 删除 staged evidence |
| Wave-3 | DUAL_READ_COMPARE: 旧 projection ↔ HR10 authority | S12 | 回退到 LEGACY_ONLY |
| Wave-4 | Authority 切换: old entries → readonly projection | S12 | 回退到 DUAL_READ_COMPARE |
| Wave-5 | Cutover cleanup: Employee.qualification 字段移除 | S13 | Post-cutover，legacy readonly 期间不执行 |

---

## 5. 退出合同

1. **`Employee.qualification`** — Authority 切换后该字段降级为 LegacyProjection 只读标签，不再参与任何业务逻辑、搜索、报表、导出。
2. **`EmployeeNote` (培训实践备注)** — 迁移到 staging 后，旧 Note 中的培训/实践内容不删除（保留审计痕迹），但不再参与正式培训事实链。
3. **`horilla_documents.Document` (培训证书)** — 文件本身不迁移/不复制，仅新增 HR10 evidence 引用关系；旧 Document 记录保留在 `horilla_documents` 中。
4. **工时表 TRAINING 条目** — 最终目标是从 `entry_type` 枚举中移除 `TRAINING`，工时表只接受 `HrLearningParticipation` 作为时间来源。
5. **所有旧入口最终 deadline**：S13 `POST_CUTOVER_CLEANUP` 阶段 — 完全由 HR10 Authority + LegacyProjection 替代。

---

## 6. 禁止事项

- 禁止在 S0 期间修改任何旧代码
- 禁止将 `Employee.qualification` 直接映射为 HR10 `HrDevelopmentFact`（资格→HR03 HrCredential，培训→HR10 staging）
- 禁止将自由文本备注直接标为 `VERIFIED` 培训事实
- 禁止在迁移过程中删除旧 `Employee.qualification` 数据（先投影、后清理）
- 禁止绕过 staging→validation→confirm pipeline 直接写 HR10 authority

---

**文档状态：S0_V1 — 基线复审完成，等待 S10 迁移执行。**
