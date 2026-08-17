"""
hr_time/providers/base.py

HR11 Provider 契约（总册 §148）。所有下游/上游集成必须通过 Provider 边界：

PersonProvider / AssignmentProvider      → HR03
ChangeEventProvider                      → HR06
AgreementProvider                        → HR07
DevelopmentTimeProvider                  → HR10
AssessmentConsumer                       → HR12
PayrollTimeConsumer                      → HR15
AcademicScheduleProvider                 → 教务
TravelDutyProvider                       → 公务/出差（若有）
DocumentProvider                         → 文件
NotificationProvider                     → 通知

铁律（总册 §148/§199）：
- Provider 失败必须显式失败（TIME_SOURCE_UNAVAILABLE），禁止 legacy fallback；
- Provider unavailable 不能当作“无冲突/无数据”；
- HR11 不复制第二业务流程（教务课表、HR10 实践日志、HR15 计算逻辑）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


class HrProviderError(Exception):
    """Provider 调用失败（显式失败，禁止静默 fallback）。"""

    def __init__(self, code: str = "TIME_SOURCE_UNAVAILABLE", message: str = ""):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


@dataclass(frozen=True)
class ProviderHealth:
    """数据源新鲜度（总册 §145）。"""

    source_updated_at: Optional[str] = None
    last_successful_sync_at: Optional[str] = None
    max_stale_seconds: Optional[int] = None
    hard_expire_seconds: Optional[int] = None
    status: str = "UNKNOWN"  # FRESH / STALE / PARTIAL / SOURCE_UNAVAILABLE


@dataclass(frozen=True)
class PersonRef:
    """HR03 人员引用（HR11 不复制人员权威事实）。"""

    staff_master_id: Optional[int] = None
    employment_relationship_id: Optional[int] = None
    legacy_employee_id: Optional[int] = None
    worker_category: Optional[str] = None
    employment_type: Optional[str] = None


@dataclass(frozen=True)
class AssignmentRef:
    """HR03 任职引用。"""

    assignment_id: Optional[int] = None
    org_id: Optional[int] = None
    post_id: Optional[int] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class PersonProvider(ABC):
    """→ HR03。获取人员/任职快照，供 eligibility 使用。"""

    @abstractmethod
    def get_person(self, *, legacy_employee_id: int, as_of: date) -> PersonRef:
        """失败必须抛 HrProviderError，禁止返回空 PersonRef 冒充成功。"""

    @abstractmethod
    def get_assignment(self, *, assignment_id: int, as_of: date) -> AssignmentRef:
        ...

    @abstractmethod
    def health(self) -> ProviderHealth:
        ...


class ChangeEventProvider(ABC):
    """← HR06。消费 'AttendanceRuleReevaluationRequested' 等变更事件。"""

    @abstractmethod
    def get_pending_reevaluation_scopes(self, *, tenant_id: int) -> list[dict]:
        ...


class AgreementProvider(ABC):
    """→ HR07。只读合同工作安排引用，不复制请假/考勤规则。"""

    @abstractmethod
    def get_work_arrangement_ref(self, *, assignment_id: int, as_of: date) -> Optional[dict]:
        ...


class DevelopmentTimeProvider(ABC):
    """→ HR10。读取培训/企业实践时段，用于 ScheduleException/冲突判断。"""

    @abstractmethod
    def get_released_time_windows(self, *, staff_id: int, start: date, end: date) -> list[dict]:
        ...


class AssessmentConsumer(ABC):
    """→ HR12。只输出冻结指标，不可反向改 HR11。"""

    @abstractmethod
    def publish_metric_basis(self, *, tenant_id: int, close_snapshot_id: int, basis: dict) -> None:
        ...


class PayrollTimeConsumer(ABC):
    """→ HR15。只输出已冻结时间基础（不含金额）。"""

    @abstractmethod
    def publish_time_basis(self, *, tenant_id: int, close_snapshot_id: int, basis: dict) -> None:
        ...


class AcademicScheduleProvider(ABC):
    """→ 教务。课程/监考日程只作冲突证据，不作为考勤真值。"""

    @abstractmethod
    def get_teaching_events(self, *, staff_id: int, start: date, end: date) -> list[dict]:
        ...

    @abstractmethod
    def health(self) -> ProviderHealth:
        ...


class TravelDutyProvider(ABC):
    """→ 公务/出差（若有）。外勤不是请假。"""

    @abstractmethod
    def get_duty_windows(self, *, staff_id: int, start: date, end: date) -> list[dict]:
        ...


class DocumentProvider(ABC):
    """→ 文件。私密对象存储 + 短期签名 URL + 下载前重新鉴权。"""

    @abstractmethod
    def create_evidence(self, *, tenant_id: int, scope: str, file_ref: str, sensitivity: str) -> dict:
        ...


class NotificationProvider(ABC):
    """→ 通知。"""

    @abstractmethod
    def notify(self, *, tenant_id: int, recipients: list[int], verb: str, ref: dict) -> None:
        ...


# 全部 Provider 契约注册表（供集成矩阵/S9 对齐使用）
ALL_HR11_PROVIDERS = {
    "PersonProvider": PersonProvider,
    "ChangeEventProvider": ChangeEventProvider,
    "AgreementProvider": AgreementProvider,
    "DevelopmentTimeProvider": DevelopmentTimeProvider,
    "AssessmentConsumer": AssessmentConsumer,
    "PayrollTimeConsumer": PayrollTimeConsumer,
    "AcademicScheduleProvider": AcademicScheduleProvider,
    "TravelDutyProvider": TravelDutyProvider,
    "DocumentProvider": DocumentProvider,
    "NotificationProvider": NotificationProvider,
}
