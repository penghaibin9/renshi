"""
hr10_development/providers/base.py

HR10 Provider 抽象接口（13 契约）。

对齐 00 §13 Provider Contract：
- 每 Provider 固定 owner domain、consumer、tenant、ids、as_of、sourceVersion、freshness
- Provider 不可用不得 silent fallback legacy
- 所有消费者不得 import 对方 Authority model 后直接写
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class ProviderStatus(Enum):
    """统一 Provider 状态（00 §11）。"""
    OK = "OK"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class ProviderResult:
    """Provider 调用结果。"""
    status: ProviderStatus
    data: Any = None
    error_message: str = ""
    source_updated_at: datetime | None = None


@dataclass
class ScheduleConflictResult:
    """排程冲突检查结果。"""
    result: str  # PASS / WARNING / BLOCKED / SOURCE_UNAVAILABLE
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    source_availability: ProviderStatus = ProviderStatus.OK


# ============================================================
# 1. PersonProvider → HR03
# ============================================================

class PersonProvider(ABC):
    """HR03 Person/Staff 读取 Provider。"""

    @abstractmethod
    def get_person(self, person_id: str, tenant_id: int) -> ProviderResult:
        """读取 HrPerson。"""
        ...

    @abstractmethod
    def get_staff_master(self, staff_master_id: str, tenant_id: int) -> ProviderResult:
        """读取 HrStaffMaster。"""
        ...

    @abstractmethod
    def get_employment_relationship(
        self, relationship_id: str, tenant_id: int
    ) -> ProviderResult:
        """读取 EmploymentRelationship。"""
        ...

    @abstractmethod
    def get_assignment(self, assignment_id: str, tenant_id: int) -> ProviderResult:
        """读取 HrStaffAssignment。"""
        ...

    @abstractmethod
    def get_education_history(
        self, staff_master_id: str, tenant_id: int, as_of: date | None = None
    ) -> ProviderResult:
        """读取 EducationHistory (as-of)。"""
        ...


# ============================================================
# 2. ExternalTeacherProvider → HR08
# ============================================================

class ExternalTeacherProvider(ABC):
    """HR08 外聘教师 Provider。"""

    @abstractmethod
    def get_engagement(
        self, engagement_id: str, tenant_id: int
    ) -> ProviderResult:
        """读取 HrExternalEngagement。"""
        ...

    @abstractmethod
    def check_activity_eligibility(
        self, engagement_id: str, activity_type: str, tenant_id: int
    ) -> ProviderResult:
        """检查外聘教师是否允许参与指定活动类型。"""
        ...


# ============================================================
# 3. QualificationEvidenceProvider → HR09
# ============================================================

class QualificationEvidenceProvider(ABC):
    """
    HR09 双师证据 Provider。
    HR10 → HR09：提供 VERIFIED DevelopmentFact 作为双师认定证据。
    """

    @abstractmethod
    def get_evidence(
        self,
        staff_master_id: str,
        tenant_id: int,
        as_of: date | None = None,
        fact_types: list[str] | None = None,
    ) -> ProviderResult:
        """获取指定教师的已核验发展事实作为双师证据。"""
        ...


# ============================================================
# 4. TimeConflictProvider → HR11
# ============================================================

class TimeConflictProvider(ABC):
    """HR11 时间冲突检查 Provider。"""

    @abstractmethod
    def check_conflict(
        self,
        staff_master_id: str,
        tenant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> ScheduleConflictResult:
        """检查指定时间窗口是否存在教学/考勤/请假/其他培训冲突。"""
        ...


# ============================================================
# 5. DevelopmentTimeProvider → HR11
# ============================================================

class DevelopmentTimeProvider(ABC):
    """
    HR10 → HR11：提供培训/企业实践时间窗口。
    HR11 据此创建排班异常 (AUTHORIZED_TRAINING / ENTERPRISE_PRACTICE)。
    """

    @abstractmethod
    def get_development_time_windows(
        self,
        staff_master_id: str,
        tenant_id: int,
        period_start: date,
        period_end: date,
    ) -> ProviderResult:
        """返回 [{type, start, end}] 格式的时间窗口。"""
        ...


# ============================================================
# 6. AssessmentFactsConsumer → HR12
# ============================================================

class AssessmentFactsConsumer(ABC):
    """HR12 考核发展事实引用 Provider。"""

    @abstractmethod
    def get_verified_facts(
        self,
        staff_master_id: str,
        tenant_id: int,
        as_of: date | None = None,
    ) -> ProviderResult:
        """获取指定教师的已核验发展事实供考核引用。"""
        ...

    @abstractmethod
    def get_plan_completion_indicators(
        self,
        staff_master_id: str,
        tenant_id: int,
        period_start: date,
        period_end: date,
    ) -> ProviderResult:
        """获取发展计划完成率指标。"""
        ...


# ============================================================
# 7. FinanceBudgetProvider → HR15
# ============================================================

class FinanceBudgetProvider(ABC):
    """HR15 财务预算 Provider。HR10 只读预算/支付投影，不建支付。"""

    @abstractmethod
    def get_budget_status(
        self, budget_ref: str, tenant_id: int
    ) -> ProviderResult:
        """读取预算预留/承诺/已支付状态。"""
        ...

    @abstractmethod
    def get_payment_projection(
        self, expense_ref: str, tenant_id: int
    ) -> ProviderResult:
        """读取费用实际支付投影。"""
        ...


# ============================================================
# 8. AcademicProvider → 教务
# ============================================================

class AcademicProvider(ABC):
    """教务系统 Provider。"""

    @abstractmethod
    def get_teaching_schedule(
        self, staff_master_id: str, tenant_id: int, period_start: date, period_end: date
    ) -> ProviderResult:
        """读取教师课表（用于时间冲突检查）。"""
        ...

    @abstractmethod
    def verify_teaching_transformation(
        self, output_id: str, tenant_id: int
    ) -> ProviderResult:
        """核验教学转化成果。"""
        ...


# ============================================================
# 9. ResearchProvider → 科研
# ============================================================

class ResearchProvider(ABC):
    """科研系统 Provider。"""

    @abstractmethod
    def verify_research_output(
        self, output_ref: str, tenant_id: int
    ) -> ProviderResult:
        """核验科研产出引用。"""
        ...


# ============================================================
# 10. AgreementProvider → HR07
# ============================================================

class AgreementProvider(ABC):
    """HR07 协议 Provider。实践协议/保密/IP 引用。"""

    @abstractmethod
    def get_agreement(
        self, agreement_id: str, tenant_id: int
    ) -> ProviderResult:
        """读取协议信息。"""
        ...

    @abstractmethod
    def create_practice_agreement(
        self,
        tenant_id: int,
        title: str,
        agreement_type: str,
        parties_json: dict[str, Any],
    ) -> ProviderResult:
        """创建企业实践相关协议。"""
        ...


# ============================================================
# 11. DocumentProvider → 文件系统
# ============================================================

class DocumentProvider(ABC):
    """文件系统 Provider。"""

    @abstractmethod
    def upload_evidence(
        self, tenant_id: int, file_data: bytes, file_name: str, content_type: str
    ) -> ProviderResult:
        """上传证据文件。"""
        ...

    @abstractmethod
    def generate_download_ticket(
        self, document_id: str, tenant_id: int, max_uses: int = 1
    ) -> ProviderResult:
        """生成短期下载票据。"""
        ...


# ============================================================
# 12. NotificationProvider → 通知
# ============================================================

class NotificationProvider(ABC):
    """通知 Provider。"""

    @abstractmethod
    def notify(
        self,
        tenant_id: int,
        recipient_ids: list[int],
        template_code: str,
        context: dict[str, Any],
    ) -> ProviderResult:
        """发送业务通知。"""
        ...


# ============================================================
# 13. EducationWritebackProvider → HR03
# ============================================================

class EducationWritebackProvider(ABC):
    """
    HR10 → HR03 学历写回 Provider。
    进修取得学位/学历经核验后通过此接口提交 HR03 EducationHistory。
    """

    @abstractmethod
    def submit_education_record(
        self,
        tenant_id: int,
        staff_master_id: str,
        education_data: dict[str, Any],
    ) -> ProviderResult:
        """提交学历记录核验请求到 HR03。"""
        ...
