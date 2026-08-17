# HR09 LegacyQualificationMapping（S0 基线复审物化 · 依据真实仓库核对）

> 文档性质：HR09-S0 前置交付；依据 `renshi` 仓库真实模型/字段/路由/方法核对后物化。
> 权威依据：《09_HR09_教师资格与双师型_施工总册_终极版.md》第 136 节。
> 核对基线：当前工作树（`F:\高校人事系统\renshi`）。
> 物化时间：2026-08-09
> 状态：`S0_BASELINE` —— HR09 施工前冻结

---

## 1. 结论先行

- Horilla `Employee.qualification = CharField(max_length=50)` 不具备教师资格/双师型认定能力。
- HR03 已有 `HrCredential` 基础模型（`renshi/hr_staff/models/credential.py`），但仅为人员持证记录，无 Credential Catalog、无 Verification History 审计链、无 Requirement 对比、无风险跟踪。
- HR09 采用 **NEW** 策略：新建 `hr_qualification` app 承载权威事实。
- 旧 `Employee.qualification` 降级为 **READONLY_PROJECTION**（单向投影，禁止回写权威）。
- HR03 `HrCredential` 保留为人员速览投影（只读引用），不扩展为 HR09 Authority。

---

## 2. 全仓搜索覆盖

S0 搜索关键词覆盖：
- `qualification` → `employee/models.py:108`（遗留字段）+ `hr_staff/constants.py:222`（TEACHER_QUALIFICATION 材料分类）
- `certificate` → `hr_staff/models/credential.py`（HrCredential 模型）+ `hr_staff/constants.py:223`（PROFESSIONAL_CERTIFICATE）
- `certification` → 无业务匹配（仅有 venv-ci/Google API 文档）
- `skill` → `hr_staff/models/credential.py:22`（SKILL_CERTIFICATE 枚举值）+ `base/models.py`（WorkType.SkillLevel）
- `license` → 无业务匹配
- `teacher` → `hr_staff/constants.py:59`（TEACHER staff category）+ `legacy_employee.py:155`（double_teacher 指标）
- `双师` → `legacy_employee.py:66-68`（double_teacher_valid UNAVAILABLE）

结论：除 `HrCredential` 外，Horilla 代码库中**无任何教师资格/双师型认定代码**。

---

## 3. 字段级映射：Legacy → HR09

| Horilla 对象 | 字段 | HR09 决策 | 策略 | 说明 |
|---|---|---|---|---|
| `Employee` | `qualification` (CharField 50) | **READONLY_PROJECTION** | 投影为当前主要资格摘要；不承载权威 | 如"高校教师资格"字符串 → 只读展示 |
| `Employee` | `experience` (IntegerField) | **不迁为双师证据** | 引用 HR03 HrWorkExperience | 数字型经验无法律/政策证据效力 |
| `horilla_documents.Document` | 全模型 | **ADAPT 底层** | 复用文件上传存储；HrCredentialDocument 包装 | 增 sensitivity/hash/version 字段 |
| `horilla_documents.DocumentRequest` | 全模型 | **READONLY** | 旧流程不扩展 | 新补材料流程走 HrCredentialVerification |
| `horilla_audit.HorillaAuditLog` | 全模型 | **KEEP 技术历史** | 正式审计走 HrCredentialStatusEvent + HrRecognitionStatusEvent | 不删除旧审计记录 |
| `base.EmployeeType` | 全模型 | **不迁** | 人员类别引用 HR03 HrStaffMaster.staff_category_code | 不靠 EmployeeType 判定 eligibility |
| `base.JobPosition` | 全模型 | **READONLY_REF** | 仅作 CredentialRequirement.target_ref 候选 | 不对标高校岗位等级 |
| `hr_staff.HrCredential` | 全模型 | **READONLY** | HR03 已有 credential 保留；HR09 不在此基础扩展 | HR09 自建 Credential Catalog + Verification 独立体系 |

---

## 4. 旧读写入口清点

### 4.1 Employee.qualification 读入口

| 路径 | 用途 | 策略 |
|---|---|---|
| `employee/models.py:108` | 模型字段定义 | REMOVE_LATER（切换后废弃） |
| `employee/forms.py` | 编辑表单 | REDIRECT → HR09 Credential API |
| `employee/views.py` | 列表/详情展示 | READONLY_PROJECTION（显示 HR09 摘要） |
| `hr_control_center/providers/legacy_employee.py` | 指标计算 | 已正确返回 UNAVAILABLE |
| 旧模板 (employee/profile/...) | 个人资料页 | 投影 HR09 当前资格摘要 |

### 4.2 Employee.qualification 写入口

| 路径 | 用途 | 策略 |
|---|---|---|
| 员工编辑页 POST | 编辑 qualification | REDIRECT（切到 HR09 API） |
| onboarding view | 入职时填 qualification | REDIRECT（入职不直接建资格） |
| Excel import | 批量导入 qualification | ADAPT → Excel→staging→mapping→audit |

---

## 5. Legacy 退出路线

```text
LEGACY_QUALIFICATION_TEXT（当前）
    ↓ DUAL_READ_COMPARE
HR09 AUTHORITY（完成切换）
    ↓
Employee.qualification → READONLY_PROJECTION（HR09 摘要投影）
    ↓ POST_CUTOVER_CLEANUP
旧写入口删除；旧 UI 字段重定向
```

---

## 6. 对账检查项

- `Employee.qualification` 字符串 → `HrPersonCredential` + `HrDoubleTeacherRecognition` 当前状态
- 旧 Document 数量 → HrCredentialDocument 覆盖率
- 已存在 `HrCredential`（HR03）→ HR09 Credential Catalog item 映射
- `double_teacher_valid` 指标 DUAL_READ_COMPARE 一致性

差异异常 → `HR09_LEGACY_DRIFT` 数据质量问题。

---

**文件状态：S0_BASELINE 冻结。**
