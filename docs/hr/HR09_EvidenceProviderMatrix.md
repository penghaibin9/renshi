# HR09_EvidenceProviderMatrix —— 证据提供者矩阵

> 物化时间：2026-08-09
> 版本：V1.0 S0 Baseline
> 依据：总册 §40 + §59-63

---

## 1. 证据来源注册表

| 来源码 | 提供者域 | 数据对象 | 就绪状态 | 占位策略 |
|---|---|---|---|---|
| HR03_EDUCATION | hr_staff | HrEducationExperience | READY | — |
| HR03_DEGREE | hr_staff | HrDegreeRecord | READY | — |
| HR03_WORK_HISTORY | hr_staff | HrWorkExperience | READY | — |
| HR03_CREDENTIAL | hr_staff | HrCredential | READY | 引用 HR03 credential；非 HR09 authority |
| HR09_CREDENTIAL | hr_qualification | HrPersonCredential | NOT_READY | S2 施工后可用 |
| HR08_ENGAGEMENT | hr_external | HrExternalEngagement | READY | — |
| HR10_ENTERPRISE_PRACTICE | hr_development | — | NOT_READY | **返回 UNAVAILABLE** |
| HR10_TRAINING | hr_development | — | NOT_READY | **返回 UNAVAILABLE** |
| ACADEMIC_TEACHING | external | 教务教学任务/课时/评价 | NOT_READY | **返回 UNAVAILABLE**（Provider 契约占位） |
| ACADEMIC_COURSE_DEVELOPMENT | external | 课程建设/教改项目 | NOT_READY | **返回 UNAVAILABLE** |
| ACADEMIC_COMPETITION | external | 竞赛/指导学生获奖 | NOT_READY | **返回 UNAVAILABLE** |
| HR12_ASSESSMENT | hr_assessment | 年度/聘期/师德考核 | NOT_READY | **返回 UNAVAILABLE** |
| RESEARCH_PROJECT | external | 科研项目/成果转化 | NOT_READY | **返回 UNAVAILABLE** |
| MANUAL_VERIFIED | hr_qualification | 人工提交证据 | READY | 人工审核后 VERIFIED |

---

## 2. Provider 统一接口契约

```python
class HrEvidenceProvider(ABC):
    """证据提供者基类。"""

    provider_key: str          # 注册 key（如 "HR10_ENTERPRISE_PRACTICE"）
    owner_domain: str          # 归属域（如 "hr_development"）
    timeout_seconds: int       # 超时（秒）
    sensitivity: str           # PUBLIC_HR / RESTRICTED_HR / SENSITIVE

    @abstractmethod
    def provide(
        self,
        person_id: UUID,
        staff_master_id: UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        """
        返回统一信封：

        ProviderEvidenceResult:
            status: ProviderStatus         # OK/PARTIAL/UNAVAILABLE/STALE/ERROR
            items: list[EvidenceItem]      # 证据项列表
            errors: list[ProviderError]     # 错误详情
            source_updated_at: datetime     # 源数据最后更新时间
            provider_version: str           # provider 版本号
        """
```

---

## 3. ProviderStatus 枚举

```text
OK              → 正常返回（可能有 0 条证据，0 ≠ UNAVAILABLE）
PARTIAL         → 部分数据可获取
UNAVAILABLE     → 服务/数据源不可用（≠ 0 ≠ false ≠ empty list）
STALE           → 数据过期但可用
ERROR           → 查询异常
NOT_APPLICABLE  → 对该 Person 不适用（如非外聘教师查 HR08）
```

---

## 4. 各 Provider 实现状态

### HR03_EDUCATION（就绪）

```python
class Hr03EducationProvider(HrEvidenceProvider):
    provider_key = "HR03_EDUCATION"
    owner_domain = "hr_staff"

    def provide(self, person_id, staff_master_id, tenant_id, as_of, **kwargs):
        # 查询 HrEducationExperience(tenant+staff, at as_of)
        # 查询 HrDegreeRecord(tenant+staff)
        # 返回: education_level, major_name, school_name, degree_level, verification_status
        pass
```

### HR03_WORK_HISTORY（就绪）

```python
class Hr03WorkHistoryProvider(HrEvidenceProvider):
    provider_key = "HR03_WORK_HISTORY"
    owner_domain = "hr_staff"

    def provide(self, person_id, staff_master_id, tenant_id, as_of, **kwargs):
        # 查询 HrWorkExperience(tenant+staff, experience_type=ENTERPRISE|INDUSTRY|...)
        # 返回: organization_name, position_title, duration_days, experience_type
        pass
```

### HR03_CREDENTIAL（就绪）

```python
class Hr03CredentialProvider(HrEvidenceProvider):
    provider_key = "HR03_CREDENTIAL"
    owner_domain = "hr_staff"

    def provide(self, person_id, staff_master_id, tenant_id, as_of, **kwargs):
        # 查询 HrCredential(tenant+staff, credential_type)
        # 返回: credential_type, credential_name, level, status, verification_status
        pass
```

### HR10_ENTERPRISE_PRACTICE（占位 · 返回 UNAVAILABLE）

```python
class Hr10EnterprisePracticeProvider(HrEvidenceProvider):
    provider_key = "HR10_ENTERPRISE_PRACTICE"
    owner_domain = "hr_development"

    def provide(self, person_id, staff_master_id, tenant_id, as_of, **kwargs):
        return ProviderEvidenceResult(
            status=ProviderStatus.UNAVAILABLE,
            items=[],
            errors=[ProviderError(
                code="MODULE_NOT_READY",
                message="HR10 培训进修与企业实践模块尚未交付。"
            )],
            source_updated_at=None,
            provider_version="0.1.0-placeholder",
        )
```

### ACADEMIC_TEACHING（占位 · 返回 UNAVAILABLE）

```python
class AcademicTeachingProvider(HrEvidenceProvider):
    provider_key = "ACADEMIC_TEACHING"
    owner_domain = "academic"

    def provide(self, person_id, staff_master_id, tenant_id, as_of, **kwargs):
        return ProviderEvidenceResult(
            status=ProviderStatus.UNAVAILABLE,
            items=[],
            errors=[ProviderError(
                code="INTEGRATION_NOT_CONFIGURED",
                message="教务系统对接尚未配置。"
            )],
            source_updated_at=None,
            provider_version="0.1.0-placeholder",
        )
```

---

## 5. Precheck 中的 Provider 状态处理

```text
Precheck 运行规则：
  for each EvidenceRequirement in RuleVersion:
      result = provider.provide(...)

      if result.status == UNAVAILABLE:
          → PrecheckItem SOURCE_UNAVAILABLE
          → 不视为 PASS，也不视为 FAIL
          → 申报人可暂提交，人工评审阶段标注

      if result.status == ERROR:
          → PrecheckItem SOURCE_UNAVAILABLE（同 UNAVAILABLE）
          → 记录 error 详情供运维排查

      if result.status == OK and no matching items:
          → PrecheckItem MISSING_EVIDENCE（确实缺证据）
          → 若 rule 为 HARD → FAIL_HARD_RULE
```

## 6. 多源聚合时间窗

同一 Evidence Package 所有 Provider 使用**统一 as_of**（通常为 submitted_at），避免跨日数据不一致。

---

**文件状态：S0_BASELINE 冻结。**
